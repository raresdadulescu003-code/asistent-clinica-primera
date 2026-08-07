"""Ce împiedică pe cineva să consume bugetul de tokeni."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clinic_agent.adapters.fake_llm import FakeLLM
from clinic_agent.adapters.memory_rate_limiter import DAY, SWEEP_INTERVAL
from clinic_agent.api.app import create_app
from clinic_agent.config.settings import Settings
from tests.test_api import SNAPSHOT
from tests.fakes import FakeSiteReader, InMemoryRepo


def build(settings: Settings, llm: FakeLLM | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings,
            llm=llm or FakeLLM(),
            site_reader=FakeSiteReader(),
            repo=InMemoryRepo(SNAPSHOT),
            run_scheduler=False,
        )
    )


def limited(settings: Settings, per_hour: int) -> Settings:
    return settings.model_copy(
        update={"rate_limit": settings.rate_limit.model_copy(update={"per_hour": per_hour})}
    )


def ask(client: TestClient, text: str, forwarded: str | None = None):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": text}]}, headers=headers
    )


# --- falsificarea IP-ului ---------------------------------------------------


def test_ip_ul_injectat_de_client_nu_ocoleste_limita(settings: Settings) -> None:
    """Regresie de securitate.

    Proxy-ul ADAUGĂ la X-Forwarded-For. Un atacator care trimite el antetul
    produce `injectat, IP-real`. Dacă am citi primul element, ar putea roti
    valoarea la fiecare cerere și limita ar fi inutilă.
    """
    client = build(limited(settings, per_hour=2))

    assert ask(client, "1", forwarded="9.9.9.9, 203.0.113.7").status_code == 200
    assert ask(client, "2", forwarded="8.8.8.8, 203.0.113.7").status_code == 200
    # Alt IP inventat în față, dar tot același client real în spate.
    assert ask(client, "3", forwarded="7.7.7.7, 203.0.113.7").status_code == 429


def test_vizitatori_reali_diferiti_raman_independenti(settings: Settings) -> None:
    client = build(limited(settings, per_hour=1))

    assert ask(client, "salut", forwarded="203.0.113.7").status_code == 200
    assert ask(client, "salut", forwarded="203.0.113.7").status_code == 429
    assert ask(client, "salut", forwarded="198.51.100.4").status_code == 200


def test_antet_lipsa_cade_pe_ip_ul_conexiunii(settings: Settings) -> None:
    client = build(limited(settings, per_hour=1))
    assert ask(client, "salut").status_code == 200
    assert ask(client, "salut").status_code == 429


# --- costul per cerere e mărginit -------------------------------------------


def test_mesajele_uriase_sunt_respinse_inainte_de_model(settings: Settings) -> None:
    llm = FakeLLM()
    client = build(settings, llm)

    assert ask(client, "x" * 50_000).status_code == 422
    assert llm.calls == []  # validarea e la graniță, înainte de orice cost


def test_o_conversatie_umflata_e_respinsa(settings: Settings) -> None:
    llm = FakeLLM()
    client = build(settings, llm)

    # Fiecare mesaj în plus se retrimite la model, deci costul crește liniar.
    messages = [{"role": "user", "content": f"mesaj {i}"} for i in range(200)]
    assert client.post("/api/chat", json={"messages": messages}).status_code == 422
    assert llm.calls == []


def test_gardienii_ruleaza_inaintea_modelului(settings: Settings) -> None:
    llm = FakeLLM()
    client = build(limited(settings, per_hour=1), llm)

    ask(client, "prima", forwarded="203.0.113.7")
    ask(client, "a doua", forwarded="203.0.113.7")

    # A doua cerere a fost oprită de limitator, nu de model.
    assert len(llm.calls) == 1


def test_refresh_ul_nu_poate_fi_declansat_de_oricine(settings: Settings) -> None:
    protected = settings.model_copy(
        update={"server": settings.server.model_copy(update={"refresh_token": "secret"})}
    )
    client = build(protected)

    assert client.post("/api/refresh").status_code == 401
    assert client.post("/api/refresh", headers={"X-Refresh-Token": "s"}).status_code == 401


@pytest.mark.parametrize("question", ["Ce vreme e afara?", "Tell me a joke", "127 * 45"])
def test_intrebarile_din_alt_domeniu_nu_costa_nimic(
    settings: Settings, question: str
) -> None:
    llm = FakeLLM()
    client = build(settings, llm)
    assert ask(client, question).status_code == 200
    assert llm.calls == []


# --- epuizarea resurselor serverului ----------------------------------------


def test_corpul_urias_e_respins_inainte_de_a_fi_citit(settings: Settings) -> None:
    client = build(settings)
    response = client.post(
        "/api/chat",
        content=b'{"messages": []}',
        headers={"Content-Type": "application/json", "Content-Length": str(50 * 1024 * 1024)},
    )
    assert response.status_code == 413


def test_limitatorul_nu_creste_la_nesfarsit() -> None:
    """Fără curățare, dicționarul ar ține o intrare per IP văzut vreodată."""
    from clinic_agent.adapters.memory_rate_limiter import MemoryRateLimiter

    now = [0.0]
    limiter = MemoryRateLimiter(per_hour=10, per_day=50, clock=lambda: now[0])

    for i in range(500):
        limiter.check(f"10.0.0.{i}")
    assert len(limiter._events) == 500

    # A doua zi, IP-urile vechi nu mai au de ce să fie ținute minte.
    now[0] = DAY + SWEEP_INTERVAL + 1
    limiter.check("203.0.113.7")
    assert len(limiter._events) == 1


def production(settings: Settings) -> Settings:
    """Setări valide de producție: originile explicite și cheia prezentă."""
    return settings.model_copy(
        update={
            "environment": "production",
            "anthropic": settings.anthropic.model_copy(update={"api_key": "sk-test"}),
        }
    )


def test_documentatia_api_nu_e_publica_in_productie(settings: Settings) -> None:
    dev = build(settings)
    assert dev.get("/api/docs").status_code == 200

    prod = build(production(settings))
    assert prod.get("/api/docs").status_code == 404
    assert prod.get("/api/openapi.json").status_code == 404


# --- configurare periculoasă: pornirea eșuează, nu merge mai departe --------


def test_cors_wildcard_opreste_pornirea_in_productie(settings: Settings) -> None:
    """Un '*' strecurat în producție ar funcționa perfect — și de asta e periculos.

    Preferăm o eroare zgomotoasă la deploy, vizibilă în log-uri.
    """
    bad = production(settings)
    bad = bad.model_copy(
        update={"server": bad.server.model_copy(update={"allowed_origins_csv": "*"})}
    )
    with pytest.raises(ValueError, match=r"\*"):
        build(bad)


def test_origini_goale_opresc_pornirea_in_productie(settings: Settings) -> None:
    bad = production(settings)
    bad = bad.model_copy(
        update={"server": bad.server.model_copy(update={"allowed_origins_csv": ""})}
    )
    with pytest.raises(ValueError, match="gol"):
        build(bad)


def test_cheia_lipsa_opreste_pornirea_in_productie(settings: Settings) -> None:
    bad = settings.model_copy(update={"environment": "production"})
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build(bad)


def test_in_dezvoltare_configurarea_permisiva_e_tolerata(settings: Settings) -> None:
    # Local vrei să poți porni fără cheie, ca să testezi degradarea elegantă.
    permissive = settings.model_copy(
        update={"server": settings.server.model_copy(update={"allowed_origins_csv": "*"})}
    )
    assert build(permissive).get("/api/health").status_code == 200
