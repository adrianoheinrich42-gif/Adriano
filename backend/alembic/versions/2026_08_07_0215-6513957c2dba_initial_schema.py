"""Initiales Schema — die sechs Tabellen des MVP.

Erzeugt die vollständige Struktur aus Abschnitt 3 des Projektplans:
users, price_alerts, flight_observations, flight_offers, device_tokens
und notification_logs — samt Fremdschlüsseln, CHECK-Constraints und den
Indizes, die der Worker und die Ergebnisliste brauchen.

Zwei Dinge, die hier drinstecken und später tragend sind:
  * UNIQUE auf notification_logs.dedupe_key — der Schutz vor doppelten
    Push-Benachrichtigungen, garantiert von der Datenbank.
  * ON DELETE CASCADE ab users — damit "Konto löschen" wirklich alles
    entfernt (DSGVO).

Diese Datei wurde mit `alembic revision --autogenerate` erzeugt und geprüft.
Migrationen werden nach dem Anwenden **nicht mehr bearbeitet** — Änderungen
kommen immer als neue Revision.

Revision ID: 6513957c2dba
Revises:
Erstellt: 2026-08-07 02:15:48.915185+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6513957c2dba"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # von Alembic erzeugt, geprüft und angewendet
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("max_active_alerts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("max_active_alerts > 0", name="ck_users_max_alerts_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=200), nullable=False),
        sa.Column(
            "platform", sa.String(length=10), server_default=sa.text("'ios'"), nullable=False
        ),
        sa.Column("environment", sa.String(length=12), nullable=False),
        sa.Column("app_version", sa.String(length=20), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox', 'production')", name="ck_tokens_environment"
        ),
        sa.CheckConstraint("platform IN ('ios')", name="ck_tokens_platform"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(
        "ix_tokens_user_active", "device_tokens", ["user_id", "is_active"], unique=False
    )
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("earliest_departure_date", sa.Date(), nullable=False),
        sa.Column("latest_return_date", sa.Date(), nullable=False),
        sa.Column("min_trip_duration_days", sa.Integer(), nullable=True),
        sa.Column("max_trip_duration_days", sa.Integer(), nullable=True),
        sa.Column("max_stops", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'EUR'"), nullable=False),
        sa.Column("adults", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "include_checked_bag", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "avoid_night_flights", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "check_interval_minutes", sa.Integer(), server_default=sa.text("360"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_alerts_currency_iso"),
        sa.CheckConstraint("destination ~ '^[A-Z]{3}$'", name="ck_alerts_destination_iata"),
        sa.CheckConstraint("origin ~ '^[A-Z]{3}$'", name="ck_alerts_origin_iata"),
        sa.CheckConstraint("adults >= 1", name="ck_alerts_adults_min_one"),
        sa.CheckConstraint("check_interval_minutes >= 15", name="ck_alerts_interval_min_15"),
        sa.CheckConstraint(
            "earliest_departure_date <= latest_return_date", name="ck_alerts_date_order"
        ),
        sa.CheckConstraint("max_price_cents > 0", name="ck_alerts_price_positive"),
        sa.CheckConstraint("max_stops >= 0", name="ck_alerts_stops_non_negative"),
        sa.CheckConstraint(
            "min_trip_duration_days IS NULL OR max_trip_duration_days IS NULL OR min_trip_duration_days <= max_trip_duration_days",
            name="ck_alerts_duration_order",
        ),
        sa.CheckConstraint("origin <> destination", name="ck_alerts_origin_ne_destination"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_alerts_due", "price_alerts", ["is_active", "last_checked_at"], unique=False
    )
    op.create_index(op.f("ix_price_alerts_user_id"), "price_alerts", ["user_id"], unique=False)
    op.create_table(
        "flight_observations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("price_alert_id", sa.UUID(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("min_price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'EUR'"), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("departure_month", sa.String(length=7), nullable=False),
        sa.Column("offers_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("search_ok", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "departure_month ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_observations_month_format"
        ),
        sa.CheckConstraint("destination ~ '^[A-Z]{3}$'", name="ck_observations_destination_iata"),
        sa.CheckConstraint("origin ~ '^[A-Z]{3}$'", name="ck_observations_origin_iata"),
        sa.CheckConstraint(
            "min_price_cents IS NULL OR min_price_cents > 0", name="ck_observations_price_positive"
        ),
        sa.CheckConstraint("offers_found >= 0", name="ck_observations_offers_non_negative"),
        sa.ForeignKeyConstraint(["price_alert_id"], ["price_alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_observations_alert_time",
        "flight_observations",
        ["price_alert_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_observations_route_month",
        "flight_observations",
        ["origin", "destination", "departure_month", "observed_at"],
        unique=False,
    )
    op.create_table(
        "flight_offers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("price_alert_id", sa.UUID(), nullable=False),
        sa.Column("flight_observation_id", sa.UUID(), nullable=True),
        sa.Column("offer_hash", sa.String(length=64), nullable=False),
        sa.Column("total_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'EUR'"), nullable=False),
        sa.Column("validating_airline", sa.String(length=2), nullable=True),
        sa.Column("outbound_departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outbound_arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outbound_stops", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inbound_departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbound_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbound_stops", sa.Integer(), nullable=True),
        sa.Column("included_checked_bags", sa.Integer(), nullable=True),
        sa.Column(
            "segments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("booking_url", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "found_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "inbound_stops IS NULL OR inbound_stops >= 0", name="ck_offers_inbound_stops"
        ),
        sa.CheckConstraint(
            "included_checked_bags IS NULL OR included_checked_bags >= 0",
            name="ck_offers_bags_non_negative",
        ),
        sa.CheckConstraint(
            "outbound_arrival_at > outbound_departure_at", name="ck_offers_outbound_time_order"
        ),
        sa.CheckConstraint("outbound_stops >= 0", name="ck_offers_outbound_stops"),
        sa.CheckConstraint("total_price_cents > 0", name="ck_offers_price_positive"),
        sa.ForeignKeyConstraint(
            ["flight_observation_id"], ["flight_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["price_alert_id"], ["price_alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("price_alert_id", "offer_hash", name="uq_offers_alert_hash"),
    )
    op.create_index(
        "ix_offers_alert_found", "flight_offers", ["price_alert_id", "found_at"], unique=False
    )
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("price_alert_id", sa.UUID(), nullable=False),
        sa.Column("flight_offer_id", sa.UUID(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("apns_status_code", sa.Integer(), nullable=True),
        sa.Column("apns_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('sent', 'failed', 'token_invalid')", name="ck_notifications_status"
        ),
        sa.CheckConstraint("price_cents > 0", name="ck_notifications_price_positive"),
        sa.ForeignKeyConstraint(["flight_offer_id"], ["flight_offers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["price_alert_id"], ["price_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_notifications_alert_time",
        "notification_logs",
        ["price_alert_id", "sent_at"],
        unique=False,
    )
    # Ende der erzeugten Befehle


def downgrade() -> None:
    # von Alembic erzeugt, geprüft und angewendet
    op.drop_index("ix_notifications_alert_time", table_name="notification_logs")
    op.drop_table("notification_logs")
    op.drop_index("ix_offers_alert_found", table_name="flight_offers")
    op.drop_table("flight_offers")
    op.drop_index("ix_observations_route_month", table_name="flight_observations")
    op.drop_index("ix_observations_alert_time", table_name="flight_observations")
    op.drop_table("flight_observations")
    op.drop_index(op.f("ix_price_alerts_user_id"), table_name="price_alerts")
    op.drop_index("ix_price_alerts_due", table_name="price_alerts")
    op.drop_table("price_alerts")
    op.drop_index("ix_tokens_user_active", table_name="device_tokens")
    op.drop_table("device_tokens")
    op.drop_table("users")
    # Ende der erzeugten Befehle
