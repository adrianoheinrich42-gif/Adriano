"""Fachlogik für Preisalarme.

Die wichtigste Regel dieses Moduls: **In jeder Abfrage steht `user_id` in der
WHERE-Klausel.** Nicht „erst laden, dann prüfen, wem er gehört" — dabei wird
die Prüfung irgendwann vergessen. Wenn die Einschränkung in der Abfrage
steckt, kann ein fremder Alarm gar nicht erst im Ergebnis auftauchen.

Die Endpunkte selbst bleiben dadurch dünn: Sie übersetzen nur noch
Rückgabewerte in HTTP-Status.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_alert import PriceAlert
from app.models.user import User
from app.schemas.price_alert import (
    PriceAlertCreate,
    PriceAlertUpdate,
    pruefe_feldkombination,
)


class AlertLimitReached(Exception):
    """Der Nutzer hat sein Kontingent aktiver Alarme ausgeschöpft.

    Kostenbremse: Jeder aktive Alarm erzeugt regelmäßig Amadeus-Anfragen.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Mehr als {limit} aktive Alarme sind nicht erlaubt.")


class AlertRulesViolated(Exception):
    """Das Ergebnis einer Änderung ergibt in sich keinen Sinn.

    Beispiel: Der Client verschiebt nur `latest_return_date` auf ein Datum
    vor dem Hinflug. Das Feld allein ist gültig, die Kombination nicht.
    """


async def list_alerts(session: AsyncSession, user_id: uuid.UUID) -> Sequence[PriceAlert]:
    """Alle Alarme eines Nutzers, neueste zuerst."""
    result = await session.execute(
        select(PriceAlert)
        .where(PriceAlert.user_id == user_id)
        .order_by(PriceAlert.created_at.desc())
    )
    return result.scalars().all()


async def get_alert(
    session: AsyncSession, user_id: uuid.UUID, alert_id: uuid.UUID
) -> PriceAlert | None:
    """Einen Alarm holen — `None`, wenn es ihn nicht gibt **oder** er fremd ist.

    Beide Fälle bewusst ununterscheidbar: Der Endpunkt antwortet auf beides
    mit 404. Ein 403 würde verraten, dass es diesen Alarm gibt.
    """
    result = await session.execute(
        select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _zaehle_aktive(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PriceAlert)
        .where(PriceAlert.user_id == user_id, PriceAlert.is_active.is_(True))
    )
    return result.scalar_one()


async def _sperre_nutzer_und_pruefe_limit(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Prüft das Alarm-Limit — und zwar rennsicher.

    `SELECT ... FOR UPDATE` auf die Nutzer-Zeile: Zwei gleichzeitige Requests
    desselben Nutzers werden dadurch nacheinander abgearbeitet. Ohne die
    Sperre könnten beide zählen, beide „noch Platz" feststellen und beide
    anlegen — das Limit wäre um eins überschritten.

    Die Sperre gilt bis zum Ende der Transaktion, also bis zum `commit()`.
    """
    result = await session.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one()

    if await _zaehle_aktive(session, user_id) >= user.max_active_alerts:
        raise AlertLimitReached(user.max_active_alerts)


async def create_alert(
    session: AsyncSession, user_id: uuid.UUID, daten: PriceAlertCreate
) -> PriceAlert:
    """Neuen Alarm anlegen. Wirft `AlertLimitReached`, wenn kein Platz mehr ist."""
    await _sperre_nutzer_und_pruefe_limit(session, user_id)

    alert = PriceAlert(user_id=user_id, **daten.model_dump())
    session.add(alert)
    await session.commit()

    # Holt die Werte, die erst die Datenbank gesetzt hat (id, created_at,
    # is_active …). Ohne das wären die Attribute nach dem commit leer.
    await session.refresh(alert)
    return alert


async def update_alert(
    session: AsyncSession,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    aenderungen: PriceAlertUpdate,
) -> PriceAlert | None:
    """Alarm ändern. `None`, wenn er nicht existiert oder fremd ist."""
    alert = await get_alert(session, user_id, alert_id)
    if alert is None:
        return None

    felder = aenderungen.gesetzte_felder()
    if not felder:
        # Leeres PATCH: nichts tun, aber auch kein Fehler — der Client
        # bekommt einfach den unveränderten Alarm zurück.
        return alert

    # Wird ein pausierter Alarm wieder scharf geschaltet, zählt er ab jetzt
    # gegen das Kontingent. Also dieselbe Prüfung wie beim Anlegen.
    if felder.get("is_active") is True and not alert.is_active:
        await _sperre_nutzer_und_pruefe_limit(session, user_id)

    for name, wert in felder.items():
        setattr(alert, name, wert)

    # Erst jetzt prüfen: Die Regeln gelten für den **zusammengeführten**
    # Stand, nicht für die einzelnen geschickten Felder.
    try:
        pruefe_feldkombination(
            origin=alert.origin,
            destination=alert.destination,
            earliest_departure_date=alert.earliest_departure_date,
            latest_return_date=alert.latest_return_date,
            min_trip_duration_days=alert.min_trip_duration_days,
            max_trip_duration_days=alert.max_trip_duration_days,
        )
    except ValueError as exc:
        # Die Änderungen hängen bereits am ORM-Objekt. Ohne Rollback würden
        # sie beim nächsten commit() irgendwo anders mitgeschrieben.
        await session.rollback()
        raise AlertRulesViolated(str(exc)) from exc

    await session.commit()
    await session.refresh(alert)
    return alert


async def delete_alert(session: AsyncSession, user_id: uuid.UUID, alert_id: uuid.UUID) -> bool:
    """Alarm löschen. `False`, wenn er nicht existiert oder fremd ist.

    Echtes Löschen, kein Verstecken: Beobachtungen und Angebote hängen per
    `ON DELETE CASCADE` daran und verschwinden mit. Wer den Preisverlauf
    behalten will, setzt stattdessen `is_active = false` (Pausieren).
    """
    alert = await get_alert(session, user_id, alert_id)
    if alert is None:
        return False

    await session.delete(alert)
    await session.commit()
    return True
