"""Scraping, snapshot-uri și starea bazei de cunoștințe.

Serviciul nu știe *cum* se citește site-ul sau unde se salvează: primește prin
constructor un `SiteReaderPort` și un `KnowledgeRepoPort`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from clinic_agent.domain.models import Snapshot
from clinic_agent.domain.pricing import estimate_tokens
from clinic_agent.domain.prompt import (
    ClinicProfile,
    PromptBlock,
    PromptTemplate,
    build_system_blocks,
    instruction_markers,
    render_instructions,
    render_site_content,
)
from clinic_agent.ports.knowledge_repo import KnowledgeRepoPort
from clinic_agent.ports.llm import LLMError, LLMPort
from clinic_agent.ports.site_reader import SiteReaderPort

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class KnowledgeStatus:
    """Ce expune `/api/health` despre conținut. Vezi secțiunea de monitorizare."""

    has_content: bool
    snapshot_id: str | None
    page_count: int
    estimated_tokens: int
    last_success_at: str | None
    age_hours: float | None
    consecutive_failures: int


class KnowledgeService:
    def __init__(
        self,
        *,
        reader: SiteReaderPort,
        repo: KnowledgeRepoPort,
        llm: LLMPort,
        clinic: ClinicProfile,
        template: PromptTemplate,
        failure_alert_threshold: int = 3,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._reader = reader
        self._repo = repo
        self._llm = llm
        self._clinic = clinic
        self._template = template
        self._threshold = failure_alert_threshold
        self._clock = clock

        self._instructions = render_instructions(template, clinic)
        self._markers = instruction_markers(self._instructions)
        self._snapshot: Snapshot | None = repo.load()
        self._blocks: tuple[PromptBlock, ...] = ()
        self._consecutive_failures = 0
        self._last_success_at: datetime | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_ok = False
        self._rebuild_blocks()

        if self._snapshot is not None:
            self._last_success_at = self._snapshot.created_at
            logger.info(
                "snapshot încărcat de pe disc: %s pagini, id=%s",
                len(self._snapshot.pages),
                self._snapshot.id,
            )

    # --- stare -----------------------------------------------------------

    @property
    def snapshot_id(self) -> str | None:
        return self._snapshot.id if self._snapshot else None

    @property
    def prompt_version(self) -> str:
        return self._template.version

    @property
    def has_content(self) -> bool:
        return self._snapshot is not None and not self._snapshot.is_empty

    @property
    def instruction_markers(self) -> tuple[str, ...]:
        """Titlurile de secțiune din prompt, pentru garda anti-scurgere."""
        return self._markers

    @property
    def system_blocks(self) -> tuple[PromptBlock, ...]:
        """Blocurile se construiesc o singură dată, la schimbarea snapshot-ului.

        Randarea a 25.000 de tokeni la fiecare întrebare ar fi risipă, dar mai
        important: orice diferență de octet ar rupe prompt caching-ul.
        """
        return self._blocks

    def status(self) -> KnowledgeStatus:
        age = None
        if self._last_success_at is not None:
            age = round(
                (self._clock() - self._last_success_at).total_seconds() / 3600, 2
            )
        return KnowledgeStatus(
            has_content=self.has_content,
            snapshot_id=self.snapshot_id,
            page_count=len(self._snapshot.pages) if self._snapshot else 0,
            estimated_tokens=(
                estimate_tokens(self._blocks[1].text) if len(self._blocks) > 1 else 0
            ),
            last_success_at=(
                self._last_success_at.isoformat() if self._last_success_at else None
            ),
            age_hours=age,
            consecutive_failures=self._consecutive_failures,
        )

    # --- actualizare -----------------------------------------------------

    async def refresh(self) -> bool:
        """Re-citește site-ul. Întoarce True dacă s-a terminat cu succes.

        Două actualizări nu rulează niciodată în paralel. Job-ul programat și
        un `POST /api/refresh` manual se pot suprapune; fără asta ar face două
        scraping-uri simultane, două salvări pe disc și două scrieri în cache
        (a doua, inutilă, la ~5 cenți).
        """
        if self._refresh_lock.locked():
            logger.info("actualizare deja în curs — aștept rezultatul ei")
            async with self._refresh_lock:
                return self._last_refresh_ok

        async with self._refresh_lock:
            self._last_refresh_ok = await self._refresh_once()
            return self._last_refresh_ok

    async def _refresh_once(self) -> bool:
        try:
            pages = await self._reader.fetch_pages()
        except Exception as exc:  # noqa: BLE001 - orice cădere de rețea
            logger.warning("scraping eșuat: %s", exc)
            pages = []

        if not pages:
            # Mai bine date de ieri decât niciun agent. Dar contorizăm, ca
            # eșecul tăcut să devină vizibil în /api/health.
            self._consecutive_failures += 1
            self._alert_if_needed()
            return False

        snapshot = Snapshot.from_pages(pages, self._clock())
        self._consecutive_failures = 0
        self._last_success_at = snapshot.created_at

        if self._snapshot is not None and snapshot.id == self._snapshot.id:
            logger.info("site-ul nu s-a schimbat (id=%s)", snapshot.id)
            return True

        self._snapshot = snapshot
        self._repo.save(snapshot)
        self._rebuild_blocks()
        logger.info(
            "snapshot nou: %s pagini, id=%s, ~%s tokeni",
            len(snapshot.pages),
            snapshot.id,
            estimate_tokens(self._blocks[1].text),
        )
        # Conținut nou = alt prefix = cache expirat. Îl scriem acum, controlat,
        # nu pe spatele primului vizitator care nimerește după actualizare.
        await self.warm_cache()
        return True

    async def warm_cache(self) -> None:
        """Job-ul de keep-alive. Nu are voie să dărâme scheduler-ul."""
        if not self.has_content:
            return
        try:
            await self._llm.warm_cache(system=self._blocks)
        except LLMError as exc:
            logger.warning("keep-alive cache eșuat: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("keep-alive cache eșuat neașteptat: %s", exc)

    def _rebuild_blocks(self) -> None:
        if self._snapshot is None:
            self._blocks = ()
            return
        self._blocks = build_system_blocks(
            self._instructions, render_site_content(self._snapshot)
        )

    def _alert_if_needed(self) -> None:
        if self._consecutive_failures >= self._threshold:
            # Semnalul vizibil cerut de secțiunea de monitorizare: fără el,
            # botul ar servi prețuri vechi la nesfârșit fără ca cineva să afle.
            logger.error(
                "SCRAPING EȘUAT DE %s ORI CONSECUTIV. Botul servește conținut "
                "vechi din %s. Verifică dacă structura site-ului s-a schimbat.",
                self._consecutive_failures,
                self._last_success_at,
            )
        else:
            logger.warning(
                "scraping eșuat (%s/%s consecutive)",
                self._consecutive_failures,
                self._threshold,
            )
