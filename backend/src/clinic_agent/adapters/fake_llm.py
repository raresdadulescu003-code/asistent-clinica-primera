"""Model fals pentru teste. Nu atinge rețeaua, deci nu costă nimic.

Nu moștenește `LLMPort` — `Protocol` se potrivește structural: are metodele
cerute, deci poate lua locul clientului real oriunde.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from clinic_agent.domain.models import ChatTurn
from clinic_agent.domain.prompt import PromptBlock
from clinic_agent.ports.llm import LLMError


class FakeLLM:
    def __init__(self, reply: str = "Program: luni-vineri 8:30-20:30.") -> None:
        self.reply = reply
        self.calls: list[list[ChatTurn]] = []
        self.warm_calls = 0
        self.fail_with: Exception | None = None

    async def stream_reply(
        self, *, system: Sequence[PromptBlock], turns: Sequence[ChatTurn]
    ) -> AsyncIterator[str]:
        self.calls.append(list(turns))
        if self.fail_with is not None:
            raise self.fail_with
        # Bucăți mici, ca testele să vadă streaming real, nu un singur bloc.
        for word in self.reply.split(" "):
            yield word + " "

    async def warm_cache(self, *, system: Sequence[PromptBlock]) -> None:
        self.warm_calls += 1
        if self.fail_with is not None:
            raise self.fail_with


class BrokenLLM:
    """Simulează cheie epuizată sau serviciu indisponibil."""

    async def stream_reply(
        self, *, system: Sequence[PromptBlock], turns: Sequence[ChatTurn]
    ) -> AsyncIterator[str]:
        raise LLMError("serviciu indisponibil")
        yield ""  # pragma: no cover - face funcția generator

    async def warm_cache(self, *, system: Sequence[PromptBlock]) -> None:
        raise LLMError("serviciu indisponibil")
