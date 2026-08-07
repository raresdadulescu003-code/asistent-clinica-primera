"""Setările aplicației, grupate pe domenii.

Fiecare grup e o clasă separată, cu propriul prefix de variabile de mediu.
Alternativa — un singur obiect plat cu 25 de câmpuri — face imposibil de spus,
citind o funcție, ce parte din configurare atinge de fapt.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Rădăcina proiectului backend/, calculată pornind de la fișierul curent:
# .../backend/src/clinic_agent/config/settings.py -> .../backend
BACKEND_ROOT = Path(__file__).resolve().parents[3]

_ENV_FILE = BACKEND_ROOT / ".env"


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


class ClinicSettings(BaseSettings):
    """Datele clinicii. Intră în promptul agentului ca variabile."""

    model_config = SettingsConfigDict(
        env_prefix="CLINIC_", env_file=_ENV_FILE, extra="ignore"
    )

    name: str = "Clinica Primera"
    site_url: str = "https://www.clinicaprimera.ro"
    phone: str = "0349 999"
    phone_alt: str = "0775 326 574"
    email: str = "office@clinicaprimera.ro"
    schedule: str = "Luni-Vineri 8:30-20:30, Sâmbătă 10:00-14:00"

    @property
    def contact(self) -> str:
        """Blocul de contact așa cum îl primește agentul în prompt."""
        return f"telefon {self.phone} sau {self.phone_alt}, email {self.email}"


class AnthropicSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANTHROPIC_", env_file=_ENV_FILE, extra="ignore"
    )

    api_key: str = ""
    model: str = "claude-haiku-4-5"
    max_tokens: int = 1024
    # TTL-ul blocului cache_control. "1h" costă 2x la scriere, dar keep-alive-ul
    # îl face rentabil; "5m" ar expira între vizitatori.
    cache_ttl: str = "1h"
    # Fiecare citire din cache resetează TTL-ul; 50 < 60 lasă marjă de siguranță.
    keepalive_minutes: int = 50
    request_timeout_seconds: float = 60.0


class ScraperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_", env_file=_ENV_FILE, extra="ignore"
    )

    sitemap_url: str = "https://www.clinicaprimera.ro/sitemap.xml"
    interval_hours: int = 24
    request_timeout_seconds: float = 20.0
    # Sub pragul ăsta pagina e considerată goală (meniu, redirect, placeholder).
    min_text_chars: int = 120
    # Pagini juridice: 18% din tokeni pentru întrebări pe care nu le pune nimeni.
    # `galerie`: doar text despre fotografii pe care agentul nu le poate arăta.
    excluded_slugs_csv: str = (
        "termeni-si-conditii,termeni-de-confidentialitate,"
        "politica-de-cookies,galerie"
    )
    # După atâtea eșecuri consecutive, log de nivel ERROR (vezi monitorizare).
    failure_alert_threshold: int = 3

    @property
    def excluded_slugs(self) -> tuple[str, ...]:
        return _split_csv(self.excluded_slugs_csv)


class CacheSettings(BaseSettings):
    """Cache-ul de răspunsuri din aplicație (nu cel de prompt de la Anthropic)."""

    model_config = SettingsConfigDict(
        env_prefix="CACHE_", env_file=_ENV_FILE, extra="ignore"
    )

    enabled: bool = True
    ttl_seconds: int = 7 * 24 * 3600
    max_entries: int = 500
    # Întrebările lungi sunt unicate și pot conține date personale — nu se memorează.
    max_question_chars: int = 200


class RateLimitSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RATE_LIMIT_", env_file=_ENV_FILE, extra="ignore"
    )

    enabled: bool = True
    per_hour: int = 30
    per_day: int = 150
    max_conversation_messages: int = 24


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SERVER_", env_file=_ENV_FILE, extra="ignore"
    )

    host: str = "0.0.0.0"
    port: int = 8000
    # Explicit, niciodată "*": widget-ul rulează pe alt domeniu decât backend-ul.
    allowed_origins_csv: str = (
        "https://www.clinicaprimera.ro,https://clinicaprimera.ro"
    )
    refresh_token: str = ""
    # Aplicația e în spatele unui proxy (Render/Railway), deci IP-ul real
    # vine din X-Forwarded-For, nu din conexiunea TCP.
    trust_forwarded_for: bool = True
    # Câte proxy-uri de încredere stau în față. Render și Railway: exact unul.
    # Contează pentru securitate — vezi `client_ip` în api/deps.py.
    trusted_proxy_hops: int = 1
    data_dir: Path = BACKEND_ROOT / "data"
    prompts_dir: Path = BACKEND_ROOT / "prompts"
    widget_dir: Path = BACKEND_ROOT / "widget"

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return _split_csv(self.allowed_origins_csv)


class Settings(BaseSettings):
    """Rădăcina configurării. Se transmite explicit lui `create_app`."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    environment: str = "development"
    clinic: ClinicSettings = Field(default_factory=ClinicSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    """Citește setările din mediu / `.env`.

    Funcție separată, nu un `settings = Settings()` la nivel de modul: în teste
    vrem să construim setări ad-hoc fără să atingem fișierul `.env` real.
    """
    return Settings()
