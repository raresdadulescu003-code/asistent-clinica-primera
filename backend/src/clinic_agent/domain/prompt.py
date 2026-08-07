"""Construirea system prompt-ului, ca structură neutră.

Domain-ul nu știe că există Anthropic, deci nu produce dicționarele lor cu
`cache_control`. Produce `PromptBlock(text, cacheable)`; adaptorul traduce.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from clinic_agent.domain.models import Snapshot

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True, slots=True)
class ClinicProfile:
    """Datele clinicii care intră în prompt, ca variabile."""

    name: str
    contact: str
    phone: str


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Textul instrucțiunilor, împreună cu versiunea lui.

    `version` vine din numele fișierului (`ro/system.v1`) și intră în cheia
    de cache. Fără el, modificarea instrucțiunilor nu ar invalida nimic.
    """

    version: str
    text: str


@dataclass(frozen=True, slots=True)
class PromptBlock:
    """Un bloc de system prompt. `cacheable` marchează granița de cache."""

    text: str
    cacheable: bool = False


def render_instructions(template: PromptTemplate, clinic: ClinicProfile) -> str:
    """Înlocuiește variabilele din șablon.

    Nu folosim `str.format`: promptul e text scris de om și orice acoladă
    rătăcită ar face metoda să crape. Înlocuim explicit doar ce cunoaștem.
    """
    values = {
        "clinic_name": clinic.name,
        "contact": clinic.contact,
        "phone": clinic.phone,
    }
    rendered = template.text
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)

    leftover = _PLACEHOLDER.findall(rendered)
    if leftover:
        raise ValueError(
            f"Variabile necompletate în {template.version}: {sorted(set(leftover))}"
        )
    return rendered.strip()


def render_site_content(snapshot: Snapshot) -> str:
    """Serializează snapshot-ul într-un singur bloc de text.

    Formatul e strict determinist: prompt caching se face pe potrivire de
    prefix, deci orice octet care se schimbă între cereri rupe cache-ul.
    """
    sections = [
        f"=== {page.title} ===\nURL: {page.url}\n\n{page.text}"
        for page in snapshot.pages
    ]
    return "\n\n".join(sections)


def instruction_markers(instructions: str) -> tuple[str, ...]:
    """Fraze care nu pot apărea într-un răspuns legitim: titlurile de secțiune.

    Se extrag din prompt, nu se scriu de mână: dacă cineva adaugă o secțiune
    nouă, garda o acoperă automat. „CUM SCRII" sau „SURSA DE ADEVĂR" n-au ce
    căuta într-un răspuns despre prețuri — prezența lor înseamnă scurgere.
    """
    markers = []
    for line in instructions.splitlines():
        candidate = line.strip()
        if (
            len(candidate) >= 5
            and candidate == candidate.upper()
            and any(ch.isalpha() for ch in candidate)
            and not any(ch.isdigit() for ch in candidate)
        ):
            markers.append(candidate)
    return tuple(markers)


def looks_like_instruction_leak(text: str, markers: Sequence[str]) -> bool:
    """Al doilea strat de apărare, determinist.

    Promptul îi cere modelului să nu-și divulge instrucțiunile, dar o apărare
    care depinde de cooperarea modelului nu e o garanție. Asta e.
    """
    # Sensibil la majuscule, deliberat: scurgerea reproduce titlurile verbatim,
    # iar o potrivire insensibilă ar bloca un răspuns legitim care conține
    # aceleași cuvinte cu litere mici.
    return any(marker in text for marker in markers)


def build_system_blocks(instructions: str, site_content: str) -> tuple[PromptBlock, ...]:
    """Instrucțiunile primele, conținutul al doilea și marcat drept cache-abil.

    Marcajul se pune pe ultimul bloc stabil: cache-ul acoperă tot ce e înainte
    de el, inclusiv instrucțiunile. Ordinea nu e negociabilă — inversată,
    conținutul ar ajunge în afara prefixului cache-uit.
    """
    return (
        PromptBlock(text=instructions, cacheable=False),
        PromptBlock(text=site_content, cacheable=True),
    )
