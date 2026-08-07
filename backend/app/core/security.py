"""Prüfung der Supabase-Zugangstoken (JWT).

Warum das hier so klein ist: **Wir stellen keine Token aus.** Login, Passwort-
Hashing, Reset-Mails und die Token-Ausgabe macht Supabase. Unsere einzige
Aufgabe ist zu prüfen, ob ein mitgeschicktes Token echt und gültig ist — und
wenn ja, wer dahintersteckt.

Ein JWT besteht aus drei mit Punkt getrennten Teilen: Kopf, Inhalt
("Claims") und Signatur. Der Inhalt ist **nicht verschlüsselt**, nur
signiert — jeder kann ihn lesen, aber niemand ohne das Geheimnis ändern.
Deshalb ist die Signaturprüfung der ganze Sicherheitsgewinn; auf ungeprüfte
Claims darf man sich nie verlassen.

Geprüft wird:
  * Signatur mit `SUPABASE_JWT_SECRET` (HS256)
  * Ablaufzeit `exp` (macht PyJWT selbst)
  * Empfänger `aud` — muss "authenticated" sein
  * Aussteller `iss` — nur wenn `SUPABASE_URL` gesetzt ist
  * `sub` ist vorhanden und eine UUID (das ist die Nutzer-ID)
"""

import uuid

import jwt
from pydantic import BaseModel

from app.config import Settings


class TokenError(Exception):
    """Token fehlt, ist kaputt, abgelaufen oder gefälscht.

    Eigene Klasse statt der PyJWT-Fehler: So kennt die API-Schicht nur einen
    Fehlertyp und die Bibliothek bleibt austauschbar.
    """


class AuthConfigError(Exception):
    """Das Backend ist nicht fertig konfiguriert (kein JWT-Secret).

    Bewusst getrennt von `TokenError`: Das ist **unser** Fehler, nicht der des
    Aufrufers — er führt zu HTTP 500, nicht zu 401.
    """


class TokenClaims(BaseModel):
    """Die Felder aus dem Token, die uns interessieren."""

    user_id: uuid.UUID
    email: str | None = None


def decode_supabase_token(token: str, settings: Settings) -> TokenClaims:
    """Token prüfen und die Nutzerangaben herausziehen.

    Wirft `TokenError`, wenn das Token nicht vertrauenswürdig ist, und
    `AuthConfigError`, wenn das Geheimnis fehlt.
    """
    if not settings.supabase_jwt_secret:
        raise AuthConfigError(
            "SUPABASE_JWT_SECRET ist nicht gesetzt — ohne Geheimnis lässt sich "
            "kein Token prüfen. Wert aus dem Supabase-Dashboard in die .env eintragen."
        )

    # `iss` nur prüfen, wenn wir ihn kennen. Sonst würde ein leerer Wert
    # jede Prüfung scheitern lassen, obwohl das Token in Ordnung ist.
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1" if settings.supabase_url else None

    try:
        payload: dict[str, object] = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],  # Liste bewusst fest: verhindert "alg: none"
            audience=settings.supabase_jwt_audience,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        # Nach außen absichtlich vage — der Grund gehört ins Log, nicht in die
        # Antwort. Sonst verrät man Angreifern, wie weit sie gekommen sind.
        raise TokenError(f"Token ungültig: {type(exc).__name__}") from exc

    raw_sub = payload.get("sub")
    if not isinstance(raw_sub, str):
        raise TokenError("Token enthält kein brauchbares Feld 'sub'.")

    try:
        user_id = uuid.UUID(raw_sub)
    except ValueError as exc:
        # Supabase nutzt UUIDs. Etwas anderes passt nicht zu `users.id`.
        raise TokenError("Feld 'sub' ist keine UUID.") from exc

    raw_email = payload.get("email")
    email = raw_email if isinstance(raw_email, str) and raw_email else None

    return TokenClaims(user_id=user_id, email=email)
