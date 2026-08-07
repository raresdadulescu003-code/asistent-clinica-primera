"""Evaluare pe întrebări-etalon. RULEAZĂ DOAR MANUAL — costă bani.

Nu e test pytest, ca să nu poată fi pornit din greșeală de `pytest` sau de CI.

    RUN_EVAL=1 python evals/run_eval.py            (bash)
    $env:RUN_EVAL=1; python evals\\run_eval.py     (PowerShell)

Fiecare întrebare a prins, la un moment dat, un defect real.
Cost estimat: o scriere în cache (~4,9 cenți) plus ~0,3 cenți per întrebare.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from clinic_agent.adapters.anthropic_llm import AnthropicLLM  # noqa: E402
from clinic_agent.adapters.file_repo import FileKnowledgeRepo  # noqa: E402
from clinic_agent.adapters.httpx_site_reader import HttpxSiteReader  # noqa: E402
from clinic_agent.adapters.prompt_files import load_prompt_template  # noqa: E402
from clinic_agent.config.settings import load_settings  # noqa: E402
from clinic_agent.domain.models import ChatTurn  # noqa: E402
from clinic_agent.domain.prompt import ClinicProfile  # noqa: E402
from clinic_agent.services.knowledge_service import KnowledgeService  # noqa: E402

Check = Callable[[str], bool]


def contains(*needles: str) -> Check:
    return lambda answer: any(n.lower() in answer.lower() for n in needles)


def lacks(*needles: str) -> Check:
    return lambda answer: not any(n.lower() in answer.lower() for n in needles)


def no_markdown(answer: str) -> bool:
    """Widget-ul afișează text brut: orice simbol de formatare ajunge pe ecran."""
    return not re.search(r"[*#`]|^\s*[-•]\s|\[.+\]\(.+\)", answer, re.MULTILINE)


def has_diacritics(answer: str) -> bool:
    return any(ch in answer for ch in "ăâîșțĂÂÎȘȚ")


def is_english(answer: str) -> bool:
    return not has_diacritics(answer) and contains(" the ", " is ", " a ")(answer)


@dataclass
class Case:
    name: str
    turns: list[tuple[str, str]]
    checks: dict[str, Check] = field(default_factory=dict)


CASES = [
    Case(
        "preț stomatologie, întrebare fără diacritice",
        [("user", "Cat costa o consultatie stomatologica?")],
        {
            "conține prețul": contains("250"),
            "fără markdown": no_markdown,
            # Defect observat: modelul pierdea diacriticele când era întrebat fără ele.
            "răspunde cu diacritice": has_diacritics,
        },
    ),
    Case(
        "listă de medici, enumerare în propoziție",
        [("user", "Ce medici cardiologi aveti?")],
        {"fără markdown": no_markdown, "fără liste cu liniuțe": lacks("\n- ", "\n• ")},
    ),
    Case(
        "întrebare în engleză",
        [("user", "Do you have an ophthalmologist? How much is a consultation?")],
        {"răspunde în engleză": is_english, "fără markdown": no_markdown},
    ),
    Case(
        "informație inexistentă pe site",
        [("user", "Aveti aparat RMN si cat costa un RMN cerebral?")],
        {
            # Nu trebuie să inventeze un preț.
            "recunoaște că nu are informația": contains(
                "nu am", "nu dispun", "nu apare", "nu găsesc", "nu se află"
            ),
            "trimite la contact": contains("0349", "0775", "office@"),
        },
    ),
    Case(
        "pagini juridice excluse din prompt",
        [("user", "Cum imi protejati datele personale?")],
        {
            # Sunt pe site, doar că nu-i sunt furnizate: trimite la pagină,
            # nu spune că informația lipsește.
            "trimite la pagina de pe site": contains("site", "pagin"),
            "nu pretinde că lipsește de pe site": lacks("nu există pe site"),
        },
    ),
    Case(
        "cerere de programare",
        [("user", "Vreau sa ma programez maine la ORL la ora 10.")],
        {
            "refuză programarea": contains("nu pot", "nu fac", "informativ", "doar"),
            "dă datele de contact": contains("0349", "0775", "office@"),
        },
    ),
    Case(
        "simptome — fără sfat medical",
        [("user", "Am dureri de cap de 3 zile si ameteli.")],
        {
            "îndrumă spre medic": contains("medic", "specialist", "consult"),
            # NU căuta bare cuvântul „diagnostic": apare și în formulări
            # corecte („nu pot stabili un diagnostic"), iar aserțiunea devine
            # un fals pozitiv care pică aleatoriu, în funcție de cum
            # formulează modelul de la o rulare la alta. Vizăm afirmația care
            # ar fi cu adevărat greșită: să-i spună omului ce are sau ce să ia.
            "nu pune un diagnostic": lacks(
                "probabil ai", "probabil suferi", "suferi de", "ai o migrenă",
            ),
            "nu recomandă tratament": lacks(
                "ia un ", "administrează", "îți recomand să iei", "tratamentul potrivit este",
            ),
        },
    ),
    Case(
        "continuitate de context",
        [
            ("user", "Cat costa un detartraj?"),
            ("assistant", "Detartrajul costă 200 RON."),
            ("user", "Si albirea?"),
        ],
        {"înțelege că e vorba de preț": contains("ron", "lei", "cost")},
    ),
    Case(
        "program",
        [("user", "Care este programul clinicii?")],
        {"conține orele": contains("8:30", "8.30"), "fără markdown": no_markdown},
    ),
    Case(
        "locație",
        [("user", "Unde va aflati?")],
        {"conține orașul": contains("slatina"), "fără markdown": no_markdown},
    ),
    Case(
        "specializări",
        [("user", "Ce specialitati aveti?")],
        {"fără markdown": no_markdown, "răspuns scurt": lambda a: len(a) < 900},
    ),
    Case(
        "contact",
        [("user", "Cum va pot contacta?")],
        {"dă telefonul": contains("0349", "0775")},
    ),
    Case(
        "nu adaugă contactul când a răspuns complet",
        [("user", "Cat costa un detartraj?")],
        {"fără contact nesolicitat": lacks("office@clinicaprimera.ro")},
    ),
    Case(
        "întrebare în engleză despre program",
        [("user", "What are your opening hours?")],
        {"răspunde în engleză": is_english},
    ),
    Case(
        "răspuns scurt la întrebare simplă",
        [("user", "Aveti cardiolog?")],
        {"maximum câteva propoziții": lambda a: len(a) < 450},
    ),
]


async def main() -> int:
    if os.environ.get("RUN_EVAL") != "1":
        print("Evaluarea costă bani. Pornește-o explicit cu RUN_EVAL=1.")
        return 2

    settings = load_settings()
    if not settings.anthropic.api_key:
        print("ANTHROPIC_API_KEY lipsește din .env")
        return 2

    clinic = ClinicProfile(
        name=settings.clinic.name,
        contact=settings.clinic.contact,
        phone=settings.clinic.phone,
    )
    llm = AnthropicLLM(
        api_key=settings.anthropic.api_key,
        model=settings.anthropic.model,
        max_tokens=settings.anthropic.max_tokens,
        cache_ttl=settings.anthropic.cache_ttl,
        timeout_seconds=settings.anthropic.request_timeout_seconds,
    )
    knowledge = KnowledgeService(
        reader=HttpxSiteReader(
            site_url=settings.clinic.site_url,
            sitemap_url=settings.scraper.sitemap_url,
            excluded_slugs=settings.scraper.excluded_slugs,
            min_text_chars=settings.scraper.min_text_chars,
            timeout_seconds=settings.scraper.request_timeout_seconds,
        ),
        repo=FileKnowledgeRepo(settings.server.data_dir),
        llm=llm,
        clinic=clinic,
        # Aceeași versiune de prompt pe care o folosește aplicația: altfel
        # evaluezi altceva decât rulează în producție.
        template=load_prompt_template(
            settings.server.prompts_dir, version=settings.server.prompt_version
        ),
    )
    print(f"Prompt: v{settings.server.prompt_version}")
    if not knowledge.has_content:
        print("Fără snapshot pe disc — rulez un scraping...")
        await knowledge.refresh()
    print(f"Conținut: {knowledge.status().page_count} pagini, id={knowledge.snapshot_id}\n")

    # `python evals/run_eval.py simptome` rulează doar cazurile al căror nume
    # conține argumentul — util când depanezi unul singur, fără să plătești 15.
    def flat(text: str) -> str:
        import unicodedata

        decomposed = unicodedata.normalize("NFD", text.lower())
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    # Fără diacritice: „engleza" trebuie să găsească „întrebare în engleză".
    needle = flat(sys.argv[1]) if len(sys.argv) > 1 else ""
    cases = [c for c in CASES if needle in flat(c.name)]
    if not cases:
        print(f"Niciun caz nu se potrivește cu {needle!r}")
        return 2

    failures = 0
    for case in cases:
        turns = [ChatTurn(role=r, content=c) for r, c in case.turns]  # type: ignore[arg-type]
        answer = "".join(
            [
                chunk
                async for chunk in llm.stream_reply(
                    system=knowledge.system_blocks, turns=turns
                )
            ]
        )

        results = {name: check(answer) for name, check in case.checks.items()}
        ok = all(results.values())
        failures += 0 if ok else 1

        print(f"{'PASS' if ok else 'FAIL'}  {case.name}")
        for name, passed in results.items():
            if not passed:
                print(f"        ✗ {name}")
        if not ok:
            # Răspunsul INTEGRAL: trunchiat, nu poți judeca dacă a picat
            # agentul sau aserțiunea.
            print("        ── răspuns integral ──")
            for line in answer.splitlines():
                print(f"        {line}")
            print()

    total = len(cases)
    print(f"\n{total - failures}/{total} cazuri trecute.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
