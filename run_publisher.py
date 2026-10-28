#!/usr/bin/env python3
from pathlib import Path

from bundles.canonical_bundle import prepare_approved_bundles
from phase4.publisher import main as publisher_main


def main() -> int:
    root = Path(__file__).resolve().parent
    result = prepare_approved_bundles(root)
    print(
        "Canonical bundle preparation | "
        f"built={len(result['built'])} | rebuilt={len(result.get('rebuilt', []))} | "
        f"existing={len(result['existing'])} | not_ready={len(result['errors'])} | "
        f"skipped={len(result['skipped'])}",
        flush=True,
    )
    if result["errors"]:
        for pn, error in sorted(result["errors"].items()):
            print(f"BUNDLE NOT READY | {pn} | {error}", flush=True)
    # Product-specific staging failures do not block other approved products.
    return publisher_main()


if __name__ == "__main__":
    raise SystemExit(main())
