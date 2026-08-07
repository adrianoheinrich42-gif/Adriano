# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
M8 — Push-Benachrichtigungen (Web-Push, PWA)        ← neu
b08b5c4 M4 — Web-Client: Anmeldung, Alarmliste, Formular
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

**M0–M8 fertig — die Kernfunktion ist damit komplett.** Ein Nutzer kann sich
anmelden, einen Preisalarm anlegen, und das Backend prüft zeitgesteuert bei
Amadeus, zeichnet den Preisverlauf auf, ordnet Treffer gegen die
Streckenhistorie ein und **schickt eine Push-Benachrichtigung**.

**Noch 4 Meilensteine: M9–M12.** Alles Komfort und Betrieb, nichts
Grundlegendes mehr.

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts` ·
`GET /push/config` · `POST/DELETE /push/subscriptions`.
Prozesse: API (`app.main:app`) **und** Worker (`app.jobs.worker`).

## ⚠️ Drei Dinge fehlen, die nur der Nutzer tun kann

Keins davon blockiert die Entwicklung, alle drei den echten Betrieb:

1. **Supabase-Projekt** → `docs/SUPABASE-EINRICHTEN.md` (Anleitung ohne
   Vorwissen, ~15 Minuten). Danach `SUPABASE_URL` und `SUPABASE_JWT_SECRET`
   in `backend/.env`, `supabaseUrl`/`supabaseAnonKey` in `web/config.js`.
   **Ohne das kann sich niemand anmelden.**
2. **VAPID-Schlüsselpaar** → `cd backend && uv run python -m scripts.vapid_schluessel`,
   die zwei ausgegebenen Zeilen in `backend/.env`. Kostet nichts, dauert eine
   Sekunde. **Nur einmal erzeugen** — ein neues Paar macht alle bestehenden
   Geräte-Anmeldungen wertlos. Ohne das läuft alles, es geht nur keine Push raus
   (der Worker sagt das beim Start deutlich).
3. **Amadeus-Zugang** → Konto auf `developers.amadeus.com`,
   `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` in `backend/.env`.

## Was umgesetzt ist

- **M0** — FastAPI, `/health`, `config.py`, `db.py`, Docker, Makefile.
- **M1** — 6 Tabellen, erste Migration, 16 Integrationstests auf die
  DB-Zusicherungen.
- **M2** — `core/security.py` (JWT HS256), `api/deps.py`, `GET /me`.
- **M3** — Alarm-CRUD (`schemas/`, `services/`, `api/routes/price_alerts.py`).
- **M4** — Web-Client: `auth.js`, `api.js`, `format.js`, `app.js`.
- **M5** — `services/amadeus.py`, `schemas/flight_offer.py`, Fixture.
- **M6** — `services/pruflauf.py`, `jobs/worker.py` (APScheduler).
- **M7** — `services/price_stats.py`; Einordnung hängt im `LaufErgebnis`.
- **M8** — siehe nächster Abschnitt.

## Zuletzt geändert — M8 (Push-Benachrichtigungen)

### Datenmodell

`device_tokens` speichert jetzt eine **Web-Push-Subscription** statt eines
APNs-Tokens: `endpoint` (Text, UNIQUE), `p256dh`, `auth`. Weggefallen:
`token`, `environment`, `app_version`. `platform` ist jetzt `'web'`.
In `notification_logs` heißen die Spalten neutral `push_status_code` /
`push_error`, und `status` kennt zusätzlich `pending`.

**Migration `22e16687014f`** — von Hand nachgearbeitet, weil Autogenerate vier
Dinge nicht hinbekam (alles im Kopf der Datei erklärt):

1. `add_column(nullable=False)` ohne Standardwert scheitert an vorhandenen
   Zeilen → ausdrückliches `DELETE` mit Begründung.
2. Unbenannte `UNIQUE`-Constraints → `downgrade()` fände sie nicht wieder.
3. **`ck_tokens_platform` (`'ios'` → `'web'`) wurde gar nicht erkannt.**
   Autogenerate vergleicht CHECK-Ausdrücke nicht zuverlässig.
4. Dasselbe bei `ck_notifications_status` (neuer Wert `pending`).

Beim ersten Anwenden fiel noch auf: PostgreSQL löscht einen CHECK automatisch
mit seiner Spalte — ein `drop_constraint` **danach** scheitert. Reihenfolge
entsprechend korrigiert.

### Backend

`app/services/push.py`, wieder zwei Hälften:

- *rein:* `bilde_dedupe_key()`, `darf_melden()` (Abkühlphase + 5-%-Regel),
  `formuliere_nachricht()` (der deterministische Satz-Baukasten).
- *Versand:* Protokoll `PushVersand` + `WebPushVersand` (pywebpush, im
  Hintergrund-Thread, weil die Bibliothek synchron ist).
- *DB:* `registriere_ziel()`, `entferne_ziel()`, `hole_letzte_meldung()`,
  `melde_treffer()`.

Dazu `api/routes/push.py` (3 Endpunkte), `schemas/push.py`,
`scripts/vapid_schluessel.py`, VAPID-Einstellungen in `config.py`, und der
Worker legt den Versand an, sofern ein Schlüsselpaar hinterlegt ist.

`pruefe_alarm()` bekam die optionalen Parameter `versand` und `settings`;
ohne sie verhält sich alles exakt wie in M7. `_speichere_angebote()` gibt
jetzt `GespeichertesAngebot` (id + offer_hash + Angebot) statt nur Preisen
zurück — das Meldeprotokoll braucht die `flight_offers.id`.

### Frontend (PWA)

Neu: `manifest.json`, `sw.js` (Service Worker), `push.js`, `icons/` (192, 512,
180 für Apple; ohne Bildbibliothek erzeugt). Die Alarmansicht hat eine
Benachrichtigungs-Karte mit vier Zuständen.

### Entscheidungen aus M8

Ausführlich in `CLAUDE.md`; die Merksätze:

- **Die Protokollzeile wird VOR dem Versand geschrieben** (`pending`). Der
  `UNIQUE`-Index muss den Platz belegen, bevor etwas Langsames passiert.
- **Reihenfolge der Bremsen:** Abkühlphase/5-%-Regel zuerst (billig), dann
  Dedupe. Bei identischem Angebot innerhalb der Abkühlphase greift deshalb die
  Abkühlphase — Dedupe erst danach.
- **Gemeldet wird nach dem Commit des Prüflaufs.** Ein Versandfehler darf
  Beobachtung und Angebote nicht zurückrollen.
- **404/410 legt ein Ziel still**, 503 nicht.
- **„Push ist an" hängt am Abonnement, nicht an `Notification.permission`.**
- **`navigator.serviceWorker.ready` abwarten**, nicht nur `register()`.

## Verifizierter Zustand (real nachgeprüft, nicht behauptet)

- **Backend-Tests:** mit DB `263 passed`; ohne DB `167 passed, 96 skipped`.
  `ruff` und `mypy app` (strict) sauber. **Diese Zahlen sind der Soll-Wert.**
- **Migration:** `base → head → base → head` sauber, `alembic check` ohne Drift.
- **M8 im echten Chromium gegen das echte Backend — 12 Schritte:**
  1. Angemeldet, Alarmansicht erscheint
  2. Push-Karte startet im Zustand „noch nicht gefragt"
  3. Manifest gültig, 3 Icons erreichbar (installierbar)
  4. Einschalten: Service Worker aktiv, abonniert, Karte umgeschaltet
  5. Backend meldet Push als aktiviert
  6. **Backend hat echt gesendet: 248 Byte `aes128gcm`, VAPID-signiert,
     Inhalt verschlüsselt** (`MUC` kam im Paket nicht im Klartext vor)
  7. Zweiter Lauf, dasselbe Angebot → still
  8. Kaum besseres Angebot → still (Abkühlphase)
  9. −10,6 % → Push trotz Abkühlphase (5-%-Regel)
  10. **Service Worker zeigt die Nachricht an:** „MUC → BCN für 160,00 €"
  11. Ausschalten meldet beim Backend ab, Karte kehrt zurück
  12. Nach dem Abmelden bleibt selbst ein Rekordpreis still

  Keine JavaScript-Fehler. Ersetzt waren nur zwei Grenzen nach außen:
  Supabase (wie in M4) und `PushManager.subscribe` — Chromium verlangt dafür
  eine Verbindung zu Googles FCM-Servern, die es in dieser Sandbox nicht gibt.
  **Verschlüsselung, VAPID-Signatur, Dedupe, Bremsen und `sw.js` liefen echt.**
- **Dabei gefunden und behoben:**
  * `register()` kehrt zurück, während der Service Worker noch „installing"
    ist → `subscribe()` scheiterte mit „no active Service Worker". Das hätte
    **jeden echten Nutzer beim ersten Besuch** getroffen. Fix:
    `navigator.serviceWorker.ready` abwarten.
  * Die Push-Karte leitete „ist an" aus `Notification.permission` ab. Wer
    früher erlaubt und danach abgemeldet hatte, sah fälschlich „sind an".
  * `registriere_ziel()` gab ein veraltetes ORM-Objekt aus der Identity Map
    zurück (Datenbank war korrekt). Fix: `populate_existing`.

## Offene Punkte / Fallstricke

- **Push auf dem iPhone ist noch nicht auf echter Hardware getestet.** Dafür
  fehlt HTTPS. Safari kann Web-Push **nur**, wenn die Seite über „Teilen → Zum
  Home-Bildschirm" installiert wurde; im normalen Tab fehlt die Schnittstelle.
  Die App erklärt das (`warumNichtVerfuegbar()` in `push.js`), aber geprüft ist
  es nicht. Einfachster Weg: Tunnel (`cloudflared`) oder M12 vorziehen.
- **Die Browsertests liegen nicht im Repository** (Playwright ist keine
  Projekt-Abhängigkeit). Wiederholen: Chromium unter `/opt/pw-browsers`,
  `playwright` per `uv pip install` in eine eigene Umgebung. Zwei Fallen:
  Chromium behandelt `new_context()` wie **Inkognito**, und dort fehlt die
  Push-API (crbug.com/401439) → `launch_persistent_context` benutzen. Und ein
  Testalarm braucht `check_interval_minutes >= 15` (DB-CHECK).
- **Kein Klick-Ziel für die Nachricht.** `sw.js` öffnet nur die Startseite;
  `Nachricht.url` ist auf `"/"` festgenagelt. Die Detailansicht kommt in M9.
- **Alarme lassen sich nicht bearbeiten** — nur anlegen, pausieren, löschen.
- **`pushsubscriptionchange` wird nicht aktiv behandelt.** Stattdessen meldet
  `push.js` die Subscription bei jedem Seitenaufruf neu an (Upsert im Backend).
  Reicht, solange die App regelmäßig geöffnet wird.
- **Keine Offline-Fähigkeit.** Der Service Worker macht nur Push, kein Caching.
  Ohne Netz zeigt die App nichts — für eine Preisalarm-App vertretbar.
- **Die Fixture ist nachgebaut, nicht mitgeschnitten.** Erste Aufgabe mit
  Amadeus-Zugang: einmal echt suchen, Antwort nach `tests/fixtures/` schreiben.
- **Falls Supabase nur asymmetrische Schlüssel anbietet** → `core/security.py`
  auf RS256/ES256 erweitern (`pyjwt[crypto]`). Betrifft genau diese Datei.
- **Die 90 Tage der Statistik sind fest**, keine Einstellung.
- **Nur ein Suchdatum pro Alarm** — der Datums-Fächer fehlt noch.
- **Kein Aufräumen alter Daten.** `flight_observations` und
  `notification_logs` wachsen unbegrenzt. Kandidat für M11/M12.
- **`GET /alerts` ohne Paginierung.** Bei 5 Alarmen egal.
- **Token ohne `email`** → 401, weil `users.email` NOT NULL ist.
- **`.env` und `.venv` fehlen nach Klonen/Entpacken immer** →
  `cp .env.example .env`, `uv sync`.
- **Postgres in dieser Sandbox:** kein Docker-Daemon, aber per apt vorhanden
  (`/usr/lib/postgresql/16/bin`, `initdb`/`pg_ctl` als User `postgres`). Das
  Datenverzeichnis muss für `postgres` erreichbar sein —
  `/var/lib/postgresql/<name>` geht, `/tmp/claude-*` nicht. **Überlebt keinen
  Container-Neustart** — lauter `s` in `pytest` heißt: nur die DB ist weg.
- **Stolperfalle SQLAlchemy async:** Nach `session.rollback()` sind alle
  Objekte der Session „abgelaufen"; der nächste Attributzugriff ergibt
  `MissingGreenlet`. Deshalb merkt sich `pruefe_faellige_alarme()` nur IDs.
- **Stolperfalle Identity Map:** Ein `RETURNING` gibt bei bereits geladenen
  Zeilen das **alte** Objekt zurück. `execution_options={"populate_existing":
  True}` erzwingt den frischen Stand (siehe `registriere_ziel`).
- **Stolperfalle Statistik-Tests:** `hole_vergleichspreise()` fragt über alle
  Nutzer ab. Tests dürfen sich keine feste Strecke teilen.
- **Stolperfalle: committete Daten in der Test-Datenbank.** Die
  Integrationstests rollen ihre Daten zurück, aber `finde_faellige_alarme()`
  sucht über **alle** Nutzer. Bleibt aus einem Handversuch ein aktiver Alarm
  liegen, schlagen ~7 Tests in `test_pruflauf.py` fehl, **ohne dass am Code
  etwas kaputt ist**. Prüfen mit `SELECT * FROM price_alerts;`, aufräumen mit
  `TRUNCATE users CASCADE;`.
- Keine echten Bugs bekannt.

## Exakter Arbeitspunkt

M8 abgeschlossen, committet und gepusht. Nichts ist halbfertig.

## Nächste Schritte — Empfehlung: M12 (Deployment) vor M9

Der Grund ist Punkt 1 der offenen Punkte: **Push ist auf dem iPhone
ungetestet**, und ohne HTTPS bleibt das so. Die Kernfunktion ist fertig — sie
einmal auf echter Hardware zu sehen, ist mehr wert als eine weitere Ansicht.

Kleinster Weg dahin:

1. Backend + Worker auf einen Hoster mit HTTPS (Render, Railway, Fly).
2. Supabase als echte Datenbank verwenden (Pooler-Port 6543 →
   `DATABASE_DISABLE_STATEMENT_CACHE=true`, steht schon in `config.py`).
3. `web/` als statische Seite ausliefern, `apiBaseURL` und `CORS_ORIGINS`
   anpassen.
4. Auf dem iPhone „Zum Home-Bildschirm hinzufügen", Benachrichtigungen
   einschalten, Alarm mit hohem Limit anlegen → es sollte klingeln.

**Alternative, wenn du lieber im Vertrauten bleibst: M9 (Detailansicht).**
`GET /offers/{id}`, Preisverlauf pro Alarm, und die `Preisbewertung` aus M7
endlich sichtbar machen — sie steckt bisher nur im Log und in der Push.
Dann auch `Nachricht.url` auf die Detailansicht zeigen lassen statt auf `/`.

Danach: M10 (Claude-Texte), M11 (Freitext-Eingabe).
