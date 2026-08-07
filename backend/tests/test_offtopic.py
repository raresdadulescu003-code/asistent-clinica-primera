"""Testul cerut explicit: filtrul nu are voie să prindă întrebări legitime.

Dacă un test din prima clasă pică, filtrul e prea lat — se îngustează lista,
nu se schimbă testul.
"""

from __future__ import annotations

import pytest

from clinic_agent.domain.language import detect_language
from clinic_agent.domain.offtopic import fallback_reply, is_offtopic, offtopic_reply

LEGITIME = [
    # Formulări care se apropie periculos de tiparele blocate.
    "Ce program aveți?",
    "Ce program de lucru are clinica sâmbăta?",
    "Aveți medic primar cardiolog?",  # „primar" — de aceea nu e pe listă
    "Cât costă o consultație?",
    "Cat costa un detartraj?",
    "Am dureri de cap de 3 zile si ameteli.",
    "Mă doare în piept când urc scările, la ce medic merg?",
    "Aveti aparat RMN si cat costa un RMN cerebral?",
    "Vreau sa ma programez maine la ORL la ora 10.",
    "Cum imi protejati datele personale?",
    "Do you have an ophthalmologist? How much is a consultation?",
    "What are your opening hours?",
    "Unde sunteți în Slatina?",
    "Copilul meu are febră 39, ce specialist recomandați?",
    "Faceți analize de sânge?",
    "Am diabet, ce medic imi recomandati?",
]

DIN_ALT_DOMENIU = [
    "Ce vreme e afară?",
    "Va ploua maine?",
    "Cine e presedintele Romaniei?",
    "Ce scor a fost la meciul de aseara?",
    "Spune-mi un banc.",
    "Tell me a joke",
    "Cat fac 2 plus 2?",
    "127 * 45",
    "Ce model esti?",
    "Esti un bot?",
    "Are you an AI?",
    "Scrie-mi un cod in python pentru sortare.",
    "Write me a poem about the sea",
    "What's the weather in Bucharest?",
]


@pytest.mark.parametrize("question", LEGITIME)
def test_intrebarile_legitime_nu_sunt_prinse(question: str) -> None:
    assert not is_offtopic(question), f"fals pozitiv: {question!r}"


@pytest.mark.parametrize("question", DIN_ALT_DOMENIU)
def test_intrebarile_din_alt_domeniu_sunt_prinse(question: str) -> None:
    assert is_offtopic(question), f"nu a fost prinsă: {question!r}"


def test_raspunsul_fix_e_in_limba_intrebarii() -> None:
    assert "Clinica Primera" in offtopic_reply("Ce vreme e afară?")
    assert offtopic_reply("Tell me a joke").startswith("I can only")


def test_detectarea_limbii() -> None:
    assert detect_language("Cat costa o consultatie?") == "ro"
    assert detect_language("How much is a consultation?") == "en"
    assert detect_language("") == "ro"  # româna e implicită


def test_mesajul_de_degradare_contine_telefonul() -> None:
    ro = fallback_reply("ro", "0349 999", "office@clinicaprimera.ro")
    en = fallback_reply("en", "0349 999", "office@clinicaprimera.ro")
    assert "0349 999" in ro and "eroare" not in ro.lower()
    assert "0349 999" in en and "error" not in en.lower()
