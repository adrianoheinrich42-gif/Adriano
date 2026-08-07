"""APNs-Gerätetoken.

Die Spalte `environment` ist kein Luxus: Ein Token aus einem Xcode-Debug-Build
funktioniert **ausschließlich** gegen den APNs-Sandbox-Server, ein Token aus
einem TestFlight-/App-Store-Build ausschließlich gegen Produktion. Wer das
mischt, bekommt `BadDeviceToken` und sucht stundenlang am falschen Ende.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import uuid_primary_key

if TYPE_CHECKING:
    from app.models.user import User


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Ein Gerät kann den Besitzer wechseln, deshalb global eindeutig.
    token: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    platform: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'ios'"))
    environment: Mapped[str] = mapped_column(String(12), nullable=False)  # sandbox|production
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Auf false setzen, wenn APNs mit 410 "Unregistered" antwortet.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="device_tokens")

    __table_args__ = (
        # Textspalte + CHECK statt PostgreSQL-ENUM: Ein neuer Wert ist dann
        # eine simple Migration statt eines ALTER TYPE.
        CheckConstraint("environment IN ('sandbox', 'production')", name="ck_tokens_environment"),
        CheckConstraint("platform IN ('ios')", name="ck_tokens_platform"),
        # Der Worker holt vor jedem Versand die aktiven Tokens eines Nutzers.
        Index("ix_tokens_user_active", "user_id", "is_active"),
    )
