# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-3tzcq4` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei.

## Wo wir stehen

Meilensteine **M0** (Setup), **M1** (Datenbankmodell), **M2** (Auth-Kette) und
**M3** (Alarm-CRUD) fertig, plus der Plattformwechsel iOS → Web.
Das Backend kann damit alles, was der Nutzer *eingibt* — es sucht nur noch
keine Flüge. Als Nächstes: **M5 (Amadeus-Anbindung)** oder **M4 (Web-Client)**.

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
- **M2 Auth-Kette:** `core/security.py` (JWT-Prüfung HS256), `api/deps.py`
  (`get_token_claims` ohne DB, `get_current_user` mit Nutzer-Anlage,
  `CurrentUser`), `services/users.py` (Upsert), `GET /me`.
- **M3 Alarm-CRUD** (neu, siehe nächster Abschnitt).
- **Plattformwechsel:** `web/` (Frontend, M0-Spiegel), `docs/PLATTFORM-WEB.md`.
  `ios/`-Ordner entfernt (liegt in Historie, Commit `def9ae6`).

## Zuletzt geändert — M3 (Alarm-CRUD)

Endpunkte, alle mit `user: CurrentUser`:
`POST /alerts` (201) · `GET /alerts` · `GET /alerts/{id}` ·
`PATCH /alerts/{id}` · `DELETE /alerts/{id}` (204).

Neue Dateien:
- `app/schemas/price_alert.py` — `PriceAlertCreate` / `PriceAlertUpdate` /
  `PriceAlertResponse`, dazu die geteilte Funktion `pruefe_feldkombination()`
  für alles, was mehrere Felder zugleich betrifft. Normalisiert IATA- und
  Währungscodes auf Großbuchstaben (`" muc "` → `"MUC"`). Beide Eingabe-
  schemata haben `extra="forbid"`, damit ein Tippfehler im Feldnamen auffällt
  statt still ignoriert zu werden.
- `app/services/price_alerts.py` — `list_alerts`, `get_alert`, `create_alert`,
  `update_alert`, `delete_alert` plus die Fehler `AlertLimitReached` (→ 409)
  und `AlertRulesViolated` (→ 422).
- `app/api/routes/price_alerts.py` — dünne Endpunkte, übersetzen nur
  Rückgabewerte in HTTP-Status.
- `tests/test_price_alert_schemas.py` (22 Tests, ohne DB),
  `tests/integration/test_price_alerts.py` (11 Tests, mit DB).

Geändert: `app/main.py` (Router eingehängt).

**Keine Migration nötig** — `price_alerts` stammt aus M1, `alembic check`
meldet keinen Drift.

### Vier Entscheidungen, die man kennen sollte

- **`user_id` steht in *jeder* Abfrage in der WHERE-Klausel**, statt den Alarm
  zu laden und danach den Besitzer zu prüfen. Die zweite Variante vergisst man
  irgendwann bei einem neuen Endpunkt; bei der ersten kann ein fremder Alarm
  gar nicht erst im Ergebnis auftauchen.
- **Fremder Alarm → 404, nicht 403.** Ein 403 hieße „den gibt es, du darfst
  nur nicht" — schon das ist eine Information, die niemanden etwas angeht.
- **PATCH validiert den zusammengeführten Stand.** `latest_return_date` allein
  ist immer ein gültiges Datum; erst zusammen mit dem *gespeicherten*
  Hinflugdatum kann es unsinnig sein. Deshalb prüft der Dienst nach dem
  Zusammenführen erneut — und rollt bei Verstoß zurück, damit die schon am
  ORM-Objekt hängenden Änderungen nicht später mitgeschrieben werden.
- **Alarm-Limit mit `SELECT … FOR UPDATE`** auf die Nutzer-Zeile. Ohne die
  Sperre könnten zwei gleichzeitige Requests beide „noch Platz" feststellen
  und beide anlegen. Gezählt werden nur **aktive** Alarme; Pausieren
  (`is_active = false`) macht wieder Platz, Reaktivieren läuft erneut gegen
  die Grenze.

## Verifizierter Zustand (in dieser Umgebung geprüft)

- **Tests:** mit DB `71 passed`; ohne DB `39 passed, 32 skipped` (erwartetes
  Skip-Verhalten der Integrationstests). Beides ist „grün".
- `ruff format`/`ruff check` sauber, `mypy app` (strict) sauber,
  `alembic check` ohne Drift.
- **End-to-End per curl** gegen echtes Postgres 16 + uvicorn, zwei Nutzer:
  Anlegen mit `"origin":"muc"` → **201** und gespeichert als `MUC`;
  `GET /alerts` → nur die eigenen; PATCH Preis → **200**;
  PATCH mit unsinnigem Zusammenspiel → **422** mit deutschem Text und der
  Alarm bleibt unverändert; fremder Zugriff (GET/PATCH/DELETE) → **404**,
  fremde Liste `[]`; ohne Token → **401**; DELETE → **204**, danach GET **404**.
  → **Abnahmekriterium M3 erfüllt.**

## Bekannte offene Punkte / Fallstricke

- **Supabase-Projekt fehlt noch (Nutzer-Aktion).** Anlegen, dann in
  `backend/.env`: `SUPABASE_URL` (Project URL) und `SUPABASE_JWT_SECRET`
  (Project Settings → API → JWT Secret). Erst danach lässt sich mit einem
  echten Login-Token testen. Findet sich dort **kein** symmetrisches Secret
  mehr, sondern nur Signing Keys/JWKS → dann muss `security.py` auf
  RS256/ES256 erweitert werden (`pyjwt[crypto]`); Endpunkte bleiben unberührt.
- **Kein Docker-Daemon in dieser Sandbox.** Postgres per apt installieren und
  mit `initdb`/`pg_ctl` als User `postgres` starten (Binary:
  `/usr/lib/postgresql/16/bin`). Achtung: Das Datenverzeichnis muss für den
  User `postgres` erreichbar sein — `/var/lib/postgresql/<name>` funktioniert,
  ein Pfad unter `/tmp/claude-*` nicht (Permission denied). Dann
  `DATABASE_URL=postgresql+asyncpg://flugalarm@127.0.0.1:5432/flugalarm`.
  **Der Server überlebt keinen Container-Neustart** — läuft `pytest` plötzlich
  mit lauter `s`, ist nur die DB weg, nicht der Code kaputt.
- **`GET /alerts` hat noch keine Paginierung.** Bei 5 Alarmen pro Nutzer egal;
  spätestens wenn das Limit steigt oder Angebote mitgeliefert werden, nachrüsten.
- **Token ohne `email`** (reine Telefon-Anmeldung) wird mit 401 abgelehnt, weil
  `users.email` NOT NULL ist. Falls das je gebraucht wird: Spalte nullable
  machen (eigene Migration), nicht die Prüfung aufweichen.
- **Web-Push braucht später HTTPS** (iPhone, außer localhost) + „zum
  Home-Bildschirm hinzufügen". Erst im Push-Meilenstein relevant.
- **`device_tokens` wird im Push-Meilenstein angepasst** (Web-Push-Subscription
  statt APNs-Token, `environment`-Spalte entfällt) — als eigene Migration.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M0–M3 abgeschlossen und gepusht. `app/jobs/` ist noch leerer Platzhalter.
Endpunkte: `GET /health`, `GET /me`, `POST/GET/PATCH/DELETE /alerts`.
Das Web-Frontend kennt noch keinen Login und keine Alarme — es zeigt nur den
Backend-Status.

## Nächste Schritte

Zwei Wege stehen offen. **Empfehlung: M5 zuerst** — dann hat der Client bei M4
schon echte Daten zu zeigen, statt zweimal gebaut zu werden.

### M5 (Amadeus-Anbindung), in Reihenfolge

1. **Zugang holen:** Konto auf `developers.amadeus.com`, Self-Service-App
   anlegen → `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in `.env`
   (Platzhalter stehen schon in `.env.example`, Test-Umgebung
   `https://test.api.amadeus.com`).
2. **Client** `app/services/amadeus.py`: OAuth2-Token holen und zwischen-
   speichern (läuft ~30 min), dann `GET /v2/shopping/flight-offers`.
   `httpx.AsyncClient` ergänzen. Hinter einem Protokoll/einer Dependency,
   damit Tests ihn ersetzen können.
3. **Normalisierung:** Amadeus-Antwort → schlanke interne Struktur
   (Preis in **Cent**, Stopps, Zeiten, Fluggesellschaft). Preise kommen als
   String wie `"249.90"` — sauber in Cent umrechnen, nie über float.
4. **Test-Fixture:** eine echte Antwort als JSON in `tests/fixtures/` legen und
   die Normalisierung ohne Netz dagegen testen. So bleibt die Testsuite offline.
5. **Noch kein Scheduler** — laut Projektplan reicht ein Skript/Endpunkt, der
   einmal sucht und das Ergebnis ausgibt.

**Abnahme M5:** Eine Suche MUC→BCN liefert normalisierte Angebote; die
Normalisierung ist gegen die gespeicherte Fixture getestet.

### M4 (Web-Client) — falls du lieber etwas sehen willst

Supabase-Login im Browser (`supabase-js` per CDN, kein Node), Token im
Speicher halten und bei jedem Aufruf als `Authorization: Bearer` mitschicken,
Alarmliste + Anlegen-Formular. Lade-, Leer- und Fehlerzustand sichtbar
implementieren. Fehler als deutschen Text zeigen, nie als Statuscode.

Danach laut Projektplan: M6 (Prüflauf) → M7 (Statistik) → M8 (Push).
