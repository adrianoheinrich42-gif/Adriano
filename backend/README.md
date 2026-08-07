# Backend (M0 + M1)

FastAPI-Anwendung mit `/health`-Endpunkt und dem vollständigen Datenbankschema
des MVP (sechs Tabellen, per Alembic migriert).

## Schnellstart

```bash
cp .env.example .env          # Werte passen für die lokale Entwicklung
uv sync                       # Abhängigkeiten installieren
docker compose -f ../docker-compose.yml up -d db
uv run alembic upgrade head   # Schema anlegen
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
uv run pytest -q             # Tests
uv run alembic upgrade head  # Schema aktualisieren
uv run alembic check         # weichen Modelle und Datenbank ab?
uv run ruff check .          # Linter
uv run ruff format .         # Formatierung
uv run mypy app              # Typprüfung (strict)
```

Vom Repo-Wurzelverzeichnis aus kürzer: `make test`, `make migrate`,
`make check`. `make help` listet alles auf.

## Struktur

```
app/
├── main.py                 # FastAPI-App, Router einhängen
├── config.py               # Einstellungen aus Umgebungsvariablen
├── db.py                   # Engine, Session, Verbindungsprüfung
├── api/routes/health.py    # GET /health
├── models/                 # die sechs Tabellen (M1)
├── core/                   # (leer) Security, Rate Limiting  → ab M2
├── schemas/                # (leer) Pydantic-Schemata        → ab M3
├── services/               # (leer) Fachlogik                → ab M5
└── jobs/                   # (leer) Scheduler                → ab M6
alembic/versions/           # Migrationen (chronologisch benannt)
tests/
├── test_health.py          # ohne Datenbank
└── integration/            # mit Datenbank; werden ohne sie übersprungen
```

Die leeren Pakete sind Absicht: Sie zeigen, wohin was gehört. Die vollständige
Begründung der Struktur steht in `docs/PROJEKTPLAN.md`, Abschnitt 6.1.

## Migrationen

Schema-Änderungen laufen **immer** über Alembic, nie über direktes SQL:

```bash
# 1. Modell in app/models/ ändern
# 2. Migration erzeugen lassen
uv run alembic revision --autogenerate -m "gepaeckfilter ergaenzt"
# 3. Erzeugte Datei in alembic/versions/ LESEN und prüfen
# 4. Anwenden
uv run alembic upgrade head
```

Drei Regeln, die Ärger sparen:

1. **Die erzeugte Migration immer lesen.** Autogenerate erkennt neue Spalten
   und Tabellen zuverlässig, aber Umbenennungen sieht es als „löschen und neu
   anlegen" — was Daten vernichtet.
2. **Eine angewendete Migration nicht mehr bearbeiten.** Änderungen kommen als
   neue Revision. Sonst laufen deine Datenbank und die deines Servers
   auseinander.
3. **Neues Modell? Import in `app/models/__init__.py` nicht vergessen.**
   Sonst erzeugt Autogenerate klaglos eine leere Migration.

`uv run alembic check` sagt dir, ob Modelle und Datenbank auseinanderlaufen.

## Drei Details, die später wichtig werden

**Testbarkeit des Health-Checks.** Die Datenbankprüfung liegt als eigene
FastAPI-Dependency (`database_probe`) vor. Dadurch können die Tests sie
ersetzen und laufen ohne Datenbank in unter einer Sekunde. Dieses Muster —
alles Externe hinter einer austauschbaren Dependency — zieht sich durch das
ganze Projekt.

**Integrationstests überspringen sich selbst.** Läuft keine Datenbank, meldet
`pytest` „skipped" statt „failed". So bleibt der Testlauf auch ohne Docker
grün, und du siehst trotzdem, dass etwas nicht geprüft wurde.

**Die Datenbank ist die letzte Verteidigungslinie.** Regeln wie „Startflughafen
≠ Zielflughafen" oder „nur eine Benachrichtigung je Angebot" stehen als
CHECK- bzw. UNIQUE-Constraint im Schema — nicht nur in Python. Pydantic schützt
nur, was durch die API kommt; ein Skript oder eine SQL-Konsole umgeht das.

