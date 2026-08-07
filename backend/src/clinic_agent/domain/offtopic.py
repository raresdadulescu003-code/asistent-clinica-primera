"""Filtrul de întrebări vădit din alt domeniu.

Motivul e experiența, nu costul: un răspuns fix e identic de fiecare dată și
vine instant, față de unul generat care variază și consumă o secundă.

REGULA DE AUR: îngust, nu larg. Un fals pozitiv — un pacient blocat pentru că
și-a descris afecțiunea cu un cuvânt de pe listă — costă infinit mai mult decât
cele 0,34 de cenți economisite. Tentația de a lărgi lista trebuie refuzată.
"""

from __future__ import annotations

import re

from clinic_agent.domain.language import Language, detect_language
from clinic_agent.domain.normalization import normalize_question

FIXED_REPLY = {
    "ro": (
        "Pot răspunde doar la întrebări despre Clinica Primera — servicii, "
        "prețuri, medici, program. Cu ce te pot ajuta?"
    ),
    "en": (
        "I can only answer questions about Clinica Primera — services, prices, "
        "doctors, opening hours. How can I help?"
    ),
}

# Tiparele se aplică pe textul NORMALIZAT: minuscule, fără diacritice,
# fără punctuație. De aceea „te-a" se scrie „te a", iar „what's" — „what s".
_PATTERNS = [
    # politică — „primar" lipsește intenționat: există „medic primar"
    r"\b(guvernul|parlamentul|alegerile|prim ministru|premierul)\b",
    r"\bpresedintele (romaniei|tarii|americii)\b",
    r"\bwho is the president\b",
    # vreme — fără `\b` la final: „vreme" și „vremea" trebuie prinse amândouă
    r"\b(ce|cum e|cum este|care e) vreme",
    r"\bva (ploua|ninge)\b",
    r"\bcate grade (e|este|sunt) afara\b",
    r"\b(what|how) s the weather\b",
    # sport — „meciul", „campionatul" au sufixe, deci potrivim doar prefixul
    r"\b(fotbal|meci|campionat|fcsb|olimpiada)",
    r"\b(football|soccer|world cup)\b",
    # glume
    r"\b(spune|zi)( mi)? (un banc|o gluma)\b",
    r"\bfa ma sa rad\b",
    r"\btell me a joke\b",
    # calcule
    r"\bcat (fac|face|e|este) \d+ (plus|minus|ori|impartit|inmultit|x)\b",
    # identitate
    r"\b(ce|care) model (esti|folosesti|de ai)\b",
    r"\besti (un |o )?(robot|bot|ai|chatgpt|gpt|claude|inteligenta artificiala)\b",
    r"\bcine te a (creat|facut|programat|antrenat)\b",
    r"\b(what model are you|are you (a |an )?(bot|robot|ai|human|chatgpt))\b",
    # cereri de cod sau de scris texte
    r"\bscrie( mi)? (un |o |niste )?(cod|program|script|functie|eseu|poezie|poem)\b",
    r"\bwrite (me )?(a |an |some )?(code|script|poem|essay|program)\b",
    r"\b(python|javascript|html|css)\b",
]

_COMPILED = [re.compile(pattern) for pattern in _PATTERNS]

# Un mesaj format doar din cifre și operatori e un calcul, nu o întrebare.
_ARITHMETIC = re.compile(r"^[\d\s+\-*/^=().,:x×÷]+$")


def is_offtopic(question: str) -> bool:
    if _ARITHMETIC.fullmatch(question.strip()) and any(ch.isdigit() for ch in question):
        return True
    normalized = normalize_question(question)
    return any(pattern.search(normalized) for pattern in _COMPILED)


def offtopic_reply(question: str) -> str:
    return FIXED_REPLY[detect_language(question)]


def fallback_reply(language: Language, phone: str, email: str) -> str:
    """Ce vede vizitatorul când modelul nu răspunde.

    Nu „a apărut o eroare": pleacă cu numărul de telefon, iar o defecțiune
    tehnică devine un lead pentru clinică.
    """
    if language == "en":
        return f"I can't answer right now. Please call {phone} or email {email}."
    return f"Momentan nu pot răspunde. Sună la {phone} sau scrie la {email}."
