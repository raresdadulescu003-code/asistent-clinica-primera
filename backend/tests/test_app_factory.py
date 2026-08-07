from __future__ import annotations

from fastapi.testclient import TestClient

from clinic_agent.adapters.fake_llm import FakeLLM
from clinic_agent.api.app import create_app
from clinic_agent.config.settings import Settings
from tests.fakes import FakeSiteReader, InMemoryRepo


def build(settings: Settings) -> TestClient:
    # Toate punctele de I/O sunt înlocuite prin argumentele lui `create_app`.
    return TestClient(
        create_app(
            settings,
            llm=FakeLLM(),
            site_reader=FakeSiteReader(),
            repo=InMemoryRepo(),
            run_scheduler=False,
        )
    )


def test_health_raspunde(settings: Settings) -> None:
    response = build(settings).get("/api/health")

    assert response.status_code == 200
    assert response.json()["environment"] == "test"


def test_doua_aplicatii_nu_impart_starea(settings: Settings) -> None:
    # Exact ce ne dă funcția-fabrică: două instanțe independente în același proces.
    other = settings.model_copy(update={"environment": "staging"})

    first = build(settings)
    second = build(other)

    assert first.get("/api/health").json()["environment"] == "test"
    assert second.get("/api/health").json()["environment"] == "staging"


def test_originile_cors_vin_din_setari(settings: Settings) -> None:
    response = build(settings).options(
        "/api/chat",
        headers={
            "Origin": "https://www.clinicaprimera.ro",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers["access-control-allow-origin"] == "https://www.clinicaprimera.ro"


def test_o_origine_straina_e_respinsa(settings: Settings) -> None:
    response = build(settings).options(
        "/api/chat",
        headers={
            "Origin": "https://site-strain.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers
