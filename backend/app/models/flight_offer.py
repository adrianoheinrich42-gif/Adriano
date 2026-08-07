"""Konkretes Flugangebot — was die Detailansicht der App zeigt.

Ein Datensatz pro **unterschiedlichem** Angebot je Alarm. Der
`UNIQUE (price_alert_id, offer_hash)` sorgt dafür, dass ein Angebot, das in
mehreren Läufen unverändert auftaucht, nur einmal gespeichert wird — dann
wandert lediglich `last_seen_at` weiter (Upsert). Sonst würde die Tabelle bei
6-Stunden-Takt sinnlos anwachsen.

`offer_hash` wird aus Route, Daten, Airline und Preis gebildet. Ändert sich
der Preis, ist es ein neues Angebot — und damit auch wieder meldenswert.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import uuid_primary_key

if TYPE_CHECKING:
    from app.models.price_alert import PriceAlert


class FlightOffer(Base):
    __tablename__ = "flight_offers"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    price_alert_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Aus welchem Prüflauf stammt der Fund? SET NULL, damit ein Aufräumen
    # alter Beobachtungen das Angebot nicht mitreißt.
    flight_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flight_observations.id", ondelete="SET NULL"),
        nullable=True,
    )

    offer_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- Preis -----------------------------------------------------------
    total_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'EUR'"))

    # --- Flugdaten -------------------------------------------------------
    validating_airline: Mapped[str | None] = mapped_column(String(2), nullable=True)

    outbound_departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outbound_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outbound_stops: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # NULL bei Einwegflügen.
    inbound_departure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inbound_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inbound_stops: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # NULL heißt "unbekannt", nicht "null Gepäckstücke". Amadeus liefert die
    # Angabe je nach Tarif nicht mit — die App zeigt dann ehrlich "unbekannt".
    included_checked_bags: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Teilstrecken: Flugnummer, Abflug-/Ankunftsflughafen, Zeiten.
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    # Selbst gebauter Deep-Link (Google Flights o. Ä.) — Amadeus liefert
    # keine buchbare URL. Siehe Projektplan, Risiko 8.2.
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Rohantwort von Amadeus. Beim Debuggen Gold wert; gehört NIE in eine
    # API-Antwort an die App.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    found_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    price_alert: Mapped["PriceAlert"] = relationship(back_populates="offers")

    __table_args__ = (
        UniqueConstraint("price_alert_id", "offer_hash", name="uq_offers_alert_hash"),
        CheckConstraint("total_price_cents > 0", name="ck_offers_price_positive"),
        CheckConstraint("outbound_stops >= 0", name="ck_offers_outbound_stops"),
        CheckConstraint(
            "inbound_stops IS NULL OR inbound_stops >= 0", name="ck_offers_inbound_stops"
        ),
        CheckConstraint(
            "included_checked_bags IS NULL OR included_checked_bags >= 0",
            name="ck_offers_bags_non_negative",
        ),
        CheckConstraint(
            "outbound_arrival_at > outbound_departure_at", name="ck_offers_outbound_time_order"
        ),
        # Ergebnisliste eines Alarms: die neuesten Funde zuerst.
        Index("ix_offers_alert_found", "price_alert_id", "found_at"),
    )
