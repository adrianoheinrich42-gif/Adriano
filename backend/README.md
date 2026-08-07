# Backend (M0)

FastAPI-Anwendung mit einem `/health`-Endpunkt, der die Datenbankverbindung
prüft. Tabellen kommen in M1 per Alembic.

## Schnellstart

```bash
cp .env.example .env          # Werte passen für die lokale Entwicklung
uv sync                       # Abhängigkeiten installieren
docker compose -f ../docker-compose.yml up -d db
uv run uvicorn app.main:app --reload
```

- API-Doku: <http://127.0.0.1:8000/docs>
- Health:   <http://127.0.0.1:8000/health>

```console
$ curl -s localhost:8000/health
{"status":"ok","database":"ok","version":"0.1.0","environment":"local"}
```

Ohne laufende Datenbank kommt stattdessen:

```json
{"status":"degraded","database":"unavailable","version":"0.1.0","environment":"local"}
```

Beides ist HTTP 200 — der Endpunkt soll auch dann antworten, wenn die Datenbank
weg ist. Der Grund steht als Kommentar in `app/api/routes/health.py`.

## Befehle

```bash
uv run pytest -q          # Tests (brauchen keine Datenbank)
uv run ruff check .       # Linter
uv run ruff format .      # Formatierung
uv run mypy app           # Typprüfung (strict)
```

Vom Repo-Wurzelverzeichnis aus geht auch `make test`, `make lint`, `make check`.

## Struktur

```
app/
├── main.py                 # FastAPI-App, Router einhängen
├── config.py               # Einstellungen aus Umgebungsvariablen
├── db.py                   # Engine, Session, Verbindungsprüfung
├── api/routes/health.py    # GET /health
├── core/                   # (leer) Security, Rate Limiting  → ab M2
├── models/                 # (leer) SQLAlchemy-Tabellen      → ab M1
├── schemas/                # (leer) Pydantic-Schemata        → ab M3
├── services/               # (leer) Fachlogik                → ab M5
└── jobs/                   # (leer) Scheduler                → ab M6
```

Die leeren Pakete sind Absicht: Sie zeigen, wohin was gehört. Die vollständige
Begründung der Struktur steht in `docs/PROJEKTPLAN.md`, Abschnitt 6.1.

## Zwei Details, die später wichtig werden

**Testbarkeit des Health-Checks.** Die Datenbankprüfung liegt als eigene
FastAPI-Dependency (`database_probe`) vor. Dadurch können die Tests sie
ersetzen und laufen ohne Datenbank in unter einer Sekunde. Dieses Muster —
alles Externe hinter einer austauschbaren Dependency — zieht sich durch das
ganze Projekt.

**Supabase-Pooler.** Läuft die Datenbank später hinter dem Supabase-Pooler im
Transaction-Modus (Port 6543), muss `DATABASE_DISABLE_STATEMENT_CACHE=true`
gesetzt werden. Sonst gibt es sporadische Fehler zu „prepared statement already
exists". Siehe Projektplan, Abschnitt 2.3.
