from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clinic_agent.adapters.fake_llm import BrokenLLM, FakeLLM
from clinic_agent.adapters.memory_cache import MemoryResponseCache
from clinic_agent.domain.models import ChatTurn, Page
from clinic_agent.domain.prompt import ClinicProfile, PromptTemplate
from clinic_agent.ports.rate_limiter import RateLimitVerdict
from clinic_agent.services.chat_service import (
    ChatService,
    ConversationTooLong,
    KnowledgeUnavailable,
    RateLimited,
)
from clinic_agent.services.knowledge_service import KnowledgeService
from tests.fakes import AllowAllLimiter, FakeSiteReader, InMemoryRepo

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
CLINIC = ClinicProfile(name="Clinica Primera", contact="tel 0349 999", phone="0349 999")
TEMPLATE = PromptTemplate(version="ro/system.v1", text="Asistent pentru {clinic_name}.")


class DenyingLimiter:
    def check(self, client_id: str) -> RateLimitVerdict:
        return RateLimitVerdict(allowed=False, window="hour", retry_after_seconds=120)


async def build_service(
    *, llm=None, cache=None, limiter=None, reader=None, with_content: bool = True
) -> tuple[ChatService, KnowledgeService, FakeLLM]:
    llm = llm or FakeLLM()
    knowledge = KnowledgeService(
        reader=reader or FakeSiteReader(),
        repo=InMemoryRepo(),
        llm=llm,
        clinic=CLINIC,
        template=TEMPLATE,
        clock=lambda: NOW,
    )
    if with_content:
        await knowledge.refresh()

    service = ChatService(
        knowledge=knowledge,
        llm=llm,
        cache=cache or MemoryResponseCache(ttl_seconds=3600, max_entries=100),
        rate_limiter=limiter or AllowAllLimiter(),
        phone="0349 999",
        email="office@clinicaprimera.ro",
    )
    return service, knowledge, llm


async def collect(stream) -> str:
    return "".join([chunk async for chunk in stream])


async def test_raspuns_normal_de_la_model() -> None:
    service, _, llm = await build_service()
    stream = await service.respond([ChatTurn("user", "Ce medici aveti?")], "1.2.3.4")
    assert "Program" in await collect(stream)
    assert len(llm.calls) == 1


async def test_baza_goala_da_503() -> None:
    service, _, _ = await build_service(
        reader=FakeSiteReader(pages=[]), with_content=False
    )
    with pytest.raises(KnowledgeUnavailable):
        await service.respond([ChatTurn("user", "salut")], "1.2.3.4")


async def test_conversatie_prea_lunga() -> None:
    service, _, _ = await build_service()
    turns = [ChatTurn("user", f"mesaj {i}") for i in range(25)]
    with pytest.raises(ConversationTooLong):
        await service.respond(turns, "1.2.3.4")


async def test_rate_limit() -> None:
    service, _, _ = await build_service(limiter=DenyingLimiter())
    with pytest.raises(RateLimited) as exc:
        await service.respond([ChatTurn("user", "salut")], "1.2.3.4")
    assert exc.value.retry_after_seconds == 120


async def test_intrebarea_din_alt_domeniu_nu_atinge_modelul() -> None:
    service, _, llm = await build_service()
    stream = await service.respond([ChatTurn("user", "Ce vreme e afara?")], "1.2.3.4")
    text = await collect(stream)
    assert "Clinica Primera" in text
    assert llm.calls == []  # niciun apel, deci niciun cost


async def test_filtrul_se_aplica_ultimului_mesaj() -> None:
    # Cineva poate discuta despre prețuri și apoi întreba ce vreme e afară.
    service, _, llm = await build_service()
    turns = [
        ChatTurn("user", "Cat costa un detartraj?"),
        ChatTurn("assistant", "250 RON."),
        ChatTurn("user", "Ce vreme e afara?"),
    ]
    text = await collect(await service.respond(turns, "1.2.3.4"))
    assert "Clinica Primera" in text
    assert llm.calls == []


async def test_a_doua_intrebare_identica_vine_din_cache() -> None:
    service, _, llm = await build_service()
    question = [ChatTurn("user", "Care e programul?")]

    first = await collect(await service.respond(question, "1.2.3.4"))
    second = await collect(
        await service.respond([ChatTurn("user", "care e programul")], "5.6.7.8")
    )

    assert first == second
    assert len(llm.calls) == 1  # al doilea vizitator nu a costat nimic


async def test_urmarile_nu_se_memoreaza() -> None:
    # „Și albirea?" depinde de context; servit altcuiva ar da răspuns greșit.
    service, _, llm = await build_service()
    turns = [
        ChatTurn("user", "Cat costa un detartraj?"),
        ChatTurn("assistant", "250 RON."),
        ChatTurn("user", "Si albirea?"),
    ]
    await collect(await service.respond(turns, "1.2.3.4"))
    await collect(await service.respond(turns, "5.6.7.8"))
    assert len(llm.calls) == 2


async def test_intrebarile_lungi_nu_se_memoreaza() -> None:
    # Sunt unicate și pot conține date personale.
    service, _, llm = await build_service()
    long_question = "Am urmatoarea problema: " + "x" * 250
    await collect(await service.respond([ChatTurn("user", long_question)], "1.2.3.4"))
    await collect(await service.respond([ChatTurn("user", long_question)], "5.6.7.8"))
    assert len(llm.calls) == 2


async def test_actualizarea_continutului_invalideaza_cache_ul() -> None:
    """Bug 2 din enunț, verificat direct."""
    reader = FakeSiteReader()
    service, knowledge, llm = await build_service(reader=reader)
    question = [ChatTurn("user", "Cat costa un detartraj?")]

    await collect(await service.respond(question, "1.2.3.4"))
    assert len(llm.calls) == 1

    reader.pages = [Page("https://x.ro/preturi", "Prețuri", "Detartraj 300 RON.")]
    await knowledge.refresh()

    await collect(await service.respond(question, "1.2.3.4"))
    # Alt snapshot_id ⇒ altă cheie ⇒ răspunsul vechi nu mai e găsit.
    assert len(llm.calls) == 2


async def test_caderea_modelului_da_numarul_de_telefon() -> None:
    service, _, _ = await build_service(llm=None)
    service._llm = BrokenLLM()  # type: ignore[attr-defined]
    text = await collect(
        await service.respond([ChatTurn("user", "Ce medici aveti?")], "1.2.3.4")
    )
    assert "0349 999" in text
    assert "eroare" not in text.lower()


async def test_raspunsul_esuat_nu_se_memoreaza() -> None:
    cache = MemoryResponseCache(ttl_seconds=3600, max_entries=100)
    service, _, _ = await build_service(cache=cache)
    service._llm = BrokenLLM()  # type: ignore[attr-defined]
    await collect(await service.respond([ChatTurn("user", "Ce program?")], "1.2.3.4"))
    assert cache.stats().entries == 0


async def test_intrebari_identice_simultane_raman_consistente() -> None:
    """Comportament sub concurență, fixat ca să nu regreseze.

    Două cereri identice care pornesc înainte ca prima să scrie în cache vor
    apela amândouă modelul — duplicare benignă, de câteva zecimi de cent.
    Ce contează e că starea rămâne coerentă: cache-ul are o singură intrare
    și următorul vizitator o primește.
    """
    import asyncio

    service, _, llm = await build_service()
    question = [ChatTurn("user", "Care e programul?")]

    # Toate trei pornesc înainte ca vreuna să apuce să scrie în cache.
    streams = [await service.respond(question, f"10.0.0.{i}") for i in range(3)]
    await asyncio.gather(*(collect(stream) for stream in streams))
    assert len(llm.calls) == 3

    # A patra cerere e servită din cache, fără apel.
    await collect(await service.respond(question, "10.0.0.9"))
    assert len(llm.calls) == 3


async def test_orice_cadere_neasteptata_da_tot_numarul_de_telefon() -> None:
    """Regresie prinsă la testarea live cu cheia goală.

    Serviciul prindea doar `LLMError`, iar o excepție de alt tip ocolea calea
    elegantă și ajungea la vizitator ca eroare roșie în widget.
    """
    llm = FakeLLM()
    llm.fail_with = RuntimeError("ceva complet neașteptat")
    service, _, _ = await build_service(llm=llm)

    text = await collect(
        await service.respond([ChatTurn("user", "Ce program aveti?")], "1.2.3.4")
    )
    assert "0349 999" in text


async def test_caderea_in_engleza_raspunde_in_engleza() -> None:
    service, _, _ = await build_service()
    service._llm = BrokenLLM()  # type: ignore[attr-defined]
    text = await collect(
        await service.respond(
            [ChatTurn("user", "How much is a consultation?")], "1.2.3.4"
        )
    )
    assert text.startswith("I can't answer right now")
