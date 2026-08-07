"""Normalizarea întrebărilor și construirea cheii de cache.

Aici se rezolvă structural cele două bug-uri din versiunea anterioară:
cheia include amprenta conținutului și versiunea promptului, nu doar întrebarea.
"""

from __future__ import annotations

import hashlib
import unicodedata


def strip_diacritics(text: str) -> str:
    """„Ce program aveți?" și „Ce program aveti?" trebuie să se potrivească.

    NFD desparte ș în s + virgulă-dedesubt, apoi aruncăm semnele combinante.
    Merge identic pentru ș/ş și ț/ţ (variantele cu sedilă din texte vechi).
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_question(text: str) -> str:
    """minuscule, fără diacritice, fără punctuație, spații colapsate."""
    lowered = strip_diacritics(text.lower())
    # Scoatem punctuația (categoria P) și simbolurile (S), nu tot ce nu e ASCII:
    # o întrebare scrisă în alt alfabet nu trebuie să se reducă la șirul gol.
    without_punctuation = "".join(
        " " if unicodedata.category(ch)[0] in {"P", "S"} else ch for ch in lowered
    )
    return " ".join(without_punctuation.split())


def response_cache_key(snapshot_id: str, prompt_version: str, question: str) -> str:
    """Cheia sub care se memorează un răspuns.

    Bug 1 (cursă la re-scraping): o cerere pornită pe conținut vechi are alt
    `snapshot_id`, deci scrie sub o cheie pe care nimeni nu o mai citește.
    Bug 2 (prompt schimbat): `prompt_version` intră în cheie, deci răspunsurile
    generate cu instrucțiunile vechi devin invizibile automat.
    """
    material = f"{snapshot_id}|{prompt_version}|{normalize_question(question)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
