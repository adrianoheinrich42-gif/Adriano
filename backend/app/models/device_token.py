"""Das Ziel einer Push-Benachrichtigung — eine Web-Push-Subscription.

Der Tabellenname ist aus M1 geblieben („device_tokens"), der Inhalt hat sich
in M8 geändert: Statt eines APNs-Gerätetokens steht hier jetzt eine
**Web-Push-Subscription**. Die besteht aus drei Teilen, die der Browser beim
Abonnieren ausspuckt:

* **`endpoint`** — eine URL beim Push-Dienst des Browserherstellers (Apple,
  Google, Mozilla). *Dorthin* schickt unser Backend die Nachricht; wir reden
  nie direkt mit dem Gerät. Die URL ist das Geheimnis: Wer sie kennt, kann
  dem Gerät Nachrichten schicken.
* **`p256dh`** — der öffentliche Schlüssel des Geräts. Damit verschlüsseln
  wir den Inhalt, sodass der Push-Dienst ihn **nicht mitlesen** kann.
* **`auth`** — ein zusätzliches Geheimnis für dieselbe Verschlüsselung.

Was dadurch entfallen ist: die Spalte `environment` (sandbox/production). Die
gab es nur, weil APNs zwei getrennte Server hat. Web-Push kennt das nicht —
es gibt genau eine Adresse, und die steht im `endpoint`.
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
    Text,
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

    # `Text` statt `String(n)`: Endpoint-URLs sind lang und ihre Länge ist
    # nirgends garantiert — Apple, Google und Mozilla bauen sie verschieden.
    # Eine zu knapp geratene Obergrenze wäre ein Fehler, der erst beim ersten
    # fremden Browser auffiele.
    #
    # `unique`: Dasselbe Gerät darf nicht zweimal in der Liste stehen, sonst
    # käme jede Meldung doppelt an. Global eindeutig und nicht nur je Nutzer,
    # weil ein Gerät den Besitzer wechseln kann.
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # Beides base64url-kodiert: p256dh ist ein 65-Byte-Schlüssel (~88 Zeichen),
    # auth sind 16 Byte (~22 Zeichen). 255 ist reichlich Luft.
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)

    platform: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'web'"))

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Auf false setzen, wenn der Push-Dienst mit 404 oder 410 antwortet: Dann
    # hat der Nutzer die Erlaubnis entzogen oder die App entfernt.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="device_tokens")

    __table_args__ = (
        # Textspalte + CHECK statt PostgreSQL-ENUM: Ein neuer Wert ist dann
        # eine simple Migration statt eines ALTER TYPE.
        CheckConstraint("platform IN ('web')", name="ck_tokens_platform"),
        # Der Worker holt vor jedem Versand die aktiven Ziele eines Nutzers.
        Index("ix_tokens_user_active", "user_id", "is_active"),
    )
