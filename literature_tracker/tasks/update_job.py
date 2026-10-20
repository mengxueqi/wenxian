"""Run a manual update without blocking the live source status view."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from .pipeline import run_full_pipeline


class UpdateJob:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="literature-update")
        self.future: Future | None = None
        self.lock = Lock()

    def start(self) -> Future:
        with self.lock:
            if self.future is None or self.future.done():
                self.future = self.executor.submit(run_full_pipeline, db_path=self.db_path)
            return self.future
