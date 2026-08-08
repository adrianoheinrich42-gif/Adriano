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
  config.py          Settings aus ENV (DB-URL, CORS, Pooler-Schalter, Supabase)
  db.py              async Engine/Session, is_database_reachable()
  api/deps.py        get_token_claims (ohne DB) + get_current_user / CurrentUser
  api/routes/        health.py, auth.py (GET /me), price_alerts.py (CRUD /alerts),
                     push.py (M8), ergebnisse.py (M9: /offers, /verlauf),
                     nlp.py (M11: POST /alerts/entwurf — legt nichts an)
  core/security.py   JWT-Prüfung der Supabase-Token (HS256)
  models/            6 SQLAlchemy-Tabellen (+ mixins.py, __init__ importiert alle)
  schemas/           price_alert.py (API-Ein/Ausgabe), flight_offer.py (intern),
                     ergebnis.py (M9), nlp.py (M11: Entwurf)
  services/          users.py, price_alerts.py, amadeus.py (Client + Normalisierung),
                     pruflauf.py (M6: reine Funktionen + Orchestrierung),
                     price_stats.py (M7: Median/Abweichung + Vergleichsabfrage),
                     push.py (M8: Textbaukasten, Bremsen, Web-Push-Versand),
                     ergebnisse.py (M9: Angebote + Preisverlauf lesen),
                     claude.py (M10: Protokoll Texter, Prompt, Antwortprüfung),
                     nlp.py (M11: Sprache → Suchkriterien + Plausibilitätsprüfung)
  jobs/worker.py     M6: APScheduler-Prozess, ruft den Prüflauf im Takt auf
  alembic/           env.py (async, URL aus config), versions/ (2 Migrationen)
backend/scripts/     amadeus_suche.py — Handsuche, vapid_schluessel.py (M8)
backend/tests/       *.py ohne DB/Netz, integration/ mit DB, fixtures/ gespeicherte
                     Amadeus-Antwort (Herkunft: fixtures/README.md lesen!),
                     attrappen.py (Doppelgänger der Flugsuche + Baukästen)
web/                 Frontend (M4): index.html, app.js (Ansichten), api.js (nur
                     hier fetch aufs Backend), auth.js (Supabase-Anmeldung),
                     format.js (Cent↔Euro, Datum), config.js, styles.css,
                     push.js + sw.js + manifest.json + icons/ (M8: PWA & Push),
                     detail.js (M9: Einordnung, SVG-Verlauf, Angebote)
docs/SUPABASE-EINRICHTEN.md  Anleitung ohne Vorwissen (Nutzer-Aktion)
docs/PROJEKTPLAN.md  Referenz: Architektur, Datenmodell, Meilensteine, Risiken
docs/PLATTFORM-WEB.md  iOS→Web-Wechsel + alle Deltas zum Projektplan
HANDOFF.md           aktueller Arbeitsstand (bei jeder Session aktuell halten)
```

## Datenmodell (6 Tabellen, `backend/app/models/`)

`users` (spiegelt Supabase-Auth-ID, keine Passwörter), `price_alerts` (Herzstück),
`flight_observations` (Preisverlauf, Strecke+Monat denormalisiert für streckenweite
Statistik), `flight_offers` (konkrete Angebote), `device_tokens` (Push-Ziel),
`notification_logs` (Versandprotokoll + Dedupe + seit M10 `title`/`body`/
`text_quelle`). Spalten/Constraints im Code.

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
- **Frontend:** kein Framework/Node einführen. Auch `supabase-js` nicht — die
  Anmeldung sind drei `fetch`-Aufrufe (`web/auth.js`). Fehler dem Nutzer als
  verständlicher deutscher Text zeigen, nie Statuscode.
- **Nur `web/api.js` ruft `fetch` aufs eigene Backend auf.** Eine Stelle für
  Token, Zeitlimit und Fehlerübersetzung.
- **Im Frontend `textContent`, nie `innerHTML`.** Auch bei Daten aus dem
  eigenen Backend — HTML aus Daten zusammenkleben ist die Gewohnheit, aus der
  später Lücken werden.
- **`[hidden] { display: none !important }` muss im CSS stehen.** Die App
  schaltet Ansichten über das `hidden`-Attribut um; jede eigene
  `display`-Regel (z. B. `.kopf { display: flex }`) würde `hidden` sonst
  aushebeln. Genau dieser Fehler ist im Browsertest aufgefallen.
- **Sekrete-Check vor jedem Commit:** kein `.env`, kein `.p8`, kein Key im Diff.

## Wichtige Entscheidungen (Kurzbegründung)

- **Web statt iOS:** kein Mac vorhanden, aber iPhone 15. PWA + Web-Push (ab
  iOS 16.4) läuft; spart 99 €/Jahr Apple. Details `docs/PLATTFORM-WEB.md`.
- **Supabase Auth statt Eigenbau:** Login/Reset/Hashing sind fehleranfällig;
  Backend prüft nur das JWT.
- **Der Client kennt beim Anmelden eine zweite URL** (Supabase) — die einzige
  bewusste Ausnahme von Leitplanke 1. Ginge der Login durchs eigene Backend,
  liefe das **Passwort über unseren Server**; genau das soll Supabase Auth
  verhindern. Alle *Daten* laufen weiterhin nur übers eigene Backend.
  Begründung in `docs/PLATTFORM-WEB.md`.
- **Der Supabase-`anon`-Schlüssel darf in `web/config.js` stehen.** Er ist
  dafür gemacht, öffentlich zu sein, und erlaubt allein nur einen
  Anmeldeversuch — anders als Amadeus-/Anthropic-/VAPID-Schlüssel, die
  Leitplanke 2 meint. Der `service_role`-Schlüssel gehört **nie** dorthin.
- **APScheduler (ab M6), 1 Worker-Instanz:** einfach, kein Redis. Grenze: zwei
  Instanzen = doppelte Läufe → dann externer Cron + `FOR UPDATE SKIP LOCKED`.
- **`/health` gibt immer HTTP 200** (Zustand im Body) — hält den Client simpel;
  echte 503-Readiness erst bei M12.
- **JWT-Prüfung nur symmetrisch (HS256)** — ein gemeinsames Geheimnis, kein
  JWKS-Abruf, keine Krypto-Bibliothek. Erweiterung auf RS256/ES256 betrifft
  ausschließlich `app/core/security.py`; Endpunkte kennen nur `CurrentUser`.
- **Nutzer-Zeile per Upsert beim ersten authentifizierten Request**, kein
  Supabase-Webhook: weniger Teile, und auch früher registrierte Nutzer bekommen
  ihre Zeile.
- **Fremde Ressourcen ergeben 404, nie 403.** Ein 403 verrät, dass es das
  Objekt gibt. Umgesetzt dadurch, dass `user_id` **in jeder Abfrage** in der
  WHERE-Klausel steht, statt nachträglich den Besitzer zu prüfen.
- **PATCH prüft den zusammengeführten Stand**, nicht nur die geschickten
  Felder (`pruefe_feldkombination` in `schemas/price_alert.py` wird von
  Create *und* Service benutzt). Ein einzelnes Feld kann für sich gültig sein
  und trotzdem nicht zum Rest passen.
- **Alarm-Limit mit `SELECT … FOR UPDATE`** auf die Nutzer-Zeile: sonst
  könnten zwei gleichzeitige Requests das Kontingent überschreiten.
- **Amadeus-Client und Normalisierung sind getrennt** (`services/amadeus.py`):
  oben HTTP + Token, unten reine Funktionen. Nur so ist die Übersetzung gegen
  eine gespeicherte Antwort testbar. **Kein Test geht je ins Netz**
  (`httpx.MockTransport`).
- **Amadeus-Zeiten sind lokale Flughafenzeiten ohne Offset** und werden genau
  so weitergereicht, statt eine Zeitzone zu erfinden. Für echte Zeitpunkte
  gibt es `dauer_minuten`.
- **Ortszeit wird als UTC gespeichert, nicht umgerechnet** (`ortszeit_als_utc`
  in `services/pruflauf.py`, M6). Die Wanduhrzeit stimmt damit in der Anzeige
  („09:15 ab München"), der **Zeitpunkt ist aber falsch**. Zwei solche Zeiten
  darf man deshalb nie voneinander abziehen — Dauern kommen aus
  `dauer_minuten`. Alternative wäre eine Flughafen-Zeitzonentabelle (~5000
  Einträge mit jährlich wechselnden Sommerzeitregeln); dafür ist es zu früh.
  Nebenwirkung: Flüge über die Datumsgrenze nach Osten (Ankunfts-Ortszeit vor
  Abflugs-Ortszeit) verletzen `ck_offers_outbound_time_order` und werden
  übersprungen statt gespeichert.
- **`alarm_zu_suchanfragen()` gibt eine Liste zurück**, obwohl vorerst genau
  ein Eintrag darin steht. Der Alarm nennt einen Zeitraum, die API will ein
  Datum — der Datums-Fächer über den Zeitraum kommt später. Weil der Prüflauf
  schon jetzt über eine Liste iteriert, ist das dann eine Änderung an **einer**
  Stelle statt ein Umbau aller Aufrufer.
- **`last_checked_at` wird auch nach einem Fehler gesetzt.** Sonst bliebe der
  Alarm fällig und der Worker hämmerte im Minutentakt gegen eine Schnittstelle,
  die gerade ohnehin nicht will. Der Fehlversuch steht als
  `flight_observation` mit `search_ok = false` in der Datenbank und wird
  dadurch aus der Preisstatistik herausgehalten.
- **Kein `FOR UPDATE SKIP LOCKED` in `finde_faellige_alarme`** — es läuft
  genau eine Worker-Instanz (siehe APScheduler-Entscheidung oben). Kämen zwei
  dazu, gehört die Sperre in genau diese eine Abfrage.
- **Amadeus bekommt das Preislimit des Nutzers NICHT mit** (kein `maxPrice`).
  Sonst lieferte die API an teuren Tagen nichts, die Beobachtung bekäme
  `min_price_cents = NULL`, und der Median in M7 sähe nur die guten Tage.
  Gefiltert wird ausschließlich lokal in `_angebot_als_zeile()`. Kostet keine
  zusätzliche Anfrage — Amadeus sortiert nach Preis, `max_ergebnisse`
  schneidet also die teuersten ab.
- **Median statt Durchschnitt** (`price_stats.py`): Ein einzelner
  Business-Class-Tarif zöge den Durchschnitt um Hunderte Euro hoch. Nur der
  Median beschreibt, was man üblicherweise zahlt.
- **Unter 10 Datenpunkten gibt es keine Prozentaussage**, sondern
  `ZU_WENIG_DATEN` — dann sagt die App „erster Treffer unter deinem Limit".
  Ehrlichkeit schlägt Scheingenauigkeit. `median_cents` und
  `abweichung_prozent` sind in dem Fall `None`, damit niemand versehentlich
  eine 0 anzeigt.
- **Die Statistik vergleicht einen Lauf nicht gegen sich selbst.** Die
  Vergleichspreise werden geholt, *bevor* die eigene Beobachtung geschrieben
  wird — sonst steckt der heutige Preis im Median, gegen den er gemessen wird.
- **Nur `search_ok = true` und `min_price_cents IS NOT NULL` zählen.** Ein
  API-Ausfall darf nicht als „an dem Tag war nichts zu holen" gelesen werden.
- **Push-Protokollzeile wird VOR dem Versand geschrieben** (Status `pending`).
  Der `UNIQUE`-Index auf `dedupe_key` muss den Platz belegen, bevor etwas
  Langsames passiert — sonst könnte zwischen Senden und Schreiben ein zweiter
  Lauf dieselbe Nachricht noch einmal verschicken.
- **Reihenfolge der Bremsen:** Abkühlphase/5-%-Regel zuerst (billig, im
  Speicher), dann Dedupe (`ON CONFLICT DO NOTHING`). Bei identischem Angebot
  innerhalb der Abkühlphase greift deshalb die Abkühlphase, nicht Dedupe.
- **Melden passiert NACH dem Commit des Prüflaufs.** Der Versand geht über das
  Netz; hinge die Transaktion so lange offen, blockierte sie die Zeilen des
  Alarms. Und ein Versandfehler darf Beobachtung und Angebote nicht
  zurückrollen — die sind unabhängig davon richtig.
- **404/410 vom Push-Dienst legt das Ziel still** (`is_active = false`), alles
  andere nicht. 410 heißt „Erlaubnis entzogen", 503 nur „gerade Schluckauf".
- **Der Client leitet „Push ist an" NICHT aus `Notification.permission` ab**,
  sondern aus einem tatsächlich vorhandenen Abonnement. Beides fällt
  auseinander (abgemeldet, zweites Gerät, Browserdaten gelöscht).
- **Keine Messung wird gegen sich selbst verglichen** — auf zwei Wegen: Der
  Prüflauf holt die Vergleichspreise, *bevor* er seine Beobachtung schreibt;
  die Detailansicht schneidet mit `hole_vergleichspreise(..., bis=heute)` den
  laufenden Tag ab. Ohne das wäre `ist_bestpreis` in der Detailansicht nie
  wahr, weil das Minimum immer schon der eigene Preis ist.
- **Die Verlaufskurve zeigt heute mit, der Vergleich nicht.** Die Kurve
  erzählt die eigene Geschichte („was habe ich beobachtet?"), die Bewertung
  fragt „was ist hier üblich?" — zwei verschiedene Fragen.
- **Der Anker (`#alarm=<id>`) ist der Ansichtszustand des Clients.** Damit
  funktionieren Browser-Zurück und der Deep-Link aus der Push ohne Router.
  Ein Pfad wie `/alarm/<id>` bräuchte einen Server, der ihn auf `index.html`
  umschreibt — der Anker läuft auch unter `python -m http.server`.
- **`navigator.serviceWorker.ready` abwarten, nicht nur `register()`.**
  `register()` kehrt zurück, solange der Worker noch „installing" ist —
  `subscribe()` scheitert dann beim **ersten** Besuch mit „no active Service
  Worker".
- **Claude wird nur gerufen, wenn wirklich eine Push rausgeht** — nie beim
  Suchen, nie beim Anzeigen. Die Detailansicht liest den Satz aus
  `notification_logs`, statt ihn neu erzeugen zu lassen. Sonst hinge der
  Lesepfad an einer fremden Schnittstelle und kostete bei jedem Öffnen Geld.
- **Jede Zahl in Claudes Text wird gegengeprüft** (`pruefe_text` in
  `services/claude.py`). Structured Output garantiert die *Form*, nicht die
  *Richtigkeit*; „18 %" statt der berechneten 21 % wäre eine erfundene Zahl in
  einer Nachricht, die wie eine Tatsache aussieht. Passt eine Zahl nicht, gilt
  der ganze Text als verworfen und der Baukasten übernimmt. Absichtlich
  streng — ein verworfener guter Satz kostet nichts.
- **`erzeuge_nachricht()` wirft nie**, und das nackte `except Exception` dort
  ist Absicht. Jede SDK-Ausnahmeklasse einzeln aufzuzählen hieße, dass die
  eine vergessene nachts die Benachrichtigung verschluckt.
- **Titel und Ziel-Adresse der Push kommen immer vom Baukasten**, auch wenn
  Claude den Text schreibt. Die URL ist Technik, kein Text.
- **In der Detailansicht wird nur ein *Claude*-Text wiederverwendet.** Der
  Baukasten hat dort eine eigene Fassung (`formuliere_einordnungssatz`) ohne
  Preis-Präfix und ohne „Direktflug · LH" — beides steht daneben schon.
- **Die App legt offen, wenn Claude formuliert hat.** Wer Text von einem
  Sprachmodell liest, soll das wissen, ohne raten zu müssen.
- **Claude bekommt keine Nutzerdaten** — keine ID, keine E-Mail. Für „schreib
  einen netten Satz" braucht es die nicht (`Erklaerfakten` ist die eine
  Stelle, an der sichtbar ist, was das Modell sieht).
- **`localhost` und `127.0.0.1` sind für den Browser zwei Herkünfte.** Beide
  stehen in `cors_origins`; sonst meldet die App „Keine Verbindung zum
  Server", während im Backend-Log ein 200 steht.
- **Kein Alarm entsteht direkt aus Claudes Ausgabe** (M11, Projektplan 8.8).
  Der Endpunkt heißt `POST /alerts/entwurf` und **speichert nichts**; er füllt
  nur das Formular vor, bestätigen muss der Mensch. Structured Output
  garantiert die Form, nicht den Inhalt — „im Oktober" kann leicht im falschen
  Jahr landen.
- **Die Plausibilitätsprüfung lässt weg statt zu raten** (`pruefe_kriterien`).
  Ein leeres Feld sieht der Nutzer, eine still erfundene Zahl nicht. Zwei
  Ausnahmen, die gekappt statt verworfen werden: Umstiege und Reisendenzahl —
  bei „40 Leuten" ist 9 näher am Wunsch als nichts.
- **Sie prüft Form, nicht Existenz.** Ob es den Flughafen `XQZ` gibt, ließe
  sich nur mit einer Flughafentabelle beantworten. Genau deshalb bestätigt der
  Nutzer.
- **Claude bekommt beim Verstehen das heutige Datum mitgeschickt.** Ohne das
  kann kein Modell „im Oktober" auflösen — es weiß nicht, ob gerade September
  oder November ist. Häufigste Ursache für Alarme im falschen Jahr.
- **Bei M11 gibt es keinen Fallback, und das ist richtig.** Einen deutschen
  Satz kann ein Baukasten schreiben, einen Satz *verstehen* nicht. Der
  Rückfall ist das normale leere Formular (HTTP 503 + verständlicher Satz).
- **Der Entwurfs-Endpunkt verlangt Anmeldung**, obwohl er nichts speichert —
  sonst wäre er ein offener Endpunkt auf unsere Anthropic-Rechnung. Aus
  demselben Grund ist die Eingabe auf 500 Zeichen gedeckelt.
- **Zwei Eigenheiten der Amadeus-API:** `maxPrice` nimmt nur ganze
  Währungseinheiten (wir runden **ab**, nie über das Nutzerlimit), und es gibt
  keinen „max. N Umstiege"-Parameter — nur `nonStop`. Der Rest wird nach dem
  Abruf gefiltert.

## Befehle

**Frisch geklont oder entpackt** (aus `backend/`, in dieser Reihenfolge):
```
cp .env.example .env                 # .env ist gitignored, fehlt also immer
uv sync                              # legt .venv an (nicht im Repo/ZIP)
docker compose up -d db              # oder lokales Postgres, siehe HANDOFF
uv run alembic upgrade head          # Schema anlegen
uv run pytest -q                     # muss grün sein, bevor es weitergeht
```

Backend (aus `backend/`):
```
uv sync                              # Abhängigkeiten
uv run alembic upgrade head          # Schema
uv run uvicorn app.main:app --reload # API → :8000  (/health, /docs)
uv run python -m app.jobs.worker     # Worker (Prüflauf im Takt), make worker
uv run pytest -q                     # Tests
uv run ruff format . && uv run ruff check . && uv run mypy app
uv run alembic revision --autogenerate -m "..."   # neue Migration
uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06   # Handsuche (make suche)
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
- **Ohne DB:** `pytest` meldet `224 passed, 134 skipped` (Integrationstests
  überspringen sich selbst). Mit DB: `358 passed`. Beides ist „grün".
- **Frontend prüfen geht wirklich:** Chromium und Playwright sind vorhanden
  (`/opt/pw-browsers`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, kein
  `playwright install`). Supabase lässt sich per `page.route("**/auth/v1/**")`
  ersetzen, das Token mit `SUPABASE_JWT_SECRET` selbst signieren — dann prüft
  das Backend unverändert scharf und **kein Testcode steht in der App**.
- **Branch:** der in der Session vorgegebene Entwicklungs-Branch (zuletzt
  `claude/project-handoff-continuation-9lcu5l`, davor
  `claude/project-handoff-continuation-3tzcq4` und
  `claude/flight-price-alert-app-8sh4sy`). Dort entwickeln, committen, pushen
  (`git push -u origin <branch>`). Keine PR ohne Auftrag.
- **Commit-Footer** (jeder Commit):
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  Claude-Session: <URL der laufenden Session>
  ```
  Modell-ID nie in Commits/Code schreiben.
- **`docs/PROJEKTPLAN.md`** ist die inhaltliche Referenz; bei Client/Push gilt
  **`docs/PLATTFORM-WEB.md`** vor. Beide bei größeren Änderungen aktuell halten.
