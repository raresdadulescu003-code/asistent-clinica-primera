"""Citirea promptului de pe disc.

Promptul stă într-un fișier versionat (`prompts/ro/system.v1.md`), iar
versiunea intră în cheia de cache. Fișier, nu constantă în cod: îl poate
modifica cineva care nu știe Python, iar `git diff` arată exact ce s-a schimbat.
"""

from __future__ import annotations

from pathlib import Path

from clinic_agent.domain.prompt import PromptTemplate


def load_prompt_template(prompts_dir: Path, language: str = "ro", version: int = 1) -> PromptTemplate:
    path = prompts_dir / language / f"system.v{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Promptul lipsește: {path}")
    return PromptTemplate(
        version=f"{language}/system.v{version}",
        text=path.read_text(encoding="utf-8"),
    )
