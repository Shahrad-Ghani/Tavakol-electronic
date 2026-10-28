from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bundles.canonical_bundle import build_canonical_bundle
from core.metadata_v3 import SCHEMA_VERSION, deterministic_product_title, get_part_number, get_source_reference, utcnow
from metadata_manager import _migrate_legacy_record, save_admin_override
from orchestrator.adapter import sync_phase3_metadata, build_integrated_product


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected object: {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def migrate(root: Path, *, build_bundles: bool = True) -> dict:
    root = root.resolve()
    metadata_dir = root / "metadata"
    backup_dir = root / "migration_backups" / "metadata_v2_1_1"
    backup_dir.mkdir(parents=True, exist_ok=True)

    old_ready = root / "ready_for_upload"
    ready_backup = root / "migration_backups" / "ready_for_upload_v2_1_1"
    if old_ready.exists() and any(old_ready.iterdir()) and not ready_backup.exists():
        shutil.copytree(old_ready, ready_backup)
        shutil.rmtree(old_ready)
        old_ready.mkdir(parents=True, exist_ok=True)

    result = {
        "schema_version": SCHEMA_VERSION,
        "started_at": utcnow(),
        "migrated": 0,
        "already_v3": 0,
        "phase3_synced": 0,
        "phase3_titles_normalized": 0,
        "products_rebuilt": 0,
        "bundles_built": 0,
        "bundle_skipped": {},
        "errors": {},
    }

    for path in sorted(metadata_dir.glob("*.json")):
        try:
            raw = read_json(path)
            source_ref = str(raw.get("source_reference") or raw.get("img_refrence_name") or raw.get("product_id") or path.stem)
            if raw.get("schema_version") == SCHEMA_VERSION and "part_number" in raw:
                data = raw
                result["already_v3"] += 1
            else:
                backup = backup_dir / path.name
                if not backup.exists():
                    shutil.copy2(path, backup)
                data = _migrate_legacy_record(raw, source_ref)
                result["migrated"] += 1

            pn = get_part_number(data)
            if pn:
                data["product_title"] = deterministic_product_title(pn)
            save_admin_override(path, data)
            data = read_json(path)
            pn = get_part_number(data)
            if not pn:
                continue

            p3_path = root / "phase3_outputs" / f"{pn}.json"
            if p3_path.exists():
                p3 = read_json(p3_path)
                page = p3.setdefault("page", {})
                expected = deterministic_product_title(pn)
                if page.get("product_title") != expected:
                    page["product_title"] = expected
                    write_json(p3_path, p3)
                    result["phase3_titles_normalized"] += 1
                sync_phase3_metadata(root, path, p3_path)
                result["phase3_synced"] += 1
                try:
                    runtime = root / "runtime_state" / f"{get_source_reference(read_json(path))}.json"
                    runtime_data = read_json(runtime) if runtime.exists() else None
                    build_integrated_product(root, path, p3_path, runtime_data)
                    result["products_rebuilt"] += 1
                except Exception as exc:
                    result["errors"][f"product:{pn}"] = f"{type(exc).__name__}: {exc}"

            if build_bundles:
                current = read_json(path)
                audit = current.get("admin_audit") or {}
                if audit.get("status") == "APPROVED" and audit.get("classification") == "FINALIZED":
                    try:
                        build_canonical_bundle(root, path, current)
                        result["bundles_built"] += 1
                    except Exception as exc:
                        result["bundle_skipped"][pn] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            result["errors"][path.name] = f"{type(exc).__name__}: {exc}"

    result["completed_at"] = utcnow()
    report = root / "migration_backups" / "v3_migration_report.json"
    write_json(report, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Tavakol Integrated legacy metadata to V3 schema")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--no-bundles", action="store_true")
    args = parser.parse_args()
    result = migrate(args.root, build_bundles=not args.no_bundles)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
