"""Anbindung an die Amadeus Flight Offers Search.

Zwei klar getrennte Hälften:

1. **Der Client** (`AmadeusClient`) — redet über HTTP, braucht Netz und
   Zugangsdaten. Das ist der Teil, der in Tests ersetzt wird.
2. **Die Normalisierung** (`normalisiere_antwort` und Helfer) — nimmt die
   fertige JSON-Antwort und macht `Flugangebot`-Objekte daraus. Reine
   Funktionen ohne Netz, ohne Zustand, ohne Datenbank. Genau deshalb lassen
   sie sich gegen eine gespeicherte Antwort testen (`tests/fixtures/`).

Zwei Eigenheiten der API, die man kennen muss:

* **`maxPrice` akzeptiert nur ganze Zahlen** in der Währung, keine Cent-
  Angabe. Wir runden deshalb ab — lieber ein paar Angebote zu wenig sehen
  als das Preislimit des Nutzers überschreiten.
* **Es gibt keinen Parameter für „höchstens N Umstiege".** Amadeus kennt nur
  `nonStop=true` (also gar keine Umstiege). Alles dazwischen müssen wir
  nach dem Abruf selbst herausfiltern.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.schemas.flight_offer import Flugangebot, Flugsegment, Teilstrecke

logger = logging.getLogger(__name__)

# Sicherheitsabstand: Ein Token, das in 30 Sekunden abläuft, holen wir lieber
# neu — sonst kippt es mitten in einer laufenden Anfrage.
_TOKEN_PUFFER_SEKUNDEN = 60


class AmadeusError(Exception):
    """Oberklasse aller Amadeus-Fehler — der Aufrufer fängt nur diese."""


class AmadeusConfigError(AmadeusError):
    """Zugangsdaten fehlen. Unser Fehler, nicht der von Amadeus."""


class AmadeusAuthError(AmadeusError):
    """Zugangsdaten wurden abgelehnt (HTTP 401)."""


class AmadeusRateLimited(AmadeusError):
    """Kontingent erschöpft (HTTP 429).

    Eigener Typ, weil der Prüflauf darauf anders reagieren muss als auf einen
    echten Fehler: nicht aufgeben, sondern später erneut versuchen.
    """


class AmadeusUnavailable(AmadeusError):
    """Netzwerkproblem oder HTTP 5xx — vorübergehend, erneut versuchbar."""


@dataclass(frozen=True)
class Suchanfrage:
    """Was gesucht werden soll — in *unseren* Begriffen, nicht in Amadeus'.

    `max_price_cents` ist wie überall im Projekt in Cent.
    """

    origin: str
    destination: str
    departure_date: date
    return_date: date | None = None
    adults: int = 1
    max_stops: int = 1
    waehrung: str = "EUR"
    max_price_cents: int | None = None
    max_ergebnisse: int = 20


class Flugsuche(Protocol):
    """Was der Rest der Anwendung von einer Flugsuche erwartet.

    Dank dieses Protokolls kann M6 einen Doppelgänger einsetzen, ohne
    Amadeus zu kennen — und ohne dass ein Test je ins Netz geht.
    """

    async def suche(self, anfrage: Suchanfrage) -> list[Flugangebot]: ...


# ---------------------------------------------------------------------------
# Normalisierung — reine Funktionen, kein Netz
# ---------------------------------------------------------------------------

_DAUER_MUSTER = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?$")


def preis_zu_cent(betrag: str) -> int:
    """`"249.90"` → `24990`.

    Über `Decimal`, nicht über `float`: `1.15 * 100` ergibt in Fließkomma-
    Arithmetik 114.99999999999999 und damit nach `int()` einen Cent zu wenig.
    Tückisch daran ist, dass es nicht jeden Betrag trifft — `249.90` geht
    zufällig gut. Deshalb gilt im ganzen Projekt „Geld immer als ganze Cent",
    umgerechnet über `Decimal`.
    """
    try:
        return int((Decimal(betrag) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise AmadeusError(f"Unlesbarer Preis von Amadeus: {betrag!r}") from exc


def dauer_zu_minuten(dauer: str) -> int:
    """ISO-8601-Dauer `"PT14H15M"` → `855` Minuten.

    Amadeus benutzt nur Tage, Stunden und Minuten. Statt eine Bibliothek für
    den vollen Standard einzubinden, deckt ein kleiner regulärer Ausdruck
    genau diesen Ausschnitt ab.
    """
    treffer = _DAUER_MUSTER.match(dauer)
    if treffer is None:
        raise AmadeusError(f"Unlesbare Dauer von Amadeus: {dauer!r}")

    tage, stunden, minuten = (int(g) if g else 0 for g in treffer.groups())
    return tage * 24 * 60 + stunden * 60 + minuten


def _zeit(wert: str) -> datetime:
    """`"2026-09-06T09:15:00"` → naives `datetime` (lokale Flughafenzeit).

    Siehe Modul-Doku von `app/schemas/flight_offer.py`: Amadeus liefert
    keinen Zeitzonen-Offset, also erfinden wir auch keinen.
    """
    try:
        return datetime.fromisoformat(wert)
    except ValueError as exc:
        raise AmadeusError(f"Unlesbare Zeitangabe von Amadeus: {wert!r}") from exc


def _segment(rohsegment: dict[str, Any]) -> Flugsegment:
    return Flugsegment(
        von=rohsegment["departure"]["iataCode"],
        nach=rohsegment["arrival"]["iataCode"],
        abflug_lokal=_zeit(rohsegment["departure"]["at"]),
        ankunft_lokal=_zeit(rohsegment["arrival"]["at"]),
        fluggesellschaft=rohsegment["carrierCode"],
        flugnummer=str(rohsegment["number"]),
        dauer_minuten=dauer_zu_minuten(rohsegment["duration"]),
        zwischenlandungen=rohsegment.get("numberOfStops", 0),
    )


def _teilstrecke(rohstrecke: dict[str, Any]) -> Teilstrecke:
    segmente = [_segment(s) for s in rohstrecke["segments"]]
    dauer = rohstrecke.get("duration")
    return Teilstrecke(
        segmente=segmente,
        # Fehlt die Gesamtdauer, summieren wir die Segmente. Das unterschlägt
        # die Umsteigezeit, ist aber besser als gar kein Wert.
        dauer_minuten=dauer_zu_minuten(dauer) if dauer else sum(s.dauer_minuten for s in segmente),
    )


def _gepaeckstuecke(rohangebot: dict[str, Any]) -> int | None:
    """Wie viele Gepäckstücke sind im Tarif enthalten?

    `None` heißt **unbekannt**. Amadeus liefert je nach Tarif entweder
    `{"quantity": 1}`, oder `{"weight": 25, "weightUnit": "KG"}`, oder gar
    nichts. Eine Gewichtsangabe lässt sich nicht in eine Stückzahl umrechnen —
    dann lieber ehrlich „unbekannt" als geraten.

    Maßgeblich ist das **erste** Segment des ersten Reisenden: Auf
    Anschlussflügen desselben Tickets gilt in aller Regel dieselbe Regel.
    """
    reisende = rohangebot.get("travelerPricings") or []
    if not reisende:
        return None

    segmente = reisende[0].get("fareDetailsBySegment") or []
    if not segmente:
        return None

    gepaeck = segmente[0].get("includedCheckedBags")
    if not isinstance(gepaeck, dict):
        return None

    menge = gepaeck.get("quantity")
    return menge if isinstance(menge, int) else None


def normalisiere_angebot(rohangebot: dict[str, Any]) -> Flugangebot:
    """Ein einzelnes Amadeus-Angebot in unsere Struktur übersetzen."""
    try:
        strecken = [_teilstrecke(s) for s in rohangebot["itineraries"]]
        if not strecken:
            raise AmadeusError("Angebot ohne Teilstrecken.")

        preis = rohangebot["price"]
        # `grandTotal` ist der Endpreis inklusive aller Gebühren; `total` kann
        # darunter liegen. Wir nehmen immer den Betrag, den der Nutzer zahlt.
        betrag = preis.get("grandTotal") or preis["total"]

        airlines = rohangebot.get("validatingAirlineCodes") or []

        return Flugangebot(
            anbieter_id=str(rohangebot.get("id", "")),
            preis_cents=preis_zu_cent(betrag),
            waehrung=preis["currency"],
            validierende_airline=airlines[0] if airlines else None,
            hinflug=strecken[0],
            rueckflug=strecken[1] if len(strecken) > 1 else None,
            inkludierte_gepaeckstuecke=_gepaeckstuecke(rohangebot),
            buchbare_plaetze=rohangebot.get("numberOfBookableSeats"),
            rohdaten=rohangebot,
        )
    except AmadeusError:
        raise
    except (KeyError, IndexError, TypeError) as exc:
        # Ein einzelnes unbrauchbares Angebot soll nicht den ganzen Prüflauf
        # kippen — `normalisiere_antwort` fängt das und überspringt es.
        raise AmadeusError(f"Angebot in unerwartetem Format: {exc}") from exc


def normalisiere_antwort(antwort: dict[str, Any]) -> list[Flugangebot]:
    """Die komplette Antwort übersetzen; kaputte Einzelangebote überspringen.

    Warum überspringen statt abbrechen: Wenn 19 von 20 Angeboten brauchbar
    sind, ist eine Benachrichtigung mit 19 Angeboten deutlich besser als gar
    keine. Das Übersprungene landet im Log.
    """
    angebote: list[Flugangebot] = []

    for rohangebot in antwort.get("data", []):
        try:
            angebote.append(normalisiere_angebot(rohangebot))
        except AmadeusError as exc:
            logger.warning("Angebot übersprungen: %s", exc)

    return angebote


def filtere_nach_umstiegen(angebote: list[Flugangebot], max_stops: int) -> list[Flugangebot]:
    """Nachträglich filtern, weil die API das nicht kann (siehe Modul-Doku)."""
    return [a for a in angebote if a.maximale_umstiege <= max_stops]


# ---------------------------------------------------------------------------
# Der HTTP-Client
# ---------------------------------------------------------------------------


class AmadeusClient:
    """Spricht mit Amadeus. Kümmert sich selbst um das Zugangstoken.

    Amadeus benutzt OAuth2 „client credentials": Erst holt man mit ID und
    Geheimnis ein Token, das rund 30 Minuten gilt, und schickt es danach bei
    jeder Anfrage mit. Wir merken es uns, statt es jedes Mal neu zu holen —
    sonst wäre jede Suche zwei Anfragen statt einer.
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        # Injizierbar, damit Tests einen `MockTransport` unterschieben können
        # und nie echtes Netz brauchen.
        self._http = http or httpx.AsyncClient(timeout=settings.amadeus_timeout_seconds)
        self._token: str | None = None
        self._token_laeuft_ab: float = 0.0
        # Ohne Sperre könnten mehrere gleichzeitige Suchen jeweils ein eigenes
        # Token holen — unnötige Anfragen gegen ein knappes Kontingent.
        self._token_sperre = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AmadeusClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # --- Token ------------------------------------------------------------

    async def _hole_token(self) -> str:
        if not self._settings.amadeus_client_id or not self._settings.amadeus_client_secret:
            raise AmadeusConfigError(
                "AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET fehlen. "
                "Zugang auf developers.amadeus.com anlegen und in die .env eintragen."
            )

        async with self._token_sperre:
            # Zweite Prüfung *innerhalb* der Sperre: Wer hier gewartet hat,
            # findet das Token womöglich schon vor.
            if self._token and time.monotonic() < self._token_laeuft_ab:
                return self._token

            try:
                antwort = await self._http.post(
                    f"{self._settings.amadeus_base_url}/v1/security/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.amadeus_client_id,
                        "client_secret": self._settings.amadeus_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise AmadeusUnavailable(f"Token nicht erreichbar: {exc}") from exc

            if antwort.status_code == 401:
                raise AmadeusAuthError("Amadeus hat die Zugangsdaten abgelehnt.")
            if antwort.status_code >= 500:
                raise AmadeusUnavailable(f"Amadeus-Token-Endpunkt: HTTP {antwort.status_code}")
            if antwort.status_code != 200:
                raise AmadeusError(f"Token-Abruf fehlgeschlagen: HTTP {antwort.status_code}")

            daten = antwort.json()
            token = str(daten["access_token"])
            gueltig = int(daten.get("expires_in", 1799))

            self._token = token
            self._token_laeuft_ab = time.monotonic() + max(gueltig - _TOKEN_PUFFER_SEKUNDEN, 0)

            logger.info("Amadeus-Token geholt, gültig für %s s", gueltig)
            return token

    async def _token_wert(self) -> str:
        if self._token and time.monotonic() < self._token_laeuft_ab:
            return self._token
        return await self._hole_token()

    # --- Suche ------------------------------------------------------------

    def _parameter(self, anfrage: Suchanfrage) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "originLocationCode": anfrage.origin,
            "destinationLocationCode": anfrage.destination,
            "departureDate": anfrage.departure_date.isoformat(),
            "adults": anfrage.adults,
            "currencyCode": anfrage.waehrung,
            "max": anfrage.max_ergebnisse,
        }

        if anfrage.return_date is not None:
            params["returnDate"] = anfrage.return_date.isoformat()

        if anfrage.max_stops == 0:
            # Der einzige Stopp-Parameter, den die API kennt.
            params["nonStop"] = "true"

        if anfrage.max_price_cents is not None:
            # Nur ganze Währungseinheiten erlaubt. Abrunden (`//`), damit wir
            # das Limit des Nutzers nie überschreiten: Aus 249,99 € wird 249 €.
            params["maxPrice"] = anfrage.max_price_cents // 100

        return params

    async def suche_roh(self, anfrage: Suchanfrage) -> dict[str, Any]:
        """Die unveränderte Amadeus-Antwort holen.

        Getrennt von `suche()`, weil zwei Stellen genau das brauchen: das
        Skript `python -m scripts.amadeus_suche --roh` zum Erzeugen einer Fixture,
        und in M6 das Wegschreiben nach `flight_offers.raw_payload`.
        """
        token = await self._token_wert()

        try:
            antwort = await self._http.get(
                f"{self._settings.amadeus_base_url}/v2/shopping/flight-offers",
                params=self._parameter(anfrage),
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise AmadeusUnavailable(f"Suche nicht erreichbar: {exc}") from exc

        if antwort.status_code == 401:
            raise AmadeusAuthError("Token abgelehnt.")
        if antwort.status_code == 429:
            raise AmadeusRateLimited("Amadeus-Kontingent erschöpft.")
        if antwort.status_code >= 500:
            raise AmadeusUnavailable(f"Amadeus-Suche: HTTP {antwort.status_code}")
        if antwort.status_code != 200:
            # Amadeus verpackt den Grund in `errors[].detail` — der gehört ins
            # Log, damit man nicht raten muss, welcher Parameter falsch war.
            raise AmadeusError(
                f"Suche fehlgeschlagen: HTTP {antwort.status_code} — {_fehlertext(antwort)}"
            )

        ergebnis: dict[str, Any] = antwort.json()
        return ergebnis

    async def suche(self, anfrage: Suchanfrage) -> list[Flugangebot]:
        """Angebote suchen, normalisieren und nach Umstiegen filtern.

        Wirft ausschließlich `AmadeusError`-Unterklassen.
        """
        angebote = normalisiere_antwort(await self.suche_roh(anfrage))
        return filtere_nach_umstiegen(angebote, anfrage.max_stops)


def _fehlertext(antwort: httpx.Response) -> str:
    try:
        fehler = antwort.json().get("errors", [])
        return "; ".join(f.get("detail", f.get("title", "?")) for f in fehler) or antwort.text[:200]
    except ValueError:
        return antwort.text[:200]
