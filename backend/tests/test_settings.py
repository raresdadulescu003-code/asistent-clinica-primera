from __future__ import annotations

from clinic_agent.config.settings import Settings


def test_grupurile_exista(settings: Settings) -> None:
    assert settings.clinic.name == "Clinica Primera"
    assert settings.anthropic.model == "claude-haiku-4-5"
    assert settings.rate_limit.per_hour == 30


def test_originile_nu_sunt_wildcard(settings: Settings) -> None:
    # Regresie: `allow_origins=["*"]` ajuns în producție e un footgun.
    assert "*" not in settings.server.allowed_origins
    assert "https://www.clinicaprimera.ro" in settings.server.allowed_origins


def test_csv_se_parseaza_in_tuplu(settings: Settings) -> None:
    assert settings.scraper.excluded_slugs == (
        "termeni-si-conditii",
        "termeni-de-confidentialitate",
        "politica-de-cookies",
        "galerie",
    )


def test_contactul_se_compune_din_telefon_si_email(settings: Settings) -> None:
    contact = settings.clinic.contact
    assert "0349 999" in contact
    assert "office@clinicaprimera.ro" in contact
