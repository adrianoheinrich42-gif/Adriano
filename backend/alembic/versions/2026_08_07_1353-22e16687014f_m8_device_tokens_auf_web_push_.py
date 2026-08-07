"""M8: device_tokens auf Web-Push, notification_logs entkoppelt

Revision ID: 22e16687014f
Revises: 6513957c2dba
Erstellt: 2026-08-07 13:53:59.618265+00:00

Diese Migration ist **von Hand nachgearbeitet**. Das Autogenerate hat vier
Dinge nicht hinbekommen, die alle beim ersten echten Lauf explodiert wären:

1. `add_column(..., nullable=False)` ohne Standardwert scheitert, sobald auch
   nur eine Zeile in der Tabelle steht. Deshalb steht unten ein ausdrückliches
   `DELETE` — siehe Begründung dort.
2. Die beiden neuen `UNIQUE`-Constraints bekamen `None` als Namen. Ein
   unbenanntes Constraint kann `downgrade()` später nicht mehr finden.
3. **Die Änderung an `ck_tokens_platform` wurde gar nicht erkannt.**
   Autogenerate vergleicht CHECK-Ausdrücke nicht zuverlässig. Ohne die
   Anpassung stünde weiterhin `platform IN ('ios')` in der Datenbank — und
   jedes Einfügen mit `'web'` wäre abgelehnt worden.
4. Dasselbe bei `ck_notifications_status`: Der neue Zustand `pending` fehlte.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "22e16687014f"
down_revision: str | None = "6513957c2dba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- device_tokens: von APNs auf Web-Push --------------------------------
    #
    # Die vorhandenen Zeilen werden gelöscht, nicht umgerechnet. Das ist kein
    # Datenverlust aus Bequemlichkeit: Ein APNs-Gerätetoken lässt sich in eine
    # Web-Push-Subscription **nicht** übersetzen — es sind verschiedene Dinge
    # von verschiedenen Anbietern. Jedes Gerät muss ohnehin neu abonnieren.
    # (Praktisch ist die Tabelle zu diesem Zeitpunkt leer: Bis M8 hat nie
    # jemand ein Token registrieren können, weil es den Endpunkt nicht gab.)
    op.execute("DELETE FROM device_tokens")

    op.add_column("device_tokens", sa.Column("endpoint", sa.Text(), nullable=False))
    op.add_column("device_tokens", sa.Column("p256dh", sa.String(length=255), nullable=False))
    op.add_column("device_tokens", sa.Column("auth", sa.String(length=255), nullable=False))

    op.drop_constraint("device_tokens_token_key", "device_tokens", type_="unique")
    op.create_unique_constraint("uq_tokens_endpoint", "device_tokens", ["endpoint"])

    # Vor dem `drop_column`: PostgreSQL löscht einen CHECK zwar automatisch
    # mit, sobald dessen Spalte verschwindet — aber dann scheitert ein
    # nachgelagertes `drop_constraint` mit „does not exist". Genau dieser
    # Fehler ist beim ersten Lauf hier aufgetreten.
    op.drop_constraint("ck_tokens_environment", "device_tokens", type_="check")

    op.drop_column("device_tokens", "token")
    op.drop_column("device_tokens", "environment")
    op.drop_column("device_tokens", "app_version")

    # Von Autogenerate übersehen: 'ios' → 'web'.
    op.drop_constraint("ck_tokens_platform", "device_tokens", type_="check")
    op.alter_column(
        "device_tokens",
        "platform",
        existing_type=sa.VARCHAR(length=10),
        server_default=sa.text("'web'"),
        existing_nullable=False,
    )
    op.create_check_constraint("ck_tokens_platform", "device_tokens", "platform IN ('web')")

    # --- notification_logs: Spalten entkoppeln, Zustand 'pending' -----------
    op.add_column("notification_logs", sa.Column("push_status_code", sa.Integer(), nullable=True))
    op.add_column("notification_logs", sa.Column("push_error", sa.Text(), nullable=True))
    op.drop_column("notification_logs", "apns_status_code")
    op.drop_column("notification_logs", "apns_reason")

    # Ebenfalls von Autogenerate übersehen. `pending` ist der Zustand, in dem
    # die Zeile vor dem Versand geschrieben wird — ohne ihn könnte der
    # UNIQUE-Index den Platz nicht rechtzeitig belegen.
    op.drop_constraint("ck_notifications_status", "notification_logs", type_="check")
    op.create_check_constraint(
        "ck_notifications_status",
        "notification_logs",
        "status IN ('pending', 'sent', 'failed', 'token_invalid')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notifications_status", "notification_logs", type_="check")
    op.create_check_constraint(
        "ck_notifications_status",
        "notification_logs",
        "status IN ('sent', 'failed', 'token_invalid')",
    )

    op.add_column("notification_logs", sa.Column("apns_reason", sa.TEXT(), nullable=True))
    op.add_column("notification_logs", sa.Column("apns_status_code", sa.INTEGER(), nullable=True))
    op.drop_column("notification_logs", "push_error")
    op.drop_column("notification_logs", "push_status_code")

    # Auch hier: Subscriptions lassen sich nicht in APNs-Tokens zurückrechnen.
    op.execute("DELETE FROM device_tokens")

    op.drop_constraint("ck_tokens_platform", "device_tokens", type_="check")
    op.alter_column(
        "device_tokens",
        "platform",
        existing_type=sa.VARCHAR(length=10),
        server_default=sa.text("'ios'"),
        existing_nullable=False,
    )
    op.create_check_constraint("ck_tokens_platform", "device_tokens", "platform IN ('ios')")

    op.add_column("device_tokens", sa.Column("app_version", sa.VARCHAR(length=20), nullable=True))
    op.add_column("device_tokens", sa.Column("environment", sa.VARCHAR(length=12), nullable=False))
    op.add_column("device_tokens", sa.Column("token", sa.VARCHAR(length=200), nullable=False))

    op.create_check_constraint(
        "ck_tokens_environment", "device_tokens", "environment IN ('sandbox', 'production')"
    )

    op.drop_constraint("uq_tokens_endpoint", "device_tokens", type_="unique")
    op.create_unique_constraint("device_tokens_token_key", "device_tokens", ["token"])

    op.drop_column("device_tokens", "auth")
    op.drop_column("device_tokens", "p256dh")
    op.drop_column("device_tokens", "endpoint")
