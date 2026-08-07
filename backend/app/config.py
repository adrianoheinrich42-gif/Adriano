"""Zentrale Konfiguration.

Alle Werte kommen aus Umgebungsvariablen oder aus einer lokalen `.env`-Datei.
Es steht bewusst **kein einziges Geheimnis** im Code — siehe `.env.example`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Allgemein -------------------------------------------------------
    app_name: str = "Flugalarm API"
    app_version: str = "0.1.0"
    environment: str = "local"  # local | staging | production
    debug: bool = True

    # --- Datenbank -------------------------------------------------------
    # Format: postgresql+asyncpg://user:passwort@host:port/datenbank
    # Der Standardwert passt zur docker-compose.yml.
    database_url: str = "postgresql+asyncpg://flugalarm:flugalarm@localhost:5432/flugalarm"

    # Supabase-Pooler im Transaction-Modus (Port 6543) verträgt keine
    # Prepared Statements. Dann hier auf `true` setzen. Siehe Projektplan 2.3.
    database_disable_statement_cache: bool = False

    # --- Supabase Auth (M2) ----------------------------------------------
    # Supabase stellt die Token aus, wir prüfen sie nur. Das Geheimnis steht
    # im Supabase-Dashboard unter "Project Settings → API → JWT Secret".
    #
    # Bewusst nur das *symmetrische* Verfahren (HS256): ein gemeinsames
    # Geheimnis, keine Netzwerkabfrage, keine zusätzliche Krypto-Bibliothek.
    # Der asymmetrische Weg (JWKS-Schlüssel per HTTPS holen) lässt sich
    # später in `app/core/security.py` ergänzen, ohne dass die Endpunkte
    # sich ändern — sie kennen nur `get_current_user`.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # Supabase setzt für eingeloggte Nutzer immer `aud: "authenticated"`.
    supabase_jwt_audience: str = "authenticated"

    # --- Amadeus (M5) ----------------------------------------------------
    # Self-Service-Zugang von developers.amadeus.com. Die Test-Umgebung
    # liefert echte Antwortstrukturen, aber nur einen Ausschnitt der Daten
    # und veraltete Preise — zum Entwickeln reicht das.
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    amadeus_base_url: str = "https://test.api.amadeus.com"

    # Lieber früh abbrechen als den Prüflauf blockieren.
    amadeus_timeout_seconds: float = 15.0

    # --- Prüflauf / Worker (M6) ------------------------------------------
    # Wie oft der Worker **nachsieht**, welche Alarme fällig sind. Nicht zu
    # verwechseln mit `check_interval_minutes` am einzelnen Alarm — das
    # bestimmt, wie oft ein Alarm tatsächlich geprüft wird. Nachsehen kostet
    # nur eine schlanke SQL-Abfrage, darum darf der Takt kurz sein.
    pruflauf_intervall_minuten: int = 5

    # Obergrenze pro Durchgang. Schützt das knappe Amadeus-Kontingent, wenn
    # nach einem längeren Ausfall alle Alarme gleichzeitig fällig sind.
    pruflauf_max_alarme_pro_lauf: int = 20

    # --- CORS ------------------------------------------------------------
    # Für die iOS-App irrelevant (native Apps kennen keine CORS-Regel),
    # aber nützlich, falls du das Backend im Browser testest.
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Einmal laden, danach zwischenspeichern."""
    return Settings()
