"""Health-Endpunkt — der erste und einfachste Endpunkt des Projekts.

Er beantwortet zwei Fragen:
  1. Läuft das Backend überhaupt?
  2. Kommt das Backend an die Datenbank?

Der Endpunkt antwortet **immer mit HTTP 200**, auch wenn die Datenbank weg
ist — der Zustand steht im Body. Das macht den iOS-Client einfach.

  Hinweis für später: Für eine echte Readiness-Probe beim Hoster (Render,
  Railway) willst du bei `degraded` einen HTTP 503 zurückgeben, damit die
  Plattform die Instanz aus dem Load Balancer nimmt. Das ist ab M12 relevant.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import is_database_reachable

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    version: str
    environment: str


# Eigene Dependency für die DB-Prüfung: So kann der Test sie ersetzen,
# ohne dass eine echte Datenbank laufen muss.
async def database_probe() -> bool:
    return await is_database_reachable()


@router.get("/health", response_model=HealthResponse, summary="Systemstatus")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    db_ok: Annotated[bool, Depends(database_probe)],
) -> HealthResponse:
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        version=settings.app_version,
        environment=settings.environment,
    )
