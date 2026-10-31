from __future__ import annotations

import json
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from metadata_manager import save_phase2 as save_phase2_metadata
from metadata_manager import save as save_metadata
from metadata_manager import portable_path, resolve_recorded_path
from pipeline import process_one, set_phase1_log_sink
from admin_audit import (
    apply_batch_category,
    find_pn_input_images,
    mark_phase1_reprocessed_if_image_only,
    mark_phase3_reprocessed,
    post_phase2_admin_hook,
    prepare_pn_input_metadata,
)
from preflight import find_images, run_preflight
from phase2 import Phase2Pipeline
from phase2.metadata_state import MetadataStore, is_phase2_eligible
from phase2.logging_bridge import set_phase2_log_sink
from phase2 import core_runtime as phase2_core
from phase2.banner_injector import inject_batch
from integrated_pipeline import IntegratedPhase3Pipeline, set_phase3_log_sink

from .adapter import build_phase3_input, build_integrated_product, sync_phase3_metadata, read_json
from core.metadata_v3 import get_part_number, get_source_reference, image_finalized, sync_category
from .events import EventLogger
from .runtime_guard import RecoveryController, RuntimeStop, classify_exception, host_reachable
from .state_store import StateStore


P2_TERMINAL_TO_PHASE3 = {"completed", "not_found_confirmed", "identity_found_unresolved", "sales_only_no_datasheet"}
_SENTINEL = object()


class IntegratedOrchestrator:
    """Streaming P1 -> P2 -> P3 orchestrator with per-item checkpoints.

    - Phase 1 uses a bounded thread pool (default 10); image API requests are independent.
    - The moment OCR produces a stable PN, Phase 2 is queued immediately.
    - Phase 2 resolves one item immediately (no wait for a 10-item micro-batch).
    - As soon as Phase 2 reaches a terminal datasheet decision, Phase 3 starts.
    - P1/P2/P3 therefore overlap across different products.
    """

    def __init__(self, root: Path, event_logger: Optional[EventLogger] = None, *, input_mode: str = "default", category_key: str | None = None):
        self.root = Path(root).resolve()
        self.input_mode = str(input_mode or "default").strip().lower()
        if self.input_mode not in {"default", "manual"}:
            raise ValueError(f"Unsupported input mode: {input_mode!r}")
        # UI V4 enforces explicit category selection before Start.  The engine
        # keeps an IC default for backwards-compatible programmatic/tests use.
        self.category_key = str(category_key or "").strip() or "ic"
        load_dotenv(self.root / ".env", override=True)
        self.log = event_logger or EventLogger(self.root)
        self.state = StateStore(self.root)
        self.recovery = RecoveryController(
            self.log, retry_seconds=float(os.getenv("NETWORK_RETRY_SECONDS", "10"))
        )
        self._p2q: "queue.Queue" = queue.Queue()
        self._p3q: "queue.Queue" = queue.Queue()
        self._p2_seen: set[str] = set()
        self._p3_seen: set[str] = set()
        self._seen_lock = threading.Lock()
        self._phase2: Optional[Phase2Pipeline] = None
        self._phase3: Optional[IntegratedPhase3Pipeline] = None
        self.p1_workers = max(1, int(os.getenv('ALTIMATE_PHASE1_WORKERS', '10')))
        self.p3_workers = max(1, int(os.getenv('ALTIMATE_PHASE3_WORKERS', '10')))
        self._pn_owner: dict[str,str] = {}
        self._pn_owner_lock = threading.Lock()
        self._product_build_lock = threading.RLock()
        self._openai_client = None
        self._threads: list[threading.Thread] = []
        self.running = False

        set_phase1_log_sink(self.log.bridge("P1", "DETAIL"))
        set_phase2_log_sink(self.log.bridge("P2", "DETAIL"))
        set_phase3_log_sink(self.log.bridge("P3", "DETAIL"))

    # ------------------------------------------------------------------
    # Preflight / recovery
    # ------------------------------------------------------------------
    def _build_phase2(self) -> Phase2Pipeline:
        key = os.getenv("MOUSER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("MOUSER_API_KEY is missing")
        proxy_file = self.root / (os.getenv("PHASE2_PROXY_FILE", "proxies.txt").strip() or "proxies.txt")
        if not proxy_file.exists():
            raise RuntimeError(f"Phase 2 proxy file missing: {proxy_file}")
        store = MetadataStore(self.root, save_callback=save_phase2_metadata)
        return Phase2Pipeline(
            project_root=self.root,
            metadata_dir=self.root / "metadata",
            datasheet_dir=self.root / "datasheets",
            proxy_file=proxy_file,
            api_key=key,
            debug_dir=self.root / "debug_html",
            metadata_store=store,
            retry_not_found=False,
            retry_manual=False,
        )

    def _check_openai(self) -> bool:
        try:
            if not host_reachable("api.openai.com"):
                return False
            # Re-create client so a changed .env key can recover without app restart.
            load_dotenv(self.root / ".env", override=True)
            from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI
            key = os.getenv("OPENAI_API_KEY", "").strip()
            if not key:
                return False
            client = OpenAI(api_key=key)
            client.models.list()
            self._openai_client = client
            return True
        except Exception:
            return False

    def _check_mouser(self) -> bool:
        try:
            load_dotenv(self.root / ".env", override=True)
            self._phase2 = self._build_phase2()
            self._phase2._ensure_network()
            assert self._phase2._session is not None
            # One cheap exact lookup validates both proxy/network and API key.
            limiter = phase2_core.SearchRateLimiter(min_interval=0.0)
            phase2_core.mouser_search_batch(
                self._phase2._session,
                self._phase2.api_key,
                [os.getenv("MOUSER_PREFLIGHT_PART", "NE555")],
                limiter,
            )
            return True
        except Exception:
            return False

    def _startup_preflight(self):
        self.log.emit("SYS", "INFO", "-", "PREFLIGHT", "checking directories, internet, OpenAI and Mouser")
        while True:
            if self.recovery.stop_requested:
                raise RuntimeStop("stopped")
            try:
                # This validates folders/logo/config and OpenAI auth.
                self._openai_client = run_preflight(self.root)
                self.log.emit("SYS", "OK", "-", "OPENAI", "API connection/authentication OK")
            except Exception as exc:
                failure = classify_exception(exc, "openai")
                if failure.fatal:
                    self.recovery.stop_for_fatal(failure, "SYS", "-")
                if failure.retryable:
                    self.recovery.wait_network_recovery("SYS", "-", "OpenAI/internet", self._check_openai)
                    continue
                raise

            try:
                self._phase2 = self._build_phase2()
                self._phase2._ensure_network()
                assert self._phase2._session is not None
                limiter = phase2_core.SearchRateLimiter(min_interval=0.0)
                phase2_core.mouser_search_batch(
                    self._phase2._session,
                    self._phase2.api_key,
                    [os.getenv("MOUSER_PREFLIGHT_PART", "NE555")],
                    limiter,
                )
                self.log.emit("SYS", "OK", "-", "MOUSER", "proxy/network/API key OK")
            except Exception as exc:
                failure = classify_exception(exc, "mouser")
                if failure.fatal:
                    self.recovery.stop_for_fatal(failure, "SYS", "-")
                if failure.retryable:
                    self.recovery.wait_network_recovery("SYS", "-", "Mouser/internet", self._check_mouser)
                    continue
                raise
            break

        # Phase 3 uses the same OpenAI account but its own configured models.
        # Each Phase3 worker creates its own isolated pipeline instance.
        self.log.emit("SYS", "OK", "-", "PREFLIGHT", "all services ready; pipeline starting")

    def _handle_failure(self, exc: BaseException, phase: str, item: str, service_hint: str) -> bool:
        """Return True when caller should retry the item from checkpoint."""
        failure = classify_exception(exc, service_hint)
        if failure.fatal:
            self.recovery.stop_for_fatal(failure, phase, item)
        if failure.retryable:
            checker = self._check_openai if service_hint == "openai" else self._check_mouser
            self.recovery.wait_network_recovery(phase, item, service_hint, checker)
            return True
        self.log.emit(phase, "ERROR", item, failure.kind, failure.message)
        return False

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    def _enqueue_p2(self, source_key: str, metadata_path: Path, pn: str):
        key = str(Path(metadata_path).resolve()).casefold()
        with self._seen_lock:
            if key in self._p2_seen:
                return
            self._p2_seen.add(key)
        self.state.update(source_key, part_number=pn, metadata_path=str(metadata_path), phase2="QUEUED")
        self._p2q.put((source_key, Path(metadata_path), pn, key))
        self.log.emit("P2", "INFO", pn, "QUEUED", "PartNumber ready; datasheet resolution queued immediately")

    def _enqueue_p3(self, source_key: str, metadata_path: Path, pn: str, *, force: bool = False, force_fact_extraction: bool = False):
        key = str(Path(metadata_path).resolve()).casefold()
        with self._seen_lock:
            if key in self._p3_seen:
                return
            self._p3_seen.add(key)
        self.state.update(source_key, part_number=pn, metadata_path=str(metadata_path), phase3="QUEUED")
        self._p3q.put((source_key, Path(metadata_path), pn, key, bool(force), bool(force_fact_extraction)))
        detail = "Phase 2 resolved; content generation queued immediately"
        if force or force_fact_extraction:
            detail += f" | force={bool(force)} | force_fact_extraction={bool(force_fact_extraction)}"
        self.log.emit("P3", "INFO", pn, "QUEUED", detail)

    def _pn_ready_callback(self, source_key: str):
        def _callback(metadata_path, data, ref):
            pn = get_part_number(data)
            if not pn:
                return
            with self._pn_owner_lock:
                claimed = self._pn_owner.get(pn.casefold())
                if claimed and claimed != source_key:
                    self.log.emit('P1','WARN',pn,'PN_DUPLICATE',f'PN already claimed by {claimed}; skip queue')
                    return
                self._pn_owner[pn.casefold()] = source_key
            category_result = apply_batch_category(self.root, Path(metadata_path), data, self.category_key)
            if category_result.get("blocked"):
                self.log.emit("P1", "ERROR", pn, "CATEGORY_CHANGE_BLOCKED",
                              "This Part Number already has a WordPress product; category was not changed")
                return
            self.state.update(source_key, part_number=pn, metadata_path=str(metadata_path), phase1="PN_READY")
            authority = str((data.get("ocr") or {}).get("manual_authority") or "OCR")
            self.log.emit("P1", "OK", pn, "PN_READY", f"PartNumber confirmed; authority={authority}; metadata={Path(metadata_path).name}")
            audit = data.get("admin_audit") or {}
            issues = set(audit.get("selected_issues") or [])
            # Image-only reprocessing must not cascade into Phase 2/3.
            if audit.get("status") == "DISAPPROVED_PENDING_REPROCESS" and issues == {"image_regeneration_needed"}:
                return
            # For an explicit SEO-only audit issue, Phase 2 remains valid.
            if audit.get("status") == "DISAPPROVED_PENDING_REPROCESS" and issues == {"seo_content_regeneration_needed"}:
                return
            latest = read_json(Path(metadata_path))
            eligible, reason = is_phase2_eligible(latest, self.root)
            if eligible:
                self._enqueue_p2(source_key, Path(metadata_path), pn)
            else:
                self.log.emit("P2", "SKIP", pn, "CHECKPOINT_PROTECTED", reason)
                ds_status = str((latest.get("datasheet") or {}).get("status") or "")
                p3_status = str((latest.get("phase3") or {}).get("status") or "")
                if ds_status in P2_TERMINAL_TO_PHASE3 and p3_status != "completed":
                    self._enqueue_p3(source_key, Path(metadata_path), pn)
        return _callback

    # ------------------------------------------------------------------
    # Resume helpers
    # ------------------------------------------------------------------
    def _find_metadata_for_source(self, source_stem: str) -> Optional[Path]:
        direct = self.root / "metadata" / f"{source_stem}.json"
        if direct.exists():
            return direct
        for path in (self.root / "metadata").glob("*.json"):
            try:
                if get_source_reference(read_json(path)) == source_stem:
                    return path
            except Exception:
                pass
        return None

    def _phase1_final_checkpoint(self, data: dict) -> tuple[bool, Optional[Path]]:
        """Recognize both V1.1 and legacy V1.0 finalized Phase-1 checkpoints.

        Integrated V1.0 could leave status.image_optimized=false after a real
        FINALIZED run.  The durable evidence is image_optimization.status plus
        the actual Final image on disk.  This gate prevents expensive
        regeneration/OCR from being repeated when migrating an old run into
        V1.1.
        """
        image_opt = data.get("image_optimization") or {}
        if str(image_opt.get("status") or "").lower() != "completed":
            return False, None
        recorded = str(image_opt.get("file") or "").strip()
        if not recorded:
            return False, None
        path = resolve_recorded_path(self.root, recorded)
        if path is not None and path.exists():
            return True, path
        # Migration fallback: an old absolute path can point at the V1.0 repo.
        # If the user copied Final/ into V1.1, recover by the canonical basename.
        basename = Path(recorded.replace("\\", "/")).name
        fallback = self.root / "Final" / basename
        if basename and fallback.exists():
            return True, fallback
        return False, None

    def _repair_legacy_phase1_status(self, metadata_path: Path, data: dict, final_path: Path) -> None:
        """V3 repair: detailed image_optimization state is authoritative; no summary booleans are persisted."""
        image_opt = data.setdefault("image_optimization", {})
        portable = portable_path(self.root, final_path)
        changed = False
        if image_opt.get("file") != portable:
            image_opt["file"] = portable; changed = True
        if image_opt.get("status") != "completed":
            image_opt["status"] = "completed"; changed = True
        if changed:
            save_metadata(metadata_path, data)

    def _resume_scan(self):
        resumed_p2 = resumed_p3 = 0
        for path in sorted((self.root / "metadata").glob("*.json")):
            try:
                data = read_json(path)
            except Exception:
                continue
            pn = get_part_number(data)
            if not pn:
                continue
            source_key = get_source_reference(data) or pn
            try:
                category_result = apply_batch_category(self.root, path, data, self.category_key)
                if category_result.get("blocked"):
                    self.log.emit("SYS", "WARN", pn, "CATEGORY_CHANGE_BLOCKED",
                                  "Existing WordPress product is protected from batch category reassignment")
                    continue
                if category_result.get("changed"):
                    self.log.emit(
                        "SYS", "WARN" if category_result.get("invalidated_downstream") else "INFO",
                        pn, "BATCH_CATEGORY_APPLIED",
                        f"{category_result.get('old_category')} -> {category_result.get('new_category')} | "
                        f"downstream_invalidated={bool(category_result.get('invalidated_downstream'))}",
                    )
                    data = read_json(path)
            except Exception as exc:
                self.log.emit("SYS", "ERROR", pn, "BATCH_CATEGORY_FAILED", str(exc))
                continue
            ds_status = str((data.get("datasheet") or {}).get("status") or "pending")
            audit = data.get("admin_audit") or {}
            audit_status = str(audit.get("status") or "")
            issues = set(audit.get("selected_issues") or [])
            force_p2 = bool(audit.get("force_phase2"))
            force_seo = bool(audit.get("force_seo"))
            force_fact = bool(audit.get("force_fact_extraction"))
            p3_json = self.root / "phase3_outputs" / f"{pn}.json"

            if ds_status == "web_error":
                self.state.update(source_key, part_number=pn, metadata_path=str(path), phase2="WEB_ERROR", phase3="BLOCKED_AWAITING_ADMIN_DECISION")
                self.log.emit("P2", "WARN", pn, "WEB_ERROR", "Datasheet source access failed; choose PDF or sales-only in Audit")
                continue

            if ds_status == "manual_required":
                self.state.update(source_key, part_number=pn, metadata_path=str(path), phase2="MANUAL_REQUIRED", phase3="BLOCKED_MANUAL_DATASHEET")
                self.log.emit("P2", "WARN", pn, "MANUAL_REQUIRED", "Phase 3 blocked until admin attaches the datasheet PDF in Audit")
                continue

            # Audit invalidations override ordinary cached terminal checkpoints.
            if audit_status == "DISAPPROVED_PENDING_REPROCESS":
                if force_p2 or ds_status not in P2_TERMINAL_TO_PHASE3:
                    self._enqueue_p2(source_key, path, pn); resumed_p2 += 1
                    continue
                if force_seo:
                    self._enqueue_p3(source_key, path, pn, force=True, force_fact_extraction=force_fact); resumed_p3 += 1
                    continue
                # Image-only is handled by the Phase-1 input loop.
                if issues == {"image_regeneration_needed"}:
                    continue

            if ds_status in P2_TERMINAL_TO_PHASE3:
                if not p3_json.exists():
                    if str((data.get('phase3') or {}).get('status') or '') == 'completed':
                        # This distributed ZIP intentionally omits historical Phase3 outputs.
                        # Never silently pay for regenerating an already completed product.
                        self.log.emit('P3','WARN',pn,'MISSING_COMPLETED_ARTIFACT',
                                      'Metadata says completed but phase3_outputs missing. Restore artifacts or explicitly request SEO regeneration in Audit.')
                        continue
                    self._enqueue_p3(source_key, path, pn); resumed_p3 += 1
                else:
                    # Reading a finished checkpoint must not rewrite old Metadata.
                    self.state.update(source_key, part_number=pn, metadata_path=str(path), phase2='COMPLETED', phase3='COMPLETED')
            else:
                eligible, reason = is_phase2_eligible(data, self.root)
                if eligible:
                    self._enqueue_p2(source_key, path, pn); resumed_p2 += 1
                else:
                    self.log.emit("P2", "SKIP", pn, "CHECKPOINT_PROTECTED", reason)
        if resumed_p2 or resumed_p3:
            self.log.emit("SYS", "INFO", "-", "RESUME", f"recovered queues | phase2={resumed_p2} | phase3={resumed_p3}")

    # ------------------------------------------------------------------
    # Phase workers
    # ------------------------------------------------------------------
    def _run_pn_input_image(self, image: Path):
        pn = image.stem.strip()
        try:
            meta_path, data = prepare_pn_input_metadata(self.root, image)
        except Exception as exc:
            self.log.emit("P1", "ERROR", pn or image.name, "PN_INPUT", str(exc))
            return
        source_key = get_source_reference(data) or pn
        self.log.emit("P1", "INFO", pn, "PN_INPUT", f"trusted filename PartNumber; OCR extraction skipped | source={image.name}")
        # Manual filename already establishes PN: P2 begins before expensive image calls.
        self._pn_ready_callback(source_key)(meta_path, data, source_key)
        self._run_phase1_image(image, source_key_override=source_key)

    @staticmethod
    def _latest_phase1_error(data: dict) -> str:
        fields = ["precheck", "regeneration", "identity_validation", "ocr", "logo", "image_optimization"]
        for key in reversed(fields):
            value = (data.get(key) or {}).get("last_error")
            if value:
                return str(value)
        return "Phase 1 did not complete"

    def _run_phase1_image(self, image: Path, source_key_override: str | None = None):
        source_key = source_key_override or image.stem
        while True:
            self.recovery.wait_manual()
            if self.recovery.stop_requested or self.recovery.fatal_failure:
                raise RuntimeStop("stopped")
            self.state.update(source_key, phase1="RUNNING", last_error=None)
            self.log.emit("P1", "INFO", source_key, "START", f"source={image.name}")

            # Fast local checkpoint gate.  A manually audited or already-finalized
            # source must never repeat regeneration/OCR simply because the original
            # input image is still present.
            existing_meta = self._find_metadata_for_source(source_key)
            if existing_meta:
                try:
                    existing_data = read_json(existing_meta)
                    manual_status = str((existing_data.get("manual_audit") or {}).get("status") or "")
                    if manual_status == "duplicate_final_exists":
                        self.state.update(source_key, phase1="SKIPPED_DUPLICATE", last_error=None)
                        self.log.emit("P1", "SKIP", source_key, "AUDIT_DUPLICATE", "manual audit resolved this source as duplicate")
                        return
                    finalized, final_path = self._phase1_final_checkpoint(existing_data)
                    if finalized and final_path is not None:
                        self._repair_legacy_phase1_status(existing_meta, existing_data, final_path)
                        pn_existing = get_part_number(existing_data) or source_key
                        self.state.update(
                            source_key, part_number=pn_existing, metadata_path=str(existing_meta),
                            phase1="COMPLETED", last_error=None,
                        )
                        self.log.emit(
                            "P1", "SKIP", pn_existing, "CHECKPOINT",
                            "Phase 1 already finalized (including legacy V1.0 checkpoint); no API calls repeated",
                        )
                        return
                except Exception as exc:
                    self.log.emit("P1", "WARN", source_key, "CHECKPOINT_READ", str(exc))

            try:
                process_one(
                    self._openai_client,
                    image,
                    self.root / "logs" / f"phase1_native_{time.strftime('%Y%m%d')}.log",
                    phase2_coordinator=None,
                    on_part_number_ready=self._pn_ready_callback(source_key),
                )
            except RuntimeStop:
                raise
            except Exception as exc:
                if self._handle_failure(exc, "P1", source_key, "openai"):
                    continue
                self.state.update(source_key, phase1="ERROR", last_error=str(exc))
                return

            meta_path = self._find_metadata_for_source(source_key)
            if not meta_path:
                self.state.update(source_key, phase1="ERROR", last_error="metadata not created")
                self.log.emit("P1", "ERROR", source_key, "METADATA", "metadata file not found")
                return
            data = read_json(meta_path)
            pn = get_part_number(data) or source_key
            if image_finalized(data):
                self.state.update(source_key, part_number=pn, metadata_path=str(meta_path), phase1="COMPLETED", last_error=None)
                self.log.emit("P1", "OK", pn, "COMPLETED", f"final_image={data.get('image_optimization',{}).get('file')}")
                p3_json = self.root / "phase3_outputs" / f"{pn}.json"
                if p3_json.exists():
                    try:
                        build_integrated_product(self.root, meta_path, p3_json, self.state.load(source_key))
                        self.log.emit("SYS", "OK", pn, "FINAL_JSON_REFRESH", "Phase 1 final image checkpoint merged")
                    except Exception as exc:
                        self.log.emit("SYS", "WARN", pn, "FINAL_JSON_REFRESH", str(exc))
                try:
                    mark_phase1_reprocessed_if_image_only(meta_path)
                except Exception as exc:
                    self.log.emit("SYS", "WARN", pn, "AUDIT_STATE", str(exc))
                return

            err = self._latest_phase1_error(data)
            failure = classify_exception(RuntimeError(err), "openai")
            if failure.fatal:
                self.recovery.stop_for_fatal(failure, "P1", pn)
            if failure.retryable:
                self.recovery.wait_network_recovery("P1", pn, "OpenAI/internet", self._check_openai)
                continue
            self.state.update(source_key, part_number=pn, metadata_path=str(meta_path), phase1="ERROR", last_error=err)
            self.log.emit("P1", "ERROR", pn, "STOPPED_ITEM", err)
            return

    def _phase2_worker(self):
        while True:
            job = self._p2q.get()
            if job is _SENTINEL:
                self._p2q.task_done(); return
            source_key, meta_path, pn, seen_key = job
            try:
                if self.recovery.stop_requested or self.recovery.fatal_failure:
                    continue
                while True:
                    self.recovery.wait_manual()
                    self.state.update(source_key, phase2="RUNNING", last_error=None)
                    self.log.emit("P2", "INFO", pn, "START", "immediate single-item datasheet resolution")
                    try:
                        current = read_json(meta_path)
                        eligible, reason = is_phase2_eligible(current, self.root)
                        if not eligible:
                            self.log.emit("P2", "SKIP", pn, "LATE_QUEUE_PROTECTED", reason)
                        else:
                            assert self._phase2 is not None
                            self._phase2.process_batch([meta_path])
                    except RuntimeStop:
                        raise
                    except Exception as exc:
                        if self._handle_failure(exc, "P2", pn, "mouser"):
                            self._phase2 = self._build_phase2()
                            continue
                        self.state.update(source_key, phase2="ERROR", last_error=str(exc)); break

                    data = read_json(meta_path)
                    ds = data.get("datasheet") or {}
                    status = str(ds.get("status") or "failed")
                    package = (ds.get("package") or {}).get("value")
                    if status == "web_error":
                        self.state.update(source_key, phase2="WEB_ERROR", phase3="BLOCKED_AWAITING_ADMIN_DECISION", last_error=None)
                        self.log.emit("P2", "WARN", pn, "WEB_ERROR", "Online search blocked or failed; choose manual PDF or continue without PDF in Audit")
                        break
                    if status == "manual_required":
                        self.state.update(source_key, phase2="MANUAL_REQUIRED", phase3="BLOCKED_MANUAL_DATASHEET", last_error=None)
                        self.log.emit("P2", "WARN", pn, "MANUAL_REQUIRED", "Exact/manual source found but PDF is missing; Phase 3 is blocked until admin attaches the PDF in Audit")
                        break
                    if status in P2_TERMINAL_TO_PHASE3:
                        self.state.update(source_key, phase2="COMPLETED", last_error=None)
                        detail = f"datasheet_status={status}"
                        if package:
                            detail += f" | package={package} | source=Mouser Package/Case"
                        self.log.emit("P2", "OK", pn, "RESOLVED", detail)
                        try:
                            route = post_phase2_admin_hook(self.root, meta_path)
                        except Exception as exc:
                            route = {"handled_locally": False, "force_seo": True, "force_fact_extraction": False}
                            self.log.emit("SYS", "WARN", pn, "AUDIT_POST_P2", str(exc))
                        if route.get("handled_locally"):
                            p3_json = self.root / "phase3_outputs" / f"{pn}.json"
                            if p3_json.exists():
                                try:
                                    build_integrated_product(self.root, meta_path, p3_json, self.state.load(source_key))
                                except Exception as exc:
                                    self.log.emit("SYS", "WARN", pn, "FINAL_JSON_REFRESH", str(exc))
                            self.state.update(source_key, phase3="COMPLETED", last_error=None)
                            self.log.emit("P3", "OK", pn, "PROGRAMMATIC_PN_REPAIR", "old/new PN both have no datasheet; previous SEO content repaired locally with zero Phase-3 API calls")
                        else:
                            self._enqueue_p3(
                                source_key, meta_path, pn,
                                force=bool(route.get("force_seo")),
                                force_fact_extraction=bool(route.get("force_fact_extraction")),
                            )
                        break

                    err = str(ds.get("last_error") or status)
                    failure = classify_exception(RuntimeError(err), "mouser")
                    if failure.fatal:
                        self.recovery.stop_for_fatal(failure, "P2", pn)
                    if failure.retryable:
                        self.recovery.wait_network_recovery("P2", pn, "Mouser/internet", self._check_mouser)
                        self._phase2 = self._build_phase2()
                        continue
                    self.state.update(source_key, phase2="ERROR", last_error=err)
                    self.log.emit("P2", "ERROR", pn, "UNRESOLVED", err)
                    break
            except RuntimeStop:
                pass
            finally:
                with self._seen_lock:
                    self._p2_seen.discard(seen_key)
                self._p2q.task_done()

    def _phase3_worker(self):
        # No shared mutable OpenAI file manager between concurrent products.
        local_phase3 = None
        while True:
            job = self._p3q.get()
            if job is _SENTINEL:
                self._p3q.task_done(); return
            source_key, meta_path, pn, seen_key, force, force_fact_extraction = job
            try:
                if self.recovery.stop_requested or self.recovery.fatal_failure:
                    continue
                while True:
                    self.recovery.wait_manual()
                    self.state.update(source_key, phase3="RUNNING", last_error=None)
                    self.log.emit("P3", "INFO", pn, "START", "building Phase 3 input from Phase 1+2 checkpoints")
                    try:
                        # A ZIP may omit datasheet assets. Never silently turn a
                        # verified-PDF product into an unapproved sales-only item.
                        live_meta = read_json(meta_path)
                        live_ds = live_meta.get('datasheet') or {}
                        if live_ds.get('status') == 'completed':
                            recorded = resolve_recorded_path(self.root, live_ds.get('file'))
                            target_pdf = recorded if recorded and recorded.is_file() else self.root / 'datasheets' / f'{pn}.pdf'
                            if not target_pdf.is_file():
                                raise FileNotFoundError(f'DATASHEET_ASSET_MISSING: {pn}, restore exact PDF to {target_pdf}')
                        input_path, _ = build_phase3_input(self.root, meta_path)
                        if local_phase3 is None:
                            local_phase3 = IntegratedPhase3Pipeline(self.root)
                        result = local_phase3.process(
                            input_path,
                            self.root / "datasheets",
                            self.root / "phase3_outputs",
                            force=bool(force),
                            force_fact_extraction=bool(force_fact_extraction),
                        )
                        p3_json = Path(result["json"])
                        sync_phase3_metadata(self.root, meta_path, p3_json)
                        self.state.update(source_key, phase3="COMPLETED", last_error=None)
                        with self._product_build_lock:
                            final_path, final_data = build_integrated_product(
                                self.root, meta_path, p3_json, self.state.load(source_key)
                            )
                        self.log.emit(
                            "P3", "OK", pn, "COMPLETED",
                            f"seo={result['score']}/100 | disposition={result['disposition']} | final_json={final_path.name}",
                        )
                        try:
                            mark_phase3_reprocessed(self.root, meta_path)
                        except Exception as exc:
                            self.log.emit("SYS", "WARN", pn, "AUDIT_STATE", str(exc))
                        break
                    except RuntimeStop:
                        raise
                    except Exception as exc:
                        if isinstance(exc, FileNotFoundError) and 'DATASHEET_ASSET_MISSING' in str(exc):
                            self.state.update(source_key, phase3='BLOCKED_MISSING_PDF', last_error=str(exc))
                            self.log.emit('P3','ERROR',pn,'MISSING_PDF',str(exc))
                            break
                        if self._handle_failure(exc, "P3", pn, "openai"):
                            # Phase3 work artifacts are checkpointed; rerun resumes/caches safely.
                            local_phase3 = None
                            continue
                        self.state.update(source_key, phase3="ERROR", last_error=str(exc))
                        break
            except RuntimeStop:
                pass
            finally:
                with self._seen_lock:
                    self._p3_seen.discard(seen_key)
                self._p3q.task_done()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------
    def run(self) -> int:
        if self.running:
            raise RuntimeError("orchestrator is already running")
        self.running = True
        try:
            self._startup_preflight()
            p2t = threading.Thread(target=self._phase2_worker, name="phase2-worker", daemon=True)
            p3_workers = [threading.Thread(target=self._phase3_worker, name=f"phase3-worker-{i+1}", daemon=True) for i in range(self.p3_workers)]
            self._threads = [p2t, *p3_workers]
            for t in self._threads:
                t.start()

            self._resume_scan()

            if self.input_mode == 'manual':
                images = find_pn_input_images(self.root)
                self.log.emit('SYS','INFO','-','PN_INPUT_DISCOVER',f'mode=manual | images={len(images)} | category={self.category_key}')
            else:
                images = find_images(self.root)
                self.log.emit('SYS','INFO','-','DISCOVER',f'mode=default | images={len(images)} | category={self.category_key}')
            # Existing P2/P3 resume queues are sufficient to run a content-only batch.
            # A blank manual input must not abort the pending Phase3 jobs.
            if not images and not (self._p2q.unfinished_tasks or self._p3q.unfinished_tasks):
                self.log.emit('SYS','INFO','-','NO_WORK','No new inputs and no eligible pending work')
            if images:
                # Each discovered file is submitted once; ownership for identical PN
                # is checked again after OCR/manual filename confirmation.
                seen_inputs = set()
                unique_images = []
                for image in images:
                    key = str(Path(image).resolve()).casefold()
                    if key not in seen_inputs:
                        unique_images.append(image); seen_inputs.add(key)
                with ThreadPoolExecutor(max_workers=self.p1_workers, thread_name_prefix='phase1-worker') as pool:
                    futures = [pool.submit(self._run_pn_input_image if self.input_mode == 'manual' else self._run_phase1_image, image) for image in unique_images]
                    for future in futures:
                        try: future.result()
                        except RuntimeStop: self.recovery.request_stop()
                        except Exception as exc: self.log.emit('P1','ERROR','-','WORKER_FAILURE',str(exc))
            if not self.recovery.fatal_failure and not self.recovery.stop_requested:
                self._p2q.join()
                banner_result = inject_batch(
                    self.root / "datasheets",
                    self.root / "assets" / "banner.png",
                    "https://tavakolelectronic.com/",
                    output_dir=self.root / "datasheets_branded",
                )
                if banner_result["errors"]:
                    self.log.emit("P2", "WARN", "-", "DATASHEET_BANNER", f"changed={len(banner_result['changed'])} | output={banner_result.get('output_dir')} | errors={banner_result['errors']}")
                else:
                    self.log.emit("P2", "OK", "-", "DATASHEET_BANNER", f"changed={len(banner_result['changed'])} | already_done={len(banner_result['skipped'])} | output={banner_result.get('output_dir')}")
                self._p3q.join()
                self.log.emit("SYS", "OK", "-", "DONE", "all available products reached their latest terminal checkpoint")
                return 0
            self.log.emit("SYS", "ERROR", "-", "STOPPED", "pipeline stopped before all queued work completed")
            return 1
        except RuntimeStop:
            self.log.emit("SYS", "ERROR", "-", "STOPPED", "runtime stop condition reached")
            return 1
        except Exception as exc:
            self.log.emit("SYS", "ERROR", "-", "UNHANDLED", f"{type(exc).__name__}: {exc}")
            return 1
        finally:
            self.recovery.stop_requested = True
            # Drain workers safely; queued jobs see stop_requested and are acknowledged.
            try: self._p2q.put(_SENTINEL)
            except Exception: pass
            for _ in range(self.p3_workers):
                try: self._p3q.put(_SENTINEL)
                except Exception: pass
            for t in self._threads:
                t.join(timeout=5)
            self.running = False

    def pause(self):
        self.recovery.request_pause()

    def resume(self):
        self.recovery.request_resume()

    def stop(self):
        self.recovery.request_stop()
