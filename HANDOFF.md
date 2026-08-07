# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-3tzcq4` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

```
68a2125 M3 — CRUD für Preisalarme
9a5aefa M2 — Auth-Kette mit Supabase-JWT
6033f2f docs: CLAUDE.md und HANDOFF.md
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst
```

## Wo wir stehen

**M0–M3 fertig** (Setup · Datenmodell · Auth · Alarm-CRUD), dazu der
Plattformwechsel iOS → Web. Das Backend kann alles, was der Nutzer *eingibt* —
es sucht nur noch keine Flüge und verschickt nichts.

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts`.
`app/jobs/` ist noch leer. Das Web-Frontend zeigt nur den Backend-Status,
kennt weder Login noch Alarme.

**Als Nächstes: M5 (Amadeus)** — Begründung und Schritte unten.
Meilenstein-Übersicht: `docs/PROJEKTPLAN.md` §5; für Client/Push gilt
`docs/PLATTFORM-WEB.md` vor.

## Was umgesetzt ist

- **M0** — FastAPI, `GET /health` (prüft DB, antwortet immer HTTP 200),
  `config.py`, `db.py`; `docker-compose.yml` (Postgres 16), `Dockerfile`,
  `Makefile` (`make help`), `.env.example`.
- **M1** — 6 Tabellen in `app/models/`, eine Alembic-Migration
  (`…6513957c2dba_initial_schema.py`). 16 Integrationstests auf die
  DB-Zusicherungen (CHECKs, Kaskade, Dedupe).
- **M2** — `core/security.py` (JWT HS256: Signatur, `exp`, `aud`, optional
  `iss`), `api/deps.py` (`get_token_claims` ohne DB, `get_current_user` mit
  Nutzer-Anlage, Kurzform `CurrentUser`), `services/users.py` (Upsert),
  `GET /me`.
- **M3** — `schemas/price_alert.py` (Create/Update/Response + geteilte
  `pruefe_feldkombination()`), `services/price_alerts.py` (CRUD, Besitz,
  Limit), `api/routes/price_alerts.py`. Keine Migration nötig, die Tabelle
  stammt aus M1.
- **Plattformwechsel** — `web/` (Frontend, M0-Spiegel), `docs/PLATTFORM-WEB.md`.
  `ios/` entfernt (liegt in der Historie, Commit `def9ae6`).

## Dauerhafte Entscheidungen aus M2/M3

Ausführlich in `CLAUDE.md` §„Wichtige Entscheidungen"; hier nur die Merksätze:

- **Nur HS256** (gemeinsames Geheimnis), kein JWKS-Abruf. Eine Umstellung auf
  RS256/ES256 betrifft ausschließlich `core/security.py`.
- **Nutzer-Zeile per Upsert** beim ersten authentifizierten Request, kein
  Supabase-Webhook.
- **`user_id` steht in jeder Abfrage in der WHERE-Klausel** — fremde Objekte
  können gar nicht erst im Ergebnis auftauchen. Fremd → **404, nie 403**.
- **PATCH validiert den zusammengeführten Stand**, nicht die geschickten
  Felder; bei Verstoß Rollback, damit die schon am ORM-Objekt hängenden
  Änderungen nicht später mitgeschrieben werden.
- **Alarm-Limit mit `SELECT … FOR UPDATE`** auf die Nutzer-Zeile; gezählt
  werden nur **aktive** Alarme, Pausieren macht Platz.
- **Löschen löscht wirklich** (Kaskade). Wer den Preisverlauf behalten will,
  pausiert (`is_active = false`).

## Verifizierter Zustand (in dieser Umgebung geprüft)

- **Tests:** mit DB `71 passed`; ohne DB `39 passed, 32 skipped` (erwartet —
  die Integrationstests überspringen sich selbst). Beides ist „grün".
- `ruff format` / `ruff check` sauber, `mypy app` (strict) sauber,
  `alembic check` ohne Drift.
- **End-to-End per curl** gegen echtes Postgres 16 + uvicorn, zwei Nutzer:
  `POST /alerts` mit `"origin":"muc"` → **201**, gespeichert als `MUC`;
  PATCH Preis → 200; PATCH mit unsinnigem Zusammenspiel → **422** (deutscher
  Text, Alarm bleibt unverändert); fremder GET/PATCH/DELETE → **404**, fremde
  Liste `[]`; ohne Token → **401**; DELETE → 204, danach GET → 404.
  `GET /me` ohne Token 401, mit gültigem Token 200 und danach genau **eine**
  Zeile in `users`.

## Offene Punkte / Fallstricke

- **Supabase-Projekt fehlt (Nutzer-Aktion).** Anlegen, dann in `backend/.env`:
  `SUPABASE_URL` und `SUPABASE_JWT_SECRET` (Dashboard → Project Settings →
  API). Ohne Secret antworten geschützte Endpunkte mit 500, `/health` bleibt
  unberührt. Gibt es dort **kein** symmetrisches Secret mehr, sondern nur
  Signing Keys/JWKS → `security.py` auf RS256/ES256 erweitern
  (`pyjwt[crypto]`); die Endpunkte bleiben unverändert.
- **`.env` fehlt nach Klonen/Entpacken immer** (gitignored) →
  `cp .env.example .env`. Ebenso fehlt `.venv` → `uv sync`.
- **Postgres in dieser Sandbox:** kein Docker-Daemon, aber per apt vorhanden
  (`/usr/lib/postgresql/16/bin`, mit `initdb`/`pg_ctl` als User `postgres`
  starten). Das Datenverzeichnis muss für `postgres` erreichbar sein —
  `/var/lib/postgresql/<name>` geht, ein Pfad unter `/tmp/claude-*` nicht
  (Permission denied). Dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm@127.0.0.1:5432/flugalarm`.
  **Der Server überlebt keinen Container-Neustart** — läuft `pytest` plötzlich
  mit lauter `s`, ist nur die DB weg, nicht der Code kaputt.
- **`GET /alerts` ohne Paginierung.** Bei 5 Alarmen pro Nutzer egal; nachrüsten,
  wenn das Limit steigt oder Angebote mitgeliefert werden.
- **Token ohne `email`** (reine Telefon-Anmeldung) → 401, weil `users.email`
  NOT NULL ist. Falls nötig: Spalte nullable machen (eigene Migration), nicht
  die Prüfung aufweichen.
- **Web-Push braucht HTTPS** (iPhone, außer localhost) + „zum Home-Bildschirm
  hinzufügen". Erst im Push-Meilenstein relevant.
- **`device_tokens` wird in M8 angepasst** (Web-Push-Subscription statt
  APNs-Token, `environment` entfällt) — als eigene Migration.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M3 ist abgeschlossen, committet (`68a2125`) und gepusht. Nichts ist halbfertig,
kein Zwischenstand liegt herum. Der nächste Meilenstein beginnt bei null.

## Nächste Schritte — M5 (Amadeus-Anbindung)

**Warum M5 vor M4 (Web-Client):** Dann hat der Client beim Bauen schon echte
Daten zu zeigen, statt zweimal gebaut zu werden.

1. **Zugang holen** (Nutzer-Aktion): Konto auf `developers.amadeus.com`,
   Self-Service-App anlegen → `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`
   in `.env` (Platzhalter stehen schon in `.env.example`, Test-Umgebung
   `https://test.api.amadeus.com`).
2. **Client** `app/services/amadeus.py`: OAuth2-Token holen und zwischen-
   speichern (~30 min gültig), dann `GET /v2/shopping/flight-offers`.
   `httpx` als Abhängigkeit ergänzen (steckt bislang nur in der Dev-Gruppe).
   Hinter einer austauschbaren Dependency, damit Tests ihn ersetzen können.
3. **Normalisierung:** Amadeus-Antwort → schlanke interne Struktur (Preis in
   **Cent**, Stopps, Zeiten, Fluggesellschaft). Preise kommen als String wie
   `"249.90"` — sauber in Cent umrechnen, nie über float.
4. **Test-Fixture:** eine echte Antwort als JSON in `tests/fixtures/` legen und
   die Normalisierung ohne Netz dagegen testen. Die Suite bleibt so offline.
5. **Noch kein Scheduler** — laut Projektplan reicht ein Skript oder Endpunkt,
   der einmal sucht und das Ergebnis ausgibt.

**Abnahme M5:** Eine Suche MUC→BCN liefert normalisierte Angebote; die
Normalisierung ist gegen die gespeicherte Fixture getestet.

### Danach

**M4 (Web-Client):** Supabase-Login im Browser (`supabase-js` per CDN, kein
Node), Token im Speicher halten und als `Authorization: Bearer` mitschicken,
Alarmliste + Anlegen-Formular, Lade-/Leer-/Fehlerzustand sichtbar. Fehler als
deutschen Text, nie als Statuscode.
Dann M6 (Prüflauf, APScheduler) → M7 (Statistik) → M8 (Push).
