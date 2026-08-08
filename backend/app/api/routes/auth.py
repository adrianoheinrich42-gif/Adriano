"""Endpunkte rund um den angemeldeten Nutzer.

`GET /me` ist bewusst der erste geschützte Endpunkt: klein genug, um die
ganze Auth-Kette (Client → Token → Prüfung → Nutzer-Zeile) zu testen, bevor
darauf aufgebaut wird.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db import get_db
from app.services.users import loesche_nutzer

router = APIRouter(tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class MeResponse(BaseModel):
    """Was der Client über sich selbst erfährt.

    Bewusst eine eigene Klasse statt des Datenbankmodells: So entscheiden
    wir, welche Spalten nach draußen gehen. Neue interne Spalten landen dann
    nicht versehentlich in der API.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Bewusst `str` und kein `EmailStr`: Die Adresse hat Supabase beim
    # Registrieren schon geprüft, und `EmailStr` zöge das Zusatzpaket
    # `email-validator` nach, ohne hier etwas zu gewinnen.
    email: str
    max_active_alerts: int
    is_active: bool
    created_at: datetime


@router.get("/me", response_model=MeResponse, summary="Angemeldeter Nutzer")
async def read_me(user: CurrentUser) -> MeResponse:
    return MeResponse.model_validate(user)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Konto und alle Daten löschen",
)
async def delete_me(user: CurrentUser, session: DbSession) -> Response:
    """Das Löschrecht aus der DSGVO — ein Endpunkt, keine E-Mail an den Betreiber.

    Weg sind danach: Alarme, Beobachtungen, gefundene Angebote, Push-Ziele
    und Versandprotokolle. Das erledigt `ON DELETE CASCADE` in der Datenbank,
    nicht eine Aufzählung im Code, die beim nächsten neuen Tabellchen
    veraltet.

    **Ohne Rückfrage und ohne Papierkorb.** Eine „Sind Sie sicher?"-Schleife
    gehört in die Oberfläche, nicht in die API; und ein Papierkorb wäre das
    Gegenteil von dem, was hier verlangt wird.

    Antwortet auch dann mit 204, wenn es die Zeile gar nicht mehr gab — für
    den Aufrufer ist das Ergebnis dasselbe: Es ist nichts mehr da.
    """
    await loesche_nutzer(session, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
