"""Die Push-Endpunkte über HTTP (M8), mit **echter Datenbank**.

Geprüft wird der Weg, den der Browser wirklich geht: Schlüssel abholen, Gerät
anmelden, wieder abmelden — und dass fremde Geräte unsichtbar bleiben.

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.device_token import DeviceToken
from app.services.users import get_or_create_user
from tests.attrappen import baue_subscription
from tests.test_auth import make_settings, make_token


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        vapid_public_key="oeffentlicher-testschluessel",
        vapid_private_key="privater-testschluessel",
    )
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def nutzer(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


def auth(user_id: uuid.UUID) -> dict[str, str]:
    # Die E-Mail wird aus der ID abgeleitet: `users.email` ist UNIQUE, und beim
    # ersten Request legt das Backend die Nutzerzeile per Upsert an. Eine feste
    # Adresse für zwei verschiedene Nutzer-IDs würde deshalb kollidieren.
    token = make_token(user_id=str(user_id), email=f"{user_id}@beispiel.de")
    return {"Authorization": f"Bearer {token}"}


# --- Schlüssel abholen ------------------------------------------------------


async def test_config_liefert_den_oeffentlichen_schluessel(client: AsyncClient, nutzer: uuid.UUID):
    antwort = await client.get("/push/config", headers=auth(nutzer))

    assert antwort.status_code == 200
    assert antwort.json() == {
        "public_key": "oeffentlicher-testschluessel",
        "aktiviert": True,
    }


async def test_config_ohne_anmeldung_ist_401(client: AsyncClient):
    assert (await client.get("/push/config")).status_code == 401


async def test_ohne_schluesselpaar_meldet_config_nicht_aktiviert(
    client: AsyncClient, nutzer: uuid.UUID
):
    """Der Client zeigt dann keinen Knopf — statt eine Erlaubnis zu erfragen,
    mit der nichts passieren würde."""
    app.dependency_overrides[get_settings] = lambda: make_settings()

    antwort = await client.get("/push/config", headers=auth(nutzer))

    assert antwort.json() == {"public_key": "", "aktiviert": False}


# --- Gerät anmelden ---------------------------------------------------------


async def test_geraet_anmelden(client: AsyncClient, nutzer: uuid.UUID, db_session: AsyncSession):
    antwort = await client.post(
        "/push/subscriptions",
        json=baue_subscription(endpoint="https://push.test/neu"),
        headers=auth(nutzer),
    )

    assert antwort.status_code == 201
    assert antwort.json() == {"aktiv": True}

    ziele = await db_session.execute(select(DeviceToken).where(DeviceToken.user_id == nutzer))
    assert ziele.scalar_one().endpoint == "https://push.test/neu"


async def test_zweimal_anmelden_ist_kein_konflikt(client: AsyncClient, nutzer: uuid.UUID):
    """Der Browser bietet dieselbe Subscription bei jedem Aufruf erneut an —
    das ist der Normalfall, kein 409."""
    daten = baue_subscription(endpoint="https://push.test/wieder")

    erste = await client.post("/push/subscriptions", json=daten, headers=auth(nutzer))
    zweite = await client.post("/push/subscriptions", json=daten, headers=auth(nutzer))

    assert erste.status_code == 201
    assert zweite.status_code == 201


async def test_zusaetzliche_felder_des_browsers_stoeren_nicht(
    client: AsyncClient, nutzer: uuid.UUID
):
    """`expirationTime` schickt der Browser mit; das abzulehnen wäre pedantisch."""
    daten = baue_subscription()
    daten["expirationTime"] = None
    daten["unbekanntesFeld"] = "irgendwas"

    antwort = await client.post("/push/subscriptions", json=daten, headers=auth(nutzer))

    assert antwort.status_code == 201


async def test_fehlende_schluessel_sind_422(client: AsyncClient, nutzer: uuid.UUID):
    antwort = await client.post(
        "/push/subscriptions",
        json={"endpoint": "https://push.test/kaputt"},
        headers=auth(nutzer),
    )

    assert antwort.status_code == 422


async def test_anmelden_ohne_token_ist_401(client: AsyncClient):
    antwort = await client.post("/push/subscriptions", json=baue_subscription())

    assert antwort.status_code == 401


# --- Gerät abmelden ---------------------------------------------------------


async def test_geraet_abmelden(client: AsyncClient, nutzer: uuid.UUID, db_session: AsyncSession):
    await client.post(
        "/push/subscriptions",
        json=baue_subscription(endpoint="https://push.test/tschuess"),
        headers=auth(nutzer),
    )

    antwort = await client.request(
        "DELETE",
        "/push/subscriptions",
        json={"endpoint": "https://push.test/tschuess"},
        headers=auth(nutzer),
    )

    assert antwort.status_code == 200
    zustand = await db_session.execute(
        select(DeviceToken.is_active).where(DeviceToken.user_id == nutzer)
    )
    assert zustand.scalar_one() is False


async def test_abmelden_eines_unbekannten_geraets_ist_kein_fehler(
    client: AsyncClient, nutzer: uuid.UUID
):
    """Abmelden ist idempotent — ein 404 böte keine Handlungsmöglichkeit."""
    antwort = await client.request(
        "DELETE",
        "/push/subscriptions",
        json={"endpoint": "https://push.test/gabesnie"},
        headers=auth(nutzer),
    )

    assert antwort.status_code == 200


async def test_fremdes_geraet_laesst_sich_nicht_abmelden(
    client: AsyncClient, nutzer: uuid.UUID, db_session: AsyncSession
):
    """Dieselbe Regel wie bei den Alarmen: Fremdes ist unsichtbar."""
    await client.post(
        "/push/subscriptions",
        json=baue_subscription(endpoint="https://push.test/meins"),
        headers=auth(nutzer),
    )
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")

    await client.request(
        "DELETE",
        "/push/subscriptions",
        json={"endpoint": "https://push.test/meins"},
        headers=auth(fremder.id),
    )

    zustand = await db_session.execute(
        select(DeviceToken.is_active).where(DeviceToken.user_id == nutzer)
    )
    assert zustand.scalar_one() is True
