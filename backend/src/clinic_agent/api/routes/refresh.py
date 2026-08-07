"""POST /api/refresh — actualizare manuală după ce se schimbă prețuri pe site."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, status

from clinic_agent.api.deps import KnowledgeServiceDep, SettingsDep

router = APIRouter(tags=["admin"])


@router.post("/refresh")
async def refresh(
    settings: SettingsDep,
    knowledge: KnowledgeServiceDep,
    x_refresh_token: str = Header(default=""),
) -> dict:
    expected = settings.server.refresh_token
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "SERVER_REFRESH_TOKEN nu e configurat"
        )
    # `compare_digest` compară în timp constant. Un `!=` obișnuit se oprește la
    # primul octet diferit, iar diferența de timp lasă tokenul să fie ghicit
    # caracter cu caracter.
    if not secrets.compare_digest(x_refresh_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token invalid")

    succeeded = await knowledge.refresh()
    return {"refreshed": succeeded, "knowledge": knowledge.status().snapshot_id}
