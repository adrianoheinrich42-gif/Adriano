"""Endpunkte für Preisalarme (CRUD).

Die Endpunkte hier sind absichtlich dünn: Sie holen den angemeldeten Nutzer,
rufen den Dienst und übersetzen dessen Rückgabe in HTTP-Status. Die Fachlogik
steht in `app/services/price_alerts.py` — so lässt sie sich ohne HTTP testen.

Zum Statuscode 404: Ein fremder Alarm liefert **404**, nicht 403. Ein 403
hieße „den gibt es, du darfst nur nicht" — schon das ist eine Information,
die niemanden etwas angeht.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db import get_db
from app.schemas.price_alert import PriceAlertCreate, PriceAlertResponse, PriceAlertUpdate
from app.services import price_alerts as service

router = APIRouter(prefix="/alerts", tags=["alerts"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

NICHT_GEFUNDEN = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Alarm nicht gefunden.",
)


@router.post(
    "",
    response_model=PriceAlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alarm anlegen",
)
async def create_alert(
    daten: PriceAlertCreate,
    user: CurrentUser,
    session: DbSession,
) -> PriceAlertResponse:
    try:
        alert = await service.create_alert(session, user.id, daten)
    except service.AlertLimitReached as exc:
        # 409 Conflict statt 400: Die Anfrage ist in Ordnung, sie passt nur
        # nicht zum aktuellen Zustand des Kontos.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Du hast bereits {exc.limit} aktive Alarme. "
                "Pausiere oder lösche einen, um einen neuen anzulegen."
            ),
        ) from exc

    return PriceAlertResponse.model_validate(alert)


@router.get("", response_model=list[PriceAlertResponse], summary="Eigene Alarme auflisten")
async def list_alerts(user: CurrentUser, session: DbSession) -> list[PriceAlertResponse]:
    alerts = await service.list_alerts(session, user.id)
    return [PriceAlertResponse.model_validate(a) for a in alerts]


@router.get("/{alert_id}", response_model=PriceAlertResponse, summary="Einen Alarm ansehen")
async def read_alert(
    alert_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> PriceAlertResponse:
    alert = await service.get_alert(session, user.id, alert_id)
    if alert is None:
        raise NICHT_GEFUNDEN
    return PriceAlertResponse.model_validate(alert)


@router.patch("/{alert_id}", response_model=PriceAlertResponse, summary="Alarm ändern")
async def update_alert(
    alert_id: uuid.UUID,
    aenderungen: PriceAlertUpdate,
    user: CurrentUser,
    session: DbSession,
) -> PriceAlertResponse:
    try:
        alert = await service.update_alert(session, user.id, alert_id, aenderungen)
    except service.AlertRulesViolated as exc:
        # 422 wie bei der Pydantic-Validierung: Der Inhalt der Anfrage passt
        # nicht — nur fiel es erst nach dem Zusammenführen mit dem
        # gespeicherten Stand auf.
        # Zahl statt `status.HTTP_422_...`: Starlette hat die Konstante
        # umbenannt, die Zahl gilt in jeder Version.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.AlertLimitReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Du hast bereits {exc.limit} aktive Alarme. "
                "Pausiere oder lösche einen, um diesen wieder zu aktivieren."
            ),
        ) from exc

    if alert is None:
        raise NICHT_GEFUNDEN
    return PriceAlertResponse.model_validate(alert)


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Alarm löschen",
)
async def delete_alert(
    alert_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    if not await service.delete_alert(session, user.id, alert_id):
        raise NICHT_GEFUNDEN
