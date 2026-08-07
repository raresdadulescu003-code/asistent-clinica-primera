from __future__ import annotations

import pytest

from clinic_agent.config.settings import (
    AnthropicSettings,
    CacheSettings,
    ClinicSettings,
    RateLimitSettings,
    ScraperSettings,
    ServerSettings,
    Settings,
)


@pytest.fixture
def settings() -> Settings:
    """Setări de test, izolate de fișierul `.env` al dezvoltatorului.

    `_env_file=None` trebuie dat fiecărui grup în parte, pentru că fiecare își
    citește singur fișierul. Fără asta, testele ar trece sau ar pica în funcție
    de ce are fiecare în `.env` — exact genul de eșec care apare abia pe alt
    calculator sau în CI.
    """
    return Settings(
        environment="test",
        clinic=ClinicSettings(_env_file=None),
        anthropic=AnthropicSettings(_env_file=None),
        scraper=ScraperSettings(_env_file=None),
        cache=CacheSettings(_env_file=None),
        rate_limit=RateLimitSettings(_env_file=None),
        server=ServerSettings(_env_file=None),
        _env_file=None,
    )
