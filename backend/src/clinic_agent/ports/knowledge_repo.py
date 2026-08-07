"""Persistarea snapshot-ului între reporniri."""

from __future__ import annotations

from typing import Protocol

from clinic_agent.domain.models import Snapshot


class KnowledgeRepoPort(Protocol):
    def load(self) -> Snapshot | None:
        """Ultimul snapshot salvat, sau None dacă nu există."""
        ...

    def save(self, snapshot: Snapshot) -> None: ...
