"""Gemeinsame Dependencies für die Endpunkte.

Eine "Dependency" ist bei FastAPI eine Funktion, die vor dem Endpunkt läuft
und ihm ein fertiges Ergebnis reicht. Der Vorteil hier: Jeder geschützte
Endpunkt schreibt nur noch `user: CurrentUser` — die ganze Token-Prüfung
steht genau einmal an einer Stelle und ist im Test austauschbar.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.security import AuthConfigError, TokenClaims, TokenError, decode_supabase_token
from app.db import get_db
from app.models.user import User
from app.services.users import get_or_create_user

logger = logging.getLogger(__name__)

# Liest den Header `Authorization: Bearer <token>`. `auto_error=False`, damit
# wir den Fehlertext selbst bestimmen (deutsch, einheitlich) — sonst antwortet
# FastAPI mit einem englischen "Not authenticated".
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase-Zugangstoken")


def _unauthorized(detail: str) -> HTTPException:
    # `WWW-Authenticate` gehört laut HTTP-Standard zu jeder 401-Antwort.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenClaims:
    """Token aus dem Header prüfen. Braucht **keine** Datenbank."""
    if credentials is None:
        raise _unauthorized("Nicht angemeldet.")

    try:
        return decode_supabase_token(credentials.credentials, settings)
    except TokenError as exc:
        logger.info("Token abgelehnt: %s", exc)
        raise _unauthorized("Zugangstoken ungültig oder abgelaufen.") from exc
    except AuthConfigError as exc:
        # Kein 401: Der Aufrufer kann nichts dafür, das Backend ist falsch
        # eingerichtet. Der Grund steht im Log, nicht in der Antwort.
        logger.error("Auth nicht konfiguriert: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Anmeldung ist auf dem Server nicht eingerichtet.",
        ) from exc


async def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_token_claims)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Angemeldeten Nutzer liefern und beim ersten Mal in `users` anlegen."""
    if claims.email is None:
        # `users.email` ist NOT NULL. Ein Token ohne E-Mail (z. B. reine
        # Telefon-Anmeldung) passt nicht zum Datenmodell — dann lieber klar
        # ablehnen als eine erfundene Adresse speichern.
        raise _unauthorized("Zugangstoken enthält keine E-Mail-Adresse.")

    user = await get_or_create_user(session, claims.user_id, claims.email)

    if not user.is_active:
        # Gesperrte Konten bleiben in der Datenbank, dürfen aber nichts tun.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dieses Konto ist gesperrt.",
        )

    return user


# Kurzschreibweise für die Endpunkte: `user: CurrentUser`.
CurrentUser = Annotated[User, Depends(get_current_user)]
