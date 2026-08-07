"""Endpunkte der Ergebnisanzeige (M9).

Drei Stück:

* `GET /alerts/{id}/offers`  — die Funde eines Alarms
* `GET /alerts/{id}/verlauf` — Preisverlauf + Einordnung aus M7
* `GET /offers/{id}`         — ein einzelnes Angebot (Ziel des Deep-Links)

Die ersten beiden hängen unter `/alerts`, gehören aber inhaltlich hierher und
nicht ins CRUD — deshalb ein eigener Router mit demselben Präfix. FastAPI
sortiert das beim Einhängen zusammen.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db import get_db
from app.schemas.ergebnis import FlightOfferResponse, PreisverlaufResponse
from app.services import ergebnisse as service

alarm_router = APIRouter(prefix="/alerts", tags=["ergebnisse"])
angebot_router = APIRouter(prefix="/offers", tags=["ergebnisse"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

NICHT_GEFUNDEN = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Nicht gefunden.",
)


@alarm_router.get(
    "/{alert_id}/offers",
    response_model=list[FlightOfferResponse],
    summary="Funde eines Alarms",
)
async def list_offers(
    alert_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = service.STANDARD_LIMIT,
) -> list[FlightOfferResponse]:
    angebote = await service.liste_angebote(session, user.id, alert_id, limit)
    if angebote is None:
        raise NICHT_GEFUNDEN
    return [FlightOfferResponse.aus(a) for a in angebote]


@alarm_router.get(
    "/{alert_id}/verlauf",
    response_model=PreisverlaufResponse,
    summary="Preisverlauf und Einordnung",
)
async def read_verlauf(
    alert_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> PreisverlaufResponse:
    verlauf = await service.hole_verlauf(session, user.id, alert_id)
    if verlauf is None:
        raise NICHT_GEFUNDEN
    return verlauf


@angebot_router.get(
    "/{offer_id}",
    response_model=FlightOfferResponse,
    summary="Ein einzelnes Angebot",
)
async def read_offer(
    offer_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> FlightOfferResponse:
    angebot = await service.hole_angebot(session, user.id, offer_id)
    if angebot is None:
        raise NICHT_GEFUNDEN
    return FlightOfferResponse.aus(angebot)
