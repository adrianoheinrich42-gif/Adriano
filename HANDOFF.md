# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-08 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.

Reihenfolge beim Einsteigen: `CLAUDE.md` → diese Datei → `git log` /
`git status`. `CLAUDE.md` enthält das Dauerwissen (Architektur, Regeln,
Entscheidungen), diese Datei nur den **aktuellen Stand**.

---

## Wo wir stehen

**Der Code ist fertig.** M0–M11 sind abgeschlossen, von M12 ist die Härtung
erledigt. **Offen ist nur noch das Deployment** — und das hängt an Konten, die
nur der Nutzer anlegen kann.

Was die App kann: anmelden · Alarm anlegen (per Formular **oder** in einem
Satz beschrieben) · Worker prüft im Takt bei Amadeus · Preise werden
statistisch eingeordnet · bei einem Treffer geht eine Push raus, von Claude
formuliert · Tippen darauf öffnet die Detailansicht mit Einordnung,
Preisverlauf und Flügen · Konto samt aller Daten löschbar.

**Endpunkte:** `GET /health` · `GET /health/ready` · `GET/DELETE /me` ·
`POST/GET/PATCH/DELETE /alerts` · `POST /alerts/entwurf` ·
`GET /alerts/{id}/offers` · `GET /alerts/{id}/verlauf` · `GET /offers/{id}` ·
`GET /push/config` · `POST/DELETE /push/subscriptions`

**Zwei Prozesse:** API (`app.main:app`) und Worker (`app.jobs.worker`).

---

## ⚠️ Vier Dinge, die nur der Nutzer tun kann

Keins blockiert die Entwicklung, alle vier den echten Betrieb. **Für jedes
gibt es eine eigene Schritt-für-Schritt-Anleitung im Ordner `anleitungen/`**
(Word-Dateien, ohne Vorwissen lesbar).

| # | Was | Ohne das … | Anleitung |
|---|---|---|---|
| 1 | **Supabase-Projekt** | kann sich niemand anmelden | `01-Supabase-einrichten.docx` |
| 2 | **Amadeus-Zugang** | findet der Worker keine Flüge | `02-Amadeus-Zugang.docx` |
| 3 | **Anthropic-Schlüssel** | schreibt der Baukasten statt Claude; Freitextfeld meldet „nicht verfügbar" | `03-Anthropic-Schluessel.docx` |
| 4 | **VAPID-Schlüsselpaar** | geht keine Push raus (1 Befehl, 1 Sekunde) | `04-VAPID-Schluesselpaar.docx` |

Danach: `05-Deployment.docx` und `06-iPhone-Push-testen.docx`.

---

## Was umgesetzt ist

| M | Inhalt | Kernstücke |
|---|---|---|
| M0 | Projektgerüst | FastAPI, `/health`, `config.py`, `db.py`, Docker, Makefile |
| M1 | Datenbank | 6 Tabellen, erste Migration, 16 Tests auf DB-Zusicherungen |
| M2 | Auth-Kette | `core/security.py` (JWT HS256), `api/deps.py`, `GET /me` |
| M3 | Alarm-CRUD | `services/price_alerts.py`, Alarm-Limit mit `FOR UPDATE` |
| M4 | Web-Client | `auth.js`, `api.js`, `format.js`, `app.js` |
| M5 | Amadeus | `services/amadeus.py`, `schemas/flight_offer.py`, Fixture |
| M6 | Prüflauf | `services/pruflauf.py`, `jobs/worker.py` (APScheduler) |
| M7 | Statistik | `services/price_stats.py` — Median, Abweichung, „zu wenig Daten" |
| M8 | Push | `services/push.py`, PWA (`manifest.json`, `sw.js`, `push.js`) |
| M9 | Ergebnisanzeige | `services/ergebnisse.py`, `web/detail.js`, Deep-Link `#alarm=<id>` |
| M10 | Claude formuliert | `services/claude.py`, `notification_logs.title/body/text_quelle` |
| M11 | Claude versteht | `services/nlp.py`, `POST /alerts/entwurf`, Freitextfeld |
| M12a | Härtung | `core/ratelimit.py`, `core/logging.py`, `services/aufraeumen.py`, `DELETE /me`, `/health/ready` |

**Migrationen (3):** `ef9189a`-Schema · `22e16687014f` (M8: Web-Push) ·
`4b42be3a6b6e` (M10: Erklärtext im Protokoll).

Alle inhaltlichen Entscheidungen stehen in **`CLAUDE.md`** unter „Wichtige
Entscheidungen" — hier nicht wiederholt.

---

## Zuletzt geändert (diese Session): M10, M11, M12a

**M10 — Claude formuliert die Benachrichtigungen** (`836091f`)
Neu `services/claude.py` (Protokoll `Texter`, Structured Output,
`pruefe_text()`), Migration `4b42be3a6b6e`. Der Baukasten aus M8 bleibt der
Rückfall. `web/detail.js` baut den Bewertungssatz nicht mehr selbst.

**M11 — Freitext füllt das Formular vor** (`29a5254`)
Neu `services/nlp.py`, `schemas/nlp.py`, `api/routes/nlp.py`,
Freitextfeld im Dialog. `POST /alerts/entwurf` **legt nichts an**.

**M12a — Härtung** (`e836bcd`)
Neu `core/ratelimit.py`, `core/logging.py`, `services/aufraeumen.py`,
`DELETE /me`, `GET /health/ready`, Löschen-Knopf im Frontend.

**Nachträglich korrigiert:** `backend/Dockerfile` nannte den Worker-Befehl
falsch (`app.jobs.scheduler` statt `app.jobs.worker`) und kopierte `alembic/`
nicht ins Bild — beides hätte beim ersten Deployment sofort geknallt.

---

## Verifizierter Zustand (real nachgeprüft, nicht behauptet)

- **Tests:** mit DB **`394 passed`**, ohne DB **`247 passed, 147 skipped`**.
  `ruff`, `mypy app` (strict), `alembic check` ohne Drift.
  **Das sind die Soll-Zahlen.**
- **Browsertests im echten Chromium** gegen das echte Backend, jeweils mit
  echter Datenbank und echt signiertem JWT; ersetzt war nur Supabase:
  M4 (11 Schritte) · M8 (12) · M9 (12) · M10 (9) · M11 (11) · M12a (12).
  Keine JavaScript-Fehler.
- **Kein Test geht ins Netz.** Alles Externe steckt hinter einem Protokoll
  (`Flugsuche`, `PushVersand`, `Texter`, `Auswerter`); der Fall „falscher
  API-Schlüssel" wird mit `httpx.MockTransport` und echter 401 nachgestellt.

### Diese Session gefunden und behoben

| Fund | Wirkung |
|---|---|
| CORS ließ nur `localhost:3000` zu, nicht `127.0.0.1:3000` | App meldete „Keine Verbindung", während im Log ein 200 stand |
| `Retry-After` fehlte in `expose_headers` | Browser darf den Kopf bei fremder Herkunft nicht lesen — „in 42 s erneut" wäre unsichtbar |
| Detailansicht recycelte auch den *Baukasten*-Push-Text | „189,50 € — … Direktflug · LH" doppelt neben Preis und Flugdaten |
| `Dockerfile`: falscher Worker-Befehl, kein `alembic/` | Deployment wäre am ersten Tag gescheitert |

---

## Offene Punkte

**Keine bekannten Bugs.** Was fehlt, fehlt bewusst:

- **Push ist nie auf echter iPhone-Hardware gelaufen.** Braucht HTTPS →
  kommt mit dem Deployment. Siehe `06-iPhone-Push-testen.docx`.
- **Claude hat nie wirklich geantwortet.** Alle Tests laufen gegen Attrappen;
  ein `ANTHROPIC_API_KEY` liegt nicht vor. Geprüft ist die Verdrahtung und
  jeder Fehlerpfad, **offen ist die Qualität** — siehe unten.
- **`booking_url` ist immer leer** — Amadeus liefert in der Suchantwort
  keinen Buchungslink. Der Knopf „Zum Angebot" erscheint deshalb nie.
- **Alarme lassen sich nicht bearbeiten** (nur anlegen, pausieren, löschen).
  Das Backend kann PATCH auf allen Feldern; es fehlt nur die Oberfläche.
- **Nur ein Suchdatum pro Alarm** — der Datums-Fächer fehlt. Vorbereitet:
  `alarm_zu_suchanfragen()` gibt schon eine Liste zurück.
- **Die Fixture ist nachgebaut, nicht mitgeschnitten.** Erste Aufgabe mit
  Amadeus-Zugang: einmal echt suchen, Antwort nach `tests/fixtures/` schreiben.
- **Rate Limiting zählt je Prozess** (siehe `core/ratelimit.py`), **Sentry ist
  nicht angebunden** (ohne DSN toter Code), **keine Offline-Fähigkeit**,
  **`GET /alerts` ohne Paginierung**, **die 90 Tage der Statistik sind fest**.

### Stolperfallen dieser Umgebung

- **Kein Docker-Daemon**, aber Postgres per apt vorhanden:
  `/usr/lib/postgresql/16/bin`, mit `initdb`/`pg_ctl` als User `postgres`
  starten. Datenverzeichnis muss für `postgres` erreichbar sein
  (`/var/lib/postgresql/<name>` geht, `/tmp/claude-*` nicht).
  **Überlebt keinen Container-Neustart** — lauter `s` bei `pytest` heißt: nur
  die DB ist weg, nichts ist kaputt.
- **Committete Daten in der Test-Datenbank.** `finde_faellige_alarme()` sucht
  über **alle** Nutzer. Bleibt aus einem Browsertest ein aktiver Alarm liegen,
  schlagen ~7 Tests in `test_pruflauf.py` fehl, **ohne dass am Code etwas
  kaputt ist**. Aufräumen: `TRUNCATE users CASCADE;`.
- **Rate-Limit-Zähler leben im Prozess.** `tests/conftest.py` leert sie
  `autouse` vor jedem Test — sonst erwischt es irgendwann jemanden.
- **SQLAlchemy async:** Nach `session.rollback()` sind alle Objekte
  „abgelaufen"; der nächste Attributzugriff ergibt `MissingGreenlet`. Deshalb
  merkt sich `pruefe_faellige_alarme()` nur IDs.
- **Identity Map:** Ein `RETURNING` gibt bei bereits geladenen Zeilen das
  **alte** Objekt zurück → `execution_options={"populate_existing": True}`.
- **Browsertests liegen nicht im Repo** (Playwright ist keine
  Projekt-Abhängigkeit). Chromium unter `/opt/pw-browsers`, `playwright` per
  `uv pip install` in eine eigene Umgebung. Zwei Fallen: Chromium behandelt
  `new_context()` wie Inkognito (dort fehlt die Push-API,
  crbug.com/401439) → `launch_persistent_context`; und ein Testalarm braucht
  `check_interval_minutes >= 15` (DB-CHECK).

---

## Exakter Arbeitspunkt

**Alles committet und gepusht, nichts halbfertig.** Letzter Commit `e836bcd`.

Am Code ist bis zum Deployment nichts mehr zu tun. Die nächste Session
beginnt erst sinnvoll, wenn mindestens Supabase und Amadeus eingerichtet sind.

---

## Nächste Schritte

### Sobald die Zugänge da sind (in dieser Reihenfolge)

1. **Zugänge eintragen** und lokal einmal komplett durchspielen:
   `cp .env.example .env`, Werte einsetzen, `make migrate`, `make dev`,
   `make worker`, `make web`. Ein Alarm auf einer echten Strecke, dann im
   Worker-Log nachsehen, ob Amadeus antwortet.
2. **Echte Amadeus-Antwort als Fixture speichern**
   (`make suche a="MUC BCN 2026-09-06"`) und `tests/fixtures/README.md`
   aktualisieren. Die jetzige Fixture ist nachgebaut.
3. **Claude-Qualität messen** — zwei Dinge, beide bisher ungeprüft:
   - *Texte (M10):* `SELECT title, body, text_quelle FROM notification_logs
     ORDER BY sent_at DESC LIMIT 5;` Steht dort dauerhaft `baukasten`, greift
     der Fallback still — der Grund steht im Worker-Log.
   - *Verstehen (M11):* Das Golden-Set aus Projektplan 9.4 fehlt noch — rund
     20 deutsche Beispielsätze gegen den **echten** Aufruf, als Skript, das
     man vor Prompt-Änderungen von Hand laufen lässt (kostet Geld, gehört
     nicht in die normale Testreihe). Wichtigste Frage: Trifft „im Oktober"
     das richtige Jahr?
4. **Deployment** → `anleitungen/05-Deployment.docx`. Kurzfassung: zwei
   Dienste aus demselben Bild (`uvicorn app.main:app` und
   `python -m app.jobs.worker`), **genau eine Worker-Instanz**,
   Readiness-Probe auf **`/health/ready`**, `LOG_FORMAT=json`, beim
   Supabase-Pooler auf Port 6543 zusätzlich
   `DATABASE_DISABLE_STATEMENT_CACHE=true`.
5. **Push auf dem iPhone** → `anleitungen/06-iPhone-Push-testen.docx`. Der
   eine Test, der seit M8 aussteht.

### Danach, falls Lust auf mehr

Alarme bearbeiten (Oberfläche fehlt, Backend kann es) · Datums-Fächer über
den Reisezeitraum · Sentry anbinden · Paginierung.
