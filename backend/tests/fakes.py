"""Dubluri de test pentru porturile de I/O. Niciuna nu atinge rețeaua sau discul."""

from __future__ import annotations

from clinic_agent.domain.models import Page, Snapshot


class FakeSiteReader:
    def __init__(self, pages: list[Page] | None = None) -> None:
        self.pages = pages if pages is not None else [
            Page("https://x.ro/preturi", "Prețuri", "Consultația stomatologică 250 RON."),
            Page("https://x.ro/echipa", "Echipa", "Dr. Toma Florentina, cardiologie."),
        ]
        self.calls = 0
        self.raise_error: Exception | None = None

    async def fetch_pages(self) -> list[Page]:
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        return list(self.pages)


class InMemoryRepo:
    def __init__(self, snapshot: Snapshot | None = None) -> None:
        self.snapshot = snapshot
        self.saves = 0

    def load(self) -> Snapshot | None:
        return self.snapshot

    def save(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.saves += 1


class AllowAllLimiter:
    def check(self, client_id: str):  # noqa: ANN201
        from clinic_agent.ports.rate_limiter import RateLimitVerdict

        return RateLimitVerdict(allowed=True)
