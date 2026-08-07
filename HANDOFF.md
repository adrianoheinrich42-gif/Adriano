# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
M7 — Preisstatistik (+ maxPrice-Verzerrung behoben)   ← neu
6f08a1a M6 — Prüflauf: Alarme und Flugsuche verbunden
db30665 M5 — Amadeus-Anbindung
68a2125 M3 — CRUD für Preisalarme
9a5aefa M2 — Auth-Kette mit Supabase-JWT
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst
```

## Wo wir stehen

**M0–M3, M5, M6 und M7 fertig.** Das Backend kann alles, was die Kernfunktion
braucht: Alarme verwalten, zeitgesteuert bei Amadeus suchen, Preisverlauf
aufzeichnen und ein Angebot gegen die Streckenhistorie einordnen.

**⚠️ M4 ist NICHT fertig** — das war in einer früheren Übergabe missverständlich.
`web/` enthält nur den M0-Spiegel: 104 Zeilen `app.js`, die `/health` abfragen
und den Serverstatus anzeigen. **Kein** Supabase-Login, **kein**
`Authorization: Bearer`, **keine** Alarmliste, **kein** Formular. Real geprüft
per `grep` über `web/` — die einzigen Treffer für „Alarm"/„anmelden" sind ein
Kommentar und ein vorbereiteter Fehlertext.

**Noch 6 Meilensteine bis „fertig": M4, M8–M12.**

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts`.
Prozesse: API (`app.main:app`) **und** Worker (`app.jobs.worker`).

Meilenstein-Übersicht: `docs/PROJEKTPLAN.md` §5; für Client/Push gilt
`docs/PLATTFORM-WEB.md` vor.

## Was umgesetzt ist

- **M0** — FastAPI, `GET /health`, `config.py`, `db.py`; `docker-compose.yml`
  (Postgres 16, API, Worker), `Dockerfile`, `Makefile`, `.env.example`.
- **M1** — 6 Tabellen in `app/models/`, eine Alembic-Migration
  (`…6513957c2dba_initial_schema.py`). 16 Integrationstests auf die
  DB-Zusicherungen.
- **M2** — `core/security.py` (JWT HS256), `api/deps.py`, `services/users.py`,
  `GET /me`.
- **M3** — `schemas/price_alert.py`, `services/price_alerts.py`,
  `api/routes/price_alerts.py`.
- **M5** — `services/amadeus.py` (Client + reine Normalisierung),
  `schemas/flight_offer.py`, `scripts/amadeus_suche.py`, Fixture.
- **M6** — `services/pruflauf.py`, `jobs/worker.py` (APScheduler),
  `tests/attrappen.py`.
- **M7** — siehe nächster Abschnitt.
- **Plattformwechsel** — `web/`, `docs/PLATTFORM-WEB.md`; `ios/` entfernt.

## Zuletzt geändert — M7 (Preisstatistik)

**Zuerst die bekannte Verzerrung behoben.** `alarm_zu_suchanfragen()` schickte
das Preislimit des Nutzers als `maxPrice` an Amadeus. Dadurch lieferte die API
an teuren Tagen gar nichts und die Beobachtung bekam `min_price_cents = NULL`
statt „der günstigste war 380 €" — der Median hätte nur die guten Tage gesehen.
Das Limit wird jetzt **nicht mehr** mitgeschickt; gefiltert wird ausschließlich
lokal in `_angebot_als_zeile()`. Kostet keine zusätzliche Anfrage.

**Neu: `app/services/price_stats.py`** — zwei Hälften wie gewohnt:

- *rein:* `median_cents()`, `abweichung_prozent()`, `bewerte_preis()`,
  Typen `Einordnung` (`zu_wenig_daten` / `guenstig` / `normal` / `teuer`) und
  `Preisbewertung` (mit `hat_aussage` und `ist_bestpreis`).
- *mit DB:* `hole_vergleichspreise()` (gleiche Strecke, gleicher Reisemonat,
  90 Tage, über **alle** Nutzer), `bewerte_angebot()`.

**In den Prüflauf eingehängt:** `LaufErgebnis` hat jetzt ein Feld `bewertung`.
`pruefe_alarm()` ordnet den **besten Treffer** ein — also das günstigste
Angebot, das wirklich zum Alarm passt, genau das, was in M8 die Push auslöst.
`_speichere_angebote()` gibt dafür jetzt die Preisliste statt nur einer Anzahl
zurück.

**Tests:** `tests/test_price_stats.py` (26, ohne DB),
`tests/integration/test_price_stats.py` (13, mit DB), plus ein neuer Test in
`tests/test_pruflauf.py` für das nicht mehr gesendete Preislimit.

**Keine Migration nötig** — M7 liest nur bestehende Tabellen.

### Entscheidungen aus M7

Ausführlich in `CLAUDE.md`; hier die Merksätze:

- **Median statt Durchschnitt.** Ein einzelner Business-Class-Tarif zöge den
  Durchschnitt um Hunderte Euro hoch.
- **Unter 10 Datenpunkten keine Prozentaussage**, sondern `ZU_WENIG_DATEN`.
  `median_cents` und `abweichung_prozent` sind dann `None`, damit niemand
  versehentlich eine 0 anzeigt.
- **Schwellen ±10 %** für „günstig"/„teuer", inklusiv. Bewusste Setzung, keine
  Wissenschaft — beide Konstanten stehen oben in `price_stats.py`.
- **Nur `search_ok = true` und `min_price_cents IS NOT NULL` zählen.**
- **Der Lauf vergleicht sich nicht gegen sich selbst** — Vergleichspreise
  werden geholt, *bevor* die eigene Beobachtung geschrieben wird.
- **`ist_bestpreis` getrennt von der Einordnung.** Ein neuer Tiefstpreis kann
  „normal" sein und trotzdem meldenswert (im Beleg unten: 230 € ist −8,4 % und
  damit „normal", aber Rekord).

## Verifizierter Zustand (zuletzt real nachgeprüft, nicht nur behauptet)

- **Tests:** mit DB `208 passed`; ohne DB `142 passed, 66 skipped`. Beides grün.
  Diese Zahlen sind der Soll-Wert für die nächste Session.
- `ruff check` sauber, `ruff format` angewandt, `mypy app` (strict) sauber,
  `alembic check` ohne Drift.
- **Statistik gegen echte, committete Daten belegt** (nicht nur im Test): 14
  Beobachtungen für HAM→LIS im November eingespielt, darunter ein Ausreißer
  über 1200 €, eine Zeile mit `search_ok = false` und eine 200 Tage alte.
  Ergebnis:

  ```
   199.00 EUR → guenstig   Median 251.00 EUR  -20.7 %  n=12  Bestpreis=True
   251.00 EUR → normal     Median 251.00 EUR   +0.0 %  n=12  Bestpreis=False
   299.00 EUR → teuer      Median 251.00 EUR  +19.1 %  n=12  Bestpreis=False
   230.00 EUR → normal     Median 251.00 EUR   -8.4 %  n=12  Bestpreis=True
   ohne Historie → zu_wenig_daten, n=0, Median=None
  ```

  `n=12` statt 14 belegt, dass Ausfall und Altzeile ausgeschlossen werden; der
  Median von 251 € trotz des 1200-€-Ausreißers belegt die Ausreißerfestigkeit.
- **Worker echt gestartet** (M6, weiterhin gültig): läuft ohne
  Amadeus-Zugangsdaten an, meldet den fehlenden Zugang als verständlichen
  deutschen Satz, schreibt die Beobachtung mit `search_ok = false` und fährt
  auf Strg-C sauber herunter.

## Offene Punkte / Fallstricke

- **M4 fehlt komplett** (siehe oben). Das Backend kann alles, was der Client
  bräuchte — es gibt ihn nur noch nicht.
- **Amadeus-Zugang fehlt (Nutzer-Aktion).** Konto auf `developers.amadeus.com`,
  Self-Service-App anlegen, `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in
  `backend/.env`. Ohne Zugangsdaten laufen alle Tests und der Worker; nur die
  echte Suche scheitert (mit klarer Meldung).
- **Die Fixture ist nachgebaut, nicht mitgeschnitten.** Erste Aufgabe mit
  Zugangsdaten: einmal echt suchen, Antwort nach `tests/fixtures/` schreiben,
  Tests laufen lassen. Details: `backend/tests/fixtures/README.md`.
- **Supabase-Projekt fehlt (Nutzer-Aktion).** `SUPABASE_URL` und
  `SUPABASE_JWT_SECRET` in `backend/.env`. Gibt es dort nur noch JWKS statt
  eines symmetrischen Secrets → `core/security.py` auf RS256/ES256 erweitern
  (`pyjwt[crypto]`); die Endpunkte bleiben unverändert.
- **Die Statistik ist noch nirgends sichtbar.** `Preisbewertung` steckt im
  `LaufErgebnis` und im Log, aber es gibt keinen Endpunkt dafür. Das ist
  Absicht — M8 (Push) und M9 (Detailansicht) sind die Abnehmer.
- **Die 90 Tage sind ein fester Wert**, keine Einstellung. Reicht vorerst;
  wenn er verstellbar sein soll, gehört er in `config.py`.
- **Nur ein Suchdatum pro Alarm** — der Datums-Fächer über den Zeitraum fehlt
  noch. `alarm_zu_suchanfragen()` gibt deshalb schon eine Liste zurück.
- **Kein Aufräumen alter Daten.** `flight_observations` wächst pro Alarm und
  Lauf (4 Zeilen/Tag bei 6-Stunden-Takt). Kandidat für M11/M12.
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
- **Stolperfalle Statistik-Tests:** `hole_vergleichspreise()` fragt bewusst
  über alle Nutzer ab. Tests dürfen sich deshalb keine feste Strecke teilen —
  `tests/integration/test_price_stats.py` würfelt sie pro Test aus.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M7 abgeschlossen, committet und gepusht. Nichts ist halbfertig.

## Nächste Schritte — Empfehlung: M4 (Web-Client)

Das Backend hat jetzt fünf Meilensteine Vorsprung vor dem Client. Man kann
nichts davon sehen oder ausprobieren, ohne `curl` zu tippen — und die
nächsten Backend-Schritte (Push) lassen sich ohne Client ohnehin nicht
sinnvoll abnehmen.

1. **Supabase-Projekt anlegen** (Nutzer-Aktion, blockiert sonst alles).
2. **Login im Browser** — `supabase-js` per CDN, kein Node (`CLAUDE.md`:
   kein Framework, bis Formulare es verlangen).
3. **Token mitschicken** — `Authorization: Bearer` an `/me` und `/alerts`.
4. **Alarmliste + Anlegen-Formular**, Lade-/Leer-/Fehlerzustand sichtbar,
   Fehler als verständlicher deutscher Text, nie ein Statuscode.
5. **Gegen das echte Backend testen** (`make dev` + `make web`).

**Alternative:** Wer lieber im Backend bleibt, nimmt **M8 (Push)** —
`device_tokens` auf Web-Push umstellen (eigene Migration), VAPID-Schlüssel,
`pywebpush`, Dedupe über `notification_logs.dedupe_key`, Abkühlphase und
5-%-Regel. Die Einordnung aus M7 liefert dafür schon den Inhalt der Nachricht.

Danach: M9–M12.
