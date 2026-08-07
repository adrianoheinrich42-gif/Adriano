"""Was die Ergebnisanzeige (M9) nach draußen gibt.

Bewusst eigene Klassen statt der Datenbankmodelle: So entscheiden wir, welche
Spalten den Browser erreichen. `raw_payload` zum Beispiel bleibt drinnen — das
ist die vollständige Amadeus-Antwort und geht niemanden etwas an.

Auch hier gilt Leitplanke 1: Der Client **rechnet nichts**. Er bekommt die
fertige Einordnung („günstig", „−21 %") und zeigt sie an. Ob ein Preis gut
ist, hat `services/price_stats.py` entschieden.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.services.price_stats import Einordnung, Preisbewertung

if TYPE_CHECKING:
    from app.models.flight_offer import FlightOffer


class SegmentResponse(BaseModel):
    """Ein einzelner Flug innerhalb einer Teilstrecke."""

    von: str
    nach: str
    abflug_lokal: datetime
    ankunft_lokal: datetime
    fluggesellschaft: str
    flugnummer: str
    dauer_minuten: int


class FlightOfferResponse(BaseModel):
    """Ein konkretes Angebot.

    Zu den Zeitfeldern: Das sind **Flughafen-Ortszeiten**, die als UTC
    gespeichert wurden (siehe `ortszeit_als_utc` in `services/pruflauf.py`).
    Die Wanduhrzeit stimmt also — „09:15 ab München" ist wirklich 09:15 —,
    aber der Zeitpunkt ist es nicht. Der Client muss sie deshalb **ohne
    Zeitzonenumrechnung** anzeigen. Wer eine Dauer braucht, nimmt
    `outbound_duration_minutes` — die ist zeitzonenfrei korrekt.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    total_price_cents: int
    currency: str
    validating_airline: str | None

    outbound_departure_at: datetime
    outbound_arrival_at: datetime
    outbound_stops: int
    outbound_duration_minutes: int
    outbound_segments: list[SegmentResponse]

    inbound_departure_at: datetime | None
    inbound_arrival_at: datetime | None
    inbound_stops: int | None
    inbound_duration_minutes: int | None
    inbound_segments: list[SegmentResponse]

    included_checked_bags: int | None
    booking_url: str | None

    found_at: datetime
    last_seen_at: datetime

    @classmethod
    def aus(cls, offer: "FlightOffer") -> "FlightOfferResponse":
        """Aus der Datenbankzeile — inklusive Aufteilung der Segmente.

        `flight_offers.segments` ist **eine** flache Liste: erst Hinflug, dann
        Rückflug. Wo die Grenze liegt, sagt `outbound_stops`: Ein Hinflug mit
        einem Umstieg besteht aus zwei Segmenten, also `stops + 1`.

        Die Aufteilung passiert hier und nicht im Browser — Leitplanke 1: Der
        Client zeigt an, er rechnet nicht. Dieselbe Überlegung gilt für die
        Dauern, die aus den Segmenten summiert werden.
        """
        alle = [SegmentResponse.model_validate(s) for s in offer.segments]
        grenze = offer.outbound_stops + 1
        hin, rueck = alle[:grenze], alle[grenze:]

        return cls(
            id=offer.id,
            total_price_cents=offer.total_price_cents,
            currency=offer.currency,
            validating_airline=offer.validating_airline,
            outbound_departure_at=offer.outbound_departure_at,
            outbound_arrival_at=offer.outbound_arrival_at,
            outbound_stops=offer.outbound_stops,
            outbound_duration_minutes=sum(s.dauer_minuten for s in hin),
            outbound_segments=hin,
            inbound_departure_at=offer.inbound_departure_at,
            inbound_arrival_at=offer.inbound_arrival_at,
            inbound_stops=offer.inbound_stops,
            inbound_duration_minutes=sum(s.dauer_minuten for s in rueck) if rueck else None,
            inbound_segments=rueck,
            included_checked_bags=offer.included_checked_bags,
            booking_url=offer.booking_url,
            found_at=offer.found_at,
            last_seen_at=offer.last_seen_at,
        )


class PreisbewertungResponse(BaseModel):
    """Die Einordnung aus M7 — endlich sichtbar.

    `median_cents` und `abweichung_prozent` sind `None`, solange es zu wenige
    Datenpunkte gibt. Der Client muss diesen Fall behandeln, statt eine 0
    anzuzeigen — genau dafür sind sie `None` und nicht 0.
    """

    einordnung: Einordnung
    datenpunkte: int
    median_cents: int | None
    minimum_cents: int | None
    abweichung_prozent: float | None
    ist_bestpreis: bool

    @classmethod
    def aus(cls, bewertung: Preisbewertung) -> "PreisbewertungResponse":
        return cls(
            einordnung=bewertung.einordnung,
            datenpunkte=bewertung.datenpunkte,
            median_cents=bewertung.median_cents,
            minimum_cents=bewertung.minimum_cents,
            abweichung_prozent=bewertung.abweichung_prozent,
            ist_bestpreis=bewertung.ist_bestpreis,
        )


class VerlaufsPunkt(BaseModel):
    """Ein Tag im Preisverlauf.

    Ein Punkt je **Tag**, nicht je Prüflauf: Bei sechs Läufen täglich wären es
    sonst 540 Punkte in 90 Tagen, und die Kurve zeigte vor allem Rauschen.
    Genommen wird der Tagestiefstpreis — das ist die Zahl, die den Nutzer
    interessiert.
    """

    tag: date
    min_price_cents: int


class PreisverlaufResponse(BaseModel):
    """Alles, was die Detailansicht über die Preislage braucht."""

    # `None`, wenn es noch keinen einzigen Fund gibt — dann kann auch nichts
    # eingeordnet werden.
    bewertung: PreisbewertungResponse | None
    aktueller_preis_cents: int | None
    punkte: list[VerlaufsPunkt]

    # Der fertige deutsche Satz (M10). Bis M9 baute ihn `web/detail.js` selbst
    # zusammen — ein Riss in Leitplanke 1, denn damit bewertete der Client.
    # Jetzt kommt er fertig aus dem Backend, wahlweise von Claude formuliert.
    erklaerung: str | None = None

    # `claude` oder `baukasten`. Der Client zeigt das an, wenn Claude
    # geschrieben hat — wer einen Text von einem Sprachmodell liest, soll das
    # wissen, ohne raten zu müssen.
    erklaerung_quelle: str | None = None
