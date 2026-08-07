from __future__ import annotations

import pytest

from clinic_agent.domain.normalization import normalize_question, response_cache_key


@pytest.mark.parametrize(
    "text",
    [
        "Care e programul?",
        "care e programul",
        "CARE E PROGRAMUL?!",
        "  care   e   programul  ",
    ],
)
def test_variante_ale_aceleiasi_intrebari_se_normalizeaza_identic(text: str) -> None:
    assert normalize_question(text) == "care e programul"


def test_diacriticele_dispar() -> None:
    assert normalize_question("Ce medici aveți?") == "ce medici aveti"
    assert normalize_question("Ce medici aveti?") == "ce medici aveti"


def test_si_varianta_cu_sedila() -> None:
    # ş (U+015F) și ţ (U+0163) apar în texte copiate din surse vechi.
    assert normalize_question("preţuri şi program") == normalize_question(
        "prețuri și program"
    )


def test_intrebarea_in_alt_alfabet_nu_devine_goala() -> None:
    # Regresie: o filtrare naivă „doar a-z" ar reduce asta la șirul gol,
    # iar toate întrebările în alt alfabet ar lovi aceeași intrare de cache.
    assert normalize_question("Πόσο κοστίζει;") != ""


def test_cheia_se_schimba_la_alt_snapshot() -> None:
    # Bug 1: un răspuns generat pe conținut vechi nu mai e citit niciodată.
    old = response_cache_key("snap_vechi", "ro/system.v1", "cat costa un detartraj")
    new = response_cache_key("snap_nou", "ro/system.v1", "cat costa un detartraj")
    assert old != new


def test_cheia_se_schimba_la_alta_versiune_de_prompt() -> None:
    # Bug 2: modificarea instrucțiunilor invalidează automat răspunsurile vechi.
    v1 = response_cache_key("snap", "ro/system.v1", "cat costa un detartraj")
    v2 = response_cache_key("snap", "ro/system.v2", "cat costa un detartraj")
    assert v1 != v2


def test_cheia_e_stabila_pentru_aceleasi_intrari() -> None:
    args = ("snap", "ro/system.v1", "Care e programul?")
    assert response_cache_key(*args) == response_cache_key(*args)


def test_cheia_ignora_diacriticele_si_punctuatia() -> None:
    with_diacritics = response_cache_key("snap", "v1", "Care e programul?")
    without = response_cache_key("snap", "v1", "care e programul")
    assert with_diacritics == without
