# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
M4 — Web-Client: Anmeldung, Alarmliste, Formular   ← neu
02306d3 M7 — Preisstatistik (+ maxPrice-Verzerrung behoben)
6f08a1a M6 — Prüflauf: Alarme und Flugsuche verbunden
db30665 M5 — Amadeus-Anbindung
68a2125 M3 — CRUD für Preisalarme
9a5aefa M2 — Auth-Kette mit Supabase-JWT
99334da Plattformwechsel iOS → Web-App (PWA)
ef9189a M1 — Datenbankmodell und erste Migration
def9ae6 M0 — Projektgerüst
```

## Wo wir stehen

**M0–M7 fertig.** Die App ist zum ersten Mal von Hand benutzbar: anmelden,
Alarm anlegen, Liste ansehen, pausieren, löschen. Das Backend prüft
zeitgesteuert bei Amadeus, zeichnet den Preisverlauf auf und ordnet Angebote
gegen die Streckenhistorie ein.

**Noch 5 Meilensteine: M8–M12.**

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts`.
Prozesse: API (`app.main:app`) **und** Worker (`app.jobs.worker`).

Meilenstein-Übersicht: `docs/PROJEKTPLAN.md` §5; für Client/Push gilt
`docs/PLATTFORM-WEB.md` vor.

## ⚠️ Zwei Dinge fehlen, die nur der Nutzer tun kann

Beides blockiert nicht die Entwicklung, aber den echten Betrieb:

1. **Supabase-Projekt** → `docs/SUPABASE-EINRICHTEN.md` (Anleitung ohne
   Vorwissen, ~15 Minuten). Danach `SUPABASE_URL` und `SUPABASE_JWT_SECRET`
   in `backend/.env`, `supabaseUrl` und `supabaseAnonKey` in `web/config.js`.
   **Ohne das kann sich niemand anmelden.**
2. **Amadeus-Zugang** → Konto auf `developers.amadeus.com`,
   `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in `backend/.env`. Ohne das
   laufen Tests und Worker, nur die echte Suche scheitert (mit klarer Meldung).

## Was umgesetzt ist

- **M0** — FastAPI, `GET /health`, `config.py`, `db.py`; `docker-compose.yml`,
  `Dockerfile`, `Makefile`, `.env.example`.
- **M1** — 6 Tabellen, eine Alembic-Migration. 16 Integrationstests auf die
  DB-Zusicherungen.
- **M2** — `core/security.py` (JWT HS256), `api/deps.py`, `services/users.py`,
  `GET /me`.
- **M3** — `schemas/price_alert.py`, `services/price_alerts.py`,
  `api/routes/price_alerts.py`.
- **M4** — siehe nächster Abschnitt.
- **M5** — `services/amadeus.py`, `schemas/flight_offer.py`,
  `scripts/amadeus_suche.py`, Fixture.
- **M6** — `services/pruflauf.py`, `jobs/worker.py`, `tests/attrappen.py`.
- **M7** — `services/price_stats.py`; Einordnung hängt im `LaufErgebnis`.

## Zuletzt geändert — M4 (Web-Client)

Neu in `web/`: `auth.js`, `api.js`, `format.js`. `index.html`, `app.js`,
`styles.css` und `config.js` neu geschrieben. Neu: `docs/SUPABASE-EINRICHTEN.md`.

| Datei | Wofür |
|---|---|
| `auth.js` | Registrieren, Anmelden, Abmelden, Token erneuern |
| `api.js` | **Einziger Ort mit `fetch` aufs Backend** — Token, Zeitlimit, deutsche Fehler |
| `format.js` | Cent ↔ Euro, Datum, „vor 5 Minuten" |
| `app.js` | Zwei Ansichten (angemeldet / nicht), Liste zeichnen |

Funktionsumfang: Registrieren und Anmelden, Alarmliste mit Lade-, Leer- und
Fehlerzustand, Anlege-Formular (Pflichtfelder oben, Seltenes eingeklappt),
Pausieren/Fortsetzen, Löschen mit Rückfrage, Abmelden. Hell und dunkel,
mobil-zuerst.

### Entscheidungen aus M4

Ausführlich in `CLAUDE.md` und `docs/PLATTFORM-WEB.md`:

- **Kein `supabase-js`.** Die Bibliothek käme über ein fremdes CDN; die drei
  Dinge, die wir brauchen, sind je ein `fetch` gegen die Supabase-REST-API.
  Damit bleibt es bei „kein Framework, kein Node, keine fremde Abhängigkeit".
- **Der Client kennt beim Anmelden eine zweite URL** — die einzige bewusste
  Ausnahme von Leitplanke 1. Ginge der Login durchs eigene Backend, liefe das
  **Passwort über unseren Server**. Alle *Daten* laufen weiter nur übers
  eigene Backend.
- **Der `anon`-Schlüssel darf in `config.js` stehen** (öffentlich by design).
  Der `service_role`-Schlüssel **nie**.
- **Nur `api.js` ruft `fetch` aufs Backend auf** — eine Stelle für Token,
  Zeitlimit und Fehlerübersetzung.
- **Bei 422 hat der Satz des Backends Vorrang** vor der eigenen Feldliste.
  FastAPI liefert für Kombinationsregeln (`loc: ["body"]`) bereits einen
  fertigen deutschen Satz; „Bitte prüfe das Feld body" hilft niemandem.
- **`textContent`, nie `innerHTML`.**
- **Liste wird bei jeder Änderung neu gezeichnet.** Bei fünf Alarmen schnell
  genug, und es gibt keinen Zustand, der auseinanderlaufen kann.

## Verifizierter Zustand (real nachgeprüft, nicht behauptet)

- **Backend-Tests:** mit DB `208 passed`; ohne DB `142 passed, 66 skipped`.
  `ruff` und `mypy app` (strict) sauber, `alembic check` ohne Drift.
  Diese Zahlen sind der Soll-Wert für die nächste Session.
- **M4 im echten Chromium gegen das echte Backend geprüft — 11 Schritte:**
  1. Anmeldeansicht erscheint, `/health` meldet „Server erreichbar."
  2. Falsches Passwort → „E-Mail-Adresse oder Passwort stimmt nicht."
  3. Anmeldung klappt, Leerzustand „Noch kein Alarm"
  4. Alarm angelegt; „muc" wurde zu MUC, „200,00" zu 20000 Cent
  5. Backend bestätigt `max_price_cents = 20000`
  6. Serverregel als deutscher Satz: „Start- und Zielflughafen dürfen nicht
     gleich sein." (kein „422", kein „body")
  7. Preis „zweihundert" wird abgefangen, bevor eine Anfrage rausgeht
  8. Pausieren wirkt (PATCH) und die Karte zeigt es
  9. Ungültiges Token → 401 → automatisch zurück zur Anmeldung
  10. Löschen mit Rückfrage, danach wieder Leerzustand
  11. Abmelden löscht die Sitzung; nach Neuladen bleibt man abgemeldet

  Keine Fehler in der Browser-Konsole. **Supabase war dabei eine Attrappe**
  (`page.route("**/auth/v1/**")`), das Token aber echt mit
  `SUPABASE_JWT_SECRET` signiert — das Backend prüfte also unverändert scharf.
  **Im Anwendungscode steht dafür keine einzige Testzeile.**
- **Dabei gefunden und behoben:** `.kopf { display: flex }` hebelte das
  `hidden`-Attribut aus — die Kopfzeile war vor dem Login sichtbar. Fix:
  `[hidden] { display: none !important }` ganz oben in `styles.css`.
- **Statistik gegen echte committete Daten belegt** (M7, weiterhin gültig):
  14 Beobachtungen HAM→LIS mit einem Ausreißer über 1200 €, einer Zeile mit
  `search_ok = false` und einer 200 Tage alten →

  ```
   199.00 EUR → guenstig   Median 251.00 EUR  -20.7 %  n=12  Bestpreis=True
   251.00 EUR → normal     Median 251.00 EUR   +0.0 %  n=12  Bestpreis=False
   299.00 EUR → teuer      Median 251.00 EUR  +19.1 %  n=12  Bestpreis=False
   230.00 EUR → normal     Median 251.00 EUR   -8.4 %  n=12  Bestpreis=True
   ohne Historie → zu_wenig_daten, n=0, Median=None
  ```

## Offene Punkte / Fallstricke

- **Der Browsertest liegt nicht im Repository.** Er brauchte Playwright, das
  keine Projekt-Abhängigkeit ist. Wer ihn wiederholen will: Chromium liegt
  unter `/opt/pw-browsers`, `playwright` per `uv pip install` in eine eigene
  Umgebung, Supabase per `page.route("**/auth/v1/**")` ersetzen, Token mit
  `SUPABASE_JWT_SECRET` signieren. Ob er als Projekt-Abhängigkeit dazukommen
  soll, ist eine offene Entscheidung (Kosten: Node-freie, aber große
  Abhängigkeit).
- **Alarme lassen sich nur anlegen und löschen, nicht bearbeiten.** Das
  Backend kann PATCH auf allen Feldern; die Oberfläche nutzt es bisher nur für
  Pausieren/Fortsetzen.
- **Die Statistik ist im Client noch nicht sichtbar.** `Preisbewertung` steckt
  im `LaufErgebnis` und im Log, es gibt keinen Endpunkt dafür. Abnehmer sind
  M8 (Push) und M9 (Detailansicht).
- **Noch keine PWA.** Kein Manifest, kein Service Worker, kein Icon — die App
  ist noch nicht „zum Home-Bildschirm hinzufügbar". Gehört zu M8.
- **Die Fixture ist nachgebaut, nicht mitgeschnitten.** Erste Aufgabe mit
  Amadeus-Zugang: einmal echt suchen, Antwort nach `tests/fixtures/` schreiben.
  Details: `backend/tests/fixtures/README.md`.
- **Falls Supabase nur asymmetrische Schlüssel anbietet** (neuere Projekte:
  „JWT Signing Keys", ECC/RSA statt „Legacy JWT Secret") →
  `core/security.py` auf RS256/ES256 erweitern (`pyjwt[crypto]`). Betrifft
  genau diese Datei; die Endpunkte kennen nur `CurrentUser`.
- **Die 90 Tage der Statistik sind fest**, keine Einstellung.
- **Nur ein Suchdatum pro Alarm** — der Datums-Fächer fehlt noch.
  `alarm_zu_suchanfragen()` gibt deshalb schon eine Liste zurück.
- **Kein Aufräumen alter Daten.** `flight_observations` wächst pro Alarm und
  Lauf. Kandidat für M11/M12.
- **`GET /alerts` ohne Paginierung.** Bei 5 Alarmen egal.
- **Token ohne `email`** → 401, weil `users.email` NOT NULL ist.
- **`device_tokens` wird in M8 angepasst** (Web-Push statt APNs) — eigene
  Migration.
- **`.env` und `.venv` fehlen nach Klonen/Entpacken immer** →
  `cp .env.example .env`, `uv sync`.
- **Postgres in dieser Sandbox:** kein Docker-Daemon, aber per apt vorhanden
  (`/usr/lib/postgresql/16/bin`, `initdb`/`pg_ctl` als User `postgres`). Das
  Datenverzeichnis muss für `postgres` erreichbar sein —
  `/var/lib/postgresql/<name>` geht, `/tmp/claude-*` nicht. **Überlebt keinen
  Container-Neustart** — lauter `s` in `pytest` heißt: nur die DB ist weg,
  nicht der Code kaputt.
- **Stolperfalle SQLAlchemy async:** Nach `session.rollback()` sind alle
  Objekte der Session „abgelaufen"; der nächste Attributzugriff ergibt
  `MissingGreenlet`. Deshalb merkt sich `pruefe_faellige_alarme()` nur IDs.
  Wer Tests um Fehlerfälle schreibt, muss IDs **vor** dem Rollback festhalten.
- **Stolperfalle Statistik-Tests:** `hole_vergleichspreise()` fragt über alle
  Nutzer ab. Tests dürfen sich keine feste Strecke teilen —
  `tests/integration/test_price_stats.py` würfelt sie pro Test aus.
- **Stolperfalle: committete Daten in der Test-Datenbank.** Die
  Integrationstests rollen ihre eigenen Daten zurück, aber
  `finde_faellige_alarme()` sucht bewusst über **alle** Nutzer. Bleibt aus
  einem Handversuch (Demo-Skript, abgebrochener Browsertest) ein aktiver
  Alarm liegen, schlagen in `tests/integration/test_pruflauf.py` etwa sieben
  Tests mit „Left contains one more item" fehl — **ohne dass am Code etwas
  kaputt ist**. Genau das ist in dieser Session passiert. Prüfen mit
  `SELECT * FROM price_alerts;`, aufräumen mit `TRUNCATE users CASCADE;`.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M4 abgeschlossen, committet und gepusht. Nichts ist halbfertig.

## Nächste Schritte — M8 (Push-Benachrichtigungen)

Der letzte fehlende Teil der Kernfunktion: Bisher merkt niemand, wenn ein
Preis passt. Reihenfolge:

1. **PWA-Grundlage** — `manifest.json`, Icons, Service Worker. Ohne das kann
   iOS gar keine Push empfangen.
2. **`device_tokens` umbauen** — Web-Push-Subscription (`endpoint`, `p256dh`,
   `auth`) statt APNs-Token, `environment` entfällt. **Eigene Migration.**
3. **VAPID-Schlüsselpaar** erzeugen, privaten Schlüssel in `backend/.env`,
   öffentlichen an den Client ausliefern.
4. **Endpunkt zum Anmelden der Subscription** (`POST /push/subscriptions`).
5. **Versand im Worker** mit `pywebpush`, nach dem Prüflauf.
6. **Dedupe + Bremsen:** `notification_logs.dedupe_key` per
   `INSERT … ON CONFLICT DO NOTHING`, dazu Abkühlphase und 5-%-Regel
   (`docs/PROJEKTPLAN.md` §4 ⑨).
7. **Nachrichtentext** aus der `Preisbewertung` von M7 — deterministischer
   Satz-Baukasten, Claude kommt erst in M10 dazu.

**Zum Testen auf dem iPhone braucht es HTTPS** (außer auf localhost) und
„Zum Home-Bildschirm hinzufügen". Ein Tunnel wie `cloudflared` oder ein
frühes Deployment ist dafür der einfachste Weg — das wäre dann faktisch ein
vorgezogenes Stück M12.

Danach: M9 (Detailansicht mit Preisverlauf), M10 (Claude-Texte), M11
(Freitext-Eingabe), M12 (Deployment).
