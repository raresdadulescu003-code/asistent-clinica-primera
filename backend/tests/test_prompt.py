from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clinic_agent.domain.models import Page, Snapshot
from clinic_agent.domain.prompt import (
    ClinicProfile,
    PromptTemplate,
    build_system_blocks,
    render_instructions,
    render_site_content,
)

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

CLINIC = ClinicProfile(
    name="Clinica Primera",
    contact="telefon 0349 999, email office@clinicaprimera.ro",
    phone="0349 999",
)


def test_variabilele_se_completeaza() -> None:
    template = PromptTemplate(
        version="ro/system.v1",
        text="Ești asistentul pentru {clinic_name}. Contact: {contact}. Tel: {phone}.",
    )
    rendered = render_instructions(template, CLINIC)

    assert "Clinica Primera" in rendered
    assert "0349 999" in rendered
    assert "{" not in rendered


def test_o_variabila_necunoscuta_crapa_imediat() -> None:
    # Mai bine o eroare la pornire decât un „{adresa}" afișat vizitatorului.
    template = PromptTemplate(version="ro/system.v1", text="Sună la {telefon_gresit}.")
    with pytest.raises(ValueError, match="telefon_gresit"):
        render_instructions(template, CLINIC)


def test_promptul_real_se_randeaza_complet() -> None:
    from clinic_agent.config.settings import BACKEND_ROOT

    text = (BACKEND_ROOT / "prompts" / "ro" / "system.v1.md").read_text(encoding="utf-8")
    rendered = render_instructions(
        PromptTemplate(version="ro/system.v1", text=text), CLINIC
    )
    assert "Clinica Primera" in rendered
    assert "{" not in rendered


def test_continutul_site_ului_e_determinist() -> None:
    # Prompt caching e potrivire de prefix: același snapshot, același text.
    snapshot = Snapshot.from_pages(
        [Page("/preturi", "Prețuri", "Detartraj 250 RON"), Page("/echipa", "Echipa", "Dr. X")],
        NOW,
    )
    assert render_site_content(snapshot) == render_site_content(snapshot)


def test_continutul_contine_titlul_si_url_ul() -> None:
    snapshot = Snapshot.from_pages([Page("/preturi", "Prețuri", "Detartraj 250 RON")], NOW)
    rendered = render_site_content(snapshot)
    assert "Prețuri" in rendered
    assert "/preturi" in rendered
    assert "250 RON" in rendered


def test_doar_al_doilea_bloc_e_cache_abil() -> None:
    blocks = build_system_blocks("instrucțiuni", "conținut site")

    assert len(blocks) == 2
    assert blocks[0].text == "instrucțiuni"
    assert blocks[0].cacheable is False
    # Marcajul stă pe ultimul bloc stabil; cache-ul acoperă tot ce e înaintea lui.
    assert blocks[1].cacheable is True
