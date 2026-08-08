"""Einstiegspunkt der FastAPI-Anwendung.

Starten (lokal):   uv run uvicorn app.main:app --reload
Interaktive Doku:  http://127.0.0.1:8000/docs
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, ergebnisse, health, nlp, price_alerts, push
from app.config import get_settings
from app.core.logging import richte_logging_ein
from app.core.ratelimit import allgemein, begrenze
from app.db import engine

# Seit M12 nicht mehr `basicConfig`: Der Formatierer aus `core/logging.py`
# schwärzt E-Mail-Adressen, Push-Endpoints und Token, bevor eine Zeile
# geschrieben wird. Siehe dort, warum das eine Sperre und keine Disziplin ist.
richte_logging_ein(get_settings().log_format, get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("Starte %s (%s)", settings.app_name, settings.environment)
    yield
    # Verbindungen sauber schließen, damit uvicorn --reload nicht hängt.
    await engine.dispose()
    logger.info("Beendet.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Ohne diese Freigabe kann der Browser den Kopf bei einer Antwort von
        # fremder Herkunft **nicht lesen** — auch wenn er mitgeschickt wird.
        # Der 429 käme an, aber „bitte in 42 Sekunden erneut" wäre für den
        # Client unsichtbar. Im Browsertest aufgefallen.
        expose_headers=["Retry-After"],
    )

    # Das allgemeine Limit (M12) hängt an den Routern, nicht an jedem
    # Endpunkt: eine Stelle, die man beim nächsten neuen Endpunkt nicht
    # vergessen kann.
    #
    # **`health.router` bekommt bewusst keins.** Die Readiness-Probe fragt der
    # Hoster im Sekundentakt; ein 429 dort hieße für ihn „Instanz kaputt", und
    # er nähme sie aus dem Verkehr. Ausgerechnet die Bremse würde den
    # Ausfall auslösen, den sie verhindern soll.
    bremse = [Depends(begrenze(allgemein, "api"))]

    app.include_router(health.router)
    app.include_router(auth.router, dependencies=bremse)
    app.include_router(price_alerts.router, dependencies=bremse)
    app.include_router(ergebnisse.alarm_router, dependencies=bremse)
    app.include_router(ergebnisse.angebot_router, dependencies=bremse)
    app.include_router(push.router, dependencies=bremse)
    # `nlp.router` hat zusätzlich sein eigenes, viel engeres Limit.
    app.include_router(nlp.router, dependencies=bremse)

    return app


app = create_app()
