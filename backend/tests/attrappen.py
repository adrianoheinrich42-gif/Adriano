"""Doppelgänger und Baukästen für Tests.

Hier steht, was mehrere Testdateien brauchen: die Attrappe der Flugsuche und
kleine Hilfsfunktionen, die einen Alarm oder ein Angebot zusammenbauen.

**Kein Test geht ins Netz.** Genau dafür gibt es das Protokoll `Flugsuche` in
`services/amadeus.py`: Der Prüflauf bekommt „irgendetwas, das suchen kann"
herein — im Betrieb den `AmadeusClient`, im Test die Attrappe hier.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.models.device_token import DeviceToken
from app.models.price_alert import PriceAlert
from app.schemas.flight_offer import Flugangebot, Flugsegment, Teilstrecke
from app.services.amadeus import (
    Suchanfrage,
    filtere_nach_umstiegen,
    normalisiere_antwort,
)
from app.services.claude import Erklaerfakten, Erklaertext
from app.services.nlp import Suchkriterien
from app.services.push import Nachricht

FIXTURE = Path(__file__).parent / "fixtures" / "amadeus_flight_offers_muc_bcn.json"


class FlugsucheAttrappe:
    """Verhält sich wie eine Flugsuche, redet aber mit niemandem.

    Merkt sich alle gestellten Anfragen (`self.anfragen`) — so lässt sich
    prüfen, dass der Prüflauf die *richtige* Suche stellt, nicht nur
    irgendeine.

    Filtert wie der echte Client nach Umstiegen. Das ist wichtig, damit ein
    Test nicht grün wird, nur weil die Attrappe großzügiger ist als Amadeus.
    """

    def __init__(
        self,
        angebote: list[Flugangebot] | None = None,
        fehler: Exception | None = None,
    ) -> None:
        self._angebote = angebote if angebote is not None else []
        self._fehler = fehler
        self.anfragen: list[Suchanfrage] = []

    async def suche(self, anfrage: Suchanfrage) -> list[Flugangebot]:
        self.anfragen.append(anfrage)
        if self._fehler is not None:
            raise self._fehler
        return filtere_nach_umstiegen(self._angebote, anfrage.max_stops)


def lade_fixture_angebote() -> list[Flugangebot]:
    """Die gespeicherte Amadeus-Antwort als fertige `Flugangebot`-Liste.

    Herkunft der Datei: `tests/fixtures/README.md` lesen — sie ist nachgebaut,
    nicht mitgeschnitten.
    """
    rohantwort: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return normalisiere_antwort(rohantwort)


def baue_alarm(**overrides: Any) -> PriceAlert:
    """Ein `PriceAlert` mit sinnvollen Standardwerten.

    Wichtig für Tests **ohne** Datenbank: Die Spalten-Standardwerte sind
    `server_default`, sie entstehen also erst beim INSERT. Ein frisch
    erzeugtes Objekt hätte dort sonst überall `None`.
    """
    daten: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "origin": "MUC",
        "destination": "BCN",
        "earliest_departure_date": date(2026, 9, 6),
        "latest_return_date": date(2026, 9, 13),
        "min_trip_duration_days": None,
        "max_trip_duration_days": None,
        "max_stops": 1,
        "max_price_cents": 25000,
        "currency": "EUR",
        "adults": 1,
        "include_checked_bag": False,
        "avoid_night_flights": False,
        "is_active": True,
        "last_checked_at": None,
        "check_interval_minutes": 360,
    }
    daten.update(overrides)
    return PriceAlert(**daten)


def baue_segment(
    von: str = "MUC",
    nach: str = "BCN",
    abflug: datetime | None = None,
    dauer_minuten: int = 130,
    fluggesellschaft: str = "LH",
    flugnummer: str = "1810",
) -> Flugsegment:
    abflug = abflug or datetime(2026, 9, 6, 9, 15)
    return Flugsegment(
        von=von,
        nach=nach,
        abflug_lokal=abflug,
        ankunft_lokal=abflug + timedelta(minutes=dauer_minuten),
        fluggesellschaft=fluggesellschaft,
        flugnummer=flugnummer,
        dauer_minuten=dauer_minuten,
    )


def baue_angebot(
    preis_cents: int = 18950,
    waehrung: str = "EUR",
    mit_rueckflug: bool = True,
    segmente: list[Flugsegment] | None = None,
    gepaeckstuecke: int | None = 1,
    airline: str | None = "LH",
) -> Flugangebot:
    """Ein `Flugangebot` von Hand — für Fälle, die in der Fixture fehlen."""
    hinsegmente = segmente or [baue_segment()]
    hinflug = Teilstrecke(
        segmente=hinsegmente,
        dauer_minuten=sum(s.dauer_minuten for s in hinsegmente),
    )

    rueckflug = None
    if mit_rueckflug:
        ruecksegment = baue_segment(
            von="BCN", nach="MUC", abflug=datetime(2026, 9, 13, 12, 0), flugnummer="1811"
        )
        rueckflug = Teilstrecke(segmente=[ruecksegment], dauer_minuten=ruecksegment.dauer_minuten)

    return Flugangebot(
        anbieter_id="1",
        preis_cents=preis_cents,
        waehrung=waehrung,
        validierende_airline=airline,
        hinflug=hinflug,
        rueckflug=rueckflug,
        inkludierte_gepaeckstuecke=gepaeckstuecke,
        rohdaten={"id": "1", "price": {"grandTotal": f"{preis_cents / 100:.2f}"}},
    )


class PushVersandAttrappe:
    """Verhält sich wie der Web-Push-Versand, schickt aber nichts.

    Merkt sich alle Zustellungen (`self.gesendet`) als Paare aus Endpoint und
    Nachricht — so lässt sich prüfen, **was** an **wen** ging, nicht nur, dass
    irgendetwas passiert ist.

    `fehler_fuer` bildet einzelne Endpoints auf einen Fehler ab. Damit lässt
    sich der wichtigste Fall nachstellen: Ein Gerät antwortet mit 410
    („Erlaubnis entzogen"), ein zweites nimmt die Nachricht an — und nur das
    erste darf danach stillgelegt sein.
    """

    def __init__(self, fehler_fuer: dict[str, Exception] | None = None) -> None:
        self.gesendet: list[tuple[str, Nachricht]] = []
        self._fehler_fuer = fehler_fuer or {}

    async def sende(self, ziel: DeviceToken, nachricht: Nachricht) -> None:
        fehler = self._fehler_fuer.get(ziel.endpoint)
        if fehler is not None:
            raise fehler
        self.gesendet.append((ziel.endpoint, nachricht))

    @property
    def anzahl(self) -> int:
        return len(self.gesendet)


class TexterAttrappe:
    """Verhält sich wie Claude, redet aber mit niemandem.

    Die wichtigste Testhilfe für M10 ist nicht der Erfolgsfall, sondern
    `fehler`: Damit lässt sich der Ausfall des Anthropic-Aufrufs nachstellen
    und belegen, dass die Benachrichtigung **trotzdem** rausgeht — Leitplanke 3
    („fällt Claude aus, funktioniert die Kernfunktion per Fallback weiter").

    Merkt sich alle Anfragen (`self.fakten`), damit prüfbar ist, *was* Claude
    zu sehen bekommt — insbesondere, dass keine Nutzerdaten dabei sind.
    """

    def __init__(
        self,
        antwort: Erklaertext | None = None,
        fehler: Exception | None = None,
    ) -> None:
        self.antwort = antwort or Erklaertext(
            titel="MUC → BCN für 189,50 €",
            text="Ein guter Fund: 189,50 € liegen deutlich unter deinem Limit.",
        )
        self._fehler = fehler
        self.fakten: list[Erklaerfakten] = []

    async def erklaere(self, fakten: Erklaerfakten) -> Erklaertext:
        self.fakten.append(fakten)
        if self._fehler is not None:
            raise self._fehler
        return self.antwort


class AuswerterAttrappe:
    """Verhält sich wie Claudes Sprachverständnis, redet aber mit niemandem.

    Merkt sich Eingabe und Datum (`self.anfragen`) — so lässt sich prüfen,
    dass das **heutige Datum wirklich mitgeschickt** wird. Ohne das kann kein
    Modell „im Oktober" auflösen, und der Alarm landet im falschen Jahr.
    """

    def __init__(
        self,
        antwort: Suchkriterien | None = None,
        fehler: Exception | None = None,
    ) -> None:
        self.antwort = antwort or Suchkriterien()
        self._fehler = fehler
        self.anfragen: list[tuple[str, date]] = []

    async def werte_aus(self, eingabe: str, heute: date) -> Suchkriterien:
        self.anfragen.append((eingabe, heute))
        if self._fehler is not None:
            raise self._fehler
        return self.antwort


# Ein echt aussehender Schlüssel (65 Byte base64url) — nur als Testdatum.
P256DH_BEISPIEL = (
    "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM="
)


def baue_subscription(
    endpoint: str = "https://push.beispiel.test/abc",
    p256dh: str = P256DH_BEISPIEL,
    auth: str = "tBHItJI5svbpez7KI4CCXg==",
) -> dict[str, object]:
    """Das JSON, das der Browser bei `subscription.toJSON()` ausspuckt."""
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": p256dh, "auth": auth}}
