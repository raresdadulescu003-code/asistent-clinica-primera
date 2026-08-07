"""Estimarea costului unui apel.

Cifrele sunt cele publicate pentru Haiku 4.5. Estimarea de tokeni e o
aproximare pentru dashboard, nu sursa de adevăr pentru facturare — aceea e
`usage` din răspunsul API-ului.
"""

from __future__ import annotations

from dataclasses import dataclass

# Calibrat pe conținutul real al site-ului: 60.440 de caractere au produs
# ~23.100 de tokeni (măsurați din câmpul `usage` al API-ului). Româna cu
# diacritice se tokenizează mai prost decât engleza — un 3,6 „de manual" ar
# subestima cu 30%.
CHARS_PER_TOKEN = 2.6


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Prețuri în USD per milion de tokeni, plus multiplicatorii de cache."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_multiplier: float = 0.10
    cache_write_5m_multiplier: float = 1.25
    cache_write_1h_multiplier: float = 2.00

    def cache_write_multiplier(self, ttl: str) -> float:
        if ttl == "1h":
            return self.cache_write_1h_multiplier
        if ttl == "5m":
            return self.cache_write_5m_multiplier
        raise ValueError(f"TTL necunoscut: {ttl!r}")


HAIKU_4_5 = ModelPricing(input_per_mtok=1.00, output_per_mtok=5.00)


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN)) if text else 0


@dataclass(frozen=True, slots=True)
class CallCost:
    """Costul unui apel, descompus pe surse."""

    input_usd: float
    cache_read_usd: float
    cache_write_usd: float
    output_usd: float

    @property
    def total_usd(self) -> float:
        return (
            self.input_usd + self.cache_read_usd + self.cache_write_usd + self.output_usd
        )

    @property
    def total_cents(self) -> float:
        return self.total_usd * 100


def estimate_call_cost(
    pricing: ModelPricing = HAIKU_4_5,
    *,
    input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    output_tokens: int = 0,
    cache_ttl: str = "1h",
) -> CallCost:
    """Costul unui apel, pornind de la numărul de tokeni pe fiecare categorie."""
    per_token_in = pricing.input_per_mtok / 1_000_000
    per_token_out = pricing.output_per_mtok / 1_000_000
    return CallCost(
        input_usd=input_tokens * per_token_in,
        cache_read_usd=cache_read_tokens * per_token_in * pricing.cache_read_multiplier,
        cache_write_usd=(
            cache_write_tokens * per_token_in * pricing.cache_write_multiplier(cache_ttl)
        ),
        output_usd=output_tokens * per_token_out,
    )
