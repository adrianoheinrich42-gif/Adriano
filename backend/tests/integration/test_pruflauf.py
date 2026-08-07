"""Der komplette Prüflauf mit **echter Datenbank** (M6).

Das Abnahmekriterium von M6 steht hier: Ein Lauf schreibt
`flight_observations` und `flight_offers`.

Die Flugsuche ist eine Attrappe (`tests/attrappen.py`) — **kein Test geht ins
Netz**, und es werden keine Amadeus-Zugangsdaten gebraucht. Ohne erreichbare
Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation
from app.models.flight_offer import FlightOffer
from app.models.price_alert import PriceAlert
from app.services.amadeus import AmadeusError, AmadeusRateLimited
from app.services.pruflauf import (
    finde_faellige_alarme,
    pruefe_alarm,
    pruefe_faellige_alarme,
)
from app.services.users import get_or_create_user
from tests.attrappen import (
    FlugsucheAttrappe,
    baue_angebot,
    lade_fixture_angebote,
)

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
async def nutzer_id(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


async def lege_alarm_an(
    session: AsyncSession, nutzer_id: uuid.UUID, **overrides: object
) -> PriceAlert:
    daten: dict[str, object] = {
        "user_id": nutzer_id,
        "origin": "MUC",
        "destination": "BCN",
        "earliest_departure_date": date(2026, 9, 6),
        "latest_return_date": date(2026, 9, 13),
        "max_stops": 1,
        "max_price_cents": 25000,
        "currency": "EUR",
        "adults": 1,
    }
    daten.update(overrides)

    alert = PriceAlert(**daten)
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def beobachtungen(session: AsyncSession, alarm_id: uuid.UUID) -> list[FlightObservation]:
    result = await session.execute(
        select(FlightObservation)
        .where(FlightObservation.price_alert_id == alarm_id)
        .order_by(FlightObservation.observed_at)
    )
    return list(result.scalars().all())


async def angebote(session: AsyncSession, alarm_id: uuid.UUID) -> list[FlightOffer]:
    result = await session.execute(
        select(FlightOffer)
        .where(FlightOffer.price_alert_id == alarm_id)
        .order_by(FlightOffer.total_price_cents)
    )
    return list(result.scalars().all())


# --- Fällige Alarme finden -------------------------------------------------


async def test_neuer_alarm_wird_als_faellig_gefunden(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    alert = await lege_alarm_an(db_session, nutzer_id)

    gefunden = await finde_faellige_alarme(db_session, JETZT)

    assert [a.id for a in gefunden] == [alert.id]


async def test_pausierter_alarm_wird_nicht_gefunden(db_session: AsyncSession, nutzer_id: uuid.UUID):
    await lege_alarm_an(db_session, nutzer_id, is_active=False)

    assert await finde_faellige_alarme(db_session, JETZT) == []


async def test_frisch_gepruefter_alarm_wird_nicht_gefunden(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Kern der Kostenbremse: Das Intervall wird in SQL ausgewertet."""
    await lege_alarm_an(
        db_session,
        nutzer_id,
        check_interval_minutes=360,
        last_checked_at=JETZT - timedelta(minutes=359),
    )

    assert await finde_faellige_alarme(db_session, JETZT) == []


async def test_alarm_nach_ablauf_seines_intervalls_wird_gefunden(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    alert = await lege_alarm_an(
        db_session,
        nutzer_id,
        check_interval_minutes=360,
        last_checked_at=JETZT - timedelta(minutes=361),
    )

    gefunden = await finde_faellige_alarme(db_session, JETZT)

    assert [a.id for a in gefunden] == [alert.id]


async def test_jeder_alarm_hat_sein_eigenes_intervall(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Zwei Alarme, gleich lange her, unterschiedliches Intervall — nur einer ist dran."""
    haeufig = await lege_alarm_an(
        db_session,
        nutzer_id,
        check_interval_minutes=15,
        last_checked_at=JETZT - timedelta(minutes=30),
    )
    await lege_alarm_an(
        db_session,
        nutzer_id,
        destination="LIS",
        check_interval_minutes=720,
        last_checked_at=JETZT - timedelta(minutes=30),
    )

    gefunden = await finde_faellige_alarme(db_session, JETZT)

    assert [a.id for a in gefunden] == [haeufig.id]


async def test_am_laengsten_wartender_alarm_kommt_zuerst(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Bei vollem Limit darf kein Alarm dauerhaft hinten runterfallen."""
    juengst = await lege_alarm_an(db_session, nutzer_id, last_checked_at=JETZT - timedelta(hours=7))
    aeltest = await lege_alarm_an(
        db_session, nutzer_id, destination="LIS", last_checked_at=JETZT - timedelta(hours=40)
    )
    nie = await lege_alarm_an(db_session, nutzer_id, destination="OPO", last_checked_at=None)

    gefunden = await finde_faellige_alarme(db_session, JETZT)

    # Nie geprüft zuerst (NULLS FIRST), dann nach Alter.
    assert [a.id for a in gefunden] == [nie.id, aeltest.id, juengst.id]


async def test_limit_begrenzt_die_menge(db_session: AsyncSession, nutzer_id: uuid.UUID):
    for ziel in ("BCN", "LIS", "OPO"):
        await lege_alarm_an(db_session, nutzer_id, destination=ziel)

    assert len(await finde_faellige_alarme(db_session, JETZT, limit=2)) == 2


# --- Ein Lauf pro Alarm ----------------------------------------------------


async def test_lauf_schreibt_beobachtung_und_angebote(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """**Das Abnahmekriterium von M6.**"""
    alert = await lege_alarm_an(db_session, nutzer_id, max_stops=1, max_price_cents=25000)
    suche = FlugsucheAttrappe(lade_fixture_angebote())

    ergebnis = await pruefe_alarm(db_session, alert, suche, JETZT)

    # Die Fixture hat drei Angebote; eines davon hat zwei Umstiege und wird
    # schon von der Suche herausgefiltert (max_stops=1).
    assert ergebnis.angebote_gefunden == 2
    assert ergebnis.angebote_gespeichert == 2
    assert ergebnis.search_ok is True
    assert ergebnis.min_preis_cents == 18950

    beobachtet = await beobachtungen(db_session, alert.id)
    assert len(beobachtet) == 1
    assert beobachtet[0].min_price_cents == 18950
    assert beobachtet[0].offers_found == 2
    assert beobachtet[0].search_ok is True
    assert beobachtet[0].origin == "MUC"
    assert beobachtet[0].departure_month == "2026-09"

    gespeichert = await angebote(db_session, alert.id)
    assert [a.total_price_cents for a in gespeichert] == [18950, 24990]
    # Alle Angebote verweisen auf den Lauf, aus dem sie stammen.
    assert all(a.flight_observation_id == beobachtet[0].id for a in gespeichert)


async def test_lauf_stellt_die_erwartete_suchanfrage(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    alert = await lege_alarm_an(db_session, nutzer_id, adults=2, max_stops=0)
    suche = FlugsucheAttrappe([])

    await pruefe_alarm(db_session, alert, suche, JETZT)

    assert len(suche.anfragen) == 1
    anfrage = suche.anfragen[0]
    assert anfrage.origin == "MUC"
    assert anfrage.destination == "BCN"
    assert anfrage.departure_date == date(2026, 9, 6)
    assert anfrage.return_date == date(2026, 9, 13)
    assert anfrage.adults == 2
    assert anfrage.max_stops == 0


async def test_lauf_setzt_last_checked_at(db_session: AsyncSession, nutzer_id: uuid.UUID):
    alert = await lege_alarm_an(db_session, nutzer_id)
    assert alert.last_checked_at is None

    await pruefe_alarm(db_session, alert, FlugsucheAttrappe([]), JETZT)

    await db_session.refresh(alert)
    assert alert.last_checked_at == JETZT


async def test_lauf_ohne_treffer_schreibt_trotzdem_eine_beobachtung(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Ohne die langweiligen Tage gibt es später keinen brauchbaren Median."""
    alert = await lege_alarm_an(db_session, nutzer_id)

    ergebnis = await pruefe_alarm(db_session, alert, FlugsucheAttrappe([]), JETZT)

    assert ergebnis.angebote_gefunden == 0
    beobachtet = await beobachtungen(db_session, alert.id)
    assert len(beobachtet) == 1
    assert beobachtet[0].min_price_cents is None
    assert beobachtet[0].offers_found == 0
    # Die Suche selbst hat funktioniert — die Zeile zählt für die Statistik.
    assert beobachtet[0].search_ok is True


async def test_teures_angebot_zaehlt_fuer_die_statistik_wird_aber_nicht_gespeichert(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """`min_price_cents` ist der günstigste *gefundene*, nicht der günstigste passende Preis."""
    alert = await lege_alarm_an(db_session, nutzer_id, max_price_cents=15000)
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])

    ergebnis = await pruefe_alarm(db_session, alert, suche, JETZT)

    assert ergebnis.angebote_gefunden == 1
    assert ergebnis.angebote_gespeichert == 0
    assert await angebote(db_session, alert.id) == []

    beobachtet = await beobachtungen(db_session, alert.id)
    assert beobachtet[0].min_price_cents == 18950
    assert beobachtet[0].offers_found == 1


# --- Upsert ----------------------------------------------------------------


async def test_gleiches_angebot_im_zweiten_lauf_legt_keine_zweite_zeile_an(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Sonst wäre die Tabelle im 6-Stunden-Takt nach einer Woche voller Dubletten."""
    alert = await lege_alarm_an(db_session, nutzer_id)
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])

    await pruefe_alarm(db_session, alert, suche, JETZT)
    spaeter = JETZT + timedelta(hours=6)
    await pruefe_alarm(db_session, alert, suche, spaeter)

    gespeichert = await angebote(db_session, alert.id)
    assert len(gespeichert) == 1
    # Erstfund bleibt stehen, „zuletzt gesehen" wandert weiter.
    assert gespeichert[0].found_at == JETZT
    assert gespeichert[0].last_seen_at == spaeter

    # Zwei Läufe, zwei Beobachtungen — der Preisverlauf bleibt vollständig.
    assert len(await beobachtungen(db_session, alert.id)) == 2


async def test_billiger_gewordenes_angebot_ist_ein_neues_angebot(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    alert = await lege_alarm_an(db_session, nutzer_id)

    await pruefe_alarm(
        db_session, alert, FlugsucheAttrappe([baue_angebot(preis_cents=18950)]), JETZT
    )
    await pruefe_alarm(
        db_session,
        alert,
        FlugsucheAttrappe([baue_angebot(preis_cents=17900)]),
        JETZT + timedelta(hours=6),
    )

    gespeichert = await angebote(db_session, alert.id)
    assert [a.total_price_cents for a in gespeichert] == [17900, 18950]


async def test_angebot_des_einen_alarms_stoert_den_anderen_nicht(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Der UNIQUE gilt je Alarm, nicht global."""
    alert_a = await lege_alarm_an(db_session, nutzer_id)
    alert_b = await lege_alarm_an(db_session, nutzer_id, destination="LIS")
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])

    await pruefe_alarm(db_session, alert_a, suche, JETZT)
    await pruefe_alarm(db_session, alert_b, suche, JETZT)

    assert len(await angebote(db_session, alert_a.id)) == 1
    assert len(await angebote(db_session, alert_b.id)) == 1


# --- Fehlerfälle -----------------------------------------------------------


async def test_erschoepftes_kontingent_ist_kein_endgueltiger_fehler(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    alert = await lege_alarm_an(db_session, nutzer_id)
    suche = FlugsucheAttrappe(fehler=AmadeusRateLimited("Kontingent erschöpft."))

    ergebnis = await pruefe_alarm(db_session, alert, suche, JETZT)

    assert ergebnis.search_ok is False
    assert ergebnis.spaeter_erneut is True
    assert ergebnis.fehler is not None


async def test_gescheiterte_suche_wird_aus_der_statistik_herausgehalten(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Sonst würde ein API-Ausfall den Median verfälschen."""
    alert = await lege_alarm_an(db_session, nutzer_id)
    suche = FlugsucheAttrappe(fehler=AmadeusError("kaputt"))

    ergebnis = await pruefe_alarm(db_session, alert, suche, JETZT)

    assert ergebnis.spaeter_erneut is False
    beobachtet = await beobachtungen(db_session, alert.id)
    assert beobachtet[0].search_ok is False
    assert beobachtet[0].min_price_cents is None


async def test_last_checked_at_wird_auch_nach_einem_fehler_gesetzt(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Sonst bliebe der Alarm fällig und der Worker hämmerte im Minutentakt."""
    alert = await lege_alarm_an(db_session, nutzer_id)
    suche = FlugsucheAttrappe(fehler=AmadeusRateLimited("Kontingent erschöpft."))

    await pruefe_alarm(db_session, alert, suche, JETZT)

    await db_session.refresh(alert)
    assert alert.last_checked_at == JETZT
    assert await finde_faellige_alarme(db_session, JETZT) == []


# --- Kompletter Durchgang --------------------------------------------------


async def test_durchgang_prueft_alle_faelligen_alarme(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    eigene = [
        (await lege_alarm_an(db_session, nutzer_id, destination=ziel)).id
        for ziel in ("BCN", "LIS", "OPO")
    ]
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])

    bericht = await pruefe_faellige_alarme(db_session, suche, JETZT)

    # Nur die eigenen Alarme bewerten: `pruefe_faellige_alarme` arbeitet
    # bewusst über *alle* fälligen Alarme, und in einer Entwicklungsdatenbank
    # können noch andere liegen.
    ergebnisse = [e for e in bericht.ergebnisse if e.alarm_id in eigene]
    assert len(ergebnisse) == 3
    assert all(e.search_ok for e in ergebnisse)
    assert sum(e.angebote_gespeichert for e in ergebnisse) == 3

    for alarm_id in eigene:
        assert len(await beobachtungen(db_session, alarm_id)) == 1
        assert len(await angebote(db_session, alarm_id)) == 1


async def test_zweiter_durchgang_direkt_danach_macht_nichts(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Das Zusammenspiel aus `last_checked_at` und Fälligkeit — die Kostenbremse."""
    alert = await lege_alarm_an(db_session, nutzer_id)
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])

    erster = await pruefe_faellige_alarme(db_session, suche, JETZT)
    zweiter = await pruefe_faellige_alarme(db_session, suche, JETZT + timedelta(minutes=5))

    assert alert.id in [e.alarm_id for e in erster.ergebnisse]
    assert alert.id not in [e.alarm_id for e in zweiter.ergebnisse]
    # Genau eine Suchanfrage für diesen Alarm, nicht zwei.
    assert len(await beobachtungen(db_session, alert.id)) == 1


async def test_ein_kaputter_alarm_beendet_den_durchgang_nicht(
    db_session: AsyncSession, nutzer_id: uuid.UUID
):
    """Reihenfolge erzwungen über `last_checked_at`: Der kaputte kommt zuerst."""
    kaputt = await lege_alarm_an(
        db_session, nutzer_id, destination="LIS", last_checked_at=JETZT - timedelta(days=2)
    )
    gesund = await lege_alarm_an(
        db_session, nutzer_id, destination="OPO", last_checked_at=JETZT - timedelta(days=1)
    )
    # IDs vorher merken: Das `rollback()` im Fehlerfall lässt alle Objekte der
    # Session ablaufen, danach würde `gesund.id` still nachladen wollen.
    kaputt_id, gesund_id = kaputt.id, gesund.id

    class NurBeimErstenKaputt(FlugsucheAttrappe):
        async def suche(self, anfrage):  # type: ignore[no-untyped-def]
            if anfrage.destination == "LIS":
                raise RuntimeError("etwas völlig Unerwartetes")
            return await super().suche(anfrage)

    bericht = await pruefe_faellige_alarme(
        db_session, NurBeimErstenKaputt([baue_angebot(preis_cents=18950)]), JETZT
    )

    ergebnisse = {e.alarm_id: e for e in bericht.ergebnisse}
    assert ergebnisse[kaputt_id].search_ok is False
    assert ergebnisse[gesund_id].search_ok is True

    # Der gesunde Alarm wurde vollständig verarbeitet …
    assert len(await angebote(db_session, gesund_id)) == 1
    # … und der kaputte hat nichts Halbfertiges hinterlassen.
    assert await beobachtungen(db_session, kaputt_id) == []
