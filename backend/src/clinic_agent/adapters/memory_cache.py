"""Cache de răspunsuri în memoria procesului.

De aceea rulăm cu un singur worker: doi workeri ar avea două cache-uri
independente și rata de acoperire s-ar înjumătăți.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from clinic_agent.ports.response_cache import CacheStats


class MemoryResponseCache:
    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None

        stored_at, value = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[key]
            self._misses += 1
            return None

        self._entries.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: str) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)  # cea mai veche folosire

    def stats(self) -> CacheStats:
        return CacheStats(hits=self._hits, misses=self._misses, entries=len(self._entries))
