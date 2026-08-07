"""Tests des Amadeus-Clients — **ohne echtes Netz**.

`httpx.MockTransport` fängt jede Anfrage ab und antwortet aus dem Test heraus.
Dadurch lässt sich prüfen, was der Client *tatsächlich* verschickt (Parameter,
Header) und wie er auf Fehlerantworten reagiert — ohne Zugangsdaten und ohne
das Amadeus-Kontingent zu verbrauchen.
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.services.amadeus import (
    AmadeusAuthError,
    AmadeusClient,
    AmadeusConfigError,
    AmadeusError,
    AmadeusRateLimited,
    AmadeusUnavailable,
    Suchanfrage,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "amadeus_flight_offers_muc_bcn.json").read_text(
        encoding="utf-8"
    )
)

ANFRAGE = Suchanfrage(
    origin="MUC",
    destination="BCN",
    departure_date=date(2026, 9, 6),
    return_date=date(2026, 9, 13),
)


def make_settings(**overrides: object) -> Settings:
    werte: dict[str, object] = {
        "amadeus_client_id": "test-id",
        "amadeus_client_secret": "test-geheimnis",
        "amadeus_base_url": "https://test.example.com",
    }
    werte.update(overrides)
    return Settings(**werte)  # type: ignore[arg-type]


class Aufzeichnung:
    """Merkt sich alle Anfragen und beantwortet sie nach Vorgabe."""

    def __init__(
        self,
        such_status: int = 200,
        such_body: dict | None = None,
        token_status: int = 200,
        token_gueltig_s: int = 1799,
    ) -> None:
        self.anfragen: list[httpx.Request] = []
        self._such_status = such_status
        self._such_body = such_body if such_body is not None else FIXTURE
        self._token_status = token_status
        self._token_gueltig_s = token_gueltig_s

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.anfragen.append(request)

        if request.url.path.endswith("/oauth2/token"):
            if self._token_status != 200:
                return httpx.Response(self._token_status, json={"error": "abgelehnt"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{len(self.token_anfragen)}",
                    "token_type": "Bearer",
                    "expires_in": self._token_gueltig_s,
                },
            )

        return httpx.Response(self._such_status, json=self._such_body)

    @property
    def token_anfragen(self) -> list[httpx.Request]:
        return [r for r in self.anfragen if r.url.path.endswith("/oauth2/token")]

    @property
    def such_anfragen(self) -> list[httpx.Request]:
        return [r for r in self.anfragen if "flight-offers" in r.url.path]


def make_client(aufzeichnung: Aufzeichnung, **settings_overrides: object) -> AmadeusClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(aufzeichnung))
    return AmadeusClient(make_settings(**settings_overrides), http=http)


# --- Zugangsdaten und Token -----------------------------------------------


async def test_fehlende_zugangsdaten_melden_konfigurationsfehler():
    client = make_client(Aufzeichnung(), amadeus_client_id="", amadeus_client_secret="")

    with pytest.raises(AmadeusConfigError, match="AMADEUS_CLIENT_ID"):
        await client.suche(ANFRAGE)

    await client.aclose()


async def test_token_wird_nur_einmal_geholt_und_wiederverwendet():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(ANFRAGE)
        await client.suche(ANFRAGE)

    # Zwei Suchen, aber nur *ein* Token-Abruf — sonst wäre jede Suche zwei
    # Anfragen gegen ein knappes Kontingent.
    assert len(aufzeichnung.token_anfragen) == 1
    assert len(aufzeichnung.such_anfragen) == 2


async def test_abgelaufenes_token_wird_erneuert():
    # `expires_in` kleiner als der Sicherheitspuffer → gilt sofort als abgelaufen.
    aufzeichnung = Aufzeichnung(token_gueltig_s=1)
    async with make_client(aufzeichnung) as client:
        await client.suche(ANFRAGE)
        await client.suche(ANFRAGE)

    assert len(aufzeichnung.token_anfragen) == 2


async def test_token_wird_als_bearer_mitgeschickt():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(ANFRAGE)

    assert aufzeichnung.such_anfragen[0].headers["Authorization"] == "Bearer token-1"


async def test_abgelehnte_zugangsdaten_geben_authfehler():
    aufzeichnung = Aufzeichnung(token_status=401)
    async with make_client(aufzeichnung) as client:
        with pytest.raises(AmadeusAuthError):
            await client.suche(ANFRAGE)


# --- Parameter -------------------------------------------------------------


def params(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


async def test_suchparameter_werden_richtig_gesetzt():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(ANFRAGE)

    p = params(aufzeichnung.such_anfragen[0])
    assert p["originLocationCode"] == "MUC"
    assert p["destinationLocationCode"] == "BCN"
    assert p["departureDate"] == "2026-09-06"
    assert p["returnDate"] == "2026-09-13"
    assert p["adults"] == "1"
    assert p["currencyCode"] == "EUR"


async def test_einwegflug_schickt_kein_rueckflugdatum():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(
            Suchanfrage(origin="MUC", destination="BCN", departure_date=date(2026, 9, 6))
        )

    assert "returnDate" not in params(aufzeichnung.such_anfragen[0])


async def test_nonstop_nur_bei_null_umstiegen():
    # Amadeus kennt keinen "höchstens N Umstiege"-Parameter, nur nonStop.
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(Suchanfrage("MUC", "BCN", date(2026, 9, 6), max_stops=0))
        await client.suche(Suchanfrage("MUC", "BCN", date(2026, 9, 6), max_stops=1))

    assert params(aufzeichnung.such_anfragen[0])["nonStop"] == "true"
    assert "nonStop" not in params(aufzeichnung.such_anfragen[1])


async def test_maxpreis_wird_auf_ganze_euro_abgerundet():
    # 249,99 € → 249, nicht 250. Aufrunden würde das Limit des Nutzers
    # überschreiten; die API akzeptiert ohnehin keine Nachkommastellen.
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(Suchanfrage("MUC", "BCN", date(2026, 9, 6), max_price_cents=24999))

    assert params(aufzeichnung.such_anfragen[0])["maxPrice"] == "249"


async def test_ohne_preisgrenze_wird_maxprice_weggelassen():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        await client.suche(ANFRAGE)

    assert "maxPrice" not in params(aufzeichnung.such_anfragen[0])


# --- Ergebnis und Fehler ---------------------------------------------------


async def test_ergebnis_ist_normalisiert_und_gefiltert():
    aufzeichnung = Aufzeichnung()
    async with make_client(aufzeichnung) as client:
        angebote = await client.suche(ANFRAGE)  # max_stops = 1 (Standard)

    # Angebot 3 hat zwei Umstiege und fällt raus — die API konnte das nicht.
    assert [a.anbieter_id for a in angebote] == ["1", "2"]
    assert angebote[0].preis_cents == 24990


@pytest.mark.parametrize(
    "status,fehler",
    [
        (401, AmadeusAuthError),
        (429, AmadeusRateLimited),
        (500, AmadeusUnavailable),
        (503, AmadeusUnavailable),
        (400, AmadeusError),
    ],
)
async def test_fehlerantworten_werden_in_eigene_typen_uebersetzt(status, fehler):
    aufzeichnung = Aufzeichnung(such_status=status, such_body={"errors": [{"detail": "kaputt"}]})
    async with make_client(aufzeichnung) as client:
        with pytest.raises(fehler):
            await client.suche(ANFRAGE)


async def test_netzwerkfehler_gilt_als_voruebergehend():
    def wirft(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1799})
        raise httpx.ConnectError("kein Netz")

    http = httpx.AsyncClient(transport=httpx.MockTransport(wirft))
    async with AmadeusClient(make_settings(), http=http) as client:
        with pytest.raises(AmadeusUnavailable):
            await client.suche(ANFRAGE)
