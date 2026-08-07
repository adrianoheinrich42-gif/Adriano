"""Preisbeobachtung — ein Datenpunkt pro Prüflauf.

Wird **immer** geschrieben, auch wenn nichts gefunden wurde oder der beste
Preis über dem Limit lag. Ohne die langweiligen Tage gibt es keinen sinnvollen
Median.

`origin`, `destination` und `departure_month` stehen hier doppelt (sie stünden
auch im zugehörigen Alarm). Das ist bewusste Denormalisierung: Nur so kann ein
brandneuer Alarm für MUC→BCN im Oktober die Beobachtungen **aller** Nutzer für
dieselbe Strecke und denselben Reisemonat nutzen, statt bei null zu starten.
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
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import uuid_primary_key

if TYPE_CHECKING:
    from app.models.price_alert import PriceAlert


class FlightObservation(Base):
    __tablename__ = "flight_observations"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    price_alert_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # NULL = in diesem Lauf wurde nichts gefunden.
    min_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'EUR'"))

    # Denormalisiert für streckenweite Statistik — siehe Modul-Docstring.
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_month: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-10"

    offers_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # false = die Amadeus-Anfrage schlug fehl. Solche Zeilen dürfen NICHT in
    # die Statistik einfließen, sonst verfälscht ein API-Ausfall den Median.
    search_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    price_alert: Mapped["PriceAlert"] = relationship(back_populates="observations")

    __table_args__ = (
        CheckConstraint(
            "min_price_cents IS NULL OR min_price_cents > 0",
            name="ck_observations_price_positive",
        ),
        CheckConstraint("offers_found >= 0", name="ck_observations_offers_non_negative"),
        CheckConstraint("origin ~ '^[A-Z]{3}$'", name="ck_observations_origin_iata"),
        CheckConstraint("destination ~ '^[A-Z]{3}$'", name="ck_observations_destination_iata"),
        CheckConstraint(
            "departure_month ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_observations_month_format"
        ),
        # Preisverlauf eines einzelnen Alarms (Detailansicht).
        Index("ix_observations_alert_time", "price_alert_id", "observed_at"),
        # Streckenweite Statistik (Median über alle Nutzer).
        Index(
            "ix_observations_route_month",
            "origin",
            "destination",
            "departure_month",
            "observed_at",
        ),
    )
