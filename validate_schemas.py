#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def check_schema(path: Path) -> None:
    Draft202012Validator.check_schema(read(path))


def validate_file(document_path: Path, schema_path: Path) -> None:
    document = read(document_path)
    schema = read(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        loc = '.'.join(str(x) for x in first.path) or '<root>'
        raise RuntimeError(f'{document_path}: {loc}: {first.message}')


def main() -> int:
    schemas = [ROOT/'metadata_schema.json', *sorted((ROOT/'schema').glob('*.json'))]
    for path in schemas:
        check_schema(path)
        print(f'[SCHEMA-OK] {path.relative_to(ROOT)}')

    groups = [
        (ROOT/'metadata', ROOT/'metadata_schema.json'),
        (ROOT/'phase3_outputs', ROOT/'schema'/'phase3_final_product.schema.json'),
        (ROOT/'products', ROOT/'schema'/'integrated_product.schema.json'),
    ]
    checked = 0
    for directory, schema in groups:
        for path in sorted(directory.glob('*.json')):
            validate_file(path, schema)
            checked += 1
            print(f'[DOCUMENT-OK] {path.relative_to(ROOT)}')
    print(f'[DONE] schemas={len(schemas)} runtime_documents={checked}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
