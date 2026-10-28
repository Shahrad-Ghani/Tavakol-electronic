from __future__ import annotations

from .logging_bridge import phase2_log

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from . import core_runtime as core
from .metadata_state import (
    MetadataStore,
    apply_result,
    invalidate_stale_datasheet,
    is_phase2_eligible,
    mark_searching,
    product_part_number,
)
from .resolver_v43 import (
    AllDatasheet,
    Datasheet4U,
    DebugHTMLStore,
    MouserEntry,
    SourceDebug,
    SOURCE_API_FAILED,
    mouser_search_all,
    resolve_one,
)


class Phase2Pipeline:
    def __init__(
        self,
        *,
        project_root: Path,
        metadata_dir: Path,
        datasheet_dir: Path,
        proxy_file: Path,
        api_key: str,
        debug_dir: Optional[Path] = None,
        schema_path: Optional[Path] = None,
        metadata_store: Optional[MetadataStore] = None,
        retry_not_found: bool = False,
        retry_manual: bool = False,
    ):
        self.project_root = project_root.resolve()
        self.metadata_dir = metadata_dir
        self.datasheet_dir = datasheet_dir
        self.proxy_file = proxy_file
        self.api_key = api_key
        self.debug_dir = debug_dir or (self.project_root / "debug_html")
        self.retry_not_found = retry_not_found
        self.retry_manual = retry_manual
        self.store = metadata_store or MetadataStore(
            self.project_root, schema_path=schema_path
        )
        self._session: Optional[core.StickyProxySession] = None
        self._d4u: Optional[Datasheet4U] = None
        self._all_data: Optional[AllDatasheet] = None

    def _ensure_network(self) -> None:
        if self._session is not None:
            return
        proxies = core.load_proxies(self.proxy_file)
        session = core.StickyProxySession(proxies)
        session.select_initial_proxy()
        debug_store = DebugHTMLStore(self.debug_dir)
        self._session = session
        self._d4u = Datasheet4U(session, debug_store)
        self._all_data = AllDatasheet(session, debug_store)

    def discover_metadata(self) -> List[Path]:
        if not self.metadata_dir.exists():
            return []
        return sorted(p for p in self.metadata_dir.glob("*.json") if p.is_file())

    def eligible_paths(self, paths: Optional[Sequence[Path]] = None) -> List[Path]:
        selected: List[Path] = []
        for path in paths or self.discover_metadata():
            try:
                data = self.store.load(path)
                eligible, reason = is_phase2_eligible(
                    data,
                    self.project_root,
                    retry_not_found=self.retry_not_found,
                    retry_manual=self.retry_manual,
                )
                if eligible:
                    selected.append(path)
                else:
                    phase2_log(f"[PHASE2-SKIP] {path.name} reason={reason}")
            except Exception as exc:
                phase2_log(f"[PHASE2-METADATA-ERROR] {path.name} {type(exc).__name__}: {exc}")
        return selected

    def process_available(self, paths: Optional[Sequence[Path]] = None) -> int:
        eligible = self.eligible_paths(paths)
        if not eligible:
            phase2_log("[PHASE2] no eligible metadata")
            return 0
        processed = 0
        # Strict micro-batching: never wait for a global count such as 75.
        for batch in core.chunks(eligible, core.MAX_PARTS_PER_MOUSER_REQUEST):
            processed += self.process_batch(batch)
        return processed

    def process_batch(self, paths: Sequence[Path]) -> int:
        if not paths:
            return 0
        if len(paths) > core.MAX_PARTS_PER_MOUSER_REQUEST:
            raise ValueError("Phase2 batch may contain at most 10 metadata files")

        # Load and group by exact PartNumber. Duplicate product JSONs sharing a
        # PartNumber use one resolver result and one PDF download.
        grouped: Dict[str, List[tuple[Path, dict]]] = defaultdict(list)
        for path in paths:
            data = self.store.load(path)
            pn = product_part_number(data)
            if not pn:
                continue
            eligible, reason = is_phase2_eligible(data, self.project_root,
                retry_not_found=self.retry_not_found, retry_manual=self.retry_manual)
            if not eligible:
                phase2_log(f"[PHASE2-PROTECTED-SKIP] {path.name} reason={reason}")
                continue
            ds = data.get("datasheet") or {}
            old_searched = str(ds.get("searched_part_number") or "").strip()
            if old_searched and core.normalize_part_for_match(old_searched) != core.normalize_part_for_match(pn):
                invalidate_stale_datasheet(data, f"PartNumber changed: {old_searched} -> {pn}")
            mark_searching(data, pn)
            self.store.save(path, data)
            grouped[pn].append((path, data))

        if not grouped:
            return 0

        try:
            self._ensure_network()
            assert self._session is not None and self._d4u is not None and self._all_data is not None
            pns = list(grouped.keys())
            mouser_map = mouser_search_all(self._session, self.api_key, pns)
        except Exception as exc:
            # Batch-level network/proxy/API initialization failures must never
            # leave products stuck in `searching`. They remain retryable.
            for records in grouped.values():
                for path, data in records:
                    ds = data.setdefault("datasheet", {})
                    ds["status"] = "failed"
                    ds["identity_status"] = "EXACT_PART_NUMBER_UNRESOLVED"
                    ds["manufacturer"] = None
                    ds["manufacturer_country"] = None
                    ds["manufacturer_country_status"] = "NOT_APPLICABLE_NO_EXACT_PART_NUMBER"
                    ds["last_error"] = f"{type(exc).__name__}: {exc}"
                    data["manufacturer"] = None
                    data["country"] = None
                    self.store.save(path, data)
                    phase2_log(f"[PHASE2-BATCH-FAILED] {path.name} {type(exc).__name__}: {exc}")
            return sum(len(records) for records in grouped.values())

        self.datasheet_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for pn, records in grouped.items():
            phase2_log("\n" + "-" * 86)
            phase2_log(f"[PHASE2-PART] {pn} metadata_records={len(records)}")
            destination = self.datasheet_dir / f"{core.safe_filename(pn)}.pdf"
            entry = mouser_map.get(
                pn,
                MouserEntry(
                    None,
                    SourceDebug(
                        pn,
                        "mouser",
                        SOURCE_API_FAILED,
                        note="missing Mouser entry after batch search",
                    ),
                ),
            )
            try:
                result = resolve_one(
                    self._session, self._d4u, self._all_data, pn, destination, entry
                )
                for path, data in records:
                    apply_result(
                        data,
                        result,
                        project_root=self.project_root,
                        destination=destination,
                    )
                    self.store.save(path, data)
                    phase2_log(f"[PHASE2-SAVED] {path.name} status={data['datasheet']['status']}")
                    count += 1
            except Exception as exc:
                # Never leave a product silently stuck in searching.
                for path, data in records:
                    ds = data.setdefault("datasheet", {})
                    ds["status"] = "failed"
                    ds["identity_status"] = "EXACT_PART_NUMBER_UNRESOLVED"
                    ds["manufacturer"] = None
                    ds["manufacturer_country"] = None
                    ds["manufacturer_country_status"] = "NOT_APPLICABLE_NO_EXACT_PART_NUMBER"
                    ds["last_error"] = f"{type(exc).__name__}: {exc}"
                    data["manufacturer"] = None
                    data["country"] = None
                    self.store.save(path, data)
                    phase2_log(f"[PHASE2-FAILED] {path.name} {type(exc).__name__}: {exc}")
                    count += 1
        return count
