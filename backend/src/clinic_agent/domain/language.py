"""Detectarea limbii întrebării: română sau engleză.

Nu folosim o bibliotecă de detectare: pe întrebări de patru cuvinte se înșală
mai des decât o listă de cuvinte-unelte, și ar fi o dependență în plus.
"""

from __future__ import annotations

from typing import Literal

from clinic_agent.domain.normalization import normalize_question

Language = Literal["ro", "en"]

# Doar cuvinte care nu există în cealaltă limbă. „a", „o", „un", „la", „de"
# lipsesc intenționat: apar în ambele și ar produce detectări greșite.
ROMANIAN_MARKERS = frozenset(
    """
    si sau este sunt aveti ai are care cat cate costa cum pentru ce nu va imi mi
    buna ziua doresc vreau medic medici clinica pret preturi program programare
    consultatie cabinet unde cand cine multumesc as putea despre foarte
    """.split()
)

ENGLISH_MARKERS = frozenset(
    """
    the is are do does you your how what much cost costs have has can could
    hello hi please want need doctor doctors clinic price prices appointment
    where when who thanks thank about consultation opening hours book
    me my to of and with this that there tell know get from they we will
    would should
    """.split()
)


def detect_language(text: str) -> Language:
    """Româna e implicită: e limba site-ului și a majorității vizitatorilor."""
    tokens = set(normalize_question(text).split())
    romanian = len(tokens & ROMANIAN_MARKERS)
    english = len(tokens & ENGLISH_MARKERS)
    return "en" if english > romanian else "ro"
