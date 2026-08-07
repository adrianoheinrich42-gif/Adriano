"""Nutzer-Zeilen anlegen und aktuell halten.

Supabase kennt den Nutzer, unsere Datenbank zunächst nicht. Statt einen
Webhook von Supabase einzurichten (mehr Teile, mehr Fehlerquellen), legen wir
die Zeile beim **ersten authentifizierten Request** an. Der Weg ist selbst-
heilend: Auch ein vor dem Start des Backends registrierter Nutzer bekommt
seine Zeile, sobald er das erste Mal etwas aufruft.
"""

import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
