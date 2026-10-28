from __future__ import annotations

from pathlib import Path
from typing import List

from . import core_runtime as core
from .pipeline import Phase2Pipeline


class Phase2Coordinator:
    """In-memory micro-batch coordinator for direct Phase-1 integration.

    Usage from Phase 1:
        coordinator.enqueue(metadata_path)  # after each product reaches PN-ready state
        ...
        coordinator.flush()                 # at the end of current Phase-1 input batch

    It processes automatically whenever 10 eligible metadata files accumulate.
    It never waits for 75 products.
    """

    def __init__(self, pipeline: Phase2Pipeline):
        self.pipeline = pipeline
        self._queue: List[Path] = []
        self._seen = set()

    def enqueue(self, metadata_path: Path) -> int:
        path = metadata_path.resolve()
        key = str(path).casefold()
        if key in self._seen:
            return 0
        eligible = self.pipeline.eligible_paths([path])
        if not eligible:
            return 0
        self._queue.append(path)
        self._seen.add(key)
        if len(self._queue) >= core.MAX_PARTS_PER_MOUSER_REQUEST:
            return self._drain(core.MAX_PARTS_PER_MOUSER_REQUEST)
        return 0

    def flush(self) -> int:
        processed = 0
        while self._queue:
            processed += self._drain(min(len(self._queue), core.MAX_PARTS_PER_MOUSER_REQUEST))
        return processed

    def _drain(self, count: int) -> int:
        batch = self._queue[:count]
        self._queue = self._queue[count:]
        for path in batch:
            self._seen.discard(str(path).casefold())
        return self.pipeline.process_batch(batch)
