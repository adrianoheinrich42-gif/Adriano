"""Tests für den Health-Endpunkt.

Wichtig: Diese Tests brauchen **keine laufende Datenbank**. Die DB-Prüfung
wird über eine FastAPI-Dependency ersetzt. Genau dafür ist `database_probe`
als eigene Dependency ausgelagert.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes.health import database_probe
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_health_meldet_ok_wenn_datenbank_erreichbar(client):
    app.dependency_overrides[database_probe] = lambda: True

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["version"]


async def test_health_meldet_degraded_wenn_datenbank_weg_ist(client):
    app.dependency_overrides[database_probe] = lambda: False

    response = await client.get("/health")

    # Bewusst 200: Der Endpunkt soll auch dann antworten, wenn die DB fehlt.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
