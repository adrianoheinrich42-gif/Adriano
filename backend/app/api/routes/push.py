"""Endpunkte für Push-Benachrichtigungen.

Drei Stück, mehr braucht der Browser nicht:

* `GET /push/config` — „welchen öffentlichen Schlüssel soll ich benutzen?"
* `POST /push/subscriptions` — „hier ist mein Gerät, schick mir Nachrichten"
* `DELETE /push/subscriptions` — „nicht mehr, danke"

Wie bei den Alarmen sind die Endpunkte dünn; die Fachlogik steht in
`app/services/push.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.push import (
    PushConfigResponse,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushSubscriptionResponse,
)
from app.services import push as service

router = APIRouter(prefix="/push", tags=["push"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/config", response_model=PushConfigResponse, summary="VAPID-Schlüssel abholen")
async def read_config(
    _: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]
) -> PushConfigResponse:
    """Der öffentliche Schlüssel — der einzige, der den Browser etwas angeht.

    Angemeldet, obwohl der Schlüssel öffentlich ist: Es gibt keinen Grund, ihn
    Fremden zu zeigen, und die App fragt ihn ohnehin erst nach dem Login ab.

    `aktiviert = false` heißt: Im Backend liegt kein Schlüsselpaar. Der Client
    zeigt dann keinen Knopf an, statt den Nutzer um eine Erlaubnis zu bitten,
    mit der nichts passieren würde.
    """
    return PushConfigResponse(
        public_key=settings.vapid_public_key,
        aktiviert=settings.push_aktiviert,
    )


@router.post(
    "/subscriptions",
    response_model=PushSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gerät für Benachrichtigungen anmelden",
)
async def create_subscription(
    daten: PushSubscriptionCreate, user: CurrentUser, session: DbSession
) -> PushSubscriptionResponse:
    """Immer 201, auch wenn das Gerät schon bekannt war.

    Der Browser bietet dieselbe Subscription bei jedem Seitenaufruf erneut an.
    Das ist kein Konflikt, sondern der Normalfall — deshalb ein Upsert und
    kein 409.
    """
    await service.registriere_ziel(
        session,
        user_id=user.id,
        endpoint=daten.endpoint,
        p256dh=daten.keys.p256dh,
        auth=daten.keys.auth,
    )
    return PushSubscriptionResponse(aktiv=True)


@router.delete(
    "/subscriptions",
    response_model=PushSubscriptionResponse,
    summary="Gerät abmelden",
)
async def delete_subscription(
    daten: PushSubscriptionDelete, user: CurrentUser, session: DbSession
) -> PushSubscriptionResponse:
    """Auch ein unbekannter Endpoint ergibt 200.

    Abmelden ist idempotent: Wer nicht angemeldet ist, ist danach genauso
    abgemeldet wie vorher. Ein 404 wäre hier nur eine Fehlermeldung ohne
    Handlungsmöglichkeit.
    """
    await service.entferne_ziel(session, user_id=user.id, endpoint=daten.endpoint)
    return PushSubscriptionResponse(aktiv=False)
