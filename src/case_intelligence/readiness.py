"""A single background probe with a fail-closed, expiring readiness snapshot."""
from __future__ import annotations

import threading
from time import monotonic
from typing import Callable


class CachedReadiness:
    def __init__(self, probe: Callable[[], bool], *, initial: bool = False,
                 interval: float = 5.0, max_age: float = 15.0):
        self._probe = probe
        self._interval = interval
        self._max_age = max_age
        self._lock = threading.Lock()
        self._value = initial
        self._checked = monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="retrieval-readiness", daemon=True)
        self._thread.start()

    def ready(self) -> bool:
        with self._lock:
            return self._value and monotonic() - self._checked <= self._max_age and not self._stop.is_set()

    def _refresh(self) -> None:
        started = monotonic()
        try:
            value = bool(self._probe())
        except Exception:
            value = False
        with self._lock:
            self._value = value
            # A slow response cannot make old readiness fresh again.
            self._checked = started

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._refresh()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
