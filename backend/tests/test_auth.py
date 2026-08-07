"""Tests für die Auth-Kette (M2) — **ohne Datenbank**.

Geprüft wird zweierlei:
  1. `decode_supabase_token` direkt: Was ist ein gültiges Token, was nicht?
  2. `GET /me` über HTTP: Kommen die richtigen Statuscodes heraus?

Es läuft kein echter Supabase-Call. Die Token für die Tests signieren wir
selbst mit einem Test-Geheimnis — genau das tut Supabase auch, nur mit einem
anderen Wert.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.config import Settings, get_settings
from app.core.security import AuthConfigError, TokenError, decode_supabase_token
from app.main import app
from app.models.user import User

TEST_SECRET = "test-geheimnis-nur-fuer-tests-mindestens-32-zeichen"
TEST_ISSUER_URL = "https://beispiel.supabase.co"
TEST_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def make_settings(**overrides: object) -> Settings:
    """Einstellungen für einen Test — nie die echte `.env` benutzen."""
    values: dict[str, object] = {
        "supabase_jwt_secret": TEST_SECRET,
        "supabase_url": TEST_ISSUER_URL,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make_token(
    *,
    secret: str = TEST_SECRET,
    user_id: str | None = str(TEST_USER_ID),
    email: str | None = "test@beispiel.de",
    audience: str = "authenticated",
    issuer: str | None = f"{TEST_ISSUER_URL}/auth/v1",
    expires_in: timedelta = timedelta(hours=1),
) -> str:
    """Baut ein Token, wie Supabase es ausstellen würde."""
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "aud": audience,
        "exp": now + expires_in,
        "iat": now,
        "role": "authenticated",
    }
    if user_id is not None:
        payload["sub"] = user_id
    if email is not None:
        payload["email"] = email
    if issuer is not None:
        payload["iss"] = issuer
    return jwt.encode(payload, secret, algorithm="HS256")


# --- 1. Die Token-Prüfung selbst ------------------------------------------


def test_gueltiges_token_liefert_nutzer_id_und_email():
    claims = decode_supabase_token(make_token(), make_settings())

    assert claims.user_id == TEST_USER_ID
    assert claims.email == "test@beispiel.de"


def test_falsches_geheimnis_wird_abgelehnt():
    # Der wichtigste Test überhaupt: ein selbst gebasteltes Token darf nicht
    # durchkommen, obwohl der Inhalt völlig plausibel aussieht.
    token = make_token(secret="ein-anderes-geheimnis-das-nicht-passt")

    with pytest.raises(TokenError):
        decode_supabase_token(token, make_settings())


def test_abgelaufenes_token_wird_abgelehnt():
    token = make_token(expires_in=timedelta(minutes=-5))

    with pytest.raises(TokenError):
        decode_supabase_token(token, make_settings())


def test_falscher_empfaenger_wird_abgelehnt():
    # `aud: "anon"` hat jeder Besucher ohne Login — das ist kein Nutzer.
    token = make_token(audience="anon")

    with pytest.raises(TokenError):
        decode_supabase_token(token, make_settings())


def test_falscher_aussteller_wird_abgelehnt():
    token = make_token(issuer="https://boese.example.com/auth/v1")

    with pytest.raises(TokenError):
        decode_supabase_token(token, make_settings())


def test_aussteller_wird_ignoriert_wenn_supabase_url_leer_ist():
    # Ohne konfigurierte URL soll die iss-Prüfung entfallen statt alles
    # abzulehnen — sonst ließe sich lokal nichts testen.
    token = make_token(issuer="https://irgendwas.example.com/auth/v1")

    claims = decode_supabase_token(token, make_settings(supabase_url=""))

    assert claims.user_id == TEST_USER_ID


def test_token_ohne_sub_wird_abgelehnt():
    with pytest.raises(TokenError):
        decode_supabase_token(make_token(user_id=None), make_settings())


def test_sub_das_keine_uuid_ist_wird_abgelehnt():
    with pytest.raises(TokenError):
        decode_supabase_token(make_token(user_id="nicht-uuid"), make_settings())


def test_kaputtes_token_wird_abgelehnt():
    with pytest.raises(TokenError):
        decode_supabase_token("das.ist.keintoken", make_settings())


def test_fehlendes_geheimnis_meldet_konfigurationsfehler():
    # Kein TokenError: Das Backend ist falsch eingerichtet, nicht der Aufrufer.
    with pytest.raises(AuthConfigError):
        decode_supabase_token(make_token(), make_settings(supabase_jwt_secret=""))


# --- 2. Der Endpunkt GET /me ----------------------------------------------


@pytest.fixture
async def client():
    # Absichtlich `lambda`: FastAPI liest die Signatur der Override-Funktion
    # und würde `**overrides` von `make_settings` als Query-Parameter deuten.
    app.dependency_overrides[get_settings] = lambda: make_settings()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_me_ohne_token_gibt_401(client):
    response = await client.get("/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_mit_ungueltigem_token_gibt_401(client):
    response = await client.get("/me", headers={"Authorization": "Bearer kaputt"})

    assert response.status_code == 401


async def test_me_mit_fremd_signiertem_token_gibt_401(client):
    token = make_token(secret="fremdes-geheimnis-aus-einer-anderen-app")

    response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    # Der Grund darf nicht verraten werden.
    assert "Signatur" not in response.json()["detail"]


async def test_me_ohne_konfiguriertes_geheimnis_gibt_500(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(supabase_jwt_secret="")

    response = await client.get("/me", headers={"Authorization": f"Bearer {make_token()}"})

    assert response.status_code == 500


async def test_me_liefert_die_nutzerdaten(client):
    # Die Datenbank-Anbindung wird hier ersetzt — der eigentliche Upsert ist
    # in `tests/integration/test_auth_flow.py` mit echter Datenbank geprüft.
    now = datetime.now(UTC)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=TEST_USER_ID,
        email="test@beispiel.de",
        max_active_alerts=5,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    response = await client.get("/me", headers={"Authorization": f"Bearer {make_token()}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(TEST_USER_ID)
    assert body["email"] == "test@beispiel.de"
    assert body["max_active_alerts"] == 5
