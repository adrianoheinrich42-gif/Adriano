# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-3tzcq4` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht** (`49ffcd3`).
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
db30665 M5 — Amadeus-Anbindung
68a2125 M3 — CRUD für Preisalarme
9a5aefa M2 — Auth-Kette mit Supabase-JWT
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst
```

## Wo wir stehen

**M0–M3 und M5 fertig** (Setup · Datenmodell · Auth · Alarm-CRUD ·
Amadeus-Anbindung), dazu der Plattformwechsel iOS → Web.
Das Backend kann Alarme verwalten **und** bei Amadeus suchen — beides aber
noch getrennt: Niemand ruft die Suche automatisch auf. Genau das ist M6.

**Noch 8 Meilensteine bis „fertig": M4, M6–M12.**

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts`.
`app/jobs/` ist noch leer. Das Web-Frontend zeigt nur den Backend-Status.

Meilenstein-Übersicht: `docs/PROJEKTPLAN.md` §5; für Client/Push gilt
`docs/PLATTFORM-WEB.md` vor.

## Was umgesetzt ist

- **M0** — FastAPI, `GET /health` (prüft DB, antwortet immer HTTP 200),
  `config.py`, `db.py`; `docker-compose.yml` (Postgres 16), `Dockerfile`,
  `Makefile` (`make help`), `.env.example`.
- **M1** — 6 Tabellen in `app/models/`, eine Alembic-Migration
  (`…6513957c2dba_initial_schema.py`). 16 Integrationstests auf die
  DB-Zusicherungen (CHECKs, Kaskade, Dedupe).
- **M2** — `core/security.py` (JWT HS256), `api/deps.py` (`get_token_claims`
  ohne DB, `get_current_user` mit Nutzer-Anlage, `CurrentUser`),
  `services/users.py` (Upsert), `GET /me`.
- **M3** — `schemas/price_alert.py` (Create/Update/Response + geteilte
  `pruefe_feldkombination()`), `services/price_alerts.py`,
  `api/routes/price_alerts.py`.
- **M5** — siehe nächster Abschnitt.
- **Plattformwechsel** — `web/`, `docs/PLATTFORM-WEB.md`; `ios/` entfernt
  (in der Historie, Commit `def9ae6`).

## Zuletzt geändert — M5 (Amadeus)

- `app/services/amadeus.py` — **zwei getrennte Hälften**: oben `AmadeusClient`
  (OAuth2-Token holen und zwischenspeichern, `suche_roh()`, `suche()`), unten
  die **reine** Normalisierung (`normalisiere_antwort`, `preis_zu_cent`,
  `dauer_zu_minuten`, `filtere_nach_umstiegen`). Fehler als eigene Typen:
  `AmadeusConfigError`, `AmadeusAuthError`, `AmadeusRateLimited`,
  `AmadeusUnavailable` — M6 muss auf „später nochmal" anders reagieren als
  auf einen echten Fehler. Dazu das Protokoll `Flugsuche` als Austauschpunkt.
- `app/schemas/flight_offer.py` — interne Struktur (`Flugangebot`,
  `Teilstrecke`, `Flugsegment`), Preis in Cent, `rohdaten` für M6.
- `scripts/amadeus_suche.py` — Handsuche, `--roh` schreibt eine neue Fixture.
  Aufruf **immer** als Modul: `uv run python -m scripts.amadeus_suche …`
  (direkt aufgerufen findet Python `app` nicht). Kürzel: `make suche a="…"`.
- `tests/fixtures/` — gespeicherte Amadeus-Antwort + `README.md` zur Herkunft.
- `tests/test_amadeus_normalisierung.py` (24) und `tests/test_amadeus_client.py`
  (17) — beide ohne Netz.
- Geändert: `pyproject.toml` (`httpx` von dev in die Hauptabhängigkeiten),
  `config.py` + `.env.example` (Amadeus-Block aktiv), `Makefile`.

**Keine Migration nötig** — M5 schreibt noch nichts in die Datenbank.

### Entscheidungen aus M5

Ausführlich in `CLAUDE.md`; hier die Merksätze:

- **Client und Normalisierung getrennt.** Nur so ist die Übersetzung gegen
  eine gespeicherte Antwort testbar. **Kein Test geht je ins Netz**
  (`httpx.MockTransport`).
- **Zeiten sind lokale Flughafenzeiten ohne Offset** und werden so
  weitergereicht, statt eine Zeitzone zu erfinden. → offener Punkt für M6.
- **`maxPrice` nur ganzzahlig** → wir runden **ab** (249,99 € → 249), damit
  das Nutzerlimit nie überschritten wird.
- **Kein „max. N Umstiege"-Parameter** in der API, nur `nonStop`. Alles
  dazwischen filtert `filtere_nach_umstiegen()` nach dem Abruf.
- **`grandTotal` schlägt `total`** — maßgeblich ist, was der Nutzer zahlt.
- **Gepäck: `None` heißt „unbekannt", nicht „null Stück".** Amadeus liefert
  je nach Tarif eine Stückzahl, ein Gewicht oder nichts. Ein Gewicht lässt
  sich nicht in Stück umrechnen → ehrlich „unbekannt".
- **Ein kaputtes Angebot kippt nicht den ganzen Lauf** — es wird übersprungen
  und protokolliert. 19 brauchbare Angebote sind besser als keins.

## Verifizierter Zustand (zuletzt real nachgeprüft, nicht nur behauptet)

- **Tests:** mit DB `112 passed`; ohne DB `80 passed, 32 skipped`. Beides grün.
  Diese Zahlen sind der Soll-Wert für die nächste Session — weicht etwas ab,
  ist etwas kaputt oder es kam Neues dazu.
- `ruff check` sauber, `mypy app` (strict) sauber, `alembic check` ohne Drift.
- Die Fixture durch die Anzeige-Logik des Skripts geschickt: zwei Angebote
  korrekt formatiert (189,50 € mit 1 Umstieg und „Gepäck: unbekannt";
  249,90 € direkt mit „1 Stück"), das Angebot mit zwei Umstiegen gefiltert.
- `make suche` ohne Zugangsdaten → **verständlicher deutscher Hinweis**,
  Exit-Code 1, kein Stacktrace.
- Frühere Meilensteine weiterhin per curl belegt (siehe Commit-Nachrichten).

## Offene Punkte / Fallstricke

- **Amadeus-Zugang fehlt (Nutzer-Aktion).** Konto auf `developers.amadeus.com`,
  Self-Service-App anlegen, `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in
  `backend/.env`. Ohne Zugangsdaten laufen alle Tests, nur die echte Suche
  nicht.
- **Die Fixture ist nachgebaut, nicht mitgeschnitten** — es lagen keine
  Zugangsdaten vor. Sie folgt der offiziellen OpenAPI-Spezifikation, aber
  Flüge und Preise sind erfunden. **Erste Aufgabe mit Zugangsdaten:** einmal
  echt suchen, Antwort nach `tests/fixtures/` schreiben, Tests laufen lassen.
  Weichen sie ab, ist die Normalisierung anzupassen — genau dafür sind sie da.
  Details: `backend/tests/fixtures/README.md`.
- **Supabase-Projekt fehlt (Nutzer-Aktion).** `SUPABASE_URL` und
  `SUPABASE_JWT_SECRET` in `backend/.env`. Ohne Secret antworten geschützte
  Endpunkte mit 500, `/health` bleibt unberührt. Gibt es dort kein
  symmetrisches Secret mehr, sondern nur JWKS → `security.py` auf RS256/ES256
  erweitern (`pyjwt[crypto]`); die Endpunkte bleiben unverändert.
- **Zeitzonen-Entscheidung steht in M6 an.** `flight_offers` hat
  `timestamptz`, Amadeus liefert naive Ortszeit ohne Offset. Entweder die
  Ortszeit als UTC ablegen (Wanduhrzeit stimmt in der Anzeige, der Zeitpunkt
  ist falsch — für Dauerberechnungen `dauer_minuten` benutzen) oder eine
  Flughafen-Zeitzonentabelle einführen. Bewusst offen gelassen.
- **`.env` und `.venv` fehlen nach Klonen/Entpacken immer** →
  `cp .env.example .env`, `uv sync`.
- **Postgres in dieser Sandbox:** kein Docker-Daemon, aber per apt vorhanden
  (`/usr/lib/postgresql/16/bin`, `initdb`/`pg_ctl` als User `postgres`). Das
  Datenverzeichnis muss für `postgres` erreichbar sein —
  `/var/lib/postgresql/<name>` geht, `/tmp/claude-*` nicht. Dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm@127.0.0.1:5432/flugalarm`.
  **Überlebt keinen Container-Neustart** — lauter `s` in `pytest` heißt: nur
  die DB ist weg, nicht der Code kaputt.
- **`GET /alerts` ohne Paginierung.** Bei 5 Alarmen egal; nachrüsten, wenn das
  Limit steigt.
- **Token ohne `email`** → 401, weil `users.email` NOT NULL ist.
- **`device_tokens` wird in M8 angepasst** (Web-Push statt APNs) — eigene
  Migration.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M5 abgeschlossen, committet und gepusht. Nichts ist halbfertig. Suche und
Alarme existieren, sind aber noch **nicht verbunden** — das ist M6.

## Nächste Schritte — M6 (Prüflauf)

Der Meilenstein, der aus zwei Bausteinen eine Anwendung macht.

1. **Alarm → Suchanfrage.** Kleine reine Funktion, die aus einem `PriceAlert`
   eine `Suchanfrage` baut (Strecke, Datum, `max_stops`, `max_price_cents`,
   `adults`). Ohne DB testbar. Achtung: Der Alarm nennt einen **Zeitraum**,
   die API will **ein** Datum — also entweder ein Datum pro Lauf durchgehen
   oder bewusst nur den frühesten Hinflug prüfen. Entscheidung dokumentieren.
2. **Fällige Alarme finden.** `is_active` und `last_checked_at` gegen
   `check_interval_minutes` — der Index `ix_price_alerts_due` ist genau dafür
   da. Bei zwei Worker-Instanzen zusätzlich `FOR UPDATE SKIP LOCKED`.
3. **Ein Lauf pro Alarm:** suchen → `flight_observation` schreiben (**auch
   ohne Treffer**, das ist der Preisverlauf) → passende Angebote als
   `flight_offers` per Upsert auf `(price_alert_id, offer_hash)` →
   `last_checked_at` setzen. `offer_hash` aus Route, Daten, Airline und Preis
   (siehe Doku in `models/flight_offer.py`) — reine Funktion, gut testbar.
4. **Zeitzonen-Entscheidung treffen** (siehe offene Punkte oben), bevor die
   ersten Zeiten in `timestamptz` landen.
5. **APScheduler** in `app/jobs/`, ein eigener Prozess neben der API. Fehler
   dürfen den Scheduler nie beenden: `AmadeusRateLimited` und
   `AmadeusUnavailable` = später erneut, alles andere protokollieren und mit
   dem nächsten Alarm weitermachen.
6. **Tests:** Fälligkeitslogik und `offer_hash` ohne DB; ein kompletter Lauf
   mit DB und einer Attrappe der `Flugsuche` (deshalb gibt es das Protokoll) —
   kein Netz.

**Abnahme M6:** Ein Lauf schreibt `flight_observations` und `flight_offers`.
Push noch nicht.

### Danach

**M4 (Web-Client):** Supabase-Login im Browser (`supabase-js` per CDN, kein
Node), Token als `Authorization: Bearer` mitschicken, Alarmliste +
Anlegen-Formular, Lade-/Leer-/Fehlerzustand sichtbar, Fehler als deutscher
Text. Dann M7 (Statistik) → M8 (Push) → M9–M12.
