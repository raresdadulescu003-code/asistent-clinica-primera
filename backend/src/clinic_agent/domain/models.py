"""Modelele de date ale aplicației. Imutabile, fără I/O.

`frozen=True` nu e stil, e o garanție: `Snapshot.id` e hash-ul conținutului,
deci conținutul nu are voie să se schimbe după calcularea lui.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Page:
    """O pagină de pe site, după curățarea HTML-ului."""

    url: str
    title: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Rezultatul unei rulări de scraping: toate paginile, plus amprenta lor.

    `id` e hash-ul conținutului, nu al momentului. Două scraping-uri care
    întorc același text produc același id, deci cache-ul de răspunsuri
    supraviețuiește unei actualizări care nu a schimbat nimic.
    """

    id: str
    pages: tuple[Page, ...]
    created_at: datetime

    @classmethod
    def from_pages(cls, pages: Sequence[Page], created_at: datetime) -> Snapshot:
        # Sortăm după URL: ordinea în care scraper-ul a terminat paginile nu are
        # voie să schimbe amprenta și să invalideze cache-ul degeaba.
        ordered = tuple(sorted(pages, key=lambda page: page.url))
        return cls(id=cls._fingerprint(ordered), pages=ordered, created_at=created_at)

    @staticmethod
    def _fingerprint(pages: Sequence[Page]) -> str:
        digest = hashlib.sha256()
        for page in pages:
            digest.update(page.url.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(page.text.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()[:16]

    @property
    def is_empty(self) -> bool:
        return not self.pages

    @property
    def total_chars(self) -> int:
        return sum(page.char_count for page in self.pages)

    def age(self, now: datetime) -> timedelta:
        """Vârsta snapshot-ului. `now` se transmite explicit, ca să fie testabil."""
        return now - self.created_at


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """Un mesaj din conversație."""

    role: Role
    content: str


def is_opening_question(turns: Sequence[ChatTurn]) -> bool:
    """Adevărat doar pentru primul mesaj al unei conversații.

    Regula care face cache-ul de răspunsuri sigur: „Și albirea?" depinde de
    ce s-a discutat înainte, deci nu poate fi servit altcuiva.
    """
    return len(turns) == 1 and turns[0].role == "user"


def last_user_message(turns: Sequence[ChatTurn]) -> str | None:
    for turn in reversed(turns):
        if turn.role == "user":
            return turn.content
    return None
