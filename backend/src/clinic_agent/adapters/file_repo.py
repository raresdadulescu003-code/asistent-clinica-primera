"""Persistarea snapshot-ului pe disc, ca JSON."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from clinic_agent.domain.models import Page, Snapshot

logger = logging.getLogger(__name__)


class FileKnowledgeRepo:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "snapshot.json"

    def load(self) -> Snapshot | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            pages = [
                Page(url=item["url"], title=item["title"], text=item["text"])
                for item in raw["pages"]
            ]
            # Reconstruim prin `from_pages`: id-ul se recalculează din conținut,
            # deci un fișier editat manual nu poate minți despre amprentă.
            return Snapshot.from_pages(pages, datetime.fromisoformat(raw["created_at"]))
        except (KeyError, ValueError, OSError) as exc:
            logger.error("snapshot ilizibil pe disc (%s): %s", self._path, exc)
            return None

    def save(self, snapshot: Snapshot) -> None:
        payload = {
            "id": snapshot.id,
            "created_at": snapshot.created_at.isoformat(),
            "pages": [
                {"url": p.url, "title": p.title, "text": p.text} for p in snapshot.pages
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Scriem în alt fișier și înlocuim atomic: o cădere la mijlocul scrierii
        # nu are voie să lase un snapshot trunchiat pe disc.
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, self._path)
