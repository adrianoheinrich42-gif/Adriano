"""Alte Daten löschen (M12) — Datenminimierung als Dauerauftrag.

Zwei Tabellen wachsen ungebremst: `flight_observations` (bei sechs Läufen
täglich rund 2.200 Zeilen je Alarm und Jahr) und `notification_logs`. Ohne
Aufräumen wird die Datenbank langsam und teuer — und, wichtiger,
`flight_observations` enthält **Reisewünsche**, und die sind personenbezogen
(Projektplan 8.10).

Der Grundsatz dahinter ist einfach: **Was niemand mehr braucht, soll auch
nicht mehr da sein.** Die Preisstatistik schaut 90 Tage zurück; alles
jenseits eines Jahres liegt nur noch herum.

## Zwei Dinge, die hier absichtlich *nicht* passieren

* **`flight_offers` wird nicht angefasst.** Die Zeilen hängen per
  `ON DELETE CASCADE` am Alarm und verschwinden mit ihm. Sie einzeln nach
  Alter zu löschen hieße, dem Nutzer Funde wegzunehmen, die er sich gerade
  ansieht.
* **Nichts wird zusammengefasst.** Man könnte alte Beobachtungen zu
  Monatsmitteln verdichten, statt sie zu löschen. Das wäre eine eigene
  Tabelle, eine eigene Migration und eine zweite Wahrheit über den
  Preisverlauf — dafür ist es zu früh.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation
from app.models.notification_log import NotificationLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AufraeumBericht:
    """Was ein Lauf gelöscht hat — fürs Log und für den Test."""

    beobachtungen: int = 0
    meldungen: int = 0

    @property
    def gesamt(self) -> int:
        return self.beobachtungen + self.meldungen


async def loesche_alte_daten(
    session: AsyncSession, aufbewahrung_tage: int, jetzt: datetime | None = None
) -> AufraeumBericht:
    """Alles löschen, was älter ist als die Aufbewahrungsfrist.

    Ein einziger Commit für beide Tabellen: Entweder der Lauf ist durch oder
    er ist es nicht. Ein halb aufgeräumter Stand wäre kein Problem — aber
    zwei Commits wären zwei Stellen, an denen etwas hängen bleiben kann, ohne
    dass es dafür einen Grund gibt.

    Die Grenze ist **`observed_at` bzw. `sent_at`**, nicht `created_at`: Es
    geht um das Alter der Messung, nicht um das der Zeile.
    """
    jetzt = jetzt or datetime.now(UTC)
    grenze = jetzt - timedelta(days=aufbewahrung_tage)

    # `cast`, weil SQLAlchemy `execute()` allgemein als `Result` typisiert.
    # Bei einem DELETE ist es tatsächlich ein `CursorResult`, und nur der
    # kennt `rowcount` — die Zahl, die wir loggen wollen.
    beobachtungen = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(FlightObservation).where(FlightObservation.observed_at < grenze)
        ),
    )
    meldungen = cast(
        "CursorResult[Any]",
        await session.execute(delete(NotificationLog).where(NotificationLog.sent_at < grenze)),
    )
    await session.commit()

    bericht = AufraeumBericht(
        beobachtungen=beobachtungen.rowcount or 0,
        meldungen=meldungen.rowcount or 0,
    )

    if bericht.gesamt > 0:
        logger.info(
            "Aufgeräumt: %d Beobachtungen und %d Meldungen älter als %d Tage gelöscht.",
            bericht.beobachtungen,
            bericht.meldungen,
            aufbewahrung_tage,
        )
    return bericht
