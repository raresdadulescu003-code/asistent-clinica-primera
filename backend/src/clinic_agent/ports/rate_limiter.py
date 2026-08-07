"""Limitarea traficului pe IP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Window = Literal["hour", "day"]


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    allowed: bool
    window: Window | None = None
    retry_after_seconds: int | None = None


class RateLimiterPort(Protocol):
    def check(self, client_id: str) -> RateLimitVerdict:
        """Verifică și, dacă e permis, înregistrează cererea."""
        ...
