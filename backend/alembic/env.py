"""Alembic-Konfiguration (asynchron, passend zu asyncpg).

Zwei Dinge weichen von der Standardvorlage ab:

1. Die Datenbank-URL kommt aus `app.config`, nicht aus `alembic.ini`.
   So steht kein Passwort in einer versionierten Datei.
2. `import app.models` ist zwingend — dadurch kennt `Base.metadata` alle
   Tabellen. Ohne diesen Import erzeugt `alembic revision --autogenerate`
   klaglos eine leere Migration.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  — registriert alle Modelle in Base.metadata
from alembic import context
from app.config import get_settings
from app.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Das doppelte %% ist kein Tippfehler: ConfigParser interpretiert ein
# einzelnes % als Platzhalter. Passwörter mit % würden sonst crashen.
_url = get_settings().database_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", _url)

target_metadata = Base.metadata


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        # Spaltentyp-Änderungen erkennen (Alembic tut das sonst nicht).
        compare_type=True,
        # Änderungen an Standardwerten erkennen.
        compare_server_default=True,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` — erzeugt SQL, ohne die DB zu berühren."""
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
