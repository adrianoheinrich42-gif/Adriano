"""M10 Erklaertext im Benachrichtigungsprotokoll

Drei Spalten in `notification_logs`: `title`, `body` und `text_quelle`. Das
Protokoll hielt bisher nur fest, *dass* gemeldet wurde — nicht, was dort
stand. Seit Claude die Texte schreibt, ist beides wichtig: zum Nachvollziehen
(„da stand ein falscher Preis") und um zu sehen, ob der Baukasten-Rückfall
gerade stillschweigend dauerhaft greift.

**Alle drei sind `nullable`, und das ist Absicht.** Die Zeile wird im Zustand
`pending` geschrieben, *bevor* gesendet wird — sie belegt zuerst nur den Platz
im UNIQUE-Index auf `dedupe_key`. Den Text vorher zu verlangen hieße, den
langsamen Claude-Aufruf vor die Schutzmauer zu ziehen; genau das soll die
Reihenfolge in `services/push.py` verhindern.

Anders als die M8-Migration `22e16687014f` kam diese hier fehlerfrei aus dem
Autogenerate — nur reine Hinzufügungen, keine Änderung an bestehenden Zeilen.

Revision ID: 4b42be3a6b6e
Revises: 22e16687014f
Erstellt: 2026-08-07 17:54:48.999610+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4b42be3a6b6e"
down_revision: str | None = "22e16687014f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_logs", sa.Column("title", sa.String(length=120), nullable=True))
    op.add_column("notification_logs", sa.Column("body", sa.String(length=400), nullable=True))
    op.add_column(
        "notification_logs", sa.Column("text_quelle", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        "ck_notifications_text_quelle",
        "notification_logs",
        "text_quelle IS NULL OR text_quelle IN ('claude', 'baukasten')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notifications_text_quelle", "notification_logs", type_="check")
    op.drop_column("notification_logs", "text_quelle")
    op.drop_column("notification_logs", "body")
    op.drop_column("notification_logs", "title")
