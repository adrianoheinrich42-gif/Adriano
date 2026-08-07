"""Die Vergleichspreis-Abfrage der Statistik (M7) mit **echter Datenbank**.

Geprüft wird genau das, was ohne Datenbank nicht prüfbar ist: Welche
`flight_observations` landen im Median und welche nicht? Falsche Antworten
darauf würden die Statistik still verfälschen — ein API-Ausfall sähe aus wie
„an dem Tag war nichts zu holen".

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation
from app.models.price_alert import PriceAlert
from app.services.price_stats import (
    MINDEST_DATENPUNKTE,
    VERGLEICHSFENSTER_TAGE,
    Einordnung,
    bewerte_angebot,
    hole_vergleichspreise,
)
from app.services.pruflauf import pruefe_alarm
from app.services.users import get_or_create_user
from tests.attrappen import FlugsucheAttrappe, baue_angebot

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
MONAT = "2026-09"


@pytest.fixture
async def nutzer_id(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


@pytest.fixture
async def alarm(db_session: AsyncSession, nutzer_id: uuid.UUID) -> PriceAlert:
    """Ein Alarm auf einer Strecke, die sonst niemand benutzt.

    Die Strecke wird je Test zufällig gewählt: `hole_vergleichspreise` fragt
    bewusst über **alle** Nutzer hinweg ab, deshalb dürfen sich Tests nicht
    über eine gemeinsame Strecke ins Gehege kommen.
    """
    alert = PriceAlert(
        user_id=nutzer_id,
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


def zufallsziel() -> str:
    """Ein zufälliger dreibuchstabiger Code — hält Tests voneinander unabhängig."""
    return uuid.uuid4().hex[:3].upper().translate(str.maketrans("0123456789", "ABCDEFGHIJ"))


async def lege_beobachtung_an(
    session: AsyncSession,
    alarm: PriceAlert,
    min_price_cents: int | None,
    observed_at: datetime = JETZT,
    search_ok: bool = True,
    ziel: str | None = None,
    monat: str = MONAT,
) -> None:
    session.add(
        FlightObservation(
            price_alert_id=alarm.id,
            observed_at=observed_at,
            min_price_cents=min_price_cents,
            currency="EUR",
            origin=alarm.origin,
            destination=ziel or alarm.destination,
            departure_month=monat,
            offers_found=1 if min_price_cents else 0,
            search_ok=search_ok,
        )
    )
    await session.commit()


# --- Was zählt in den Median? ----------------------------------------------


async def test_beobachtungen_der_strecke_werden_gefunden(
    db_session: AsyncSession, alarm: PriceAlert
):
    for preis in (19000, 20000, 21000):
        await lege_beobachtung_an(db_session, alarm, preis)

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert sorted(preise) == [19000, 20000, 21000]


async def test_gescheiterte_suchen_zaehlen_nicht(db_session: AsyncSession, alarm: PriceAlert):
    """Sonst läse sich ein Amadeus-Ausfall als „an dem Tag war nichts zu holen"."""
    await lege_beobachtung_an(db_session, alarm, 20000)
    await lege_beobachtung_an(db_session, alarm, 9900, search_ok=False)

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [20000]


async def test_laeufe_ohne_fund_zaehlen_nicht(db_session: AsyncSession, alarm: PriceAlert):
    """`min_price_cents IS NULL` ist kein Preis und darf den Median nicht verschieben."""
    await lege_beobachtung_an(db_session, alarm, 20000)
    await lege_beobachtung_an(db_session, alarm, None)

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [20000]


async def test_andere_strecke_zaehlt_nicht(db_session: AsyncSession, alarm: PriceAlert):
    await lege_beobachtung_an(db_session, alarm, 20000)
    await lege_beobachtung_an(db_session, alarm, 9900, ziel=zufallsziel())

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [20000]


async def test_anderer_reisemonat_zaehlt_nicht(db_session: AsyncSession, alarm: PriceAlert):
    """Weihnachten und September sind nicht vergleichbar."""
    await lege_beobachtung_an(db_session, alarm, 20000)
    await lege_beobachtung_an(db_session, alarm, 45000, monat="2026-12")

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [20000]


async def test_zu_alte_beobachtungen_zaehlen_nicht(db_session: AsyncSession, alarm: PriceAlert):
    """Preise von vor einem Jahr sagen wenig über heute."""
    await lege_beobachtung_an(db_session, alarm, 20000)
    await lege_beobachtung_an(
        db_session,
        alarm,
        9900,
        observed_at=JETZT - timedelta(days=VERGLEICHSFENSTER_TAGE + 1),
    )

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [20000]


async def test_bis_schneidet_die_juengsten_beobachtungen_ab(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Für die Detailansicht (M9): Sie ordnet einen gerade beobachteten Preis
    ein — läge dessen eigene Beobachtung im Vergleichsmaterial, verglichen
    sich die Zahlen gegen sich selbst und `ist_bestpreis` wäre nie wahr."""
    await lege_beobachtung_an(db_session, alarm, 20000, observed_at=JETZT - timedelta(days=1))
    await lege_beobachtung_an(db_session, alarm, 15000, observed_at=JETZT)

    preise = await hole_vergleichspreise(
        db_session, alarm.origin, alarm.destination, MONAT, JETZT, bis=JETZT
    )

    assert preise == [20000]


async def test_ohne_bis_zaehlt_alles_bis_jetzt(db_session: AsyncSession, alarm: PriceAlert):
    """Der Prüflauf braucht `bis` nicht — er fragt, bevor er selbst schreibt."""
    await lege_beobachtung_an(db_session, alarm, 20000, observed_at=JETZT - timedelta(days=1))
    await lege_beobachtung_an(db_session, alarm, 15000, observed_at=JETZT)

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert sorted(preise) == [15000, 20000]


async def test_beobachtungen_anderer_nutzer_zaehlen_mit(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Kern der Denormalisierung: Ein neuer Alarm erbt fremde Historie."""
    fremder = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    fremder_alarm = PriceAlert(
        user_id=fremder.id,
        origin=alarm.origin,
        destination=alarm.destination,
        earliest_departure_date=date(2026, 9, 6),
        latest_return_date=date(2026, 9, 13),
        max_price_cents=99000,
    )
    db_session.add(fremder_alarm)
    await db_session.commit()

    await lege_beobachtung_an(db_session, fremder_alarm, 17500)

    preise = await hole_vergleichspreise(db_session, alarm.origin, alarm.destination, MONAT, JETZT)

    assert preise == [17500]


# --- Einordnung gegen echte Daten ------------------------------------------


async def test_bewertung_gegen_ausreichende_historie(db_session: AsyncSession, alarm: PriceAlert):
    for _ in range(MINDEST_DATENPUNKTE):
        await lege_beobachtung_an(db_session, alarm, 20000)

    bewertung = await bewerte_angebot(
        db_session, 16000, alarm.origin, alarm.destination, MONAT, JETZT
    )

    assert bewertung.einordnung is Einordnung.GUENSTIG
    assert bewertung.median_cents == 20000
    assert bewertung.abweichung_prozent == -20.0


async def test_neue_strecke_hat_keine_aussage(db_session: AsyncSession, alarm: PriceAlert):
    bewertung = await bewerte_angebot(
        db_session, 16000, alarm.origin, alarm.destination, MONAT, JETZT
    )

    assert bewertung.einordnung is Einordnung.ZU_WENIG_DATEN
    assert bewertung.datenpunkte == 0


# --- Zusammenspiel mit dem Prüflauf ----------------------------------------


async def test_pruflauf_liefert_eine_bewertung_mit(db_session: AsyncSession, alarm: PriceAlert):
    """M6 und M7 zusammen: Ein Lauf ordnet seinen besten Treffer ein."""
    for _ in range(MINDEST_DATENPUNKTE):
        await lege_beobachtung_an(db_session, alarm, 25000)

    suche = FlugsucheAttrappe([baue_angebot(preis_cents=20000)])
    ergebnis = await pruefe_alarm(db_session, alarm, suche, JETZT)

    assert ergebnis.bewertung is not None
    assert ergebnis.bewertung.preis_cents == 20000
    assert ergebnis.bewertung.einordnung is Einordnung.GUENSTIG
    assert ergebnis.bewertung.median_cents == 25000


async def test_lauf_ohne_treffer_hat_keine_bewertung(db_session: AsyncSession, alarm: PriceAlert):
    ergebnis = await pruefe_alarm(db_session, alarm, FlugsucheAttrappe([]), JETZT)

    assert ergebnis.bewertung is None


async def test_zu_teurer_fund_wird_nicht_bewertet(db_session: AsyncSession, alarm: PriceAlert):
    """Eingeordnet wird der beste **Treffer**, nicht der beste Fund."""
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=99000)])

    ergebnis = await pruefe_alarm(db_session, alarm, suche, JETZT)

    assert ergebnis.angebote_gefunden == 1
    assert ergebnis.bewertung is None


async def test_eigene_beobachtung_verschiebt_den_median_nicht(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Lauf vergleicht sich nicht gegen sich selbst.

    Sonst stünde der heutige Preis im Median, gegen den er gemessen wird —
    bei knapp zehn Datenpunkten zieht das das Ergebnis Richtung „normal".
    """
    for _ in range(MINDEST_DATENPUNKTE):
        await lege_beobachtung_an(db_session, alarm, 25000)

    suche = FlugsucheAttrappe([baue_angebot(preis_cents=20000)])
    ergebnis = await pruefe_alarm(db_session, alarm, suche, JETZT)

    assert ergebnis.bewertung is not None
    # Genau MINDEST_DATENPUNKTE — die eigene, gerade geschriebene Beobachtung
    # ist nicht dabei.
    assert ergebnis.bewertung.datenpunkte == MINDEST_DATENPUNKTE
    assert ergebnis.bewertung.median_cents == 25000
