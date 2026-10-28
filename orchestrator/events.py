from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


class EventLogger:
    """Thread-safe one-line logger feeding files, console and optional UI callbacks."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.logs_dir = self.root / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[dict], None]] = []
        self.events: "queue.Queue[dict]" = queue.Queue()

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._subscribers.append(callback)

    @staticmethod
    def _clean(value) -> str:
        return " ".join(str(value or "-").replace("\r", " ").replace("\n", " ").split())

    def emit(self, phase: str, level: str, item: str, stage: str, message: str) -> dict:
        now = datetime.now()
        phase = self._clean(phase).upper()
        level = self._clean(level).upper()
        item = self._clean(item)
        stage = self._clean(stage).upper()
        message = self._clean(message)
        line = f"{now.strftime('%H:%M:%S')} | {phase:<4} | {item:<18} | {stage:<18} | {level:<7} | {message}"
        event = {
            "timestamp": now.isoformat(timespec="seconds"),
            "phase": phase,
            "level": level,
            "item": item,
            "stage": stage,
            "message": message,
            "line": line,
        }
        with self._lock:
            print(line, flush=True)
            day = now.strftime("%Y%m%d")
            targets = [self.logs_dir / f"orchestrator_{day}.log"]
            if phase in {"P1", "P2", "P3"}:
                targets.append(self.logs_dir / f"{phase.lower()}_{day}.log")
            for target in targets:
                with target.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        self.events.put(event)
        for callback in tuple(self._subscribers):
            try:
                callback(event)
            except Exception:
                pass
        return event

    def bridge(self, phase: str, default_stage: str) -> Callable[[str], None]:
        def _sink(raw: str) -> None:
            text = self._clean(raw)
            item = "-"
            stage = default_stage
            level = "INFO"
            # Existing phase logs often begin with [TAG] and then PN/ref.
            if text.startswith("[") and "]" in text:
                tag, rest = text[1:].split("]", 1)
                stage = tag[:18]
                rest = rest.strip()
                if rest:
                    item = rest.split("|", 1)[0].strip() or "-"
                upper = tag.upper()
                if any(x in upper for x in ("FAIL", "ERROR", "BLOCK")):
                    level = "ERROR"
                elif any(x in upper for x in ("OK", "FOUND", "FINALIZED", "SAVED")):
                    level = "OK"
                elif any(x in upper for x in ("WARN", "RETRY", "MANUAL", "AMBIGUOUS")):
                    level = "WARN"
                elif "SKIP" in upper:
                    level = "SKIP"
            self.emit(phase, level, item, stage, text)
        return _sink
