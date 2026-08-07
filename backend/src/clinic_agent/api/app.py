"""Fabrica aplicației: aici se leagă toate piesele.

Ăsta e singurul loc care știe simultan de setări, adapters și servicii —
„composition root". Restul codului vede doar interfețe.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from clinic_agent import __version__
from clinic_agent.adapters.anthropic_llm import AnthropicLLM
from clinic_agent.adapters.file_repo import FileKnowledgeRepo
from clinic_agent.adapters.httpx_site_reader import HttpxSiteReader
from clinic_agent.adapters.memory_cache import MemoryResponseCache
from clinic_agent.adapters.memory_rate_limiter import MemoryRateLimiter
from clinic_agent.adapters.prompt_files import load_prompt_template
from clinic_agent.api.routes import chat, health, refresh
from clinic_agent.config.settings import Settings, load_settings
from clinic_agent.domain.prompt import ClinicProfile
from clinic_agent.ports.knowledge_repo import KnowledgeRepoPort
from clinic_agent.ports.llm import LLMPort
from clinic_agent.ports.site_reader import SiteReaderPort
from clinic_agent.services.chat_service import ChatService
from clinic_agent.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

# 24 de mesaje × 2000 de caractere ≈ 48 KB; 256 KB lasă marjă confortabilă.
MAX_BODY_BYTES = 256 * 1024


def create_app(
    settings: Settings,
    *,
    llm: LLMPort | None = None,
    site_reader: SiteReaderPort | None = None,
    repo: KnowledgeRepoPort | None = None,
    run_scheduler: bool = True,
) -> FastAPI:
    """Argumentele opționale sunt punctele de injecție pentru teste.

    `create_app(settings, llm=FakeLLM(), run_scheduler=False)` dă o aplicație
    completă care nu atinge nici rețeaua, nici ceasul.
    """
    _validate_production_config(settings)

    clinic = ClinicProfile(
        name=settings.clinic.name,
        contact=settings.clinic.contact,
        phone=settings.clinic.phone,
    )
    template = load_prompt_template(settings.server.prompts_dir)

    llm = llm or AnthropicLLM(
        api_key=settings.anthropic.api_key,
        model=settings.anthropic.model,
        max_tokens=settings.anthropic.max_tokens,
        cache_ttl=settings.anthropic.cache_ttl,
        timeout_seconds=settings.anthropic.request_timeout_seconds,
    )
    site_reader = site_reader or HttpxSiteReader(
        site_url=settings.clinic.site_url,
        sitemap_url=settings.scraper.sitemap_url,
        excluded_slugs=settings.scraper.excluded_slugs,
        min_text_chars=settings.scraper.min_text_chars,
        timeout_seconds=settings.scraper.request_timeout_seconds,
    )
    repo = repo or FileKnowledgeRepo(settings.server.data_dir)

    response_cache = MemoryResponseCache(
        ttl_seconds=settings.cache.ttl_seconds,
        max_entries=settings.cache.max_entries,
    )
    rate_limiter = MemoryRateLimiter(
        per_hour=settings.rate_limit.per_hour,
        per_day=settings.rate_limit.per_day,
    )

    knowledge_service = KnowledgeService(
        reader=site_reader,
        repo=repo,
        llm=llm,
        clinic=clinic,
        template=template,
        failure_alert_threshold=settings.scraper.failure_alert_threshold,
    )
    chat_service = ChatService(
        knowledge=knowledge_service,
        llm=llm,
        cache=response_cache,
        rate_limiter=rate_limiter,
        phone=settings.clinic.phone,
        email=settings.clinic.email,
        max_conversation_messages=settings.rate_limit.max_conversation_messages,
        max_cacheable_question_chars=settings.cache.max_question_chars,
        cache_enabled=settings.cache.enabled,
    )

    app = FastAPI(
        title=f"Asistent {settings.clinic.name}",
        version=__version__,
        # În producție nu publicăm harta API-ului: nu e o breșă, dar nici nu
        # are ce căuta pe internet suprafața internă a unui serviciu public.
        docs_url=None if settings.is_production else "/api/docs",
        openapi_url=None if settings.is_production else "/api/openapi.json",
        lifespan=_lifespan(settings, knowledge_service, run_scheduler=run_scheduler),
    )

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        """Respinge corpurile uriașe înainte să fie citite în memorie.

        Fără asta, un POST de 100 MB e încărcat integral în RAM și abia apoi
        respins de validare. Antetul se verifică înainte de citirea corpului.
        """
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Mesaj prea mare."}, status_code=413)
        return await call_next(request)

    # Widget-ul rulează pe clinicaprimera.ro, backend-ul pe alt domeniu:
    # fără originile astea, browserul blochează fiecare cerere.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.server.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Refresh-Token"],
    )

    app.state.settings = settings
    app.state.knowledge_service = knowledge_service
    app.state.chat_service = chat_service
    app.state.response_cache = response_cache

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(refresh.router, prefix="/api")

    # Backend-ul își servește singur widget-ul: un singur lucru de găzduit,
    # și `data-api-url` din snippet e mereu același domeniu cu scriptul.
    widget_dir = settings.server.widget_dir
    if widget_dir.exists():
        app.mount("/widget", StaticFiles(directory=widget_dir), name="widget")

    return app


def _validate_production_config(settings: Settings) -> None:
    """Oprește pornirea la configurări periculoase, în loc să meargă mai departe.

    O eroare la pornire se vede imediat în log-urile de deploy. Un `*` la CORS
    strecurat în producție nu s-ar vedea niciodată — ar funcționa perfect.
    """
    if not settings.is_production:
        return

    origins = settings.server.allowed_origins
    if not origins:
        raise ValueError(
            "SERVER_ALLOWED_ORIGINS e gol în producție: widget-ul nu ar putea "
            "apela API-ul de pe site-ul clinicii."
        )
    if any(origin.strip() == "*" for origin in origins):
        raise ValueError(
            "SERVER_ALLOWED_ORIGINS conține '*'. În producție originile se "
            "enumeră explicit — altfel orice site poate folosi API-ul "
            "clinicii din browserul vizitatorilor lui."
        )
    if not settings.anthropic.api_key:
        raise ValueError("ANTHROPIC_API_KEY lipsește în producție.")


def _lifespan(settings: Settings, knowledge: KnowledgeService, *, run_scheduler: bool):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.anthropic.api_key:
            logger.warning("ANTHROPIC_API_KEY lipsește — apelurile către model vor eșua")

        scheduler: AsyncIOScheduler | None = None
        if run_scheduler:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(
                knowledge.refresh,
                "interval",
                hours=settings.scraper.interval_hours,
                id="scraping",
            )
            # Sub 60 de minute, cu marjă: o citire din cache resetează TTL-ul,
            # deci 0,25 cenți la 50 de minute înlocuiesc o rescriere de 4,9.
            scheduler.add_job(
                knowledge.warm_cache,
                "interval",
                minutes=settings.anthropic.keepalive_minutes,
                id="keepalive",
            )
            scheduler.start()
            logger.info(
                "scheduler pornit: scraping la %sh, keep-alive la %s min",
                settings.scraper.interval_hours,
                settings.anthropic.keepalive_minutes,
            )

        # Pornirea nu așteaptă scraping-ul: serverul răspunde imediat cu 503
        # pe /api/chat, iar conținutul apare peste câteva secunde.
        if knowledge.has_content:
            asyncio.create_task(knowledge.warm_cache())
        else:
            logger.info("fără snapshot pe disc — pornesc un scraping imediat")
            asyncio.create_task(knowledge.refresh())

        yield

        if scheduler is not None:
            scheduler.shutdown(wait=False)

    return lifespan


def create_app_from_env() -> FastAPI:
    """Punct de intrare pentru uvicorn: `uvicorn ...:create_app_from_env --factory`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return create_app(load_settings())
