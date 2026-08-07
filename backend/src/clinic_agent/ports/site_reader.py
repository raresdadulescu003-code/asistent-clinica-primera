"""Citirea conținutului public al site-ului."""

from __future__ import annotations

from typing import Protocol

from clinic_agent.domain.models import Page


class SiteReaderPort(Protocol):
    async def fetch_pages(self) -> list[Page]:
        """Paginile utile ale site-ului, deja curățate de HTML.

        Descoperirea URL-urilor, excluderile și deduplicarea sunt detalii de
        implementare — serviciul primește doar rezultatul.
        """
        ...
