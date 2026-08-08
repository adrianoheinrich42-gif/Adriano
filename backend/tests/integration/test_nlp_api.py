"""Der Entwurfs-Endpunkt über HTTP (M11), mit **echter Datenbank**.

Der Weg, den der Browser wirklich geht — und vor allem die eine Frage, die
sich nur hier beantworten lässt: **Legt der Endpunkt wirklich keinen Alarm
an?** Das ist die Regel aus Projektplan 8.8, und sie wäre über einen
Unit-Test nicht prüfbar.

Der Auswerter wird per `dependency_overrides` durch eine Attrappe ersetzt.
**Kein Test geht ins Netz.**

Ohne erreichbare Datenbank überspringen sich diese Tests selbst.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.nlp import hole_auswerter
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.price_alert import PriceAlert
from app.services.nlp import Suchkriterien
from app.services.users import get_or_create_user
from tests.attrappen import AuswerterAttrappe
from tests.test_auth import make_settings, make_token

# Weit genug in der Zukunft, damit die Plausibilitätsprüfung nicht anspringt,
# egal wann dieser Test läuft.
HINREISE = date.today() + timedelta(days=60)
RUECKREISE = HINREISE + timedelta(days=14)

GUTE_ANTWORT = Suchkriterien(
    von="MUC",
    nach="LIS",
    frueheste_hinreise=HINREISE,
    spaeteste_rueckreise=RUECKREISE,
    hoechstpreis_euro=250,
    mindestens_tage=14,
)


@pytest.fixture
def auswerter() -> AuswerterAttrappe:
    return AuswerterAttrappe(GUTE_ANTWORT)


@pytest.fixture
async def client(
    db_session: AsyncSession, auswerter: AuswerterAttrappe
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        anthropic_api_key="sk-ant-attrappe"
    )
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[hole_auswerter] = lambda: auswerter

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def nutzer(db_session: AsyncSession) -> uuid.UUID:
    user = await get_or_create_user(db_session, uuid.uuid4(), f"{uuid.uuid4()}@beispiel.de")
    return user.id


def auth(user_id: uuid.UUID) -> dict[str, str]:
    token = make_token(user_id=str(user_id), email=f"{user_id}@beispiel.de")
    return {"Authorization": f"Bearer {token}"}


# --- Der Normalfall --------------------------------------------------------


async def test_entwurf_fuellt_die_formularfelder(client: AsyncClient, nutzer: uuid.UUID):
    antwort = await client.post(
        "/alerts/entwurf",
        json={"text": "im Oktober für zwei Wochen nach Lissabon, höchstens 250 €"},
        headers=auth(nutzer),
    )

    assert antwort.status_code == 200
    koerper = antwort.json()
    assert koerper["vollstaendig"] is True
    assert koerper["felder"]["origin"] == "MUC"
    assert koerper["felder"]["destination"] == "LIS"
    # Cent, nicht Euro: Der Client soll nur eintragen, nicht umrechnen.
    assert koerper["felder"]["max_price_cents"] == 25000
    assert koerper["felder"]["min_trip_duration_days"] == 14


async def test_der_entwurf_legt_keinen_alarm_an(
    client: AsyncClient, db_session: AsyncSession, nutzer: uuid.UUID
):
    """Die Regel aus Projektplan 8.8, als Test.

    Der wertvollste Test dieser Datei: Ein Endpunkt, der versehentlich
    speichert, sähe von außen genauso aus — bis irgendwann Alarme in der Liste
    stehen, die niemand bestätigt hat.
    """
    vorher = await db_session.execute(select(func.count()).select_from(PriceAlert))

    await client.post(
        "/alerts/entwurf", json={"text": "nach Lissabon im Oktober"}, headers=auth(nutzer)
    )

    nachher = await db_session.execute(select(func.count()).select_from(PriceAlert))
    assert nachher.scalar() == vorher.scalar()


async def test_der_entwurf_laesst_sich_direkt_anlegen(client: AsyncClient, nutzer: uuid.UUID):
    """Die Felder passen wirklich zu `POST /alerts` — nicht nur ungefähr.

    Ohne diesen Test könnte die Übersetzung einen Feldnamen verfehlen, und der
    Fehler fiele erst im Browser auf, wenn der Nutzer auf „Anlegen" drückt.
    """
    entwurf = await client.post(
        "/alerts/entwurf", json={"text": "egal, die Attrappe antwortet fest"}, headers=auth(nutzer)
    )

    angelegt = await client.post("/alerts", json=entwurf.json()["felder"], headers=auth(nutzer))

    assert angelegt.status_code == 201, angelegt.text
    assert angelegt.json()["destination"] == "LIS"


async def test_claude_bekommt_nur_den_satz(
    client: AsyncClient, nutzer: uuid.UUID, auswerter: AuswerterAttrappe
):
    """Keine Nutzer-ID, keine E-Mail — nur der Text und das heutige Datum."""
    await client.post("/alerts/entwurf", json={"text": "nach Lissabon"}, headers=auth(nutzer))

    eingabe, heute = auswerter.anfragen[0]
    assert eingabe == "nach Lissabon"
    assert str(nutzer) not in eingabe
    assert heute == date.today()


# --- Die Wege, die schiefgehen ---------------------------------------------


async def test_ohne_anmeldung_kein_entwurf(client: AsyncClient):
    """Sonst wäre das ein offener Endpunkt auf unsere Anthropic-Rechnung."""
    antwort = await client.post("/alerts/entwurf", json={"text": "nach Lissabon"})

    assert antwort.status_code == 401


async def test_ausfall_ergibt_einen_verstaendlichen_satz(
    db_session: AsyncSession, nutzer: uuid.UUID
):
    app.dependency_overrides[get_settings] = lambda: make_settings(
        anthropic_api_key="sk-ant-attrappe"
    )
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[hole_auswerter] = lambda: AuswerterAttrappe(
        fehler=TimeoutError("Anthropic antwortet nicht")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        antwort = await ac.post(
            "/alerts/entwurf", json={"text": "nach Lissabon"}, headers=auth(nutzer)
        )

    app.dependency_overrides.clear()

    assert antwort.status_code == 503
    # Der Nutzer liest den nächsten Schritt, nicht den Grund.
    assert "von Hand" in antwort.json()["detail"]


async def test_ohne_schluessel_dieselbe_antwort(db_session: AsyncSession, nutzer: uuid.UUID):
    """Für den Nutzer ist „kein Schlüssel hinterlegt" dasselbe wie „gerade weg"."""
    app.dependency_overrides[get_settings] = lambda: make_settings(anthropic_api_key="")
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        antwort = await ac.post(
            "/alerts/entwurf", json={"text": "nach Lissabon"}, headers=auth(nutzer)
        )

    app.dependency_overrides.clear()

    assert antwort.status_code == 503
    assert "von Hand" in antwort.json()["detail"]


async def test_zu_kurze_eingabe_wird_abgelehnt(client: AsyncClient, nutzer: uuid.UUID):
    antwort = await client.post("/alerts/entwurf", json={"text": "hi"}, headers=auth(nutzer))

    assert antwort.status_code == 422
