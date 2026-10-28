from __future__ import annotations

import threading
from typing import Callable, Optional

_sink: Optional[Callable[[str], None]] = None
_lock = threading.Lock()


def set_phase2_log_sink(callback: Optional[Callable[[str], None]]) -> None:
    global _sink
    with _lock:
        _sink = callback


def phase2_log(*args, **kwargs) -> None:
    text = " ".join(str(x) for x in args)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    print(text, **kwargs)
    callback = _sink
    if callback:
        try:
            callback(text)
        except Exception:
            pass
