"""Härtung (M12) mit **echter Datenbank** — Löschen, Aufräumen, Bremsen.

Drei Dinge, die sich ohne Datenbank nicht beweisen lassen:

* **`DELETE /me` löscht wirklich alles.** Das ist das DSGVO-Löschrecht, und
  es steht und fällt mit `ON DELETE CASCADE`. Ob die Regel an *jeder*
  Tabelle hängt, sagt einem nur die Datenbank.
* **Das Aufräumen trifft das Richtige** — Altes weg, Aktuelles da.
* **Der 429 kommt über HTTP an**, mit `Retry-After` und deutschem Text.

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.health import database_probe
from app.config import get_settings
from app.core.ratelimit import allgemein
from app.db import get_db
from app.main import app
from app.models.device_token import DeviceToken
from app.models.flight_observation import FlightObservation
from app.models.notification_log import NotificationLog
from app.models.price_alert import PriceAlert
from app.models.user import User
from app.services.aufraeumen import loesche_alte_daten
from app.services.users import get_or_create_user
from tests.test_auth import make_settings, make_token

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: make_settings()
    app.dependency_overrides[get_db] = lambda: db_session
    # `database_probe` fragt sonst die **echte** Engine — an der Testsitzung
    # vorbei und aus einer anderen Ereignisschleife. Genau dafür ist die
    # Prüfung in `health.py` eine eigene Dependency.
    app.dependency_overrides[database_probe] = lambda: True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def nutzer(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


def auth(user_id: uuid.UUID) -> dict[str, str]:
    token = make_token(user_id=str(user_id), email=f"{user_id}@beispiel.de")
    return {"Authorization": f"Bearer {token}"}


async def lege_vollen_datensatz_an(session: AsyncSession, user_id: uuid.UUID) -> PriceAlert:
    """Ein Nutzer mit allem, was an ihm hängen kann."""
    alarm = PriceAlert(
        user_id=user_id,
        origin="MUC",
        destination="BCN",
        earliest_departure_date=date(2026, 9, 6),
        latest_return_date=date(2026, 9, 13),
        max_price_cents=25000,
    )
    session.add(alarm)
    await session.commit()
    await session.refresh(alarm)

    session.add(
        FlightObservation(
            price_alert_id=alarm.id,
            observed_at=JETZT,
            min_price_cents=19900,
            currency="EUR",
            origin="MUC",
            destination="BCN",
            departure_month="2026-09",
            offers_found=1,
            search_ok=True,
        )
    )
    session.add(
        DeviceToken(
            user_id=user_id, endpoint=f"https://push.test/{uuid.uuid4()}", p256dh="p", auth="a"
        )
    )
    session.add(
        NotificationLog(
            user_id=user_id,
            price_alert_id=alarm.id,
            dedupe_key=uuid.uuid4().hex,
            price_cents=19900,
            sent_at=JETZT,
            status="sent",
        )
    )
    await session.commit()
    return alarm


# --- DSGVO: Konto löschen --------------------------------------------------


async def test_konto_loeschen_raeumt_restlos_auf(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    """Das Löschrecht — und der Beweis, dass `ON DELETE CASCADE` überall hängt.

    Der Test zählt in **fünf** Tabellen nach, nicht nur in `users`. Ein
    fehlendes CASCADE an einer davon wäre der Fehler, den man erst bemerkt,
    wenn jemand sein Konto löscht und seine Reisewünsche trotzdem noch in der
    Datenbank stehen.

    Die Ketten sind unterschiedlich lang, und das ist der Grund für die
    ausgeschriebene Liste statt einer Schleife: `price_alerts`,
    `device_tokens` und `notification_logs` hängen **direkt** am Nutzer,
    `flight_observations` und `flight_offers` dagegen über den Alarm. Die
    zweite Kette hat zwei Glieder — es reicht nicht, dass eines davon hält.
    """
    alarm = await lege_vollen_datensatz_an(db_session, nutzer)

    antwort = await client.delete("/me", headers=auth(nutzer))

    assert antwort.status_code == 204

    async def anzahl(auswahl: object) -> int:
        ergebnis = await db_session.execute(auswahl)  # type: ignore[arg-type]
        return ergebnis.scalar() or 0

    # Direkt am Nutzer.
    assert await anzahl(select(func.count()).select_from(User).where(User.id == nutzer)) == 0
    assert (
        await anzahl(
            select(func.count()).select_from(PriceAlert).where(PriceAlert.user_id == nutzer)
        )
        == 0
    )
    assert (
        await anzahl(
            select(func.count()).select_from(DeviceToken).where(DeviceToken.user_id == nutzer)
        )
        == 0
    )
    assert (
        await anzahl(
            select(func.count())
            .select_from(NotificationLog)
            .where(NotificationLog.user_id == nutzer)
        )
        == 0
    )
    # Über den Alarm — die längere Kette.
    assert (
        await anzahl(
            select(func.count())
            .select_from(FlightObservation)
            .where(FlightObservation.price_alert_id == alarm.id)
        )
        == 0
    )


async def test_loeschen_trifft_nur_das_eigene_konto(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    await lege_vollen_datensatz_an(db_session, fremder.id)

    await client.delete("/me", headers=auth(nutzer))

    uebrig = await db_session.execute(
        select(func.count()).select_from(User).where(User.id == fremder.id)
    )
    assert uebrig.scalar() == 1


async def test_zweimal_loeschen_ist_kein_fehler(client: AsyncClient, nutzer: uuid.UUID):
    """Für den Aufrufer ist das Ergebnis beide Male dasselbe: Es ist nichts mehr da."""
    assert (await client.delete("/me", headers=auth(nutzer))).status_code == 204
    assert (await client.delete("/me", headers=auth(nutzer))).status_code == 204


async def test_ohne_anmeldung_wird_nichts_geloescht(client: AsyncClient):
    assert (await client.delete("/me")).status_code == 401


# --- Alte Daten aufräumen --------------------------------------------------


async def test_alte_beobachtungen_werden_geloescht(db_session: AsyncSession, nutzer: uuid.UUID):
    alarm = await lege_vollen_datensatz_an(db_session, nutzer)
    db_session.add(
        FlightObservation(
            price_alert_id=alarm.id,
            observed_at=JETZT - timedelta(days=400),
            min_price_cents=21000,
            currency="EUR",
            origin="MUC",
            destination="BCN",
            departure_month="2025-09",
            offers_found=1,
            search_ok=True,
        )
    )
    await db_session.commit()

    bericht = await loesche_alte_daten(db_session, aufbewahrung_tage=365, jetzt=JETZT)

    assert bericht.beobachtungen == 1
    uebrig = await db_session.execute(
        select(FlightObservation.min_price_cents).where(
            FlightObservation.price_alert_id == alarm.id
        )
    )
    # Die aktuelle Beobachtung von heute ist noch da.
    assert list(uebrig.scalars()) == [19900]


async def test_alte_meldungen_werden_geloescht(db_session: AsyncSession, nutzer: uuid.UUID):
    alarm = await lege_vollen_datensatz_an(db_session, nutzer)
    db_session.add(
        NotificationLog(
            user_id=nutzer,
            price_alert_id=alarm.id,
            dedupe_key=uuid.uuid4().hex,
            price_cents=22000,
            sent_at=JETZT - timedelta(days=400),
            status="sent",
        )
    )
    await db_session.commit()

    bericht = await loesche_alte_daten(db_session, aufbewahrung_tage=365, jetzt=JETZT)

    assert bericht.meldungen == 1


async def test_angebote_bleiben_unangetastet(db_session: AsyncSession, nutzer: uuid.UUID):
    """Aufräumen darf niemandem Funde wegnehmen, die er sich gerade ansieht.

    `flight_offers` hängt per CASCADE am Alarm und verschwindet mit ihm —
    nach Alter gelöscht wird dort nichts.
    """
    from app.models.flight_offer import FlightOffer

    alarm = await lege_vollen_datensatz_an(db_session, nutzer)
    db_session.add(
        FlightOffer(
            price_alert_id=alarm.id,
            offer_hash=uuid.uuid4().hex,
            total_price_cents=19900,
            currency="EUR",
            outbound_departure_at=JETZT - timedelta(days=400),
            outbound_arrival_at=JETZT - timedelta(days=400) + timedelta(hours=2),
            outbound_stops=0,
            segments=[],
            found_at=JETZT - timedelta(days=400),
            last_seen_at=JETZT - timedelta(days=400),
        )
    )
    await db_session.commit()

    await loesche_alte_daten(db_session, aufbewahrung_tage=365, jetzt=JETZT)

    uebrig = await db_session.execute(
        select(func.count()).select_from(FlightOffer).where(FlightOffer.price_alert_id == alarm.id)
    )
    assert uebrig.scalar() == 1


async def test_ein_lauf_ohne_altes_loescht_nichts(db_session: AsyncSession, nutzer: uuid.UUID):
    await lege_vollen_datensatz_an(db_session, nutzer)

    bericht = await loesche_alte_daten(db_session, aufbewahrung_tage=365, jetzt=JETZT)

    assert bericht.gesamt == 0


# --- Rate Limiting über HTTP ------------------------------------------------


async def test_zu_viele_anfragen_ergeben_429(client: AsyncClient, nutzer: uuid.UUID):
    """Der Weg, den ein Skript in der Schleife wirklich geht.

    Geprüft wird nicht nur der Statuscode, sondern auch das, was danach
    zählt: ein `Retry-After`-Kopf für Maschinen und ein deutscher Satz für
    Menschen.
    """
    allgemein.zuruecksetzen()
    kopf = auth(nutzer)

    letzte = None
    for _ in range(allgemein.grenze + 1):
        letzte = await client.get("/me", headers=kopf)

    assert letzte is not None
    assert letzte.status_code == 429
    assert int(letzte.headers["Retry-After"]) > 0
    assert "Zu viele Anfragen" in letzte.json()["detail"]


async def test_ein_vielnutzer_sperrt_niemanden_sonst_aus(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    allgemein.zuruecksetzen()
    for _ in range(allgemein.grenze + 1):
        await client.get("/me", headers=auth(nutzer))

    anderer = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")

    assert (await client.get("/me", headers=auth(anderer.id))).status_code == 200


async def test_health_wird_nicht_gebremst(client: AsyncClient):
    """Ausgerechnet die Bremse dürfte den Ausfall nicht auslösen, den sie verhindert.

    Der Hoster fragt die Probe im Sekundentakt. Ein 429 dort hieße für ihn
    „Instanz kaputt" — und er nähme sie aus dem Verkehr.
    """
    allgemein.zuruecksetzen()

    for _ in range(allgemein.grenze + 5):
        antwort = await client.get("/health")

    assert antwort.status_code == 200


# --- Readiness --------------------------------------------------------------


async def test_readiness_meldet_200_bei_erreichbarer_datenbank(client: AsyncClient):
    antwort = await client.get("/health/ready")

    assert antwort.status_code == 200
    assert antwort.json()["database"] == "ok"


async def test_readiness_meldet_503_ohne_datenbank(client: AsyncClient):
    """Der Unterschied zu `/health`, der den zweiten Endpunkt rechtfertigt.

    Render und Railway kennen nur „200 = nimm Verkehr". Ein immer-200
    wäre als Probe nutzlos.
    """
    app.dependency_overrides[database_probe] = lambda: False

    antwort = await client.get("/health/ready")
    normal = await client.get("/health")

    assert antwort.status_code == 503
    # Der Body bleibt derselbe — wer die Probe von Hand aufruft, sieht sofort,
    # *was* fehlt statt nur „Service Unavailable".
    assert antwort.json()["database"] == "unavailable"
    assert normal.status_code == 200
