#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from core.category_registry import category_keys
from orchestrator.engine import IntegratedOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalog Automation Agent — Integrated V4")
    parser.add_argument("--mode", choices=("default", "manual"), required=True,
                        help="default reads input/; manual reads input_PN/ and trusts filename as PN")
    parser.add_argument("--category", choices=category_keys(), required=True,
                        help="Category key from config/category_registry.json; applies to the whole run")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    return IntegratedOrchestrator(root, input_mode=args.mode, category_key=args.category).run()


if __name__ == "__main__":
    raise SystemExit(main())
