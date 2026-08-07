"""GET /api/health — starea aplicației, inclusiv semnalele de monitorizare."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from clinic_agent import __version__
from clinic_agent.api.deps import KnowledgeServiceDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    request: Request, settings: SettingsDep, knowledge: KnowledgeServiceDep
) -> dict:
    status = knowledge.status()
    cache_stats = request.app.state.response_cache.stats()

    return {
        # „ok" cere conținut *și* un scraper care nu s-a rupt: un bot care
        # servește prețuri vechi de o săptămână nu e sănătos, e periculos.
        "status": "ok" if status.has_content and status.consecutive_failures == 0 else "degraded",
        "version": __version__,
        "environment": settings.environment,
        "clinic": settings.clinic.name,
        "knowledge": asdict(status),
        "cache": {
            "hits": cache_stats.hits,
            "misses": cache_stats.misses,
            "hit_rate": cache_stats.hit_rate,
            "entries": cache_stats.entries,
        },
    }
