"""Melden und Versenden (M8) mit **echter Datenbank**, aber ohne Netz.

Der Versand steckt hinter dem Protokoll `PushVersand`, deshalb setzen diese
Tests eine Attrappe ein. Geprüft wird das, was ohne Datenbank nicht prüfbar
ist: die Dedupe-Mauer, das Protokoll und das Stilllegen toter Ziele.

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.device_token import DeviceToken
from app.models.notification_log import NotificationLog
from app.models.price_alert import PriceAlert
from app.services.price_stats import Einordnung, Preisbewertung
from app.services.pruflauf import bilde_offer_hash, pruefe_alarm
from app.services.push import (
    PushFehler,
    entferne_ziel,
    hole_letzte_meldung,
    melde_treffer,
    registriere_ziel,
)
from app.services.users import get_or_create_user
from tests.attrappen import FlugsucheAttrappe, PushVersandAttrappe, baue_angebot

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

EINSTELLUNGEN = Settings(
    push_abkuehlphase_stunden=6,
    push_mindest_verbesserung_prozent=5.0,
)

BEWERTUNG = Preisbewertung(
    preis_cents=18950,
    einordnung=Einordnung.GUENSTIG,
    datenpunkte=12,
    median_cents=24000,
    minimum_cents=17000,
    abweichung_prozent=-21.0,
)


def zufallsziel() -> str:
    return uuid.uuid4().hex[:3].upper().translate(str.maketrans("0123456789", "ABCDEFGHIJ"))


@pytest.fixture
async def alarm(db_session: AsyncSession) -> PriceAlert:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    alert = PriceAlert(
        user_id=user.id,
        origin="MUC",
        destination=zufallsziel(),
        earliest_departure_date=date(2026, 9, 6),
        latest_return_date=date(2026, 9, 13),
        max_stops=1,
        max_price_cents=25000,
        currency="EUR",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


async def lege_ziel_an(session: AsyncSession, alarm: PriceAlert, endpoint: str) -> DeviceToken:
    return await registriere_ziel(
        session, alarm.user_id, endpoint, p256dh="p256dh-wert", auth="auth-wert"
    )


async def melde(
    session: AsyncSession,
    alarm: PriceAlert,
    versand: PushVersandAttrappe,
    preis_cents: int = 18950,
    jetzt: datetime = JETZT,
):
    """Ein Meldeversuch mit einem frisch angelegten Angebot."""
    angebot = baue_angebot(preis_cents=preis_cents)
    return await melde_treffer(
        session=session,
        alert=alarm,
        angebot=angebot,
        offer_hash=bilde_offer_hash(angebot),
        flight_offer_id=None,
        bewertung=BEWERTUNG,
        versand=versand,
        settings=EINSTELLUNGEN,
        jetzt=jetzt,
    )


# --- Ziele registrieren -----------------------------------------------------


async def test_ziel_wird_angelegt(db_session: AsyncSession, alarm: PriceAlert):
    ziel = await lege_ziel_an(db_session, alarm, "https://push.test/eins")

    assert ziel.is_active is True
    assert ziel.platform == "web"


async def test_zweimal_anmelden_ergibt_kein_zweites_ziel(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Browser bietet dieselbe Subscription bei jedem Aufruf erneut an.

    Ohne Upsert stünde das Gerät nach einer Woche zwanzigmal in der Tabelle —
    und jede Meldung käme zwanzigmal an.
    """
    await lege_ziel_an(db_session, alarm, "https://push.test/gleich")
    await lege_ziel_an(db_session, alarm, "https://push.test/gleich")

    anzahl = await db_session.execute(
        select(DeviceToken).where(DeviceToken.user_id == alarm.user_id)
    )
    assert len(list(anzahl.scalars().all())) == 1


async def test_erneutes_anmelden_weckt_ein_stillgelegtes_ziel(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Wer neu abonniert, will offensichtlich wieder Nachrichten."""
    ziel = await lege_ziel_an(db_session, alarm, "https://push.test/wieder")
    await entferne_ziel(db_session, alarm.user_id, ziel.endpoint)

    erneut = await lege_ziel_an(db_session, alarm, "https://push.test/wieder")

    assert erneut.is_active is True


async def test_fremdes_ziel_laesst_sich_nicht_abmelden(db_session: AsyncSession, alarm: PriceAlert):
    """`user_id` steht in der WHERE-Klausel, nicht in einer Nachprüfung."""
    await lege_ziel_an(db_session, alarm, "https://push.test/meins")

    assert await entferne_ziel(db_session, uuid.uuid4(), "https://push.test/meins") is False


# --- Die Dedupe-Mauer -------------------------------------------------------


async def test_dasselbe_angebot_wird_nur_einmal_gemeldet(
    db_session: AsyncSession, alarm: PriceAlert
):
    """**Der wichtigste Test von M8.**

    Beim zweiten Versuch darf keine Nachricht mehr rausgehen — auch wenn die
    Abkühlphase längst vorbei wäre.
    """
    await lege_ziel_an(db_session, alarm, "https://push.test/dedupe")
    versand = PushVersandAttrappe()

    erste = await melde(db_session, alarm, versand)
    zweite = await melde(db_session, alarm, versand, jetzt=JETZT + timedelta(days=3))

    assert erste.gemeldet is True
    assert zweite.gemeldet is False
    assert zweite.grund == "schon_gemeldet"
    assert versand.anzahl == 1


async def test_billiger_gewordener_flug_ist_ein_neues_angebot(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Preis steckt im `offer_hash` — deshalb ist er wieder meldenswert."""
    await lege_ziel_an(db_session, alarm, "https://push.test/billiger")
    versand = PushVersandAttrappe()

    await melde(db_session, alarm, versand, preis_cents=20000)
    zweite = await melde(
        db_session, alarm, versand, preis_cents=15000, jetzt=JETZT + timedelta(hours=7)
    )

    assert zweite.gemeldet is True
    assert versand.anzahl == 2


# --- Abkühlphase gegen echte Protokollzeilen --------------------------------


async def test_abkuehlphase_verhindert_die_zweite_meldung(
    db_session: AsyncSession, alarm: PriceAlert
):
    await lege_ziel_an(db_session, alarm, "https://push.test/ruhe")
    versand = PushVersandAttrappe()

    await melde(db_session, alarm, versand, preis_cents=20000)
    zweite = await melde(
        db_session, alarm, versand, preis_cents=19900, jetzt=JETZT + timedelta(hours=1)
    )

    assert zweite.gemeldet is False
    assert zweite.grund == "abkuehlphase"
    assert versand.anzahl == 1


async def test_letzte_meldung_wird_gefunden(db_session: AsyncSession, alarm: PriceAlert):
    await lege_ziel_an(db_session, alarm, "https://push.test/letzte")
    await melde(db_session, alarm, PushVersandAttrappe(), preis_cents=20000)

    letzte = await hole_letzte_meldung(db_session, alarm.id)

    assert letzte is not None
    assert letzte.price_cents == 20000


# --- Versand und Protokoll --------------------------------------------------


async def test_meldung_geht_an_alle_geraete(db_session: AsyncSession, alarm: PriceAlert):
    await lege_ziel_an(db_session, alarm, "https://push.test/handy")
    await lege_ziel_an(db_session, alarm, "https://push.test/laptop")
    versand = PushVersandAttrappe()

    ergebnis = await melde(db_session, alarm, versand)

    assert ergebnis.zugestellt == 2
    assert {endpoint for endpoint, _ in versand.gesendet} == {
        "https://push.test/handy",
        "https://push.test/laptop",
    }


async def test_totes_ziel_wird_stillgelegt_das_lebende_nicht(
    db_session: AsyncSession, alarm: PriceAlert
):
    """410 heißt „Erlaubnis entzogen" — weiterversuchen wäre sinnlos."""
    await lege_ziel_an(db_session, alarm, "https://push.test/tot")
    await lege_ziel_an(db_session, alarm, "https://push.test/lebt")
    versand = PushVersandAttrappe(
        fehler_fuer={"https://push.test/tot": PushFehler("weg", status_code=410)}
    )

    ergebnis = await melde(db_session, alarm, versand)

    assert ergebnis.zugestellt == 1
    assert ergebnis.fehlgeschlagen == 1

    zustand = await db_session.execute(
        select(DeviceToken.endpoint, DeviceToken.is_active).where(
            DeviceToken.user_id == alarm.user_id
        )
    )
    assert dict(zustand.all()) == {
        "https://push.test/tot": False,
        "https://push.test/lebt": True,
    }


async def test_voruebergehender_fehler_legt_kein_ziel_still(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Ein 503 ist Schluckauf beim Push-Dienst, kein Grund zum Aufgeben."""
    await lege_ziel_an(db_session, alarm, "https://push.test/schluckauf")
    versand = PushVersandAttrappe(
        fehler_fuer={"https://push.test/schluckauf": PushFehler("später", status_code=503)}
    )

    await melde(db_session, alarm, versand)

    ziel = await db_session.execute(
        select(DeviceToken.is_active).where(DeviceToken.user_id == alarm.user_id)
    )
    assert ziel.scalar_one() is True


async def test_protokollzeile_haelt_das_ergebnis_fest(db_session: AsyncSession, alarm: PriceAlert):
    await lege_ziel_an(db_session, alarm, "https://push.test/protokoll")

    await melde(db_session, alarm, PushVersandAttrappe(), preis_cents=18950)

    zeile = await db_session.execute(
        select(NotificationLog).where(NotificationLog.price_alert_id == alarm.id)
    )
    log = zeile.scalar_one()
    assert log.status == "sent"
    assert log.price_cents == 18950
    assert log.push_error is None


async def test_ohne_registriertes_geraet_wird_der_fehlschlag_protokolliert(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Kein Gerät ist kein Absturz — aber es muss nachvollziehbar sein."""
    ergebnis = await melde(db_session, alarm, PushVersandAttrappe())

    assert ergebnis.gemeldet is False
    zeile = await db_session.execute(
        select(NotificationLog).where(NotificationLog.price_alert_id == alarm.id)
    )
    log = zeile.scalar_one()
    assert log.status == "failed"
    assert log.push_error is not None


async def test_gescheiterte_meldung_blockiert_die_naechste_nicht(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Was nie ankam, darf die Abkühlphase nicht auslösen."""
    await melde(db_session, alarm, PushVersandAttrappe(), preis_cents=20000)  # ohne Gerät

    assert await hole_letzte_meldung(db_session, alarm.id) is None


# --- Zusammenspiel mit dem Prüflauf ----------------------------------------


async def test_pruflauf_meldet_den_besten_treffer(db_session: AsyncSession, alarm: PriceAlert):
    """M6, M7 und M8 zusammen — der komplette Weg von der Suche zur Nachricht."""
    await lege_ziel_an(db_session, alarm, "https://push.test/kette")
    versand = PushVersandAttrappe()
    suche = FlugsucheAttrappe(
        [baue_angebot(preis_cents=22000), baue_angebot(preis_cents=17000, airline="OS")]
    )

    ergebnis = await pruefe_alarm(db_session, alarm, suche, JETZT, versand, EINSTELLUNGEN)

    assert ergebnis.meldung is not None
    assert ergebnis.meldung.gemeldet is True
    assert versand.anzahl == 1
    # Gemeldet wird der günstigste passende Treffer, nicht der erstbeste.
    _, nachricht = versand.gesendet[0]
    assert "170,00 €" in nachricht.titel


async def test_ohne_versand_laeuft_alles_wie_vorher(db_session: AsyncSession, alarm: PriceAlert):
    """M6/M7-Verhalten bleibt unberührt, wenn kein Versand übergeben wird."""
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=17000)])

    ergebnis = await pruefe_alarm(db_session, alarm, suche, JETZT)

    assert ergebnis.angebote_gespeichert == 1
    assert ergebnis.meldung is None


async def test_lauf_ohne_treffer_meldet_nichts(db_session: AsyncSession, alarm: PriceAlert):
    versand = PushVersandAttrappe()

    ergebnis = await pruefe_alarm(
        db_session, alarm, FlugsucheAttrappe([]), JETZT, versand, EINSTELLUNGEN
    )

    assert ergebnis.meldung is None
    assert versand.anzahl == 0


async def test_zweiter_lauf_mit_demselben_angebot_meldet_nicht_erneut(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Alltagsfall: Alle sechs Stunden wird derselbe Flug gefunden."""
    await lege_ziel_an(db_session, alarm, "https://push.test/alltag")
    versand = PushVersandAttrappe()
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=17000)])

    await pruefe_alarm(db_session, alarm, suche, JETZT, versand, EINSTELLUNGEN)
    await db_session.refresh(alarm)
    zweiter = await pruefe_alarm(
        db_session, alarm, suche, JETZT + timedelta(days=1), versand, EINSTELLUNGEN
    )

    assert zweiter.meldung is not None
    assert zweiter.meldung.grund == "schon_gemeldet"
    assert versand.anzahl == 1
