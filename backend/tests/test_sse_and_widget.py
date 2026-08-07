"""Contractul SSE și servirea widget-ului."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from clinic_agent.adapters.fake_llm import FakeLLM
from clinic_agent.api.app import create_app
from clinic_agent.api.sse import done_event, error_event, token_event
from clinic_agent.config.settings import Settings
from tests.fakes import FakeSiteReader, InMemoryRepo


def parse(event: str) -> dict:
    assert event.startswith("data: ") and event.endswith("\n\n")
    return json.loads(event[6:-2])


def test_formatul_evenimentelor() -> None:
    assert parse(token_event("text")) == {"type": "token", "text": "text"}
    assert parse(done_event()) == {"type": "done"}
    assert parse(error_event("ups")) == {"type": "error", "message": "ups"}


def test_diacriticele_nu_sunt_escapate_in_json() -> None:
    # `ensure_ascii=False` ține evenimentele mici și lizibile în DevTools.
    assert "ă" in token_event("ăâîșț")


def test_ghilimelele_din_raspuns_nu_rup_fluxul() -> None:
    event = token_event('el a spus "da"\nși a plecat')
    assert event.count("\n\n") == 1  # doar separatorul de la final
    assert parse(event)["text"] == 'el a spus "da"\nși a plecat'


def test_widgetul_e_servit_de_backend(settings: Settings) -> None:
    app = create_app(
        settings,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(),
        run_scheduler=False,
    )
    response = TestClient(app).get("/widget/widget.js")

    assert response.status_code == 200
    assert "attachShadow" in response.text


def test_avertismentul_de_confidentialitate_exista_in_ambele_limbi(
    settings: Settings,
) -> None:
    widget = (settings.server.widget_dir / "widget.js").read_text(encoding="utf-8")
    assert "Nu introduce date personale sau medicale." in widget
    assert "Please don't enter personal or medical data." in widget


def test_garda_de_mixed_content_exista(settings: Settings) -> None:
    """Backend pe http + site pe https = cereri blocate TĂCUT de browser."""
    widget = (settings.server.widget_dir / "widget.js").read_text(encoding="utf-8")
    assert 'location.protocol === "https:"' in widget
    assert 'indexOf("http://") === 0' in widget


def test_widgetul_si_backendul_folosesc_acelasi_contract(settings: Settings) -> None:
    # Dacă cineva redenumește un tip de eveniment, testul ăsta îl prinde.
    widget = (settings.server.widget_dir / "widget.js").read_text(encoding="utf-8")
    assert 'event.type === "token"' in widget
    assert 'event.type === "error"' in widget
    assert '"data: "' in widget
