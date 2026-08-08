"""Nutzer-Zeilen anlegen und aktuell halten.

Supabase kennt den Nutzer, unsere Datenbank zunächst nicht. Statt einen
Webhook von Supabase einzurichten (mehr Teile, mehr Fehlerquellen), legen wir
die Zeile beim **ersten authentifizierten Request** an. Der Weg ist selbst-
heilend: Auch ein vor dem Start des Backends registrierter Nutzer bekommt
seine Zeile, sobald er das erste Mal etwas aufruft.
"""

import uuid
from typing import Any, cast

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_or_create_user(session: AsyncSession, user_id: uuid.UUID, email: str) -> User:
    """Nutzer holen — und anlegen, falls es ihn noch nicht gibt.

    Umgesetzt als ein einziges `INSERT ... ON CONFLICT`, nicht als
    "erst SELECT, dann INSERT": Zwei gleichzeitige erste Requests desselben
    Nutzers würden sonst beide die Zeile anlegen wollen und einer bekäme
    einen Unique-Fehler. Die Datenbank löst das atomar.

    Bei Konflikt wird die E-Mail aktualisiert, damit eine Adressänderung in
    Supabase bei uns ankommt.
    """
    statement = (
        pg_insert(User)
        .values(id=user_id, email=email)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={"email": email, "updated_at": func.now()},
        )
        .returning(User)
    )

    # `execution_options(populate_existing=True)`: Liegt der Nutzer schon im
    # Identity-Map-Cache dieser Session, soll das ORM die frischen Werte aus
    # der Datenbank übernehmen statt den alten Stand zu behalten.
    result = await session.execute(statement, execution_options={"populate_existing": True})
    user = result.scalar_one()
    await session.commit()
    return user


async def loesche_nutzer(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Konto löschen — und mit ihm restlos alles (M12, DSGVO).

    Ein einziges `DELETE` auf `users` reicht, weil **jede** abhängige Tabelle
    per `ON DELETE CASCADE` an dieser Zeile hängt: Alarme, Beobachtungen,
    Angebote, Push-Ziele, Versandprotokolle. Genau dafür wurde die Regel in M1
    gesetzt (`CLAUDE.md`: „ON DELETE CASCADE ab `users` — Konto löschen =
    alles weg"). Hier zahlt sich das aus: Das Löschrecht ist eine Zeile SQL
    statt einer Liste, die man beim nächsten neuen Tabellchen vergisst.

    **Der Supabase-Zugang bleibt bestehen.** Wir löschen unsere Daten; das
    Anmeldekonto gehört Supabase und wird dort gelöscht. Meldet sich derselbe
    Mensch danach noch einmal an, entsteht beim ersten Request eine frische,
    leere Nutzer-Zeile — richtig so, aber erwähnenswert.

    Gibt zurück, ob wirklich etwas gelöscht wurde.
    """
    # `cast`: `execute()` ist allgemein als `Result` typisiert, bei einem
    # DELETE aber ein `CursorResult` — nur der kennt `rowcount`.
    ergebnis = cast(
        "CursorResult[Any]", await session.execute(delete(User).where(User.id == user_id))
    )
    await session.commit()
    return bool(ergebnis.rowcount)
