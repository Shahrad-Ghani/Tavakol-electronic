from pathlib import Path
import json
from jsonschema import Draft202012Validator

def validate_json(data, schema_path):
    schema=json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e:list(e.path))
    if errors:
        lines=[]
        for e in errors[:20]:
            loc=".".join(str(x) for x in e.path) or "<root>"
            lines.append(f"{loc}: {e.message}")
        raise ValueError("Schema validation failed:\n"+"\n".join(lines))
