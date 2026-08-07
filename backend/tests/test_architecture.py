"""Regula de aur, verificată automat.

Fără testul ăsta, „domain-ul nu importă anthropic" e o intenție care se erodează
în prima zi cu deadline. Așa, se rupe build-ul.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import clinic_agent

SRC = Path(clinic_agent.__file__).parent

INTERZISE = {"anthropic", "httpx", "bs4", "fastapi", "apscheduler"}
# `services/` are voie să vadă FastAPI? Nu — orchestrarea nu știe de HTTP.
PACHETE_PURE = ["domain", "ports", "services"]


def _module_importate(fisier: Path) -> set[str]:
    arbore = ast.parse(fisier.read_text(encoding="utf-8"))
    module: set[str] = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            module.update(alias.name.split(".")[0] for alias in nod.names)
        elif isinstance(nod, ast.ImportFrom) and nod.module and nod.level == 0:
            module.add(nod.module.split(".")[0])
    return module


@pytest.mark.parametrize("pachet", PACHETE_PURE)
def test_pachetele_pure_nu_importa_biblioteci_de_io(pachet: str) -> None:
    for fisier in (SRC / pachet).rglob("*.py"):
        incalcari = _module_importate(fisier) & INTERZISE
        assert not incalcari, f"{fisier.name} importă {sorted(incalcari)}"


def test_domain_nu_depinde_de_restul_aplicatiei() -> None:
    # Săgețile de dependență merg spre interior: domain-ul e frunza.
    for fisier in (SRC / "domain").rglob("*.py"):
        arbore = ast.parse(fisier.read_text(encoding="utf-8"))
        for nod in ast.walk(arbore):
            if isinstance(nod, ast.ImportFrom) and (nod.module or "").startswith(
                "clinic_agent."
            ):
                assert nod.module.startswith("clinic_agent.domain"), (
                    f"{fisier.name} importă {nod.module}"
                )
