"""Limitare pe IP, cu ferestre glisante, în memoria procesului."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

from clinic_agent.ports.rate_limiter import RateLimitVerdict

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * 3600
SWEEP_INTERVAL = 600


class MemoryRateLimiter:
    def __init__(
        self,
        *,
        per_hour: int,
        per_day: int,
        max_tracked_clients: int = 20_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_hour = per_hour
        self._per_day = per_day
        self._max_clients = max_tracked_clients
        self._clock = clock
        # NU defaultdict: cu el, orice interogare creează o intrare, inclusiv
        # pentru cereri respinse. Intrările se și curăță periodic — altfel
        # dicționarul crește la nesfârșit, câte o intrare per IP văzut vreodată.
        self._events: dict[str, deque[float]] = {}
        self._last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Aruncă IP-urile care n-au mai fost văzute de peste o zi."""
        if now - self._last_sweep < SWEEP_INTERVAL and len(self._events) < self._max_clients:
            return
        self._last_sweep = now
        stale = [
            client
            for client, events in self._events.items()
            if not events or now - events[-1] > DAY
        ]
        for client in stale:
            del self._events[client]
        if len(self._events) >= self._max_clients:
            logger.warning(
                "limitatorul urmărește %s IP-uri după curățare — trafic anormal?",
                len(self._events),
            )

    def check(self, client_id: str) -> RateLimitVerdict:
        now = self._clock()
        self._sweep(now)
        events = self._events.get(client_id)
        if events is None:
            events = deque()
            self._events[client_id] = events

        while events and now - events[0] > DAY:
            events.popleft()

        in_last_hour = sum(1 for moment in events if now - moment <= HOUR)
        if in_last_hour >= self._per_hour:
            oldest_in_hour = next(m for m in events if now - m <= HOUR)
            return RateLimitVerdict(
                allowed=False,
                window="hour",
                retry_after_seconds=int(HOUR - (now - oldest_in_hour)) + 1,
            )

        if len(events) >= self._per_day:
            return RateLimitVerdict(
                allowed=False,
                window="day",
                retry_after_seconds=int(DAY - (now - events[0])) + 1,
            )

        events.append(now)
        return RateLimitVerdict(allowed=True)
