# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
M6 — Prüflauf: Alarme und Flugsuche verbunden   ← neu in dieser Session
db30665 M5 — Amadeus-Anbindung
68a2125 M3 — CRUD für Preisalarme
9a5aefa M2 — Auth-Kette mit Supabase-JWT
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst
```

> **Achtung, Branch-Wechsel.** Die vorherige Session lief auf
> `claude/project-handoff-continuation-3tzcq4`; dieser Branch ist der direkte
> Nachfolger und enthält dessen komplette Historie. Es gibt keinen zweiten
> Entwicklungsstrang.

## Wo wir stehen

**M0–M3, M5 und M6 fertig** (Setup · Datenmodell · Auth · Alarm-CRUD ·
Amadeus-Anbindung · Prüflauf), dazu der Plattformwechsel iOS → Web.

Damit ist zum ersten Mal die **Kernfunktion vollständig**: Ein Nutzer legt
einen Alarm an, und das Backend prüft ihn von selbst regelmäßig bei Amadeus
und speichert Preisverlauf und passende Angebote. Was noch fehlt, ist die
Benachrichtigung (M8) und ein Client, der mehr zeigt als den Serverstatus (M4).

**Noch 7 Meilensteine bis „fertig": M4, M7–M12.**

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts`.
Prozesse: API (`app.main:app`) **und** Worker (`app.jobs.worker`).

Meilenstein-Übersicht: `docs/PROJEKTPLAN.md` §5; für Client/Push gilt
`docs/PLATTFORM-WEB.md` vor.

## Was umgesetzt ist

- **M0** — FastAPI, `GET /health` (prüft DB, antwortet immer HTTP 200),
  `config.py`, `db.py`; `docker-compose.yml` (Postgres 16), `Dockerfile`,
  `Makefile` (`make help`), `.env.example`.
- **M1** — 6 Tabellen in `app/models/`, eine Alembic-Migration
  (`…6513957c2dba_initial_schema.py`). 16 Integrationstests auf die
  DB-Zusicherungen (CHECKs, Kaskade, Dedupe).
- **M2** — `core/security.py` (JWT HS256), `api/deps.py`, `services/users.py`
  (Upsert), `GET /me`.
- **M3** — `schemas/price_alert.py`, `services/price_alerts.py`,
  `api/routes/price_alerts.py`.
- **M5** — `services/amadeus.py` (Client + reine Normalisierung),
  `schemas/flight_offer.py`, `scripts/amadeus_suche.py`, Fixture.
- **M6** — siehe nächster Abschnitt.
- **Plattformwechsel** — `web/`, `docs/PLATTFORM-WEB.md`; `ios/` entfernt
  (in der Historie, Commit `def9ae6`).

## Zuletzt geändert — M6 (Prüflauf)

- **`app/services/pruflauf.py`** — der Meilenstein. Zwei Hälften wie in
  `amadeus.py`:
  - *rein:* `alarm_zu_suchanfragen()` (→ **Liste**), `ist_faellig()`,
    `ortszeit_als_utc()`, `bilde_offer_hash()`, `_angebot_als_zeile()`.
  - *mit DB:* `finde_faellige_alarme()`, `pruefe_alarm()` (ein Alarm),
    `pruefe_faellige_alarme()` (ein Durchgang), Ergebnistypen `LaufErgebnis`
    und `LaufBericht`.
  Die Suche kommt als Protokoll `Flugsuche` herein — deshalb braucht kein Test
  Amadeus-Zugangsdaten und **kein Test geht ins Netz**.
- **`app/jobs/worker.py`** — zweiter Prozess, APScheduler. `lauf_sicher()`
  fängt garantiert alles ab: Eine Ausnahme im Job darf den Scheduler nie
  beenden. `max_instances=1` (keine Parallelläufe), `coalesce=True` (verpasste
  Takte werden nicht nachgeholt). Startet sofort einen ersten Lauf und fährt
  auf SIGINT/SIGTERM sauber herunter.
- **`tests/attrappen.py`** — `FlugsucheAttrappe` (merkt sich alle Anfragen,
  filtert wie der echte Client nach Umstiegen) plus `baue_alarm()`,
  `baue_angebot()`, `baue_segment()`, `lade_fixture_angebote()`.
- **Tests:** `tests/test_pruflauf.py` (29, ohne DB), `tests/test_worker.py`
  (6, ohne DB), `tests/integration/test_pruflauf.py` (21, mit DB).
- Geändert: `config.py` + `.env.example` (Worker-Block), `pyproject.toml`
  (`apscheduler`; mypy-Ausnahme, weil APScheduler keine Typen mitliefert),
  `Makefile` (`make worker`), `docker-compose.yml` (Dienst `worker`),
  `backend/README.md` (Struktur war veraltet).

**Keine Migration nötig** — M6 nutzt nur bestehende Tabellen. `alembic check`
meldet keinen Drift.

### Entscheidungen aus M6

Ausführlich in `CLAUDE.md`; hier die Merksätze:

- **`alarm_zu_suchanfragen()` gibt eine Liste zurück** — vorerst mit genau
  einem Eintrag. Der Alarm nennt einen *Zeitraum*, die API will *ein* Datum.
  Der Datums-Fächer über den Zeitraum kostet pro Alarm ein Vielfaches an
  API-Anfragen und kommt später; weil der Prüflauf schon jetzt über eine Liste
  iteriert, ist das dann eine Änderung an **einer** Stelle.
  Die eine Anfrage heute: Hinflug = frühester erlaubter Tag; Rückflug =
  Hinflug + `min_trip_duration_days` (falls gesetzt), sonst
  `latest_return_date`, in beiden Fällen gedeckelt auf `latest_return_date`;
  fällt er auf den Hinflugtag oder davor → Einwegsuche.
- **Ortszeit wird als UTC gespeichert, nicht umgerechnet** (`ortszeit_als_utc`).
  Wanduhrzeit stimmt, Zeitpunkt nicht — Dauern deshalb **immer** aus
  `dauer_minuten`, nie durch Abziehen zweier gespeicherter Zeiten.
- **Flüge über die Datumsgrenze nach Osten werden übersprungen.** Tokio 21:00
  ab, Honolulu 09:00 an am selben Tag: als Wanduhrzeit korrekt, als Zeitpunkt
  eine negative Dauer — der CHECK `ck_offers_outbound_time_order` verbietet
  das. Übersprungen statt gespeichert, wie bei kaputten Angeboten in M5.
- **`last_checked_at` wird auch nach einem Fehler gesetzt**, sonst hämmert der
  Worker im Minutentakt gegen eine gerade kaputte Schnittstelle.
- **`min_price_cents` in der Beobachtung ist der günstigste *gefundene*
  Preis**, nicht der günstigste passende. Auch ein Angebot über dem Limit ist
  ein Datenpunkt für den Preisverlauf.
- **Ein kaputter Alarm beendet den Durchgang nicht** — Rollback, protokollieren,
  weiter mit dem nächsten.
- **Kein `FOR UPDATE SKIP LOCKED`** — es läuft genau eine Worker-Instanz.

## Verifizierter Zustand (zuletzt real nachgeprüft, nicht nur behauptet)

- **Tests:** mit DB `168 passed`; ohne DB `115 passed, 53 skipped`. Beides grün.
  Diese Zahlen sind der Soll-Wert für die nächste Session — weicht etwas ab,
  ist etwas kaputt oder es kam Neues dazu.
- `ruff check` sauber, `ruff format` angewandt, `mypy app` (strict) sauber,
  `alembic check` ohne Drift.
- **Worker echt gestartet** (lokales Postgres, ein Alarm in der DB, keine
  Amadeus-Zugangsdaten): Er lief an, prüfte den fälligen Alarm sofort, meldete
  den fehlenden Zugang als **verständlichen deutschen Satz** im Log statt mit
  einem Stacktrace, schrieb eine `flight_observation` mit `search_ok = false`,
  setzte `last_checked_at` und fuhr auf Strg-C sauber herunter.
- Der Abnahmetest von M6 (`test_lauf_schreibt_beobachtung_und_angebote`) prüft
  gegen die gespeicherte Amadeus-Fixture: 3 Angebote, davon eines mit zwei
  Umstiegen herausgefiltert, 2 gespeichert, Beobachtung mit `min_price` 189,50 €.
- Frühere Meilensteine weiterhin per curl belegt (siehe Commit-Nachrichten).

## Offene Punkte / Fallstricke

- **`maxPrice` verzerrt die spätere Preisstatistik (wichtig für M7).** Die
  Suchanfrage schickt das Preislimit des Nutzers an Amadeus mit. Dadurch
  liefert die API an teuren Tagen gar nichts, und die Beobachtung bekommt
  `min_price_cents = NULL` statt „der günstigste war 380 €". Für den Median in
  M7 ist das schlecht. Der Fix ist klein und lokal: `max_price_cents` in
  `alarm_zu_suchanfragen()` weglassen und nur noch lokal filtern (das
  passiert in `_angebot_als_zeile()` ohnehin schon). Kostet keine zusätzliche
  API-Anfrage, nur etwas mehr Antwortdaten. **Bewusst nicht in M6 gemacht**,
  weil es eine inhaltliche Entscheidung für M7 ist.
- **Amadeus-Zugang fehlt (Nutzer-Aktion).** Konto auf `developers.amadeus.com`,
  Self-Service-App anlegen, `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in
  `backend/.env`. Ohne Zugangsdaten laufen alle Tests und der Worker; nur die
  echte Suche scheitert (mit klarer Meldung).
- **Die Fixture ist nachgebaut, nicht mitgeschnitten.** **Erste Aufgabe mit
  Zugangsdaten:** einmal echt suchen, Antwort nach `tests/fixtures/` schreiben,
  Tests laufen lassen. Details: `backend/tests/fixtures/README.md`.
- **Supabase-Projekt fehlt (Nutzer-Aktion).** `SUPABASE_URL` und
  `SUPABASE_JWT_SECRET` in `backend/.env`. Gibt es dort kein symmetrisches
  Secret mehr, sondern nur JWKS → `core/security.py` auf RS256/ES256 erweitern
  (`pyjwt[crypto]`); die Endpunkte bleiben unverändert.
- **Nur ein Suchdatum pro Alarm** (siehe Entscheidungen) — der Datums-Fächer
  fehlt noch.
- **Kein Aufräumen alter Daten.** `flight_observations` wächst pro Alarm und
  Lauf. Bei 6-Stunden-Takt sind das 4 Zeilen pro Alarm und Tag — unkritisch,
  aber irgendwann braucht es eine Aufräum-Aufgabe (Kandidat für M11/M12).
- **`GET /alerts` ohne Paginierung.** Bei 5 Alarmen egal.
- **Token ohne `email`** → 401, weil `users.email` NOT NULL ist.
- **`device_tokens` wird in M8 angepasst** (Web-Push statt APNs) — eigene
  Migration.
- **`.env` und `.venv` fehlen nach Klonen/Entpacken immer** →
  `cp .env.example .env`, `uv sync`.
- **Postgres in dieser Sandbox:** kein Docker-Daemon, aber per apt vorhanden
  (`/usr/lib/postgresql/16/bin`, `initdb`/`pg_ctl` als User `postgres`). Das
  Datenverzeichnis muss für `postgres` erreichbar sein —
  `/var/lib/postgresql/<name>` geht, `/tmp/claude-*` nicht. Dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm@127.0.0.1:5432/flugalarm`.
  **Überlebt keinen Container-Neustart** — lauter `s` in `pytest` heißt: nur
  die DB ist weg, nicht der Code kaputt.
- **Stolperfalle SQLAlchemy async:** Nach `session.rollback()` sind **alle**
  Objekte der Session „abgelaufen". Der nächste Attributzugriff will still
  nachladen — im asynchronen Betrieb ergibt das `MissingGreenlet`. Deshalb
  merkt sich `pruefe_faellige_alarme()` nur die IDs und lädt jeden Alarm mit
  `await session.get(...)` neu. Wer Tests um Fehlerfälle herum schreibt, muss
  IDs **vor** dem Rollback festhalten.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M6 abgeschlossen, committet und gepusht. Nichts ist halbfertig. Die
Kernfunktion läuft Ende-zu-Ende, es fehlen nur noch Zugangsdaten für echte
Daten.

## Nächste Schritte — Vorschlag: M7 (Preisstatistik)

M7 ist der nächste Backend-Schritt und macht aus „Preis unter Limit" ein
„gutes Angebot". Er baut direkt auf den `flight_observations` auf, die M6 jetzt
schreibt.

1. **Zuerst die `maxPrice`-Verzerrung beheben** (siehe offene Punkte oben) —
   sonst rechnet die Statistik auf beschnittenen Daten.
2. **Median und Perzentile** je Strecke und Reisemonat über alle Nutzer
   (`ix_observations_route_month` ist genau dafür da). Reine Funktion in
   `services/`, Eingabe eine Liste von Preisen — ohne DB testbar.
3. **Mindestanzahl Datenpunkte** festlegen: Unter *n* Beobachtungen gibt es
   keine Aussage, sondern ehrlich „noch zu wenig Daten". Nur Zeilen mit
   `search_ok = true` zählen.
4. **Bewertung** („günstig / normal / teuer") als deterministische Statistik in
   Python — Leitplanke 3 aus `CLAUDE.md`: Claude entscheidet nicht.
5. **Tests** ohne DB für die Rechnung, mit DB für die Abfrage.

**Alternative Reihenfolge:** Wer lieber etwas sehen will, zieht **M4
(Web-Client)** vor — Supabase-Login im Browser (`supabase-js` per CDN, kein
Node), Token als `Authorization: Bearer`, Alarmliste + Anlegen-Formular,
Lade-/Leer-/Fehlerzustand sichtbar, Fehler als deutscher Text. Das Backend
kann alles, was der Client dafür braucht.

Danach: M8 (Push) → M9–M12.
