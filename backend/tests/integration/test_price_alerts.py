"""Alarm-CRUD mit **echter Datenbank** (M3).

Der Schwerpunkt liegt auf dem, was ohne Datenbank nicht prüfbar ist:
Gehört ein Alarm wirklich nur seinem Besitzer? Greift das Kontingent? Und
setzt die Datenbank die Standardwerte, die wir erwarten?

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.price_alert import PriceAlert
from app.services.users import get_or_create_user
from tests.test_auth import make_settings, make_token

HEUTE = date.today()
IN_30_TAGEN = HEUTE + timedelta(days=30)
IN_45_TAGEN = HEUTE + timedelta(days=45)


def alarm_json(**overrides: object) -> dict[str, object]:
    daten: dict[str, object] = {
        "origin": "MUC",
        "destination": "BCN",
        "earliest_departure_date": IN_30_TAGEN.isoformat(),
        "latest_return_date": IN_45_TAGEN.isoformat(),
        "max_price_cents": 25000,
    }
    daten.update(overrides)
    return daten


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """API-Client auf der Test-Session (wird am Testende zurückgerollt)."""
    app.dependency_overrides[get_settings] = lambda: make_settings()
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def auth(user_id: uuid.UUID, email: str = "a@beispiel.de") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id=str(user_id), email=email)}"}


@pytest.fixture
def nutzer_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def nutzer_b() -> uuid.UUID:
    return uuid.uuid4()


# --- Anlegen und Lesen -----------------------------------------------------


async def test_alarm_anlegen_und_wiederfinden(client: AsyncClient, nutzer_a):
    antwort = await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))

    assert antwort.status_code == 201
    alarm = antwort.json()
    assert alarm["origin"] == "MUC"
    assert alarm["max_price_cents"] == 25000
    # Standardwerte kommen aus der Datenbank, nicht aus Python.
    assert alarm["is_active"] is True
    assert alarm["check_interval_minutes"] == 360
    assert alarm["last_checked_at"] is None
    # `user_id` gehört nicht in die Antwort.
    assert "user_id" not in alarm

    liste = await client.get("/alerts", headers=auth(nutzer_a))
    assert [a["id"] for a in liste.json()] == [alarm["id"]]

    einzeln = await client.get(f"/alerts/{alarm['id']}", headers=auth(nutzer_a))
    assert einzeln.status_code == 200


async def test_alarm_anlegen_ohne_token_gibt_401(client: AsyncClient):
    antwort = await client.post("/alerts", json=alarm_json())

    assert antwort.status_code == 401


async def test_ungueltige_eingabe_gibt_422(client: AsyncClient, nutzer_a):
    antwort = await client.post(
        "/alerts", json=alarm_json(destination="MUC"), headers=auth(nutzer_a)
    )

    assert antwort.status_code == 422


# --- Fremdzugriff ----------------------------------------------------------


async def test_fremde_alarme_sind_unsichtbar(client: AsyncClient, nutzer_a, nutzer_b):
    erstellt = await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))
    fremde_id = erstellt.json()["id"]

    # B sieht A's Alarm weder in der Liste …
    liste = await client.get("/alerts", headers=auth(nutzer_b, "b@beispiel.de"))
    assert liste.json() == []

    # … noch einzeln. 404, nicht 403 — sonst wäre die Existenz verraten.
    for methode, kwargs in (
        ("get", {}),
        ("patch", {"json": {"max_price_cents": 1}}),
        ("delete", {}),
    ):
        antwort = await getattr(client, methode)(
            f"/alerts/{fremde_id}", headers=auth(nutzer_b, "b@beispiel.de"), **kwargs
        )
        assert antwort.status_code == 404, methode


async def test_unbekannte_id_gibt_404(client: AsyncClient, nutzer_a):
    antwort = await client.get(f"/alerts/{uuid.uuid4()}", headers=auth(nutzer_a))

    assert antwort.status_code == 404


# --- Ändern ----------------------------------------------------------------


async def test_patch_aendert_nur_das_geschickte_feld(client: AsyncClient, nutzer_a):
    alarm = (await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))).json()

    antwort = await client.patch(
        f"/alerts/{alarm['id']}", json={"max_price_cents": 19900}, headers=auth(nutzer_a)
    )

    assert antwort.status_code == 200
    geaendert = antwort.json()
    assert geaendert["max_price_cents"] == 19900
    assert geaendert["destination"] == "BCN"  # unverändert
    assert geaendert["max_stops"] == 1


async def test_patch_prueft_den_zusammengefuehrten_stand(client: AsyncClient, nutzer_a):
    """Der Kern der PATCH-Validierung.

    `latest_return_date` allein ist ein gültiges Datum. Erst zusammen mit dem
    **gespeicherten** Hinflugdatum ergibt es keinen Sinn — genau das muss
    auffallen.
    """
    alarm = (await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))).json()

    antwort = await client.patch(
        f"/alerts/{alarm['id']}",
        json={"latest_return_date": (IN_30_TAGEN - timedelta(days=5)).isoformat()},
        headers=auth(nutzer_a),
    )

    assert antwort.status_code == 422
    assert "Rückreisedatum" in antwort.json()["detail"]

    # Und der gespeicherte Alarm ist unverändert geblieben.
    unveraendert = await client.get(f"/alerts/{alarm['id']}", headers=auth(nutzer_a))
    assert unveraendert.json()["latest_return_date"] == IN_45_TAGEN.isoformat()


async def test_leeres_patch_gibt_den_alarm_unveraendert_zurueck(client: AsyncClient, nutzer_a):
    alarm = (await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))).json()

    antwort = await client.patch(f"/alerts/{alarm['id']}", json={}, headers=auth(nutzer_a))

    assert antwort.status_code == 200
    assert antwort.json()["max_price_cents"] == alarm["max_price_cents"]


# --- Löschen ---------------------------------------------------------------


async def test_loeschen_entfernt_den_alarm(client: AsyncClient, nutzer_a, db_session):
    alarm = (await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))).json()

    antwort = await client.delete(f"/alerts/{alarm['id']}", headers=auth(nutzer_a))

    assert antwort.status_code == 204
    # Gegenprobe direkt in der Datenbank, nicht nur über die API.
    assert await db_session.get(PriceAlert, uuid.UUID(alarm["id"])) is None

    nachher = await client.get(f"/alerts/{alarm['id']}", headers=auth(nutzer_a))
    assert nachher.status_code == 404


# --- Kontingent ------------------------------------------------------------


async def test_limit_bremst_das_anlegen(client: AsyncClient, db_session: AsyncSession, nutzer_a):
    user = await get_or_create_user(db_session, nutzer_a, "limit@beispiel.de")
    user.max_active_alerts = 2
    await db_session.commit()

    for i in range(2):
        antwort = await client.post(
            "/alerts", json=alarm_json(destination=["BCN", "LIS"][i]), headers=auth(nutzer_a)
        )
        assert antwort.status_code == 201

    dritter = await client.post(
        "/alerts", json=alarm_json(destination="FCO"), headers=auth(nutzer_a)
    )

    assert dritter.status_code == 409
    assert "2 aktive Alarme" in dritter.json()["detail"]


async def test_pausierter_alarm_zaehlt_nicht_gegen_das_limit(
    client: AsyncClient, db_session: AsyncSession, nutzer_a
):
    user = await get_or_create_user(db_session, nutzer_a, "limit2@beispiel.de")
    user.max_active_alerts = 1
    await db_session.commit()

    erster = (await client.post("/alerts", json=alarm_json(), headers=auth(nutzer_a))).json()

    # Pausieren macht wieder Platz …
    pause = await client.patch(
        f"/alerts/{erster['id']}", json={"is_active": False}, headers=auth(nutzer_a)
    )
    assert pause.status_code == 200
    assert pause.json()["is_active"] is False

    zweiter = await client.post(
        "/alerts", json=alarm_json(destination="LIS"), headers=auth(nutzer_a)
    )
    assert zweiter.status_code == 201

    # … und das Wiederaktivieren des ersten läuft dann gegen die Grenze.
    reaktivieren = await client.patch(
        f"/alerts/{erster['id']}", json={"is_active": True}, headers=auth(nutzer_a)
    )
    assert reaktivieren.status_code == 409
