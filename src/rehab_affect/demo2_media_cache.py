"""Bounded process-local results; callers must authorize every cache lookup."""

from __future__ import annotations

import copy
import time
from collections import OrderedDict
from threading import Lock
from typing import Any


class MediaResultCache:
    def __init__(self, *, max_entries: int, max_bytes: int, ttl: float):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl = ttl
        self._entries: OrderedDict[tuple, tuple[float, int, Any]] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def _expire(self, now: float) -> None:
        for key, (deadline, size, _) in list(self._entries.items()):
            if now >= deadline:
                del self._entries[key]
                self._bytes -= size

    def get(self, key: tuple) -> Any | None:
        with self._lock:
            self._expire(time.monotonic())
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(entry[2])

    def put(self, key: tuple, value: Any, *, size: int) -> None:
        if self.ttl <= 0 or self.max_entries <= 0 or not 0 < size <= self.max_bytes:
            return
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            while self._entries and (len(self._entries) >= self.max_entries or self._bytes + size > self.max_bytes):
                _, (_, removed_size, _) = self._entries.popitem(last=False)
                self._bytes -= removed_size
            self._entries[key] = (now + self.ttl, size, copy.deepcopy(value))
            self._bytes += size
