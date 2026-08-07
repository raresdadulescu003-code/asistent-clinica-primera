"""POST /api/chat — singurul endpoint pe care îl folosește widget-ul."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from clinic_agent.api.deps import ChatServiceDep, ClientIpDep, SettingsDep
from clinic_agent.api.schemas import ChatRequest
from clinic_agent.api.sse import SSE_HEADERS, done_event, error_event, token_event
from clinic_agent.domain.language import Language, detect_language
from clinic_agent.services.chat_service import (
    ConversationTooLong,
    KnowledgeUnavailable,
    RateLimited,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Mesajele de eroare merg direct pe ecranul vizitatorului, deci sunt scrise
# pentru el, nu pentru dezvoltator — și toate se termină cu o cale de ieșire.
MESSAGES: dict[str, dict[Language, str]] = {
    "unavailable": {
        "ro": "Asistentul se pregătește. Încearcă din nou în câteva minute sau sună la {phone}.",
        "en": "The assistant is starting up. Please try again shortly or call {phone}.",
    },
    "too_long": {
        "ro": "Conversația a devenit prea lungă. Reîmprospătează pagina pentru a începe alta, sau sună la {phone}.",
        "en": "This conversation has grown too long. Refresh the page to start a new one, or call {phone}.",
    },
    "rate_limited": {
        "ro": "Ai trimis multe mesaje într-un timp scurt. Încearcă mai târziu sau sună la {phone}.",
        "en": "You've sent a lot of messages in a short time. Please try later or call {phone}.",
    },
    "internal": {
        "ro": "Momentan nu pot răspunde. Sună la {phone} sau scrie la {email}.",
        "en": "I can't answer right now. Please call {phone} or email {email}.",
    },
}


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    service: ChatServiceDep,
    settings: SettingsDep,
    ip: ClientIpDep,
) -> StreamingResponse:
    turns = payload.to_turns()
    language = detect_language(turns[-1].content)

    def message(key: str) -> str:
        return MESSAGES[key][language].format(
            phone=settings.clinic.phone, email=settings.clinic.email
        )

    # Gardienii rulează aici, înainte de a începe streaming-ul: odată trimise
    # antetele SSE, codul de stare nu mai poate fi schimbat.
    try:
        stream = await service.respond(turns, ip)
    except KnowledgeUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, message("unavailable"))
    except ConversationTooLong:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message("too_long"))
    except RateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            message("rate_limited"),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    async def events() -> AsyncIterator[str]:
        try:
            async for chunk in stream:
                yield token_event(chunk)
        except Exception as exc:  # noqa: BLE001 - ultima plasă de siguranță
            logger.exception("eroare în timpul streaming-ului: %s", exc)
            yield error_event(message("internal"))
        yield done_event()

    return StreamingResponse(
        events(), media_type="text/event-stream", headers=SSE_HEADERS
    )
