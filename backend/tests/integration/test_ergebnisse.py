"""Die Ergebnisanzeige (M9) über HTTP, mit **echter Datenbank**.

Zwei Schwerpunkte:

1. **Gehört das wirklich mir?** Fremde Alarme und fremde Angebote müssen 404
   ergeben, nicht 403 — dieselbe Regel wie beim Alarm-CRUD.
2. **Stimmt der Verlauf?** Ein Punkt je Tag, nicht je Prüflauf; gescheiterte
   Suchen zählen nicht.

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.flight_observation import FlightObservation
from app.models.price_alert import PriceAlert
from app.services.price_stats import MINDEST_DATENPUNKTE
from app.services.pruflauf import pruefe_alarm
from app.services.users import get_or_create_user
from tests.attrappen import FlugsucheAttrappe, baue_angebot
from tests.test_auth import make_settings, make_token

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: make_settings()
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def auth(user_id: uuid.UUID) -> dict[str, str]:
    token = make_token(user_id=str(user_id), email=f"{user_id}@beispiel.de")
    return {"Authorization": f"Bearer {token}"}


def zufallsziel() -> str:
    return uuid.uuid4().hex[:3].upper().translate(str.maketrans("0123456789", "ABCDEFGHIJ"))


async def lege_alarm_an(session: AsyncSession, user_id: uuid.UUID) -> PriceAlert:
    alert = PriceAlert(
        user_id=user_id,
        origin="MUC",
        destination=zufallsziel(),
        earliest_departure_date=date(2026, 9, 6),
        latest_return_date=date(2026, 9, 13),
        max_stops=1,
        max_price_cents=25000,
        currency="EUR",
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


@pytest.fixture
async def nutzer(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


@pytest.fixture
async def alarm(db_session: AsyncSession, nutzer: uuid.UUID) -> PriceAlert:
    return await lege_alarm_an(db_session, nutzer)


async def lege_beobachtung_an(
    session: AsyncSession,
    alarm: PriceAlert,
    preis: int | None,
    observed_at: datetime,
    search_ok: bool = True,
) -> None:
    session.add(
        FlightObservation(
            price_alert_id=alarm.id,
            observed_at=observed_at,
            min_price_cents=preis,
            currency="EUR",
            origin=alarm.origin,
            destination=alarm.destination,
            departure_month="2026-09",
            offers_found=1 if preis else 0,
            search_ok=search_ok,
        )
    )
    await session.commit()


# --- Angebotsliste ----------------------------------------------------------


async def test_liste_ist_leer_solange_nichts_gefunden_wurde(
    client: AsyncClient, alarm: PriceAlert, nutzer: uuid.UUID
):
    """Wichtig: leere Liste mit 200, nicht 404. Der Alarm existiert ja."""
    antwort = await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))

    assert antwort.status_code == 200
    assert antwort.json() == []


async def test_gefundene_angebote_erscheinen_guenstigste_zuerst(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    suche = FlugsucheAttrappe(
        [baue_angebot(preis_cents=22000), baue_angebot(preis_cents=17000, airline="OS")]
    )
    await pruefe_alarm(db_session, alarm, suche, JETZT)

    antwort = await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))

    preise = [a["total_price_cents"] for a in antwort.json()]
    assert preise == [17000, 22000]


async def test_angebot_enthaelt_was_die_anzeige_braucht(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=17000)]), JETZT
    )

    angebot = (await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))).json()[0]

    assert angebot["currency"] == "EUR"
    assert angebot["validating_airline"] == "LH"
    assert angebot["outbound_stops"] == 0
    assert angebot["outbound_departure_at"].startswith("2026-09-06T09:15")
    assert angebot["included_checked_bags"] == 1


async def test_segmente_werden_in_hin_und_rueckflug_getrennt(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    """`flight_offers.segments` ist eine flache Liste — die Grenze ergibt sich
    aus `outbound_stops`. Das aufzuteilen ist Aufgabe des Backends, nicht des
    Browsers (Leitplanke 1)."""
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=17000)]), JETZT
    )

    angebot = (await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))).json()[0]

    assert [s["von"] for s in angebot["outbound_segments"]] == ["MUC"]
    assert [s["von"] for s in angebot["inbound_segments"]] == ["BCN"]
    assert angebot["outbound_duration_minutes"] == 130
    assert angebot["inbound_duration_minutes"] == 130


async def test_einwegflug_hat_keine_rueckflugdaten(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=17000, mit_rueckflug=False)])
    await pruefe_alarm(db_session, alarm, suche, JETZT)

    angebot = (await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))).json()[0]

    assert angebot["inbound_segments"] == []
    assert angebot["inbound_duration_minutes"] is None
    assert angebot["inbound_departure_at"] is None


async def test_rohdaten_werden_nicht_ausgeliefert(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    """`raw_payload` ist die vollständige Amadeus-Antwort — die bleibt drinnen."""
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=17000)]), JETZT
    )

    angebot = (await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))).json()[0]

    assert "raw_payload" not in angebot
    assert "offer_hash" not in angebot


async def test_fremder_alarm_ergibt_404(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    """404, nicht 403 — ein 403 verriete, dass es den Alarm gibt."""
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    fremder_alarm = await lege_alarm_an(db_session, fremder.id)

    antwort = await client.get(f"/alerts/{fremder_alarm.id}/offers", headers=auth(nutzer))

    assert antwort.status_code == 404


async def test_ohne_anmeldung_401(client: AsyncClient, alarm: PriceAlert):
    assert (await client.get(f"/alerts/{alarm.id}/offers")).status_code == 401


# --- Einzelnes Angebot (Ziel des Deep-Links) --------------------------------


async def test_einzelnes_angebot_abrufen(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=17000)]), JETZT
    )
    liste = (await client.get(f"/alerts/{alarm.id}/offers", headers=auth(nutzer))).json()

    antwort = await client.get(f"/offers/{liste[0]['id']}", headers=auth(nutzer))

    assert antwort.status_code == 200
    assert antwort.json()["total_price_cents"] == 17000


async def test_fremdes_angebot_ergibt_404(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    fremder_alarm = await lege_alarm_an(db_session, fremder.id)
    await pruefe_alarm(
        db_session, fremder_alarm, FlugsucheAttrappe([baue_angebot(preis_cents=17000)]), JETZT
    )
    fremdes = (
        await client.get(f"/alerts/{fremder_alarm.id}/offers", headers=auth(fremder.id))
    ).json()[0]

    antwort = await client.get(f"/offers/{fremdes['id']}", headers=auth(nutzer))

    assert antwort.status_code == 404


async def test_unbekanntes_angebot_ergibt_404(client: AsyncClient, nutzer: uuid.UUID):
    assert (await client.get(f"/offers/{uuid.uuid4()}", headers=auth(nutzer))).status_code == 404


# --- Preisverlauf -----------------------------------------------------------


async def test_verlauf_fasst_je_tag_zusammen(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    """Vier Läufe an einem Tag ergeben **einen** Punkt — den Tagestiefstpreis.

    Ohne die Zusammenfassung wären es bei 6-Stunden-Takt 540 Punkte in 90
    Tagen, und die Kurve zeigte vor allem Rauschen.
    """
    tag = datetime(2026, 8, 5, tzinfo=UTC)
    for stunde, preis in ((6, 22000), (12, 19000), (18, 21000)):
        await lege_beobachtung_an(db_session, alarm, preis, tag.replace(hour=stunde))

    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    assert verlauf["punkte"] == [{"tag": "2026-08-05", "min_price_cents": 19000}]


async def test_verlauf_ist_zeitlich_sortiert(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    for tage_zurueck, preis in ((1, 19000), (3, 21000), (2, 20000)):
        await lege_beobachtung_an(
            db_session, alarm, preis, datetime.now(UTC) - timedelta(days=tage_zurueck)
        )

    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    tage = [p["tag"] for p in verlauf["punkte"]]
    assert tage == sorted(tage)


async def test_gescheiterte_suchen_stehen_nicht_im_verlauf(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    jetzt = datetime.now(UTC)
    await lege_beobachtung_an(db_session, alarm, 20000, jetzt)
    await lege_beobachtung_an(db_session, alarm, 9900, jetzt, search_ok=False)

    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    assert [p["min_price_cents"] for p in verlauf["punkte"]] == [20000]


async def test_ohne_treffer_gibt_es_keine_bewertung(
    client: AsyncClient, alarm: PriceAlert, nutzer: uuid.UUID
):
    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    assert verlauf["bewertung"] is None
    assert verlauf["aktueller_preis_cents"] is None
    assert verlauf["punkte"] == []


async def test_bewertung_erscheint_sobald_es_einen_treffer_gibt(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    jetzt = datetime.now(UTC)
    for i in range(MINDEST_DATENPUNKTE):
        await lege_beobachtung_an(db_session, alarm, 25000, jetzt - timedelta(days=i + 1))
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=20000)]), jetzt
    )

    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    assert verlauf["aktueller_preis_cents"] == 20000
    assert verlauf["bewertung"]["einordnung"] == "guenstig"
    assert verlauf["bewertung"]["median_cents"] == 25000
    assert verlauf["bewertung"]["abweichung_prozent"] == -20.0


async def test_bei_zu_wenig_daten_bleiben_die_zahlen_null(
    client: AsyncClient, db_session: AsyncSession, alarm: PriceAlert, nutzer: uuid.UUID
):
    """Die Regel aus M7 muss bis in die JSON-Antwort durchhalten: `null`,
    nicht 0 — sonst zeigt der Client versehentlich „0 %"."""
    await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([baue_angebot(preis_cents=20000)]), datetime.now(UTC)
    )

    verlauf = (await client.get(f"/alerts/{alarm.id}/verlauf", headers=auth(nutzer))).json()

    assert verlauf["bewertung"]["einordnung"] == "zu_wenig_daten"
    assert verlauf["bewertung"]["median_cents"] is None
    assert verlauf["bewertung"]["abweichung_prozent"] is None


async def test_fremder_verlauf_ergibt_404(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    fremder_alarm = await lege_alarm_an(db_session, fremder.id)

    antwort = await client.get(f"/alerts/{fremder_alarm.id}/verlauf", headers=auth(nutzer))

    assert antwort.status_code == 404
