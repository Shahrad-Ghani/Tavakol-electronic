import json
from pathlib import Path

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path, data):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def read_text(path):
    return Path(path).read_text(encoding="utf-8")

def resolve(base_file, maybe_path):
    if not maybe_path: return None
    p=Path(maybe_path)
    return p if p.is_absolute() else (Path(base_file).parent/p).resolve()
