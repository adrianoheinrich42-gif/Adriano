"""Health-Endpunkt — der erste und einfachste Endpunkt des Projekts.

Er beantwortet zwei Fragen:
  1. Läuft das Backend überhaupt?
  2. Kommt das Backend an die Datenbank?

Seit M12 gibt es dafür **zwei** Endpunkte, und der Unterschied ist der Punkt:

* **`GET /health`** antwortet **immer mit HTTP 200**, der Zustand steht im
  Body. Das ist die Auskunft für die App — sie soll „Backend läuft, Datenbank
  hakt" anzeigen können, statt in ihre allgemeine Fehlerbehandlung zu fallen.
* **`GET /health/ready`** antwortet bei Problemen mit **HTTP 503**. Das ist
  die Auskunft für den Hoster: Render und Railway kennen nur „200 = nimm
  Verkehr, alles andere = nimm die Instanz raus". Ein immer-200-Endpunkt wäre
  als Readiness-Probe nutzlos — die Plattform würde Anfragen auf eine
  Instanz leiten, die gar nicht arbeiten kann.

Zwei Endpunkte statt eines Schalters, weil die beiden Aufrufer wirklich
verschiedene Dinge wollen: Der eine will *wissen*, wie es steht, der andere
will *entscheiden*.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
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


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness-Probe für den Hoster (503, wenn nicht arbeitsfähig)",
    responses={503: {"description": "Nicht arbeitsfähig — Datenbank nicht erreichbar"}},
)
async def ready(
    antwort: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db_ok: Annotated[bool, Depends(database_probe)],
) -> HealthResponse:
    """Derselbe Inhalt wie `/health`, aber mit aussagekräftigem Statuscode.

    Der Statuscode wird über das `Response`-Objekt gesetzt statt über eine
    `HTTPException`: So bleibt der Body in **beiden** Fällen derselbe. Wer die
    Probe von Hand aufruft, sieht auch beim 503 sofort, *was* fehlt — bei
    einer Ausnahme stünde dort nur „Service Unavailable".
    """
    if not db_ok:
        antwort.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        version=settings.app_version,
        environment=settings.environment,
    )
