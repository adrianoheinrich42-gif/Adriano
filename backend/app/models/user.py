"""Nutzer.

Diese Tabelle **spiegelt** Supabases `auth.users`. Passwörter, E-Mail-
Bestätigung und Token-Ausgabe macht Supabase — hier stehen nur die Felder,
die unsere Anwendung zusätzlich braucht.

Deshalb hat `id` keinen Standardwert: Die ID kommt aus dem JWT von Supabase.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.device_token import DeviceToken
    from app.models.price_alert import PriceAlert


class User(TimestampMixin, Base):
    __tablename__ = "users"

    # Kein server_default: Die ID stammt aus Supabase Auth.
    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    # Kostenbremse: begrenzt, wie viele Alarme ein Nutzer gleichzeitig laufen
    # lassen darf. Pro Alarm entstehen wiederkehrende Amadeus-Anfragen.
    max_active_alerts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )

    # Sperren statt löschen — Datensätze bleiben nachvollziehbar.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    price_alerts: Mapped[list["PriceAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    device_tokens: Mapped[list["DeviceToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("max_active_alerts > 0", name="ck_users_max_alerts_positive"),
    )
