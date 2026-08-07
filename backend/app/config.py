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

    # --- Web-Push / VAPID (M8) -------------------------------------------
    # Das Schlüsselpaar erzeugst du einmal selbst (kostenlos):
    #     uv run python -m scripts.vapid_schluessel
    # Der öffentliche Schlüssel geht an den Browser, der private bleibt hier.
    # Beide gehören in `.env`, nie ins Repository.
    vapid_public_key: str = ""
    vapid_private_key: str = ""

    # Pflichtangabe des Web-Push-Standards: eine Kontaktadresse, an die sich
    # der Push-Dienst wenden kann, wenn unser Server Unsinn schickt. Muss
    # `mailto:` oder `https://` sein.
    vapid_subject: str = "mailto:flugalarm@example.org"

    # Höchstens eine Meldung je Alarm in diesem Zeitraum. Ohne diese Bremse
    # würde ein Alarm, dessen Limit großzügig gesetzt ist, bei jedem Prüflauf
    # melden — und die App landet stummgeschaltet.
    push_abkuehlphase_stunden: int = 6

    # Ausnahme von der Abkühlphase: So viel Prozent muss ein Preis besser sein
    # als die letzte Meldung, damit trotzdem gemeldet wird. „Jetzt 2 € billiger"
    # ist keine zweite Nachricht wert, „jetzt 40 € billiger" schon.
    push_mindest_verbesserung_prozent: float = 5.0

    @property
    def push_aktiviert(self) -> bool:
        """Ohne Schlüsselpaar läuft alles weiter — nur eben ohne Versand."""
        return bool(self.vapid_public_key and self.vapid_private_key)

    # --- Claude / Anthropic (M10) ----------------------------------------
    # Schlüssel von console.anthropic.com. Er steht ausschließlich hier in
    # der Umgebung, nie im Repository und nie im Browser (Leitplanke 2).
    anthropic_api_key: str = ""

    # Projektentscheidung: das günstigste Modell reicht. Beide Claude-
    # Aufgaben (kurzer Erklärtext, später Sprache → Suchkriterien) sind
    # einfach und gut abgegrenzt. Erst messen, dann größer werden.
    anthropic_model: str = "claude-haiku-4-5"

    # Der Text ist Beiwerk und darf den Prüflauf nicht aufhalten. Nach
    # dieser Zeit greift der deterministische Baukasten.
    anthropic_timeout_seconds: float = 8.0

    # Ein einziger Wiederholungsversuch. Mehr würde die Wartezeit
    # vervielfachen, um einen Satz zu retten, den wir auch selbst schreiben
    # können.
    anthropic_max_retries: int = 1

    # Titel und Text zusammen sind gut 60 Token. 300 lässt Luft und
    # begrenzt zugleich, was ein Ausrutscher kosten kann.
    anthropic_max_tokens: int = 300

    @property
    def claude_aktiviert(self) -> bool:
        """Ohne Schlüssel formuliert der Baukasten — die App läuft vollständig."""
        return bool(self.anthropic_api_key)

    # --- CORS ------------------------------------------------------------
    # Welche Herkunft darf der Browser haben, wenn er das Backend anspricht?
    #
    # `localhost` und `127.0.0.1` sind **derselbe Rechner, aber für den
    # Browser zwei verschiedene Herkünfte**. Wer die App über die eine Adresse
    # öffnet und nur die andere freigegeben hat, bekommt „Keine Verbindung zum
    # Server" — obwohl das Backend läuft und im Log ein 200 steht. Genau das
    # ist beim Browsertest passiert, deshalb stehen beide hier.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    """Einmal laden, danach zwischenspeichern."""
    return Settings()
