"""Auth-Kette mit **echter Datenbank** (M2).

Hier wird geprüft, was ohne Datenbank nicht prüfbar ist: dass beim ersten
authentifizierten Request wirklich eine `users`-Zeile entsteht, dass ein
zweiter Request keine zweite Zeile anlegt und dass `GET /me` von vorn bis
hinten funktioniert.

Ohne erreichbare Datenbank überspringen sich diese Tests selbst (Fixture
`db_session` in `tests/conftest.py`).
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.user import User
from app.services.users import get_or_create_user
from tests.test_auth import make_settings, make_token


@pytest.fixture
def neue_user_id() -> uuid.UUID:
    """Frische ID pro Test — die Tests stören sich so nicht gegenseitig."""
    return uuid.uuid4()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """API-Client, der auf der Test-Session arbeitet.

    Wichtig: Der Endpunkt bekommt genau die Session der Fixture. Alles, was
    er schreibt, hängt damit an deren Transaktion und wird am Testende
    zurückgerollt — die Datenbank bleibt sauber.
    """
    # `lambda`, siehe Hinweis in tests/test_auth.py.
    app.dependency_overrides[get_settings] = lambda: make_settings()
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_erster_aufruf_legt_den_nutzer_an(db_session: AsyncSession, neue_user_id):
    user = await get_or_create_user(db_session, neue_user_id, "neu@beispiel.de")

    assert user.id == neue_user_id
    assert user.email == "neu@beispiel.de"
    # Standardwerte kommen aus der Datenbank, nicht aus Python.
    assert user.max_active_alerts == 5
    assert user.is_active is True


async def test_zweiter_aufruf_legt_keine_zweite_zeile_an(db_session: AsyncSession, neue_user_id):
    await get_or_create_user(db_session, neue_user_id, "erst@beispiel.de")
    await get_or_create_user(db_session, neue_user_id, "erst@beispiel.de")

    treffer = await db_session.execute(select(User).where(User.id == neue_user_id))
    assert len(treffer.scalars().all()) == 1


async def test_geaenderte_email_wird_uebernommen(db_session: AsyncSession, neue_user_id):
    await get_or_create_user(db_session, neue_user_id, "alt@beispiel.de")

    user = await get_or_create_user(db_session, neue_user_id, "neu@beispiel.de")

    assert user.email == "neu@beispiel.de"


async def test_me_legt_den_nutzer_an_und_gibt_ihn_zurueck(
    client: AsyncClient, db_session: AsyncSession, neue_user_id
):
    token = make_token(user_id=str(neue_user_id), email="frisch@beispiel.de")

    response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["id"] == str(neue_user_id)

    # Gegenprobe direkt in der Datenbank — nicht nur der Antwort glauben.
    in_db = await db_session.get(User, neue_user_id)
    assert in_db is not None
    assert in_db.email == "frisch@beispiel.de"


async def test_gesperrter_nutzer_bekommt_403(
    client: AsyncClient, db_session: AsyncSession, neue_user_id
):
    await get_or_create_user(db_session, neue_user_id, "gesperrt@beispiel.de")
    user = await db_session.get(User, neue_user_id)
    assert user is not None
    user.is_active = False
    await db_session.flush()

    token = make_token(user_id=str(neue_user_id), email="gesperrt@beispiel.de")
    response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
