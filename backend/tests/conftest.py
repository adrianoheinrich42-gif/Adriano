"""Gemeinsame Test-Fixtures.

Die Unit-Tests (`tests/test_*.py`) laufen ohne Datenbank. Die
Integrationstests in `tests/integration/` brauchen eine — sie werden
**übersprungen**, wenn keine erreichbar ist, statt fehlzuschlagen. So bleibt
`pytest` auch ohne laufenden Docker-Container grün.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings

REQUIRED_TABLES = {
    "users",
    "price_alerts",
    "flight_observations",
    "flight_offers",
    "device_tokens",
    "notification_logs",
}


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Eine Session pro Test, die am Ende **immer** zurückgerollt wird.

    Dadurch beeinflussen sich Tests nicht gegenseitig und die Datenbank
    bleibt sauber — auch wenn ein Test mittendrin scheitert.
    """
    engine = create_async_engine(get_settings().database_url)

    try:
        connection = await engine.connect()
    except Exception:
        await engine.dispose()
        pytest.skip("Keine Datenbank erreichbar — Integrationstests übersprungen.")

    try:
        # Transaktion zuerst öffnen: Ein `execute()` davor würde implizit eine
        # eigene starten und das spätere `begin()` scheitern lassen.
        transaction = await connection.begin()

        result = await connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        present = {row[0] for row in result}
        if not REQUIRED_TABLES.issubset(present):
            await transaction.rollback()
            pytest.skip("Schema fehlt — bitte zuerst 'uv run alembic upgrade head' ausführen.")

        # `join_transaction_mode="create_savepoint"`: Ein `session.commit()`
        # im getesteten Code (z. B. beim Anlegen eines Nutzers) gibt dann nur
        # einen SAVEPOINT frei, statt die äußere Transaktion zu beenden. Das
        # abschließende Rollback räumt trotzdem alles weg.
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
    finally:
        await connection.close()
        await engine.dispose()
