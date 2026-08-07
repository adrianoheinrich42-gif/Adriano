"""Endpunkte rund um den angemeldeten Nutzer.

`GET /me` ist bewusst der erste geschützte Endpunkt: klein genug, um die
ganze Auth-Kette (Client → Token → Prüfung → Nutzer-Zeile) zu testen, bevor
darauf aufgebaut wird.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser

router = APIRouter(tags=["auth"])


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
