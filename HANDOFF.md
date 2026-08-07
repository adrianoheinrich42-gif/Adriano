# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/flight-price-alert-app-8sh4sy` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei.

## Wo wir stehen

Meilensteine **M0** (Setup) und **M1** (Datenbankmodell) fertig, plus der
**Plattformwechsel iOS → Web**. Backend läuft und ist getestet; das
Web-Frontend zeigt den Backend-Status. Als Nächstes: **M2 (Auth-Kette)**.

Meilenstein-Übersicht in `docs/PROJEKTPLAN.md` §5 (Client-Meilenstein M4/M8/M9
sind laut `docs/PLATTFORM-WEB.md` jetzt Web statt iOS).

## Was umgesetzt ist

- **M0 Backend:** FastAPI mit `GET /health` (prüft DB, antwortet immer HTTP 200),
  `config.py` (ENV), `db.py` (async Engine/Session). 2 Tests ohne DB.
- **M0 Infra:** `docker-compose.yml` (Postgres 16), `Dockerfile`, `Makefile`,
  `.gitignore` (schließt `.env`, `.p8` aus), `backend/.env.example`.
- **M1 Datenmodell:** 6 SQLAlchemy-Tabellen in `backend/app/models/` +
  `mixins.py`. Eine Alembic-Migration (`...6513957c2dba_initial_schema.py`).
  16 Integrationstests prüfen die DB-Zusicherungen (CHECKs, Kaskade, Dedupe).
- **Plattformwechsel:** `web/` (Frontend, M0-Spiegel), `docs/PLATTFORM-WEB.md`.
  `ios/`-Ordner entfernt (liegt in Historie, Commit `def9ae6`).

## Zuletzt geändert (letzter Commit `99334da`, „Plattformwechsel … PWA")

Neu: `web/index.html`, `web/app.js`, `web/config.js`, `web/styles.css`,
`web/README.md`, `docs/PLATTFORM-WEB.md`.
Geändert: `README.md`, `Makefile`, `docs/PROJEKTPLAN.md` (Verweis-Banner,
Apple-Konto als entfallen markiert).
Gelöscht: der komplette `ios/`-Ordner.

Commit-Historie:
```
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst (Backend + iOS, iOS später entfernt)
1465cc0 docs: Projektplan
```

## Verifizierter Zustand (in dieser Umgebung geprüft)

- Backend `/health` liefert mit laufender DB `{"status":"ok","database":"ok"}`,
  ohne DB `"degraded"` — beide HTTP 200.
- Web-Frontend: alle Dateien HTTP 200 über `python -m http.server`; CORS-Freigabe
  für `localhost:3000` greift im Preflight und im GET.
- `ruff check` und `mypy app` sauber. Migration: `upgrade head` auf leerer DB,
  `downgrade base`, erneut `upgrade`, `alembic check` ohne Drift — alles ok.
- **Tests:** mit DB `18 passed`; ohne DB `2 passed, 16 skipped` (erwartetes
  Skip-Verhalten der Integrationstests).

## Bekannte offene Punkte / Fallstricke

- **Kein Docker-Daemon in dieser Sandbox.** Für echte DB-Tests Postgres per apt
  installieren und mit `initdb`/`pg_ctl` als User `postgres` starten (Binary:
  `/usr/lib/postgresql/16/bin`), dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm:flugalarm@127.0.0.1:5432/flugalarm`.
- **Xcode-Projekt existierte, wurde aber nie kompiliert** (kein Mac) — jetzt
  ohnehin entfernt. Kein offenes iOS-Thema mehr.
- **Web-Push braucht später HTTPS** (iPhone, außer localhost) + „zum
  Home-Bildschirm hinzufügen". Erst im Push-Meilenstein relevant.
- **`device_tokens` wird im Push-Meilenstein angepasst** (Web-Push-Subscription
  statt APNs-Token, `environment`-Spalte entfällt) — als eigene Migration.
- Keine echten Bugs bekannt. `python-multipart` o. Ä. noch nicht nötig.

## Exakter Arbeitspunkt

M0 und M1 abgeschlossen und gepusht. **Noch nicht begonnen: M2.**
`app/core/`, `app/schemas/`, `app/services/`, `app/jobs/` sind leere Platzhalter.
Es gibt genau einen Endpunkt (`/health`) und keine Auth.

## Nächste Schritte — M2 (Auth-Kette), in Reihenfolge

1. **Supabase-Projekt** anlegen (Nutzer-Aktion). Klären: symmetrisches
   `JWT_SECRET` oder asymmetrisch (JWKS)? — bestimmt die Prüf-Logik. ENV-Keys
   `SUPABASE_URL`, `SUPABASE_JWT_SECRET` in `.env.example` sind schon vermerkt.
2. **JWT-Prüfung** in `app/core/security.py`: Signatur prüfen, User-ID (`sub`)
   herausziehen. Bibliothek ergänzen (`pyjwt`, ggf. `cryptography`).
3. **Dependency** `get_current_user` in `app/api/deps.py` (liest
   `Authorization: Bearer`, gibt User-ID/`User` zurück, sonst 401).
4. **`GET /me`** in `app/api/routes/auth.py` (Router in `main.py` einhängen) —
   gibt mit gültigem Token die User-ID zurück.
5. **User-Anlage:** beim ersten authentifizierten Request `users`-Zeile per
   Upsert anlegen (Supabase-ID = `users.id`).
6. **Tests:** ohne Token → 401; mit gefälschtem/gültigem Token (Test-Secret) →
   passendes Ergebnis. Muster wie `test_health.py` (Dependency überschreiben),
   kein echter Supabase-Call im Test.

**Abnahme M2:** `GET /me` gibt mit gültigem JWT die User-ID zurück, ohne 401.

Danach laut Projektplan: M3 (Alarm-CRUD) → M5 (Amadeus) → M6 (Prüflauf) →
M7 (Statistik). Alles Backend, komplett ohne Mac auf Windows machbar.
