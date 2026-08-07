# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-3tzcq4` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei.

## Wo wir stehen

Meilensteine **M0** (Setup), **M1** (Datenbankmodell) und **M2** (Auth-Kette,
Backend-Seite) fertig, plus der Plattformwechsel iOS → Web.
Als Nächstes: **M3 (Alarm-CRUD)**.

**Ein offener Punkt aus M2 ist Nutzer-Aktion:** das Supabase-Projekt existiert
noch nicht (siehe unten). Der Backend-Code ist fertig und getestet — sobald
`SUPABASE_JWT_SECRET` in der `.env` steht, funktioniert er mit echten Token
ohne Codeänderung.

Meilenstein-Übersicht in `docs/PROJEKTPLAN.md` §5 (Client-Meilenstein M4/M8/M9
sind laut `docs/PLATTFORM-WEB.md` jetzt Web statt iOS).

## Was umgesetzt ist

- **M0 Backend:** FastAPI mit `GET /health` (prüft DB, antwortet immer HTTP 200),
  `config.py` (ENV), `db.py` (async Engine/Session).
- **M0 Infra:** `docker-compose.yml` (Postgres 16), `Dockerfile`, `Makefile`,
  `.gitignore` (schließt `.env`, `.p8` aus), `backend/.env.example`.
- **M1 Datenmodell:** 6 SQLAlchemy-Tabellen in `backend/app/models/` +
  `mixins.py`. Eine Alembic-Migration (`...6513957c2dba_initial_schema.py`).
  16 Integrationstests prüfen die DB-Zusicherungen (CHECKs, Kaskade, Dedupe).
- **M2 Auth-Kette** (neu, siehe nächster Abschnitt).
- **Plattformwechsel:** `web/` (Frontend, M0-Spiegel), `docs/PLATTFORM-WEB.md`.
  `ios/`-Ordner entfernt (liegt in Historie, Commit `def9ae6`).

## Zuletzt geändert — M2 (Auth-Kette)

Neue Dateien:
- `app/core/security.py` — `decode_supabase_token()`: prüft Signatur (HS256),
  `exp`, `aud` und — falls `SUPABASE_URL` gesetzt — `iss`; liefert
  `TokenClaims(user_id, email)`. Eigene Fehler `TokenError` (→ 401) und
  `AuthConfigError` (→ 500, weil das Backend falsch eingerichtet ist).
- `app/api/deps.py` — `get_token_claims` (Header `Authorization: Bearer`,
  **ohne** DB) und darauf aufbauend `get_current_user` (legt die `users`-Zeile
  an, prüft `is_active` → 403). Kurzform `CurrentUser` für alle Endpunkte.
- `app/services/users.py` — `get_or_create_user()`: ein einziges
  `INSERT … ON CONFLICT (id) DO UPDATE … RETURNING`, damit zwei gleichzeitige
  erste Requests nicht kollidieren.
- `app/api/routes/auth.py` — `GET /me` mit eigenem Antwortschema `MeResponse`.
- `tests/test_auth.py` (15 Tests, ohne DB), `tests/integration/test_auth_flow.py`
  (5 Tests, mit DB).

Geändert: `pyproject.toml` (+`pyjwt`), `app/config.py` (`supabase_url`,
`supabase_jwt_secret`, `supabase_jwt_audience`), `app/main.py` (Router),
`.env.example` (Supabase-Block nach oben, jetzt aktiv), `tests/conftest.py`
(`join_transaction_mode="create_savepoint"`, damit ein `commit()` im
getesteten Code die Test-Transaktion nicht beendet).

**Keine Migration nötig** — `users` gab es schon aus M1, `alembic check`
meldet keinen Drift.

### Zwei Entscheidungen, die man kennen sollte

- **Nur HS256 (symmetrisch).** Ein gemeinsames Geheimnis, kein Netzwerkabruf,
  keine Krypto-Bibliothek. Nutzt Supabase asymmetrische Schlüssel (JWKS), wird
  das ausschließlich in `app/core/security.py` ergänzt — die Endpunkte kennen
  nur `CurrentUser` und bleiben unverändert.
- **Nutzer-Anlage per Upsert beim ersten Request**, nicht per Supabase-Webhook.
  Weniger bewegliche Teile und selbstheilend: Auch wer sich vor dem ersten
  Backend-Start registriert hat, bekommt seine Zeile.

## Verifizierter Zustand (in dieser Umgebung geprüft)

- **Tests:** mit DB `38 passed`; ohne DB `17 passed, 21 skipped` (erwartetes
  Skip-Verhalten der Integrationstests). Beides ist „grün".
- `ruff format`/`ruff check` sauber, `mypy app` (strict) sauber,
  `alembic check` ohne Drift.
- **End-to-End per curl** gegen echtes Postgres 16 + uvicorn:
  `/me` ohne Token → **401**, mit kaputtem Token → **401** mit deutschem Text,
  mit selbst signiertem gültigem Token → **200** und
  `{"id":"aaaa…","email":"echt@beispiel.de","max_active_alerts":5,…}`.
  Nach zwei Aufrufen steht in `users` **genau eine** Zeile.
  → **Abnahmekriterium M2 (Backend) erfüllt.**

## Bekannte offene Punkte / Fallstricke

- **Supabase-Projekt fehlt noch (Nutzer-Aktion).** Anlegen, dann in
  `backend/.env`: `SUPABASE_URL` (Project URL) und `SUPABASE_JWT_SECRET`
  (Project Settings → API → JWT Secret). Erst danach lässt sich mit einem
  echten Login-Token testen. Findet sich dort **kein** symmetrisches Secret
  mehr, sondern nur Signing Keys/JWKS → siehe Entscheidung oben, dann muss
  `security.py` auf RS256/ES256 erweitert werden (`pyjwt[crypto]`).
- **Kein Docker-Daemon in dieser Sandbox.** Für echte DB-Tests Postgres per apt
  installieren und mit `initdb`/`pg_ctl` als User `postgres` starten (Binary:
  `/usr/lib/postgresql/16/bin`). Achtung: Das Datenverzeichnis muss für den
  User `postgres` erreichbar sein — `/var/lib/postgresql/<name>` funktioniert,
  ein Pfad unter `/tmp/claude-*` nicht (Permission denied). Dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm@127.0.0.1:5432/flugalarm`.
- **Token ohne `email`** (reine Telefon-Anmeldung) wird mit 401 abgelehnt, weil
  `users.email` NOT NULL ist. Falls das je gebraucht wird: Spalte nullable
  machen (eigene Migration), nicht die Prüfung aufweichen.
- **Web-Push braucht später HTTPS** (iPhone, außer localhost) + „zum
  Home-Bildschirm hinzufügen". Erst im Push-Meilenstein relevant.
- **`device_tokens` wird im Push-Meilenstein angepasst** (Web-Push-Subscription
  statt APNs-Token, `environment`-Spalte entfällt) — als eigene Migration.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M0, M1, M2 (Backend) abgeschlossen und gepusht. **Noch nicht begonnen: M3.**
`app/jobs/` ist leerer Platzhalter; `app/schemas/` enthält noch nichts (die
M2-Schemata liegen bewusst bei ihren Endpunkten bzw. in `core/security.py`).
Endpunkte: `GET /health`, `GET /me`. Das Web-Frontend kennt noch keinen Login.

## Nächste Schritte — M3 (Alarm-CRUD), in Reihenfolge

1. **Schemata** in `app/schemas/price_alert.py`: `PriceAlertCreate`,
   `PriceAlertUpdate`, `PriceAlertResponse` (Pydantic v2). Regeln spiegeln, was
   die DB-CHECKs schon erzwingen: IATA-Codes groß, Preis in **Cent**,
   `date_to >= date_from`, Stopps ≥ 0.
2. **Service** `app/services/price_alerts.py`: anlegen, auflisten, ändern,
   löschen — **immer** mit `user_id` in der WHERE-Klausel, damit niemand
   fremde Alarme sieht. Beim Anlegen `users.max_active_alerts` prüfen
   (→ 409 statt 500 aus der DB).
3. **Router** `app/api/routes/price_alerts.py`: `POST /alerts`,
   `GET /alerts`, `GET /alerts/{id}`, `PATCH /alerts/{id}`,
   `DELETE /alerts/{id}` — alle mit `user: CurrentUser`. In `main.py` einhängen.
4. **Tests:** ohne DB die Schema-Regeln (Validierung), mit DB die Fremdzugriffe
   (Alarm von Nutzer A ist für Nutzer B **404**, nicht 403 — sonst verrät man
   dessen Existenz) und die `max_active_alerts`-Grenze.

**Abnahme M3:** Ein angemeldeter Nutzer kann Alarme anlegen, sehen, ändern und
löschen; fremde Alarme sind unsichtbar.

Danach laut Projektplan: M5 (Amadeus) → M6 (Prüflauf) → M7 (Statistik).
Alles Backend, komplett ohne Mac auf Windows machbar.
