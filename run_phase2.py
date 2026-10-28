#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from phase2 import core_runtime as core
from phase2.pipeline import Phase2Pipeline
from phase2.metadata_state import MetadataStore
from metadata_manager import save_phase2 as phase2_save_metadata


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Tavakol Electronic Phase 2 Production V1.0 — read metadata JSON, "
            "resolve exact datasheets in Mouser micro-batches <=10, update JSON."
        )
    )
    p.add_argument("--project-root", type=Path, default=Path("."))
    p.add_argument("--metadata-dir", type=Path)
    p.add_argument("--datasheet-dir", type=Path)
    p.add_argument("--proxies", type=Path)
    p.add_argument("--debug-dir", type=Path)
    p.add_argument("--schema", type=Path)
    p.add_argument("--no-schema-validation", action="store_true")
    p.add_argument("--api-key")
    p.add_argument("--retry-not-found", action="store_true")
    p.add_argument("--retry-manual", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="0 = all currently eligible metadata")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    metadata_dir = (args.metadata_dir or (root / "metadata")).resolve()
    datasheet_dir = (args.datasheet_dir or (root / "datasheets")).resolve()
    proxy_file = (args.proxies or (root / "proxies.txt")).resolve()
    debug_dir = (args.debug_dir or (root / "debug_html")).resolve()

    schema_path = None
    if not args.no_schema_validation:
        candidate = args.schema or (root / "metadata_schema.json")
        if candidate.exists():
            schema_path = candidate.resolve()

    api_key = core.resolve_api_key(args.api_key, root / ".env")
    store = MetadataStore(root, save_callback=phase2_save_metadata)
    pipeline = Phase2Pipeline(
        project_root=root,
        metadata_dir=metadata_dir,
        datasheet_dir=datasheet_dir,
        proxy_file=proxy_file,
        api_key=api_key,
        debug_dir=debug_dir,
        schema_path=schema_path,
        metadata_store=store,
        retry_not_found=args.retry_not_found,
        retry_manual=args.retry_manual,
    )
    paths = pipeline.eligible_paths()
    if args.limit > 0:
        paths = paths[:args.limit]
    print(f"[PHASE2] eligible_now={len(paths)} | mouser_micro_batch_max=10 | global_wait_target=NONE")
    processed = pipeline.process_available(paths)
    print(f"[PHASE2-DONE] metadata_processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
