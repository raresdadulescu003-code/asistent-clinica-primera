"""Ce are nevoie aplicația de la un model de limbaj."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from clinic_agent.domain.models import ChatTurn
from clinic_agent.domain.prompt import PromptBlock


class LLMError(Exception):
    """Modelul nu a putut răspunde. Traduce orice eroare a furnizorului."""


class LLMPort(Protocol):
    def stream_reply(
        self, *, system: Sequence[PromptBlock], turns: Sequence[ChatTurn]
    ) -> AsyncIterator[str]:
        """Răspunsul, bucată cu bucată, pe măsură ce e generat."""
        ...

    async def warm_cache(self, *, system: Sequence[PromptBlock]) -> None:
        """Citește promptul fără să genereze nimic, ca să reseteze TTL-ul cache-ului."""
        ...
