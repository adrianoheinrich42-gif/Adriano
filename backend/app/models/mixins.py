"""Wiederverwendbare Spalten-Bausteine für alle Tabellen."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_primary_key() -> Mapped[uuid.UUID]:
    """UUID-Primärschlüssel, den die Datenbank selbst erzeugt.

    `gen_random_uuid()` ist seit PostgreSQL 13 eingebaut — keine Extension nötig.
    """
    return mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """`created_at` / `updated_at` für Tabellen, die verändert werden."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Achtung: `onupdate` setzt SQLAlchemy beim UPDATE über das ORM.
    # Ein direktes `UPDATE ...` per SQL-Konsole aktualisiert die Spalte nicht.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
