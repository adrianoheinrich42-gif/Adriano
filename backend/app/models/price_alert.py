"""Preisalarm — die Suchbedingung eines Nutzers.

Das Herzstück des Datenmodells. Alles andere hängt hieran.

Zu den `CheckConstraint`s: Diese Regeln stehen **zusätzlich** zur Pydantic-
Validierung in der API. Warum doppelt? Weil Pydantic nur schützt, was durch
die API kommt. Ein Skript, eine Migration oder eine SQL-Konsole umgeht das.
Die Datenbank ist die letzte Verteidigungslinie.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, uuid_primary_key

if TYPE_CHECKING:
    from app.models.flight_observation import FlightObservation
    from app.models.flight_offer import FlightOffer
    from app.models.user import User


class PriceAlert(TimestampMixin, Base):
    __tablename__ = "price_alerts"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Strecke ---------------------------------------------------------
    # String(3) statt CHAR(3): CHAR füllt in Postgres mit Leerzeichen auf,
    # was bei Vergleichen überrascht. Die Länge sichert der CHECK unten.
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)

    # --- Zeitraum --------------------------------------------------------
    earliest_departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    latest_return_date: Mapped[date] = mapped_column(Date, nullable=False)
    min_trip_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_trip_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Bedingungen -----------------------------------------------------
    max_stops: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    max_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'EUR'"))
    adults: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    include_checked_bag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    avoid_night_flights: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # --- Steuerung des Prüflaufs -----------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("360"),  # 6 Stunden
    )

    user: Mapped["User"] = relationship(back_populates="price_alerts")
    observations: Mapped[list["FlightObservation"]] = relationship(
        back_populates="price_alert", cascade="all, delete-orphan"
    )
    offers: Mapped[list["FlightOffer"]] = relationship(
        back_populates="price_alert", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("origin ~ '^[A-Z]{3}$'", name="ck_alerts_origin_iata"),
        CheckConstraint("destination ~ '^[A-Z]{3}$'", name="ck_alerts_destination_iata"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_alerts_currency_iso"),
        CheckConstraint("origin <> destination", name="ck_alerts_origin_ne_destination"),
        CheckConstraint(
            "earliest_departure_date <= latest_return_date",
            name="ck_alerts_date_order",
        ),
        CheckConstraint("max_price_cents > 0", name="ck_alerts_price_positive"),
        CheckConstraint("max_stops >= 0", name="ck_alerts_stops_non_negative"),
        CheckConstraint("adults >= 1", name="ck_alerts_adults_min_one"),
        CheckConstraint(
            "min_trip_duration_days IS NULL "
            "OR max_trip_duration_days IS NULL "
            "OR min_trip_duration_days <= max_trip_duration_days",
            name="ck_alerts_duration_order",
        ),
        # Untergrenze gegen versehentliches Dauerfeuer auf die Amadeus-API.
        CheckConstraint("check_interval_minutes >= 15", name="ck_alerts_interval_min_15"),
        # Genau die Abfrage, die der Worker in Schritt 4 stellt:
        # "welche aktiven Alarme sind fällig?"
        Index("ix_price_alerts_due", "is_active", "last_checked_at"),
    )
