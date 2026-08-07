"""Interne Darstellung eines Flugangebots.

Bewusst **nicht** Amadeus' Format: Deren Antwort ist tief verschachtelt, hat
Preise als Zeichenkette und trägt viel mit, was wir nie brauchen. Alles, was
danach kommt (Bewertung, Speichern, Anzeige), soll mit dieser schlanken
Struktur arbeiten — dann berührt ein Anbieterwechsel nur
`app/services/amadeus.py`.

**Zeiten sind lokale Flughafenzeiten ohne Zeitzone.** Amadeus liefert
`"2026-09-06T09:15:00"` — ohne Offset, und der Offset ist aus der Antwort
auch nicht ableitbar. Genau so wird der Wert hier weitergereicht, statt eine
Zeitzone zu erfinden. Für die Anzeige ist das richtig (der Reisende will die
Uhrzeit am Flughafen sehen). Wer echte Zeitpunkte braucht, nimmt
`dauer_minuten` — die liefert Amadeus mit und die ist zeitzonenfrei korrekt.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Flugsegment(BaseModel):
    """Ein Flug von A nach B ohne Umsteigen."""

    von: str
    nach: str
    abflug_lokal: datetime
    ankunft_lokal: datetime
    fluggesellschaft: str  # IATA-Code, z. B. "LH"
    flugnummer: str
    dauer_minuten: int

    # Technische Zwischenlandung ohne Flugzeugwechsel (selten). Zählt für den
    # Reisenden nicht als Umstieg, ist aber ein Qualitätsmerkmal.
    zwischenlandungen: int = 0


class Teilstrecke(BaseModel):
    """Hin- oder Rückweg: ein oder mehrere Segmente hintereinander."""

    segmente: list[Flugsegment] = Field(min_length=1)
    dauer_minuten: int

    @property
    def umstiege(self) -> int:
        """Was der Nutzer als „Stopps" versteht: Segmente minus eins."""
        return len(self.segmente) - 1

    @property
    def abflug_lokal(self) -> datetime:
        return self.segmente[0].abflug_lokal

    @property
    def ankunft_lokal(self) -> datetime:
        return self.segmente[-1].ankunft_lokal

    @property
    def von(self) -> str:
        return self.segmente[0].von

    @property
    def nach(self) -> str:
        return self.segmente[-1].nach


class Flugangebot(BaseModel):
    """Ein vollständiges Angebot, so wie unsere Anwendung es sieht."""

    # Amadeus' laufende Nummer innerhalb *einer* Antwort ("1", "2", …).
    # Taugt nicht als dauerhafte Kennung — dafür kommt in M6 der `offer_hash`.
    anbieter_id: str

    preis_cents: int
    waehrung: str

    # Die Airline, die das Ticket ausstellt. Kann fehlen.
    validierende_airline: str | None = None

    hinflug: Teilstrecke
    rueckflug: Teilstrecke | None = None

    # `None` heißt **unbekannt**, nicht „null Gepäckstücke" — Amadeus gibt die
    # Angabe je nach Tarif gar nicht oder nur als Gewicht heraus. Die App zeigt
    # dann ehrlich „unbekannt", statt etwas zu behaupten.
    inkludierte_gepaeckstuecke: int | None = None

    buchbare_plaetze: int | None = None

    # Die unveränderte Rohantwort dieses einen Angebots. Beim Debuggen Gold
    # wert und in M6 der Inhalt von `flight_offers.raw_payload`. Gehört NIE
    # in eine API-Antwort an die App.
    rohdaten: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def ist_hin_und_rueckflug(self) -> bool:
        return self.rueckflug is not None

    @property
    def maximale_umstiege(self) -> int:
        """Die schlechtere der beiden Richtungen — danach filtert der Nutzer."""
        if self.rueckflug is None:
            return self.hinflug.umstiege
        return max(self.hinflug.umstiege, self.rueckflug.umstiege)
