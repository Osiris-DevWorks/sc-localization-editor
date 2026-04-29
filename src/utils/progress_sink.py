"""Thread-safe progress sink for fan-out pipelines.

Workers call `advance()` from any thread; the sink coalesces those updates into
a single `(completed, total, message)` tuple and pushes it through a callback.
The callback is throttled so high-frequency updates from many threads don't
flood the Qt event loop.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

ProgressCallback = Callable[[int, int, str], None]


class ProgressSink:
    __slots__ = (
        "_cb",
        "_lock",
        "_completed",
        "_total",
        "_message",
        "_min_interval",
        "_last_emit",
        "_last_emitted_tuple",
    )

    def __init__(
        self,
        callback: ProgressCallback | None = None,
        total: int = 0,
        min_interval: float = 0.05,
    ) -> None:
        self._cb = callback
        self._lock = threading.Lock()
        self._completed = 0
        self._total = total
        self._message = ""
        self._min_interval = min_interval
        self._last_emit = 0.0
        self._last_emitted_tuple: tuple[int, int, str] | None = None

    def set_total(self, total: int) -> None:
        with self._lock:
            self._total = total
        self._emit(force=True)

    def add_total(self, delta: int) -> None:
        with self._lock:
            self._total += delta
        self._emit(force=True)

    def advance(self, delta: int = 1, message: str | None = None) -> None:
        with self._lock:
            self._completed += delta
            if message is not None:
                self._message = message
        self._emit()

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = message
        self._emit()

    def snapshot(self) -> tuple[int, int, str]:
        with self._lock:
            return (self._completed, self._total, self._message)

    def flush(self) -> None:
        self._emit(force=True)

    def _emit(self, force: bool = False) -> None:
        if self._cb is None:
            return
        now = time.monotonic()
        with self._lock:
            payload = (self._completed, self._total, self._message)
            done = self._total > 0 and self._completed >= self._total
            if not force and not done:
                if now - self._last_emit < self._min_interval:
                    return
                if payload == self._last_emitted_tuple:
                    return
            self._last_emit = now
            self._last_emitted_tuple = payload
        try:
            self._cb(*payload)
        except Exception:
            pass
