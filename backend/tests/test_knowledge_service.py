from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from clinic_agent.adapters.fake_llm import FakeLLM
from clinic_agent.domain.models import Page, Snapshot
from clinic_agent.domain.prompt import ClinicProfile, PromptTemplate
from clinic_agent.services.knowledge_service import KnowledgeService
from tests.fakes import FakeSiteReader, InMemoryRepo

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

CLINIC = ClinicProfile(name="Clinica Primera", contact="tel 0349 999", phone="0349 999")
TEMPLATE = PromptTemplate(version="ro/system.v1", text="Asistent pentru {clinic_name}.")


def build(reader=None, repo=None, llm=None) -> KnowledgeService:
    return KnowledgeService(
        reader=reader or FakeSiteReader(),
        repo=repo or InMemoryRepo(),
        llm=llm or FakeLLM(),
        clinic=CLINIC,
        template=TEMPLATE,
        clock=lambda: NOW,
    )


async def test_refresh_construieste_blocurile_de_prompt() -> None:
    service = build()
    assert not service.has_content

    assert await service.refresh() is True

    assert service.has_content
    blocks = service.system_blocks
    assert "Clinica Primera" in blocks[0].text
    assert "250 RON" in blocks[1].text
    assert blocks[1].cacheable is True


async def test_snapshotul_se_salveaza_pe_disc() -> None:
    repo = InMemoryRepo()
    service = build(repo=repo)
    await service.refresh()
    assert repo.saves == 1
    assert repo.snapshot is not None


async def test_scraping_esuat_pastreaza_versiunea_anterioara() -> None:
    # Mai bine date de ieri decât niciun agent.
    reader = FakeSiteReader()
    service = build(reader=reader)
    await service.refresh()
    good_id = service.snapshot_id

    reader.raise_error = ConnectionError("site căzut")
    assert await service.refresh() is False

    assert service.snapshot_id == good_id
    assert service.has_content
    assert service.status().consecutive_failures == 1


async def test_trei_esecuri_consecutive_produc_un_log_de_eroare(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeSiteReader(pages=[])
    service = build(reader=reader)

    with caplog.at_level(logging.ERROR):
        await service.refresh()
        await service.refresh()
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        await service.refresh()

    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert service.status().consecutive_failures == 3


async def test_un_succes_reseteaza_contorul() -> None:
    reader = FakeSiteReader(pages=[])
    service = build(reader=reader)
    await service.refresh()
    assert service.status().consecutive_failures == 1

    reader.pages = [Page("https://x.ro/a", "A", "conținut suficient de lung")]
    await service.refresh()
    assert service.status().consecutive_failures == 0


async def test_continut_neschimbat_nu_rescrie_snapshotul() -> None:
    repo = InMemoryRepo()
    service = build(repo=repo)
    await service.refresh()
    await service.refresh()
    # A doua rulare a găsit același conținut, deci nu are ce salva.
    assert repo.saves == 1


async def test_continut_nou_incalzeste_cache_ul() -> None:
    llm = FakeLLM()
    reader = FakeSiteReader()
    service = build(reader=reader, llm=llm)
    await service.refresh()
    assert llm.warm_calls == 1


async def test_keep_alive_ul_nu_darama_aplicatia_daca_modelul_cade() -> None:
    from clinic_agent.adapters.fake_llm import BrokenLLM

    service = build(llm=BrokenLLM())
    await service.refresh()
    await service.warm_cache()  # nu trebuie să arunce


async def test_snapshotul_de_pe_disc_se_incarca_la_pornire() -> None:
    stored = Snapshot.from_pages([Page("https://x.ro/a", "A", "text vechi")], NOW)
    service = build(repo=InMemoryRepo(stored))
    assert service.has_content
    assert service.snapshot_id == stored.id


async def test_doua_actualizari_simultane_nu_scrapeaza_de_doua_ori() -> None:
    """Job-ul programat și un /api/refresh manual se pot suprapune.

    Fără coalescere: două scraping-uri simultane, două salvări pe disc și
    două scrieri în cache — a doua inutilă, la ~5 cenți.
    """
    import asyncio

    class SlowReader(FakeSiteReader):
        async def fetch_pages(self):  # noqa: ANN201
            await asyncio.sleep(0.05)
            return await super().fetch_pages()

    reader = SlowReader()
    llm = FakeLLM()
    service = build(reader=reader, llm=llm)

    results = await asyncio.gather(*(service.refresh() for _ in range(4)))

    assert all(results)
    assert reader.calls == 1
    assert llm.warm_calls == 1


async def test_starea_expusa_in_health() -> None:
    service = build()
    await service.refresh()
    status = service.status()
    assert status.page_count == 2
    assert status.estimated_tokens > 0
    assert status.age_hours == 0.0
    assert status.snapshot_id is not None
