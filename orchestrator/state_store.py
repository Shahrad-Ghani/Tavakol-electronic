from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class StateStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "runtime_state"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _safe(name: str) -> str:
        out = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))
        return out[:180] or "unknown"

    def path_for(self, source_key: str) -> Path:
        return self.dir / f"{self._safe(source_key)}.json"

    def load(self, source_key: str) -> dict:
        path = self.path_for(source_key)
        if not path.exists():
            return {
                "schema_version": "tavakol-runtime-state-v1",
                "source_key": source_key,
                "part_number": None,
                "metadata_path": None,
                "phase1": "PENDING",
                "phase2": "PENDING",
                "phase3": "PENDING",
                "last_error": None,
                "updated_at": utc_now(),
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, source_key: str, **changes) -> dict:
        with self._lock:
            state = self.load(source_key)
            state.update(changes)
            state["updated_at"] = utc_now()
            path = self.path_for(source_key)
            fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return state
