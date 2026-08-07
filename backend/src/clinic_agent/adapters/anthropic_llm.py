"""Clientul Anthropic. Singurul loc din aplicație care importă `anthropic`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence

import anthropic

from clinic_agent.domain.models import ChatTurn
from clinic_agent.domain.prompt import PromptBlock
from clinic_agent.ports.llm import LLMError

logger = logging.getLogger(__name__)


class AnthropicLLM:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int,
        cache_ttl: str,
        timeout_seconds: float,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._max_tokens = max_tokens
        self._cache_ttl = cache_ttl

    def _system(self, blocks: Sequence[PromptBlock]) -> list[dict]:
        """Traduce blocurile neutre din domain în formatul Anthropic.

        Aici — și numai aici — apare `cache_control`. Marcajul stă pe ultimul
        bloc stabil, deci cache-ul acoperă tot prefixul de dinaintea lui.
        """
        payload: list[dict] = []
        for block in blocks:
            item: dict = {"type": "text", "text": block.text}
            if block.cacheable:
                item["cache_control"] = {"type": "ephemeral", "ttl": self._cache_ttl}
            payload.append(item)
        return payload

    @staticmethod
    def _messages(turns: Sequence[ChatTurn]) -> list[dict]:
        return [{"role": turn.role, "content": turn.content} for turn in turns]

    async def stream_reply(
        self, *, system: Sequence[PromptBlock], turns: Sequence[ChatTurn]
    ) -> AsyncIterator[str]:
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system(system),
                messages=self._messages(turns),
            ) as stream:
                async for chunk in stream.text_stream:
                    yield chunk
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise LLMError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # Nu doar APIError: cheie lipsă, DNS căzut, TLS, o schimbare în SDK.
            # Orice iese de aici trebuie să fie LLMError, altfel serviciul nu
            # recunoaște situația și vizitatorul vede o eroare în loc de telefon.
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        usage = final.usage
        # Fără linia asta nu ai cum să afli dacă prompt caching chiar funcționează.
        logger.info(
            "apel model: cache_read=%s cache_write=%s input=%s output=%s",
            usage.cache_read_input_tokens,
            usage.cache_creation_input_tokens,
            usage.input_tokens,
            usage.output_tokens,
        )

    async def warm_cache(self, *, system: Sequence[PromptBlock]) -> None:
        """Citește promptul fără să genereze output.

        `max_tokens=0` face exact prefill-ul și se oprește: costă 0,25 cenți
        și resetează TTL-ul, în loc de 4,9 cenți cât ar costa o rescriere.
        Nu merge combinat cu streaming, de aceea apelul e non-streaming.
        """
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=0,
                system=self._system(system),
                messages=[{"role": "user", "content": "ping"}],
            )
        except anthropic.APIError as exc:
            raise LLMError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        logger.info(
            "keep-alive cache: read=%s write=%s",
            response.usage.cache_read_input_tokens,
            response.usage.cache_creation_input_tokens,
        )
