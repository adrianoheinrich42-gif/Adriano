"""Ergebnisse lesen (M9) — Angebote und Preisverlauf eines Alarms.

Reines Lesen; hier wird nichts geschrieben und nichts entschieden. Die
Bewertung kommt fertig aus `price_stats.py`, die Angebote hat der Prüflauf
abgelegt.

**Fremdes ergibt 404, nie 403** — dieselbe Regel wie beim Alarm-CRUD. Umgesetzt
dadurch, dass `user_id` in **jeder** Abfrage in der WHERE-Klausel steht, statt
nachträglich den Besitzer zu prüfen. Ein 403 verriete, dass es das Objekt gibt.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation
from app.models.flight_offer import FlightOffer
from app.models.price_alert import PriceAlert
from app.schemas.ergebnis import PreisbewertungResponse, PreisverlaufResponse, VerlaufsPunkt
from app.services.price_stats import VERGLEICHSFENSTER_TAGE, bewerte_preis, hole_vergleichspreise

# Mehr Angebote als das zeigt keine sinnvolle Oberfläche an, und die Liste
# wächst mit jedem Prüflauf.
STANDARD_LIMIT = 20


async def liste_angebote(
    session: AsyncSession,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    limit: int = STANDARD_LIMIT,
) -> list[FlightOffer] | None:
    """Die Angebote eines Alarms, günstigste zuerst.

    Gibt `None` zurück, wenn es den Alarm nicht gibt **oder** er einem anderen
    gehört — der Aufrufer macht daraus einen 404. Eine leere Liste heißt
    dagegen: Alarm existiert, hat aber noch nichts gefunden. Diese beiden Fälle
    auseinanderzuhalten ist der Grund für `| None`.
    """
    gehoert_mir = await session.execute(
        select(PriceAlert.id).where(PriceAlert.id == alert_id, PriceAlert.user_id == user_id)
    )
    if gehoert_mir.scalar_one_or_none() is None:
        return None

    ergebnis = await session.execute(
        select(FlightOffer)
        .where(FlightOffer.price_alert_id == alert_id)
        # Günstigste zuerst; bei gleichem Preis das zuletzt gesehene, denn ein
        # Angebot von heute früh ist eher noch buchbar als eines von letzter
        # Woche.
        .order_by(FlightOffer.total_price_cents, FlightOffer.last_seen_at.desc())
        .limit(limit)
    )
    return list(ergebnis.scalars().all())


async def hole_angebot(
    session: AsyncSession, user_id: uuid.UUID, offer_id: uuid.UUID
) -> FlightOffer | None:
    """Ein einzelnes Angebot — nur, wenn es zu einem eigenen Alarm gehört.

    Der Join auf `price_alerts` ist die Besitzprüfung: Ohne ihn könnte jeder
    mit einer geratenen UUID fremde Funde lesen.
    """
    ergebnis = await session.execute(
        select(FlightOffer)
        .join(PriceAlert, PriceAlert.id == FlightOffer.price_alert_id)
        .where(FlightOffer.id == offer_id, PriceAlert.user_id == user_id)
    )
    return ergebnis.scalar_one_or_none()


async def hole_verlauf(
    session: AsyncSession,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    jetzt: datetime | None = None,
    tage: int = VERGLEICHSFENSTER_TAGE,
) -> PreisverlaufResponse | None:
    """Preisverlauf und Einordnung für die Detailansicht.

    Der Verlauf zeigt **diesen einen Alarm** (was habe *ich* beobachtet?),
    die Einordnung vergleicht dagegen mit der **ganzen Strecke über alle
    Nutzer** (was ist hier üblich?). Das ist Absicht: Die Kurve soll die
    eigene Geschichte erzählen, die Bewertung braucht möglichst viele Daten.
    """
    jetzt = jetzt or datetime.now(UTC)

    gefunden = await session.execute(
        select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user_id)
    )
    alarm = gefunden.scalar_one_or_none()
    if alarm is None:
        return None

    seit = jetzt - timedelta(days=tage)

    # Ein Punkt je Tag statt je Prüflauf: `min()` über den Tag zusammengefasst.
    tag = cast(FlightObservation.observed_at, Date).label("tag")
    verlauf = await session.execute(
        select(tag, func.min(FlightObservation.min_price_cents).label("preis"))
        .where(
            FlightObservation.price_alert_id == alert_id,
            FlightObservation.search_ok.is_(True),
            FlightObservation.min_price_cents.is_not(None),
            FlightObservation.observed_at >= seit,
        )
        .group_by(tag)
        .order_by(tag)
    )
    punkte = [VerlaufsPunkt(tag=zeile.tag, min_price_cents=zeile.preis) for zeile in verlauf]

    # Der „aktuelle" Preis ist der günstigste gespeicherte Treffer — also das,
    # was der Nutzer gerade buchen könnte, nicht der letzte beobachtete
    # Tiefstpreis (der kann über dem Limit gelegen haben).
    bester = await session.execute(
        select(func.min(FlightOffer.total_price_cents)).where(
            FlightOffer.price_alert_id == alert_id
        )
    )
    aktuell: int | None = bester.scalar_one_or_none()

    bewertung = None
    if aktuell is not None:
        monat = alarm.earliest_departure_date.strftime("%Y-%m")
        # `bis` = Beginn des heutigen Tages: Verglichen wird gegen **bisher**,
        # nicht gegen jetzt. Ohne diese Grenze steckte die Beobachtung, aus der
        # der aktuelle Preis stammt, selbst im Vergleichsmaterial — und
        # „Bestpreis" käme in der Detailansicht nie zustande, weil das Minimum
        # immer schon der eigene Preis wäre. Genau das ist im Browsertest
        # aufgefallen.
        heute_beginn = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
        vergleichspreise = await hole_vergleichspreise(
            session, alarm.origin, alarm.destination, monat, jetzt, bis=heute_beginn
        )
        bewertung = PreisbewertungResponse.aus(bewerte_preis(aktuell, vergleichspreise))

    return PreisverlaufResponse(bewertung=bewertung, aktueller_preis_cents=aktuell, punkte=punkte)
