"""Dependențele pe care le injectează FastAPI în rute.

Rutele nu construiesc niciodată un serviciu — îl cer. Un singur loc decide
cine primește ce, iar în teste se poate înlocui cu `dependency_overrides`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from clinic_agent.config.settings import Settings
from clinic_agent.services.chat_service import ChatService
from clinic_agent.services.knowledge_service import KnowledgeService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_knowledge_service(request: Request) -> KnowledgeService:
    return request.app.state.knowledge_service


def client_ip(request: Request) -> str:
    """IP-ul real al vizitatorului, pentru limitarea de trafic.

    În spatele unui proxy (Render, Railway) `request.client.host` e IP-ul
    proxy-ului — adică *toți* vizitatorii ar împărți aceeași limită.

    SECURITATE: nu lua PRIMUL element din X-Forwarded-For. Proxy-urile adaugă
    la antet, nu îl rescriu, deci un client care trimite el însuși
    `X-Forwarded-For: 1.1.1.1` produce `1.1.1.1, IP-ul-real`. Cine ia primul
    element citește o valoare controlată de atacator, iar acesta o poate roti
    la fiecare cerere ca să ocolească limita complet.

    Elementul de încredere e al `trusted_proxy_hops`-lea de la COADĂ: adăugat
    de proxy-ul cel mai apropiat de noi, pe care nimeni din afară nu-l poate
    falsifica.
    """
    settings: Settings = request.app.state.settings
    if settings.server.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            hops = max(1, settings.server.trusted_proxy_hops)
            if parts:
                return parts[-hops] if len(parts) >= hops else parts[0]
    return request.client.host if request.client else "necunoscut"


SettingsDep = Annotated[Settings, Depends(get_settings)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
ClientIpDep = Annotated[str, Depends(client_ip)]
