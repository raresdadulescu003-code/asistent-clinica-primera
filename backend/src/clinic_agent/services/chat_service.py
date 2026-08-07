"""Orchestrarea unui răspuns: gardieni, cache, apel către model."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence

from clinic_agent.domain.language import detect_language
from clinic_agent.domain.models import ChatTurn, is_opening_question, last_user_message
from clinic_agent.domain.normalization import response_cache_key
from clinic_agent.domain.offtopic import fallback_reply, is_offtopic, offtopic_reply
from clinic_agent.domain.prompt import looks_like_instruction_leak
from clinic_agent.ports.llm import LLMError, LLMPort
from clinic_agent.ports.rate_limiter import RateLimiterPort, Window
from clinic_agent.ports.response_cache import ResponseCachePort
from clinic_agent.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

LEAK_REFUSAL = {
    "ro": "\n\nSunt asistentul informațional al Clinicii Primera. Cu ce te pot ajuta?",
    "en": "\n\nI'm the information assistant for Clinica Primera. How can I help?",
}


class ChatError(Exception):
    """Cerere respinsă de un gardian, înainte de orice apel către model."""


class KnowledgeUnavailable(ChatError):
    pass


class ConversationTooLong(ChatError):
    pass


class RateLimited(ChatError):
    def __init__(self, window: Window, retry_after_seconds: int) -> None:
        super().__init__(f"limită depășită ({window})")
        self.window = window
        self.retry_after_seconds = retry_after_seconds


class ChatService:
    def __init__(
        self,
        *,
        knowledge: KnowledgeService,
        llm: LLMPort,
        cache: ResponseCachePort,
        rate_limiter: RateLimiterPort,
        phone: str,
        email: str,
        max_conversation_messages: int = 24,
        max_cacheable_question_chars: int = 200,
        cache_enabled: bool = True,
    ) -> None:
        self._knowledge = knowledge
        self._llm = llm
        self._cache = cache
        self._rate_limiter = rate_limiter
        self._phone = phone
        self._email = email
        self._max_messages = max_conversation_messages
        self._max_question_chars = max_cacheable_question_chars
        self._cache_enabled = cache_enabled

    async def respond(
        self, turns: Sequence[ChatTurn], client_id: str
    ) -> AsyncIterator[str]:
        """Gardienii rulează *înainte* de a întoarce iteratorul.

        De aceea metoda e `async def` care întoarce un iterator, nu ea însăși
        un generator: corpul unui generator nu se execută până la primul
        `__anext__`, iar atunci ruta ar fi trimis deja antetele HTTP și n-ar mai
        putea răspunde cu 429 sau 503.
        """
        if not self._knowledge.has_content:
            raise KnowledgeUnavailable("baza de cunoștințe e goală")

        if len(turns) > self._max_messages:
            raise ConversationTooLong("conversație prea lungă")

        verdict = self._rate_limiter.check(client_id)
        if not verdict.allowed:
            raise RateLimited(verdict.window or "hour", verdict.retry_after_seconds or 60)

        question = last_user_message(turns) or ""

        if is_offtopic(question):
            # Răspuns fix, fără apel către model: instant și identic de fiecare dată.
            return _once(offtopic_reply(question))

        cache_key = self._cache_key(turns, question)
        if cache_key is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("răspuns servit din cache")
                return _once(cached)

        return self._stream(turns, question, cache_key)

    def _cache_key(self, turns: Sequence[ChatTurn], question: str) -> str | None:
        """None înseamnă „nu se memorează".

        Două reguli: doar primul mesaj al unei conversații (un follow-up depinde
        de context și, servit altcuiva, ar da un răspuns greșit) și doar
        întrebări scurte (cele lungi sunt unicate și pot conține date personale).
        """
        if not self._cache_enabled:
            return None
        if not is_opening_question(turns):
            return None
        if len(question) > self._max_question_chars:
            return None
        snapshot_id = self._knowledge.snapshot_id
        if snapshot_id is None:
            return None
        return response_cache_key(snapshot_id, self._knowledge.prompt_version, question)

    async def _stream(
        self, turns: Sequence[ChatTurn], question: str, cache_key: str | None
    ) -> AsyncIterator[str]:
        collected: list[str] = []
        markers = self._knowledge.instruction_markers

        try:
            async for chunk in self._llm.stream_reply(
                system=self._knowledge.system_blocks, turns=turns
            ):
                collected.append(chunk)
                # Verificăm ÎNAINTE de a trimite bucata. Prima potrivire oprește
                # fluxul, deci regulile nu ies niciodată. Ce a apucat să plece
                # e cel mult propoziția de rol, care oricum nu e secretă.
                #
                # Nu tamponăm începutul: răspunsurile au două-trei propoziții,
                # deci o fereastră de verificare le-ar transforma pe aproape
                # toate într-un singur bloc și ar anula streaming-ul.
                if looks_like_instruction_leak("".join(collected), markers):
                    yield self._leak_refusal(question)
                    return
                yield chunk
        except Exception as exc:  # noqa: BLE001
            # Deliberat larg. Orice cădere — model, rețea, un bug de-al nostru —
            # trebuie să ajungă la vizitator ca mesaj normal cu numărul de
            # telefon, nu ca eroare roșie. `CancelledError` nu e `Exception`,
            # deci întreruperea conexiunii de către vizitator trece nestingherită.
            logger.error("apelul către model a eșuat: %s: %s", type(exc).__name__, exc)
            # Vizitatorul pleacă cu numărul de telefon, nu cu impresia că
            # site-ul e stricat. Răspunsul incomplet NU se memorează.
            message = fallback_reply(detect_language(question), self._phone, self._email)
            yield ("\n\n" if collected else "") + message
            return

        if looks_like_instruction_leak("".join(collected), markers):
            return  # nu memorăm un răspuns care conține instrucțiuni

        if cache_key is not None:
            # Cheia conține amprenta conținutului cu care s-a generat răspunsul.
            # O cerere pornită înainte de un re-scraping scrie sub o cheie
            # veche, pe care nimeni nu o mai citește — cursa e inofensivă.
            self._cache.set(cache_key, "".join(collected))


    def _leak_refusal(self, question: str) -> str:
        logger.error(
            "răspunsul modelului conținea instrucțiunile de sistem — blocat "
            "înainte de a ajunge la vizitator"
        )
        return LEAK_REFUSAL[detect_language(question)]


async def _once(text: str) -> AsyncIterator[str]:
    yield text
