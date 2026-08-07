"""Verifică exact cifrele din analiza de cost a proiectului.

Dacă un test de aici pică, ori s-au schimbat prețurile modelului, ori cineva
a stricat formula — în ambele cazuri vrem să aflăm imediat.
"""

from __future__ import annotations

import pytest

from clinic_agent.domain.pricing import (
    HAIKU_4_5,
    estimate_call_cost,
    estimate_tokens,
)

SITE_TOKENS = 24_500


def test_citirea_din_cache_costa_0_25_centi() -> None:
    cost = estimate_call_cost(cache_read_tokens=SITE_TOKENS)
    assert cost.total_cents == pytest.approx(0.245, abs=0.005)


def test_scrierea_in_cache_pe_o_ora_costa_4_9_centi() -> None:
    cost = estimate_call_cost(cache_write_tokens=SITE_TOKENS, cache_ttl="1h")
    assert cost.total_cents == pytest.approx(4.9, abs=0.05)


def test_scrierea_pe_5_minute_e_mai_ieftina_dar_expira() -> None:
    one_hour = estimate_call_cost(cache_write_tokens=SITE_TOKENS, cache_ttl="1h")
    five_min = estimate_call_cost(cache_write_tokens=SITE_TOKENS, cache_ttl="5m")
    assert five_min.total_usd < one_hour.total_usd
    assert one_hour.total_usd / five_min.total_usd == pytest.approx(2.0 / 1.25)


def test_generarea_raspunsului_costa_0_08_centi() -> None:
    cost = estimate_call_cost(output_tokens=160)
    assert cost.total_cents == pytest.approx(0.08, abs=0.005)


def test_keep_alive_ul_e_de_20_de_ori_mai_ieftin_decat_rescrierea() -> None:
    # Justificarea job-ului la 50 de minute, exprimată ca test.
    keepalive = estimate_call_cost(cache_read_tokens=SITE_TOKENS)
    rewrite = estimate_call_cost(cache_write_tokens=SITE_TOKENS, cache_ttl="1h")
    assert rewrite.total_usd / keepalive.total_usd == pytest.approx(20.0)


def test_costul_se_descompune_pe_surse() -> None:
    cost = estimate_call_cost(
        input_tokens=50, cache_read_tokens=SITE_TOKENS, output_tokens=160
    )
    assert cost.cache_write_usd == 0
    assert cost.total_usd == pytest.approx(
        cost.input_usd + cost.cache_read_usd + cost.output_usd
    )


def test_ttl_necunoscut_crapa() -> None:
    with pytest.raises(ValueError):
        HAIKU_4_5.cache_write_multiplier("30m")


def test_estimarea_de_tokeni_e_calibrata_pe_masuratoarea_reala() -> None:
    assert estimate_tokens("") == 0
    # Măsurat pe site-ul real: 60.440 de caractere → 23.095 de tokeni facturați.
    assert estimate_tokens("x" * 60_440) == pytest.approx(23_100, rel=0.05)
