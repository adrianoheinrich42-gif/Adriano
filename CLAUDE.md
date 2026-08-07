# CLAUDE.md — Projektwissen für Claude-Code-Sessions

Kompaktes Dauerwissen. Details stehen im Code und in `docs/`; hier nur, was man
zum Weiterarbeiten wirklich braucht. Sprache im Projekt: **Deutsch** (Code-
Kommentare, Doku, Commit-Messages).

## Ziel

Flugpreis-Alarm-App (Lern-/Portfolioprojekt). Nutzer legt einen Preisalarm an
(Strecke, Zeitraum, max. Stopps, max. Preis, optional Gepäck). Ein Backend prüft
die Preise **zeitgesteuert** und schickt bei einem passenden Angebot eine
**Push-Benachrichtigung**. Student: „AI for Business", Anfänger — Entscheidungen
anfängerfreundlich erklären, in kleinen Schritten arbeiten.

## Drei Leitplanken (nicht verletzen)

1. **Client ist dumm.** Zeigt Daten an, schickt Formulare. Jede Bewertung
   („gutes Angebot?") passiert im Backend. Der Client kennt nur *eine* URL: das
   eigene Backend.
2. **Kein Schlüssel im Client.** Amadeus-, Anthropic-, VAPID-Schlüssel liegen
   ausschließlich in Backend-Umgebungsvariablen. Nie ins Repo (`.env` ist
   gitignored).
3. **Claude entscheidet nicht, Claude formuliert.** Preisbewertung ist
   deterministische Statistik in Python. Claude macht nur (a) Sprache →
   Suchkriterien und (b) kurze Erklärtexte. Fällt Claude aus, funktioniert die
   Kernfunktion per Fallback weiter.

## Tech-Stack

- **Backend:** Python (Ziel 3.12; Repo läuft ab 3.11), FastAPI, SQLAlchemy 2.0
  async, Alembic, asyncpg, Pydantic v2 / pydantic-settings. Paketmanager **uv**.
- **DB:** PostgreSQL — lokal via Docker, später Supabase (Auth + DB).
- **Client:** **Web-App / PWA** — reines HTML/CSS/JS, **kein Framework**, **kein
  Node**. Ausgeliefert mit `python -m http.server`. (Früher iOS/Swift geplant —
  umgestellt, siehe `docs/PLATTFORM-WEB.md`.)
- **Flugdaten:** Amadeus Flight Offers Search (ab M5).
- **Push:** Web-Push / VAPID mit `pywebpush` (ab M8). Kein Apple-Konto nötig.
- **KI:** Claude API, Modell **`claude-haiku-4-5`**, mit Structured Output
  (Pydantic-Schema). Prompt-Caching lohnt bei Haiku erst ab 4096 Token Prefix —
  nicht vorab optimieren.
- **Qualität:** ruff (Lint+Format), mypy `strict`, pytest. Ziel-Version py311.

## Architektur

Zwei Prozesse, eine DB:
- **API** (`app.main:app`) — beantwortet Client-Anfragen, muss schnell sein.
- **Worker** (`app/jobs/`, ab M6) — langsame externe Calls (Amadeus, Push) im
  Zeittakt. Getrennt, damit ein Prüflauf die API nicht blockiert.

Ablauf: Alarm anlegen → Worker prüft fällige Alarme regelmäßig bei Amadeus →
jeder Lauf schreibt eine `flight_observation` (auch ohne Treffer) → passendes,
noch nicht gemeldetes Angebot → Push. Vollständig in `docs/PROJEKTPLAN.md` §4.

## Wichtige Ordner/Dateien

```
backend/app/
  main.py            FastAPI-App, Router, lifespan
  config.py          Settings aus ENV (DB-URL, CORS, Pooler-Schalter)
  db.py              async Engine/Session, is_database_reachable()
  api/routes/        Endpunkte — aktuell nur health.py (GET /health)
  models/            6 SQLAlchemy-Tabellen (+ mixins.py, __init__ importiert alle)
  core/ schemas/ services/ jobs/   leer, Zielorte für M2+ (siehe backend/README)
  alembic/           env.py (async, URL aus config), versions/ (1 Migration)
  tests/             test_health.py (ohne DB), integration/ (mit DB), conftest.py
web/                 Frontend: index.html, app.js, config.js, styles.css
docs/PROJEKTPLAN.md  Referenz: Architektur, Datenmodell, Meilensteine, Risiken
docs/PLATTFORM-WEB.md  iOS→Web-Wechsel + alle Deltas zum Projektplan
HANDOFF.md           aktueller Arbeitsstand (bei jeder Session aktuell halten)
```

## Datenmodell (6 Tabellen, `backend/app/models/`)

`users` (spiegelt Supabase-Auth-ID, keine Passwörter), `price_alerts` (Herzstück),
`flight_observations` (Preisverlauf, Strecke+Monat denormalisiert für streckenweite
Statistik), `flight_offers` (konkrete Angebote), `device_tokens` (Push-Ziel),
`notification_logs` (Versandprotokoll + Dedupe). Spalten/Constraints im Code.

## Coding-Regeln / Konventionen

- **Geld immer `integer` in Cent**, nie float.
- **IATA-Codes `String(3)`** (nicht CHAR) mit Regex-CHECK, der Großschreibung
  erzwingt. Textspalten mit CHECK statt PostgreSQL-ENUM.
- **Constraints gehören in die DB**, nicht nur in Pydantic — die DB ist die
  letzte Verteidigungslinie (Skripte/SQL umgehen Pydantic).
- **`ON DELETE CASCADE` ab `users`** (DSGVO: Konto löschen = alles weg).
- **Dedupe = DB-Garantie:** `UNIQUE` auf `notification_logs.dedupe_key`, nicht
  nur Programmlogik.
- **Alles Externe hinter austauschbarer Dependency/Protokoll** (Testbarkeit).
  Beispiel: `database_probe` in `health.py`, im Client `config.js`.
- **Zeit:** alles UTC/`timestamptz` speichern, Reisedaten als `date`, Umrechnung
  nur in der Anzeige.
- **Migrationen:** immer über Alembic. Erzeugte Migration **lesen** vor dem
  Anwenden. Angewendete Migration **nie** editieren → neue Revision. Neues Modell
  → Import in `app/models/__init__.py` (sonst leere Migration).
- **Frontend:** kein Framework/Node einführen, bis Formulare es verlangen.
  Fehler dem Nutzer als verständlicher deutscher Text zeigen, nie Statuscode.
- **Sekrete-Check vor jedem Commit:** kein `.env`, kein `.p8`, kein Key im Diff.

## Wichtige Entscheidungen (Kurzbegründung)

- **Web statt iOS:** kein Mac vorhanden, aber iPhone 15. PWA + Web-Push (ab
  iOS 16.4) läuft; spart 99 €/Jahr Apple. Details `docs/PLATTFORM-WEB.md`.
- **Supabase Auth statt Eigenbau:** Login/Reset/Hashing sind fehleranfällig;
  Backend prüft nur das JWT.
- **APScheduler (ab M6), 1 Worker-Instanz:** einfach, kein Redis. Grenze: zwei
  Instanzen = doppelte Läufe → dann externer Cron + `FOR UPDATE SKIP LOCKED`.
- **`/health` gibt immer HTTP 200** (Zustand im Body) — hält den Client simpel;
  echte 503-Readiness erst bei M12.

## Befehle

Backend (aus `backend/`):
```
uv sync                              # Abhängigkeiten
uv run alembic upgrade head          # Schema
uv run uvicorn app.main:app --reload # API → :8000  (/health, /docs)
uv run pytest -q                     # Tests
uv run ruff format . && uv run ruff check . && uv run mypy app
uv run alembic revision --autogenerate -m "..."   # neue Migration
```
Frontend (aus `web/`): `python -m http.server 3000` → http://localhost:3000
DB: `docker compose up -d db`. Kürzel im **Makefile** (`make help`).

## Für zukünftige Sessions unbedingt beachten

- **Zuerst `HANDOFF.md` lesen** — dort steht der exakte Stand + nächste Schritte.
- **Repo-Zustand real prüfen** (`git log`, `git status`), nicht nur Chat/Docs.
- **Verifizieren, nicht behaupten:** Änderungen mit Tests/curl belegen. Diese
  Umgebung hat oft keinen Docker-Daemon, aber Postgres ist per apt installierbar
  (`/usr/lib/postgresql/16/bin`, mit `initdb`/`pg_ctl` als User `postgres`
  starten) — so lässt sich der DB-Pfad echt testen.
- **Ohne DB:** `pytest` meldet `2 passed, 16 skipped` (Integrationstests
  überspringen sich selbst). Mit DB: `18 passed`. Beides ist „grün".
- **Branch:** `claude/flight-price-alert-app-8sh4sy`. Hier entwickeln, committen,
  pushen (`git push -u origin <branch>`). Keine PR ohne Auftrag.
- **Commit-Footer** (jeder Commit):
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011GZSyL9be1cXvHuh9bv4gd
  ```
  Modell-ID nie in Commits/Code schreiben.
- **`docs/PROJEKTPLAN.md`** ist die inhaltliche Referenz; bei Client/Push gilt
  **`docs/PLATTFORM-WEB.md`** vor. Beide bei größeren Änderungen aktuell halten.
