# HANDOFF.md — Arbeitsstand

**Stand:** 2026-08-07 · Branch `claude/project-handoff-continuation-9lcu5l` ·
Arbeitsverzeichnis **sauber**, alles committet und **gepusht**.
Zuerst `CLAUDE.md` lesen, dann diese Datei, dann `git log` / `git status`.

Meilenstein-Commits (dazwischen liegen reine Doku-Commits):

```
M10 — Claude formuliert die Benachrichtigungstexte  ← neu
09029bc M9 — Ergebnisanzeige: Detailansicht + Deep-Link
46005f3 M8 — Push-Benachrichtigungen (Web-Push, PWA)
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

**M0–M10 fertig.** Der Nutzer kann sich anmelden, Alarme anlegen, bekommt eine
Push, wenn ein Preis passt — **von Claude formuliert** — und sieht nach dem
Tippen darauf direkt die Detailansicht mit Einordnung, Preisverlauf und den
gefundenen Flügen.

**Noch 2 Meilensteine: M11 und M12.** Freitext-Eingabe, Deployment.

Endpunkte: `GET /health` · `GET /me` · `POST/GET/PATCH/DELETE /alerts` ·
`GET /alerts/{id}/offers` · `GET /alerts/{id}/verlauf` · `GET /offers/{id}` ·
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
4. **Anthropic-Schlüssel** (optional) → Konto auf `console.anthropic.com`,
   Guthaben aufladen, `ANTHROPIC_API_KEY` in `backend/.env`. **Ohne den
   Schlüssel läuft alles vollständig weiter** — die Benachrichtigungen
   formuliert dann der eingebaute Satz-Baukasten. Rechnen musst du mit rund
   0,1 Cent je verschickter Nachricht.

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
- **M8** — Web-Push: `services/push.py`, `api/routes/push.py`, PWA
  (`manifest.json`, `sw.js`, `push.js`, Icons), Migration `22e16687014f`.
- **M9** — `services/ergebnisse.py`, `schemas/ergebnis.py`, `web/detail.js`.
- **M10** — siehe nächster Abschnitt.

## Zuletzt geändert — M10 (Claude formuliert die Texte)

Bis M9 schrieb ein Satz-Baukasten in Python die Benachrichtigungen. Der bleibt
— aber im Normalfall formuliert jetzt Claude.

**Leitplanke 3, wörtlich umgesetzt:** Claude *entscheidet* nichts. Ob ein Preis
gut ist, hat `price_stats.py` ausgerechnet; Claude bekommt die fertigen Zahlen
und macht daraus einen freundlichen deutschen Satz. Fällt er aus, greift der
Baukasten und die Push geht trotzdem raus.

**Neu:** `services/claude.py` (Protokoll `Texter`, `ClaudeTexter` mit
Structured Output, Prompt-Bau, Antwortprüfung), `anthropic`-Abhängigkeit,
Anthropic-Einstellungen in `config.py`, Migration `4b42be3a6b6e`.

**Geändert:** `push.py` (`erzeuge_nachricht()`, `formuliere_einordnungssatz()`,
`melde_treffer(..., texter=…)`), `pruflauf.py` und `worker.py` reichen den
`Texter` durch, `ergebnisse.py` liefert den fertigen Satz an die
Detailansicht, `web/detail.js` baut ihn nicht mehr selbst.

**Datenmodell:** `notification_logs` bekam `title`, `body` und `text_quelle`
(`claude` | `baukasten`). Das Protokoll hielt bisher nur fest, *dass* gemeldet
wurde, nicht was dort stand.

### Entscheidungen aus M10

- **Claude wird nur aufgerufen, wenn wirklich eine Push rausgeht.** Nie beim
  Suchen, nie beim Anzeigen. Die Detailansicht liest den Satz aus dem
  Protokoll, statt ihn neu erzeugen zu lassen — sonst hinge der Lesepfad an
  einer fremden Schnittstelle und kostete bei jedem Öffnen Geld.
- **Jede Zahl im erzeugten Text wird gegengeprüft** (`pruefe_text()`).
  Structured Output garantiert die *Form*, nicht die *Richtigkeit*; „18 %"
  statt der berechneten 21 % wäre eine erfundene Zahl in einer Nachricht, die
  wie eine Tatsache aussieht. Passt eine Zahl nicht, gilt der ganze Text als
  verworfen. Bewusst streng: Ein verworfener guter Satz kostet nichts.
- **`erzeuge_nachricht()` wirft nie** — ein nacktes `except Exception` ist hier
  genau richtig. Sonst müsste jede Ausnahmeklasse des SDK aufgezählt werden,
  und die eine vergessene wäre die, die nachts die Benachrichtigung verschluckt.
- **Titel und Ziel-Adresse kommen immer vom Baukasten.** Die URL ist Technik,
  kein Text.
- **Nur ein *Claude*-Text wird in der Detailansicht wiederverwendet.** Der
  Baukasten hat für diese Ansicht eine eigene Fassung
  (`formuliere_einordnungssatz()`) ohne Preis-Präfix und ohne
  „Direktflug · LH" — beides steht dort schon daneben.
- **Die App legt offen, wenn Claude geschrieben hat** („von Claude
  formuliert"). Wer Text von einem Sprachmodell liest, soll das wissen.
- **`web/detail.js` baut keinen Bewertungssatz mehr.** Das war ein Riss in
  Leitplanke 1 und eine zweite Stelle mit derselben Aussage in anderen Worten.
- **Claude sieht keine Nutzerdaten** — keine ID, keine E-Mail. Für „schreib
  einen netten Satz" braucht es die nicht; ein Test hält das fest.

## Davor geändert — M9 (Ergebnisanzeige)

Die Bewertung aus M7 steckte bis jetzt nur im Log und in der Push-Nachricht.
Ab hier ist sie sichtbar.

**Backend:** `services/ergebnisse.py` (reines Lesen), `schemas/ergebnis.py`,
`api/routes/ergebnisse.py` mit drei Endpunkten:

| Endpunkt | Inhalt |
|---|---|
| `GET /alerts/{id}/offers` | Funde, günstigste zuerst |
| `GET /alerts/{id}/verlauf` | Tagespunkte + Einordnung + aktueller Preis |
| `GET /offers/{id}` | ein einzelnes Angebot |

**Frontend:** `web/detail.js` — Bewertungskarte mit Badge, Preisverlauf als
selbst gezeichnetes SVG (keine Diagramm-Bibliothek, ~20 Zeilen), Angebotsliste
mit Hin-/Rückflug, Dauer, Umstiegen und Gepäck. Neue Formatierer in
`format.js` (`uhrzeitLesbar`, `dauerLesbar`, `tagKurz`).

**Deep-Link:** `Nachricht.url` im Backend baut `/#alarm=<id>`; `app.js` liest
den Anker, `sw.js` navigiert beim Antippen dorthin. Damit funktioniert auch
der Zurück-Knopf des Browsers.

### Entscheidungen aus M9

- **Keine Messung wird gegen sich selbst verglichen** — auf zwei Wegen: Der
  Prüflauf holt die Vergleichspreise, *bevor* er schreibt; die Detailansicht
  schneidet mit `bis=heute` den laufenden Tag ab.
- **Die Kurve zeigt heute mit, der Vergleich nicht.** Zwei verschiedene
  Fragen: „was habe ich beobachtet?" gegen „was ist hier üblich?".
- **Ein Punkt je Tag**, nicht je Prüflauf — sonst 540 Punkte in 90 Tagen.
- **Der Anker ist der Ansichtszustand**, kein Router. Ein Pfad `/alarm/<id>`
  bräuchte einen Server, der ihn umschreibt.
- **Segmente werden im Backend in Hin- und Rückflug getrennt**, ebenso die
  Dauern summiert — Leitplanke 1: Der Client rechnet nicht.
- **`raw_payload` und `offer_hash` verlassen das Backend nicht.**

## Davor geändert — M8 (Push-Benachrichtigungen)

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

- **Backend-Tests:** mit DB `315 passed`; ohne DB `189 passed, 126 skipped`.
  `ruff` und `mypy app` (strict) sauber, `alembic check` ohne Drift.
  **Diese Zahlen sind der Soll-Wert.**
- **M10 im echten Chromium gegen das echte Backend — 9 Schritte:** Zwei Alarme
  nebeneinander, einmal antwortet Claude, einmal fällt er aus.
  1. Beide Alarme angelegt und geprüft (Attrappen für Suche, Versand, Claude)
  2. Angemeldet, beide in der Liste
  3. Detailansicht zeigt **Claudes** Satz („24 % unter dem üblichen Preis von
     250 € — ein guter Moment zum Buchen.")
  4. Herkunftshinweis „von Claude formuliert" sichtbar
  5. Die deterministische Einordnung („günstig", 189,50 €) steht unverändert
     daneben — Claude hat sie nicht angefasst
  6. Beim Ausfall steht der Baukasten-Satz da, mit Median und ohne
     Sperrbildschirm-Anhang
  7. Dort **kein** Herkunftshinweis — er lügt nicht
  8. `GET /alerts/{id}/verlauf` liefert Satz *und* Quelle fertig aus
  9. `detail.js` enthält nachweislich keinen selbst gebauten Satz mehr

  Keine JavaScript-Fehler. **Kein Test ging ins Netz** — auch der Fall
  „falscher API-Schlüssel" nicht: Dafür bekommt der echte `ClaudeTexter` einen
  `httpx.MockTransport` untergeschoben, der eine echte 401 der Anthropic-API
  nachstellt (`tests/test_claude.py`).
- **Dabei gefunden und behoben:**
  * **CORS ließ nur `http://localhost:3000` zu, nicht `http://127.0.0.1:3000`.**
    Für den Browser sind das zwei Herkünfte. Wer die App über die andere
    Schreibweise öffnet, sieht „Keine Verbindung zum Server", obwohl im
    Backend-Log ein 200 steht. Beide stehen jetzt in `cors_origins`.
  * Die Detailansicht übernahm auch den **Baukasten**-Text der Push — der
    beginnt mit dem Preis und endet mit „Direktflug · LH", was dort schon
    daneben steht. Jetzt wird nur ein Claude-Text wiederverwendet.
  * Ein Test schlug fehl, **weil die Zahlenprüfung funktionierte**: Der echte
    Prüflauf rechnet seine eigene Bewertung aus, mein fest verdrahteter
    Claude-Text nannte eine dazu nicht passende Prozentzahl — und wurde
    korrekt verworfen.
- **M9 im echten Chromium gegen das echte Backend — 12 Schritte:** Liste →
  Klick auf die Strecke → Detailansicht; Bewertung „199,00 € · Bestpreis";
  Preisverlauf als SVG mit 13 Tagespunkten; Angebote günstigste zuerst;
  Ortszeit unverfälscht („09:15 MUC → 11:25 BCN · 2 Std. 10 Min.");
  Zurück-Knopf **und** Browser-Zurück; Deep-Link `#alarm=<id>`; und die
  Push-Nachricht baut nachweislich genau diese Adresse. Keine
  JavaScript-Fehler.
- **Dabei gefunden und behoben:** Die Detailansicht verglich den aktuellen
  Preis gegen eine Historie, die dessen **eigene** Beobachtung von heute
  enthielt — `ist_bestpreis` konnte dort strukturell nie wahr werden. Fix:
  `hole_vergleichspreise(..., bis=heute_beginn)`.
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
- **Alarme lassen sich nicht bearbeiten** — nur anlegen, pausieren, löschen.
  Das Backend kann PATCH auf allen Feldern.
- **Die Angebotsliste ist auf 20 begrenzt** und hat keine Paginierung.
- **`booking_url` ist immer leer**, weil Amadeus in der Suchantwort keinen
  Buchungslink liefert. Der Knopf „Zum Angebot" erscheint deshalb nie. Für
  echte Buchbarkeit bräuchte es die Flight-Offers-Price-API.
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

M10 abgeschlossen, committet und gepusht. Nichts ist halbfertig.

## Nächste Schritte — Empfehlung: M12 (Deployment)

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

**Alternative: M11 (Freitext-Eingabe).** „Im Oktober für zwei Wochen nach
Lissabon, höchstens 250 €" → Structured Output → **vorausgefülltes Formular,
das der Nutzer bestätigen muss**. Die Hälfte der Arbeit steht schon:
`services/claude.py` hat den Client, das Protokoll und das Fehlermuster; neu
sind ein zweites Pydantic-Schema, ein zweiter Prompt und die
Plausibilitätsprüfung (Datum in der Zukunft? IATA-Code echt?). Wichtig laut
Projektplan 8.8: **Kein Alarm entsteht direkt aus Claudes Ausgabe.**

Was M10 dafür hinterlässt: Der Aufruf schlägt bei M11 im Anfrage-Pfad zu,
nicht im Worker — dort ist das Zeitlimit von 8 Sekunden zu großzügig, und der
Fallback ist kein Textbaustein, sondern das leere Formular mit einem
ehrlichen Hinweis.

### Noch nicht überprüft

**Claude hat in diesem Projekt noch nie wirklich geantwortet.** Alle Tests
laufen gegen Attrappen und einen `MockTransport`; ein `ANTHROPIC_API_KEY`
liegt nicht vor. Geprüft ist damit die gesamte Verdrahtung und jeder
Fehlerpfad — offen ist die Textqualität: Hält sich Haiku 4.5 an den Ton, und
wie oft verwirft `pruefe_text()` zu Recht oder zu Unrecht? Erster Schritt mit
Schlüssel: `make worker` starten, einen Alarm melden lassen, `SELECT title,
body, text_quelle FROM notification_logs ORDER BY sent_at DESC LIMIT 5;`.
Steht dort dauerhaft `baukasten`, greift der Fallback still — dann ins
Worker-Log sehen, dort steht der Grund.
