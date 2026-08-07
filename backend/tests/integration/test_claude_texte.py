"""Claude-Texte im Zusammenspiel (M10) — echte Datenbank, **kein Netz**.

Was ohne Datenbank nicht prüfbar ist:

* Landet der erzeugte Text wirklich im Protokoll — und mit der richtigen
  Quellenangabe?
* Geht die Benachrichtigung **trotzdem** raus, wenn Claude ausfällt? Das ist
  das Abnahmekriterium für M10 aus `docs/PROJEKTPLAN.md`.
* Zeigt die Detailansicht denselben Satz, ohne dafür ein zweites Mal bei
  Anthropic anzuklopfen?

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.flight_observation import FlightObservation
from app.models.notification_log import NotificationLog
from app.models.price_alert import PriceAlert
from app.services.claude import Erklaertext
from app.services.ergebnisse import hole_verlauf
from app.services.price_stats import MINDEST_DATENPUNKTE, Einordnung, Preisbewertung
from app.services.pruflauf import bilde_offer_hash, pruefe_alarm
from app.services.push import QUELLE_BAUKASTEN, QUELLE_CLAUDE, melde_treffer, registriere_ziel
from app.services.users import get_or_create_user
from tests.attrappen import (
    FlugsucheAttrappe,
    PushVersandAttrappe,
    TexterAttrappe,
    baue_angebot,
)

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

EINSTELLUNGEN = Settings(push_abkuehlphase_stunden=6, push_mindest_verbesserung_prozent=5.0)

BEWERTUNG = Preisbewertung(
    preis_cents=18950,
    einordnung=Einordnung.GUENSTIG,
    datenpunkte=12,
    median_cents=24000,
    minimum_cents=17000,
    abweichung_prozent=-21.0,
)

CLAUDE_TEXT = Erklaertext(
    titel="MUC → BCN für 189,50 €",
    text="21 % unter dem üblichen Preis von 240 € — ein guter Moment zum Buchen.",
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


async def melde(
    session: AsyncSession,
    alarm: PriceAlert,
    versand: PushVersandAttrappe,
    texter: TexterAttrappe | None,
    preis_cents: int = 18950,
):
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
        jetzt=JETZT,
        texter=texter,
    )


async def hole_protokollzeile(session: AsyncSession, alarm: PriceAlert) -> NotificationLog:
    ergebnis = await session.execute(
        select(NotificationLog).where(NotificationLog.price_alert_id == alarm.id)
    )
    return ergebnis.scalar_one()


# --- Der Text landet im Protokoll ------------------------------------------


async def test_claude_text_wird_verschickt_und_protokolliert(
    db_session: AsyncSession, alarm: PriceAlert
):
    versand = PushVersandAttrappe()
    await registriere_ziel(db_session, alarm.user_id, "https://push.test/a", "p", "a")

    ergebnis = await melde(db_session, alarm, versand, TexterAttrappe(CLAUDE_TEXT))

    assert ergebnis.gemeldet
    assert versand.gesendet[0][1].text == CLAUDE_TEXT.text

    zeile = await hole_protokollzeile(db_session, alarm)
    assert zeile.text_quelle == QUELLE_CLAUDE
    assert zeile.body == CLAUDE_TEXT.text
    assert zeile.title == CLAUDE_TEXT.titel


async def test_ausfall_von_claude_stoppt_die_benachrichtigung_nicht(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Das Abnahmekriterium für M10 — hier über die ganze Kette.

    Claude wirft, und trotzdem: Die Push geht raus, sie enthält den
    Baukasten-Text, und das Protokoll sagt ehrlich, wer geschrieben hat.
    """
    versand = PushVersandAttrappe()
    await registriere_ziel(db_session, alarm.user_id, "https://push.test/b", "p", "a")

    ergebnis = await melde(
        db_session, alarm, versand, TexterAttrappe(fehler=TimeoutError("Anthropic antwortet nicht"))
    )

    assert ergebnis.gemeldet
    assert versand.anzahl == 1
    assert "189,50 €" in versand.gesendet[0][1].text

    zeile = await hole_protokollzeile(db_session, alarm)
    assert zeile.status == "sent"
    assert zeile.text_quelle == QUELLE_BAUKASTEN


async def test_ohne_texter_bleibt_alles_wie_in_m8(db_session: AsyncSession, alarm: PriceAlert):
    versand = PushVersandAttrappe()
    await registriere_ziel(db_session, alarm.user_id, "https://push.test/c", "p", "a")

    await melde(db_session, alarm, versand, None)

    zeile = await hole_protokollzeile(db_session, alarm)
    assert zeile.text_quelle == QUELLE_BAUKASTEN
    assert zeile.body is not None


async def test_claude_sieht_die_berechneten_zahlen(db_session: AsyncSession, alarm: PriceAlert):
    """Leitplanke 3: Claude bekommt fertige Statistik, er rechnet sie nicht aus."""
    texter = TexterAttrappe(CLAUDE_TEXT)

    await melde(db_session, alarm, PushVersandAttrappe(), texter)

    assert len(texter.fakten) == 1
    fakten = texter.fakten[0]
    assert fakten.abweichung_prozent == -21.0
    assert fakten.median_text == "240,00 €"
    assert fakten.datenpunkte == 12


async def test_nicht_zugestellte_nachricht_wird_trotzdem_festgehalten(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Gerade die *nicht* angekommene Nachricht ist beim Nachforschen interessant."""
    await melde(db_session, alarm, PushVersandAttrappe(), TexterAttrappe(CLAUDE_TEXT))

    zeile = await hole_protokollzeile(db_session, alarm)
    assert zeile.status == "failed"  # kein Gerät registriert
    assert zeile.body == CLAUDE_TEXT.text


# --- Die Detailansicht benutzt denselben Text ------------------------------


async def lege_historie_an(session: AsyncSession, alarm: PriceAlert, preis: int, anzahl: int):
    """Vergleichsmaterial anlegen — **an einem früheren Tag**.

    Der laufende Tag zählt für die Detailansicht bewusst nicht mit
    (`bis=heute_beginn`, siehe `hole_verlauf`), sonst verglichen sich die
    Zahlen gegen sich selbst. Beobachtungen von heute wären hier also
    unsichtbar, und die Einordnung fiele auf „zu wenig Daten" zurück.
    """
    for _ in range(anzahl):
        session.add(
            FlightObservation(
                price_alert_id=alarm.id,
                observed_at=JETZT - timedelta(days=1),
                min_price_cents=preis,
                currency="EUR",
                origin=alarm.origin,
                destination=alarm.destination,
                departure_month="2026-09",
                offers_found=1,
                search_ok=True,
            )
        )
    await session.commit()


async def test_detailansicht_zeigt_den_text_aus_der_meldung(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Kern der Entscheidung: **kein zweiter Claude-Aufruf** beim Anzeigen.

    Der Prüflauf hat den Satz schon geschrieben; die Detailansicht liest ihn
    nur aus dem Protokoll. Bemerkenswert daran ist, was *nicht* passiert —
    diesem Test steht überhaupt kein Texter zur Verfügung.
    """
    await lege_historie_an(db_session, alarm, 25000, MINDEST_DATENPUNKTE)

    # Der Prüflauf rechnet seine **eigene** Bewertung aus (hier: 24 % unter
    # dem Median von 250 €). Der Text muss zu diesen Zahlen passen — sonst
    # verwirft ihn die Nachprüfung zu Recht, und der Test prüfte am Ende nur
    # noch den Fallback.
    passender_text = Erklaertext(
        titel="MUC → BCN für 189,50 €",
        text="24 % unter dem üblichen Preis von 250 € — ein guter Moment zum Buchen.",
    )
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])
    await pruefe_alarm(
        db_session,
        alarm,
        suche,
        JETZT,
        versand=PushVersandAttrappe(),
        settings=EINSTELLUNGEN,
        texter=TexterAttrappe(passender_text),
    )

    verlauf = await hole_verlauf(db_session, alarm.user_id, alarm.id, JETZT)

    assert verlauf is not None
    assert verlauf.aktueller_preis_cents == 18950
    assert verlauf.erklaerung == passender_text.text
    assert verlauf.erklaerung_quelle == QUELLE_CLAUDE


async def test_ohne_meldung_formuliert_der_baukasten(db_session: AsyncSession, alarm: PriceAlert):
    """Es wurde noch nie gemeldet — die Detailansicht braucht trotzdem einen Satz."""
    await lege_historie_an(db_session, alarm, 25000, MINDEST_DATENPUNKTE)
    # Ein günstigerer Tag in der Historie, damit 189,50 € nicht der Bestpreis
    # ist — sonst prüfte der Test den Satz ohne Prozentangabe.
    await lege_historie_an(db_session, alarm, 17000, 1)

    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])
    await pruefe_alarm(db_session, alarm, suche, JETZT)  # ohne Versand, also ohne Meldung

    verlauf = await hole_verlauf(db_session, alarm.user_id, alarm.id, JETZT)

    assert verlauf is not None
    assert verlauf.erklaerung_quelle == QUELLE_BAUKASTEN
    assert verlauf.erklaerung is not None
    assert "24 % unter dem üblichen Preis" in verlauf.erklaerung
    assert "250,00 €" in verlauf.erklaerung


async def test_baukasten_text_der_meldung_wird_nicht_recycelt(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Der Push-Baukasten schreibt für den Sperrbildschirm, nicht für die Seite.

    Sein Satz beginnt mit dem Preis und endet mit „Direktflug · LH" — in der
    Detailansicht steht beides schon daneben. Deshalb wird nur ein
    **Claude**-Text wiederverwendet; für den Baukasten gibt es die eigene
    Fassung `formuliere_einordnungssatz()`.
    """
    await lege_historie_an(db_session, alarm, 25000, MINDEST_DATENPUNKTE)
    await lege_historie_an(db_session, alarm, 17000, 1)

    suche = FlugsucheAttrappe([baue_angebot(preis_cents=18950)])
    await pruefe_alarm(
        db_session,
        alarm,
        suche,
        JETZT,
        versand=PushVersandAttrappe(),
        settings=EINSTELLUNGEN,
        texter=TexterAttrappe(fehler=TimeoutError("Anthropic antwortet nicht")),
    )

    verlauf = await hole_verlauf(db_session, alarm.user_id, alarm.id, JETZT)

    assert verlauf is not None
    assert verlauf.erklaerung_quelle == QUELLE_BAUKASTEN
    assert verlauf.erklaerung is not None
    assert "Direktflug" not in verlauf.erklaerung
    assert "24 % unter dem üblichen Preis" in verlauf.erklaerung


async def test_text_einer_anderen_preisstufe_wird_nicht_wiederverwendet(
    db_session: AsyncSession, alarm: PriceAlert
):
    """Sonst stünde unter „169,00 €" ein Satz, der über 189,50 € redet."""
    await lege_historie_an(db_session, alarm, 25000, MINDEST_DATENPUNKTE)

    # Erst eine Meldung über 189,50 €, danach taucht ein günstigeres Angebot auf.
    await melde(db_session, alarm, PushVersandAttrappe(), TexterAttrappe(CLAUDE_TEXT))
    suche = FlugsucheAttrappe([baue_angebot(preis_cents=16900)])
    await pruefe_alarm(db_session, alarm, suche, JETZT)

    verlauf = await hole_verlauf(db_session, alarm.user_id, alarm.id, JETZT)

    assert verlauf is not None
    assert verlauf.aktueller_preis_cents == 16900
    assert verlauf.erklaerung != CLAUDE_TEXT.text
    assert verlauf.erklaerung_quelle == QUELLE_BAUKASTEN


async def test_ohne_treffer_gibt_es_keine_erklaerung(db_session: AsyncSession, alarm: PriceAlert):
    """Kein Preis, keine Einordnung, kein Satz — statt eines leeren Rahmens."""
    verlauf = await hole_verlauf(db_session, alarm.user_id, alarm.id, JETZT)

    assert verlauf is not None
    assert verlauf.erklaerung is None
    assert verlauf.bewertung is None
