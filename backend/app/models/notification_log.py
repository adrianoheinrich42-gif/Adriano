"""Protokoll versendeter Benachrichtigungen — und Schutz vor Doppelmeldungen.

Der `UNIQUE`-Index auf `dedupe_key` ist die eigentliche Schutzmauer gegen
Spam. Der Schlüssel wird als `sha256(price_alert_id + offer_hash)` gebildet;
der Worker schreibt mit `INSERT ... ON CONFLICT DO NOTHING`. Kommt keine Zeile
zurück, wurde bereits gemeldet — dann keine Push.

Der entscheidende Punkt: Das ist eine **Datenbank-Garantie**, keine
Programmlogik. Selbst wenn zwei Worker im selben Moment denselben Fund
verarbeiten, kann physisch nur einer die Zeile schreiben.

Zusätzlich im Code (siehe Projektplan, Schritt 9, umgesetzt in
`services/push.py`):
  * Abkühlphase: höchstens eine Push je Alarm in 6 Stunden
  * erneute Meldung nur bei mindestens 5 % Preisverbesserung

Die Spalten hießen bis M8 `apns_status_code` und `apns_reason`. Seit dem
Wechsel auf Web-Push heißen sie neutral `push_status_code` und `push_error` —
ein Name, der eine Technik nennt, die es im Projekt nicht mehr gibt, führt
zuverlässig in die Irre.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import uuid_primary_key

if TYPE_CHECKING:
    from app.models.user import User


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    price_alert_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL: Das Protokoll überlebt, auch wenn das Angebot aufgeräumt wird.
    flight_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flight_offers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Die Schutzmauer. sha256 als Hex = 64 Zeichen.
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # `pending` ist in M8 dazugekommen und ist der Zustand, in dem die Zeile
    # **zuerst** geschrieben wird — vor dem Versand. Nur so ist der
    # UNIQUE-Index eine echte Schutzmauer: Er muss den Platz belegen, bevor
    # irgendetwas Langsames passiert. Ginge die Zeile erst nach dem Versand
    # hinein, könnte zwischen Senden und Schreiben ein zweiter Lauf dieselbe
    # Push noch einmal verschicken.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    push_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    push_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'token_invalid')",
            name="ck_notifications_status",
        ),
        CheckConstraint("price_cents > 0", name="ck_notifications_price_positive"),
        # Für die Abkühlphase: "wann wurde für diesen Alarm zuletzt gemeldet?"
        Index("ix_notifications_alert_time", "price_alert_id", "sent_at"),
    )
