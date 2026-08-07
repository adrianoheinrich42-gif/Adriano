"""Datenbank-Anbindung (SQLAlchemy 2.0, async).

In M0 gibt es noch keine Tabellen — hier steht nur die Verbindung und eine
Prüffunktion für den Health-Endpunkt. Die Tabellen kommen in M1 per Alembic.
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Basisklasse aller Tabellen-Modelle (ab M1)."""


def _build_engine() -> AsyncEngine:
    settings = get_settings()

    connect_args: dict[str, object] = {}
    if settings.database_disable_statement_cache:
        # Nötig hinter dem Supabase-Pooler im Transaction-Modus.
        connect_args["statement_cache_size"] = 0

    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,  # tote Verbindungen automatisch aussortieren
        connect_args=connect_args,
    )


engine: AsyncEngine = _build_engine()

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI-Dependency: eine Session pro Request."""
    async with SessionFactory() as session:
        yield session


async def is_database_reachable() -> bool:
    """Ein billiger `SELECT 1`, um die Verbindung zu prüfen.

    Wirft nie — der Health-Endpunkt soll auch dann antworten, wenn die
    Datenbank gerade weg ist.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — hier ist Auffangen gewollt
        logger.warning("Datenbank nicht erreichbar: %s", type(exc).__name__)
        return False
    return True
