"""Teste pe endpoint-uri, cu `FakeLLM` injectat. Zero apeluri reale."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from clinic_agent.adapters.fake_llm import FakeLLM
from clinic_agent.api.app import create_app
from clinic_agent.config.settings import Settings
from clinic_agent.domain.models import Page, Snapshot
from tests.fakes import FakeSiteReader, InMemoryRepo

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

SNAPSHOT = Snapshot.from_pages(
    [
        Page("https://x.ro/preturi", "Prețuri", "Consultația stomatologică 250 RON."),
        Page("https://x.ro/echipa", "Echipa", "Dr. Toma Florentina, cardiologie."),
    ],
    NOW,
)


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM(reply="Programul este luni-vineri 8:30-20:30.")


@pytest.fixture
def client(settings: Settings, llm: FakeLLM) -> TestClient:
    """Aplicație cu snapshot deja încărcat, fără scheduler și fără rețea."""
    app = create_app(
        settings,
        llm=llm,
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(SNAPSHOT),
        run_scheduler=False,
    )
    return TestClient(app)


def read_sse(response) -> list[dict]:
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def ask(client: TestClient, *messages: tuple[str, str], ip: str = "1.2.3.4"):
    return client.post(
        "/api/chat",
        json={"messages": [{"role": r, "content": c} for r, c in messages]},
        headers={"X-Forwarded-For": ip},
    )


# --- fluxul normal ---------------------------------------------------------


def test_chat_intoarce_evenimente_sse(client: TestClient) -> None:
    response = ask(client, ("user", "Care e programul?"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = read_sse(response)
    assert events[-1] == {"type": "done"}
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "8:30" in text


def test_streaming_ul_vine_in_bucati(client: TestClient) -> None:
    events = read_sse(ask(client, ("user", "Care e programul?")))
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) > 1


def test_intrebarea_din_alt_domeniu_nu_atinge_modelul(
    client: TestClient, llm: FakeLLM
) -> None:
    events = read_sse(ask(client, ("user", "Ce vreme e afara?")))
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "Clinica Primera" in text
    assert llm.calls == []


# --- gardieni --------------------------------------------------------------


def test_baza_goala_da_503(settings: Settings) -> None:
    app = create_app(
        settings,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(None),
        run_scheduler=False,
    )
    response = ask(TestClient(app), ("user", "salut"))
    assert response.status_code == 503
    assert settings.clinic.phone in response.json()["detail"]


def test_conversatie_prea_lunga_da_400(client: TestClient) -> None:
    messages = [("user", f"mesaj {i}") for i in range(25)]
    response = ask(client, *messages)
    assert response.status_code == 400
    assert settings_phone_in(response)


def settings_phone_in(response) -> bool:
    return "0349 999" in response.json()["detail"]


def test_rate_limit_da_429(settings: Settings) -> None:
    strict = settings.model_copy(
        update={"rate_limit": settings.rate_limit.model_copy(update={"per_hour": 2})}
    )
    app = create_app(
        strict,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(SNAPSHOT),
        run_scheduler=False,
    )
    client = TestClient(app)

    assert ask(client, ("user", "prima")).status_code == 200
    assert ask(client, ("user", "a doua")).status_code == 200
    third = ask(client, ("user", "a treia"))

    assert third.status_code == 429
    assert "Retry-After" in third.headers


def test_limita_e_pe_ip_nu_globala(settings: Settings) -> None:
    strict = settings.model_copy(
        update={"rate_limit": settings.rate_limit.model_copy(update={"per_hour": 1})}
    )
    app = create_app(
        strict,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(SNAPSHOT),
        run_scheduler=False,
    )
    client = TestClient(app)

    assert ask(client, ("user", "salut"), ip="1.1.1.1").status_code == 200
    assert ask(client, ("user", "salut"), ip="1.1.1.1").status_code == 429
    # Alt vizitator, în spatele aceluiași proxy, nu trebuie afectat.
    assert ask(client, ("user", "salut"), ip="2.2.2.2").status_code == 200


def test_mesajele_de_eroare_sunt_in_limba_intrebarii(client: TestClient) -> None:
    # Limba se ia din ULTIMUL mesaj, cel pe care tocmai l-a scris vizitatorul.
    messages = [("user", f"mesaj {i}") for i in range(24)]
    messages.append(("user", "What are your opening hours?"))
    response = ask(client, *messages)

    assert response.status_code == 400
    assert response.json()["detail"].startswith("This conversation")


# --- validare --------------------------------------------------------------


def test_lista_goala_de_mesaje_e_respinsa(client: TestClient) -> None:
    assert client.post("/api/chat", json={"messages": []}).status_code == 422


def test_ultimul_mesaj_trebuie_sa_fie_al_utilizatorului(client: TestClient) -> None:
    assert ask(client, ("user", "salut"), ("assistant", "buna")).status_code == 422


def test_mesajele_uriase_sunt_respinse(client: TestClient) -> None:
    assert ask(client, ("user", "x" * 5000)).status_code == 422


# --- health ----------------------------------------------------------------


def test_health_expune_starea_cunostintelor_si_a_cache_ului(client: TestClient) -> None:
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["knowledge"]["page_count"] == 2
    assert body["knowledge"]["consecutive_failures"] == 0
    assert body["knowledge"]["snapshot_id"] == SNAPSHOT.id
    assert set(body["cache"]) == {"hits", "misses", "hit_rate", "entries"}


def test_health_reflecta_rata_de_acoperire(client: TestClient) -> None:
    ask(client, ("user", "Care e programul?"))
    ask(client, ("user", "care e programul"))

    cache = client.get("/api/health").json()["cache"]
    assert cache["hits"] == 1
    assert cache["hit_rate"] > 0


def test_health_e_degraded_fara_continut(settings: Settings) -> None:
    app = create_app(
        settings,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(None),
        run_scheduler=False,
    )
    assert TestClient(app).get("/api/health").json()["status"] == "degraded"


# --- refresh ---------------------------------------------------------------


def test_refresh_fara_token_e_respins(settings: Settings) -> None:
    protected = settings.model_copy(
        update={"server": settings.server.model_copy(update={"refresh_token": "secret"})}
    )
    app = create_app(
        protected,
        llm=FakeLLM(),
        site_reader=FakeSiteReader(),
        repo=InMemoryRepo(SNAPSHOT),
        run_scheduler=False,
    )
    client = TestClient(app)

    assert client.post("/api/refresh").status_code == 401
    assert (
        client.post("/api/refresh", headers={"X-Refresh-Token": "gresit"}).status_code
        == 401
    )
    assert (
        client.post("/api/refresh", headers={"X-Refresh-Token": "secret"}).status_code
        == 200
    )


def test_refresh_fara_token_configurat_e_indisponibil(client: TestClient) -> None:
    assert client.post("/api/refresh").status_code == 503
