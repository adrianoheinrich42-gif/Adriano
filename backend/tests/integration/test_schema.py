"""Integrationstests für das Datenbankschema.

Diese Tests prüfen nicht Python-Code, sondern die **Datenbank selbst**: Halten
die CHECK-Constraints? Greift das Kaskadenlöschen? Verhindert der UNIQUE-Index
auf `dedupe_key` wirklich die zweite Benachrichtigung?

Das ist genau die Art von Zusicherung, die man nicht "hofft", sondern testet —
denn sie ist die Grundlage dafür, dass die App keinen Spam verschickt.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DeviceToken,
    FlightObservation,
    FlightOffer,
    NotificationLog,
    PriceAlert,
    User,
)


async def _user(session: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@beispiel.de")
    session.add(user)
    await session.flush()
    return user


async def _count(session: AsyncSession, modell: type, bedingung: ColumnElement[bool]) -> int | None:
    """Zeilen einer Tabelle zählen, eingegrenzt auf die Daten eines Tests.

    Global zu zählen wäre fragil: In der Entwicklungsdatenbank liegen oft
    Datensätze aus anderen Läufen.
    """
    return await session.scalar(select(func.count()).select_from(modell).where(bedingung))


def _alert(user: User, **overrides: object) -> PriceAlert:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "origin": "MUC",
        "destination": "BCN",
        "earliest_departure_date": date(2026, 10, 1),
        "latest_return_date": date(2026, 10, 20),
        "max_price_cents": 15000,
    }
    return PriceAlert(**(defaults | overrides))


# ---------------------------------------------------------------------------
# Gültige Daten
# ---------------------------------------------------------------------------


async def test_gueltiger_alarm_bekommt_id_und_standardwerte(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()
    await db_session.refresh(alert)

    assert alert.id is not None, "Die Datenbank muss die UUID selbst erzeugen"
    assert alert.currency == "EUR"
    assert alert.max_stops == 1
    assert alert.adults == 1
    assert alert.is_active is True
    assert alert.check_interval_minutes == 360
    assert alert.last_checked_at is None


# ---------------------------------------------------------------------------
# CHECK-Constraints — die Datenbank als letzte Verteidigungslinie
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("beschreibung", "overrides"),
    [
        ("Start gleich Ziel", {"destination": "MUC"}),
        ("Rückflug vor Hinflug", {"latest_return_date": date(2026, 9, 1)}),
        ("IATA klein geschrieben", {"origin": "muc"}),
        ("Preis null", {"max_price_cents": 0}),
        ("negative Stopps", {"max_stops": -1}),
        ("null Reisende", {"adults": 0}),
        ("Prüfintervall unter 15 Minuten", {"check_interval_minutes": 5}),
        (
            "Mindestdauer größer als Höchstdauer",
            {"min_trip_duration_days": 10, "max_trip_duration_days": 3},
        ),
    ],
)
async def test_ungueltiger_alarm_wird_abgelehnt(
    db_session: AsyncSession, beschreibung: str, overrides: dict[str, object]
) -> None:
    user = await _user(db_session)
    db_session.add(_alert(user, **overrides))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_geraetetoken_nur_plattform_web(db_session: AsyncSession) -> None:
    """Seit M8 ist Web-Push die einzige Plattform — 'ios' gibt es nicht mehr."""
    user = await _user(db_session)
    db_session.add(
        DeviceToken(
            user_id=user.id,
            endpoint="https://push.beispiel.test/xyz",
            p256dh="p256dh-wert",
            auth="auth-wert",
            platform="ios",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_derselbe_endpoint_kann_kein_zweites_mal_gespeichert_werden(
    db_session: AsyncSession,
) -> None:
    """Sonst käme jede Meldung doppelt an — der Browser meldet sich oft neu an."""
    user = await _user(db_session)
    for _ in range(2):
        db_session.add(
            DeviceToken(
                user_id=user.id,
                endpoint="https://push.beispiel.test/doppelt",
                p256dh="p256dh-wert",
                auth="auth-wert",
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# Der wichtigste Test des Projekts: Schutz vor Doppelbenachrichtigung
# ---------------------------------------------------------------------------


async def test_gleicher_dedupe_key_kann_kein_zweites_mal_gespeichert_werden(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()

    dedupe_key = "a" * 64

    db_session.add(
        NotificationLog(
            user_id=user.id,
            price_alert_id=alert.id,
            dedupe_key=dedupe_key,
            price_cents=9400,
            status="sent",
        )
    )
    await db_session.flush()

    # Zweiter Versuch mit demselben Schlüssel — die Datenbank muss ihn abweisen.
    db_session.add(
        NotificationLog(
            user_id=user.id,
            price_alert_id=alert.id,
            dedupe_key=dedupe_key,
            price_cents=9400,
            status="sent",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_gleiches_angebot_wird_pro_alarm_nur_einmal_gespeichert(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()

    abflug = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    def angebot() -> FlightOffer:
        return FlightOffer(
            price_alert_id=alert.id,
            offer_hash="b" * 64,
            total_price_cents=9400,
            outbound_departure_at=abflug,
            outbound_arrival_at=abflug + timedelta(hours=2),
        )

    db_session.add(angebot())
    await db_session.flush()

    db_session.add(angebot())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_ankunft_vor_abflug_wird_abgelehnt(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()

    abflug = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    db_session.add(
        FlightOffer(
            price_alert_id=alert.id,
            offer_hash="c" * 64,
            total_price_cents=9400,
            outbound_departure_at=abflug,
            outbound_arrival_at=abflug - timedelta(hours=1),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# Kaskadenlöschen — wichtig für "Konto löschen" (DSGVO)
# ---------------------------------------------------------------------------


async def test_nutzer_loeschen_entfernt_alle_abhaengigen_daten(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    db_session.add(
        DeviceToken(
            user_id=user.id,
            endpoint=f"https://push.beispiel.test/{uuid.uuid4().hex}",
            p256dh="p256dh-wert",
            auth="auth-wert",
        )
    )
    await db_session.flush()

    db_session.add(
        FlightObservation(
            price_alert_id=alert.id,
            min_price_cents=9400,
            origin="MUC",
            destination="BCN",
            departure_month="2026-10",
            offers_found=3,
        )
    )
    await db_session.flush()

    # Bewusst ein Core-DELETE statt `session.delete(user)`: So wird die
    # Kaskade der **Datenbank** geprüft (ON DELETE CASCADE), nicht die des
    # ORM. Genau darauf verlässt sich später das Löschen eines Kontos.
    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.flush()

    # Nur die Daten dieses Nutzers zählen — die Tabelle kann andere enthalten.
    assert await _count(db_session, PriceAlert, PriceAlert.user_id == user.id) == 0
    assert await _count(db_session, DeviceToken, DeviceToken.user_id == user.id) == 0
    assert (
        await _count(db_session, FlightObservation, FlightObservation.price_alert_id == alert.id)
        == 0
    )


# ---------------------------------------------------------------------------
# Preisverlauf
# ---------------------------------------------------------------------------


async def test_beobachtung_ohne_fund_ist_erlaubt(db_session: AsyncSession) -> None:
    """Läufe ohne Treffer gehören in den Verlauf — sonst verzerrt sich der Median."""
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()

    beobachtung = FlightObservation(
        price_alert_id=alert.id,
        min_price_cents=None,
        origin="MUC",
        destination="BCN",
        departure_month="2026-10",
        offers_found=0,
        search_ok=True,
    )
    db_session.add(beobachtung)
    await db_session.flush()
    await db_session.refresh(beobachtung)

    assert beobachtung.min_price_cents is None
    assert beobachtung.observed_at is not None


async def test_monatsformat_wird_erzwungen(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    alert = _alert(user)
    db_session.add(alert)
    await db_session.flush()

    db_session.add(
        FlightObservation(
            price_alert_id=alert.id,
            origin="MUC",
            destination="BCN",
            departure_month="Okt 26",  # falsches Format
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
