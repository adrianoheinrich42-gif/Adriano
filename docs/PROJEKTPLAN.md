# Flugpreis-Alarm — Projektplan (MVP)

Portfolio- und Lernprojekt: native iOS-App mit Python-Backend, das Flugpreise
überwacht und bei passenden Angeboten eine Push-Benachrichtigung schickt.

Dieses Dokument ist die Planungsgrundlage. Es enthält bewusst **noch keinen
Produktivcode** — nur Architektur, Entscheidungen, Datenmodell und Meilensteine.

---

## 0. Leitplanken (die drei Sätze, an die wir uns halten)

1. **Die App ist ein dummer Client.** Sie zeigt Daten an und schickt Formulare
   ab. Jede Entscheidung ("ist das ein gutes Angebot?") fällt im Backend.
2. **Kein Schlüssel verlässt das Backend.** Amadeus-, Anthropic- und
   APNs-Schlüssel liegen ausschließlich in Umgebungsvariablen des Servers.
   Die App kennt genau eine URL: die deines eigenen Backends.
3. **Claude entscheidet nichts, Claude formuliert.** Preisbewertung ist
   deterministische Statistik in Python. Claude wandelt Sprache in Struktur um
   und schreibt Erklärtexte — mehr nicht.

---

## 1. Systemarchitektur

### 1.1 Bausteine

```
┌──────────────────────┐
│  iOS-App (SwiftUI)   │  Nur UI + Netzwerk. Kennt nur die Backend-URL.
└──────────┬───────────┘
           │ HTTPS + JWT (Bearer-Token)
           ▼
┌──────────────────────┐        ┌────────────────────┐
│  FastAPI (API)       │◄──────►│  PostgreSQL        │
│  - Auth-Prüfung      │        │  (Supabase)        │
│  - CRUD Preisalarme  │        │  - User, Alerts    │
│  - Rate Limiting     │        │  - Preisverlauf    │
│  - Validierung       │        │  - Device-Tokens   │
└──────────────────────┘        └─────────┬──────────┘
                                          │ gleiche DB
┌──────────────────────┐                  │
│  Worker (Scheduler)  │◄─────────────────┘
│  Läuft als eigener   │
│  Prozess, alle N Min │
└──┬────────┬───────┬──┘
   │        │       │
   ▼        ▼       ▼
Amadeus   APNs   Anthropic
(Preise) (Push)  (nur Texte)
```

**Zwei Prozesse, eine Datenbank.** Das ist die wichtigste Struktur-
entscheidung. Der API-Prozess beantwortet Anfragen der App und muss schnell
sein. Der Worker macht langsame Dinge (externe API-Calls, viele Sekunden pro
Alarm). Würden beide im selben Prozess laufen, würde eine laufende Preisprüfung
die App blockieren.

### 1.2 Warum die App nicht selbst sucht

iOS gibt Apps keine verlässliche Hintergrundzeit. `BGAppRefreshTask` läuft,
wann iOS will — vielleicht einmal am Tag, vielleicht nie, und gar nicht, wenn
die App länger nicht geöffnet wurde. Für „prüfe alle 6 Stunden" ist das
unbrauchbar. Außerdem müssten API-Schlüssel dann im Client liegen. Deshalb:
Server.

### 1.3 Datenfluss in einem Satz

App legt einen Alarm an → Worker prüft ihn regelmäßig bei Amadeus → jedes
Ergebnis wird als Datenpunkt gespeichert → wenn ein Angebot die Bedingungen
erfüllt **und** noch nicht gemeldet wurde, schickt der Worker eine Push-
Nachricht über APNs.

---

## 2. Technologieauswahl (mit Begründung)

### 2.1 iOS

| Bereich | Empfehlung | Warum |
|---|---|---|
| Sprache | Swift 6 | Aktuell, strikte Concurrency hilft beim Lernen |
| Mindest-iOS | **iOS 17** | Erlaubt `@Observable` statt `ObservableObject` — deutlich weniger Boilerplate im MVVM |
| UI | SwiftUI | Kein Storyboard, wenig Code, schnelle Iteration |
| Architektur | MVVM mit `@Observable` | View → ViewModel → Service. Reicht für diese App-Größe völlig |
| Netzwerk | `URLSession` + `async/await` | Keine Drittbibliothek nötig. Alamofire wäre hier Ballast |
| JSON | `Codable` | Eingebaut |
| Token-Speicher | **Keychain** | `UserDefaults` ist unverschlüsselt — dort gehört kein Auth-Token hin |
| Tests | Swift Testing (`@Test`) | Neuer, lesbarer als XCTest; XCTest bleibt für UI-Tests |
| Abhängigkeiten | Swift Package Manager | Kein CocoaPods |

**Keine** Drittbibliotheken im MVP außer optional dem Supabase-Swift-SDK für
Login. Jede Bibliothek ist Lernstoff, den du nicht brauchst.

### 2.2 Backend

| Bereich | Empfehlung | Warum |
|---|---|---|
| Sprache | Python 3.12 | |
| Framework | FastAPI | Async, automatische OpenAPI-Doku (praktisch für die iOS-Seite) |
| Validierung | Pydantic v2 | Kommt mit FastAPI; erzwingt serverseitige Validierung |
| ORM | SQLAlchemy 2.0 (async) | Industriestandard. Lernwert höher als bei SQLModel |
| Migrationen | **Alembic** | Von Tag 1. Schema-Änderungen ohne Datenverlust sind eine Kernfähigkeit |
| DB-Treiber | `asyncpg` | Schnellster Postgres-Treiber für async |
| HTTP-Client | `httpx` (async) | Für Amadeus und APNs |
| Scheduler | **APScheduler** im Worker-Prozess | Einfach, kein Redis nötig. Alternative unten |
| Push | `aioapns` | Spricht APNs über HTTP/2 mit `.p8`-Token-Auth |
| Claude | offizielles `anthropic`-SDK | |
| Tests | `pytest`, `pytest-asyncio`, `respx` | `respx` mockt httpx-Aufrufe — Tests ohne echte API-Calls |
| Qualität | `ruff` (Lint+Format), `mypy` | |
| Container | Docker | Ein Image, zwei Startbefehle (api / worker) |

**Scheduler — die Alternative kennen:** APScheduler ist an *einen* Prozess
gebunden. Startest du später zwei Worker-Instanzen, läuft jeder Job doppelt.
Sobald das relevant wird, wechselst du auf einen externen Cron (Render Cron
Job / GitHub Actions), der `python -m app.jobs.check_prices` aufruft. Für den
MVP: eine Worker-Instanz, APScheduler, fertig. Notiere dir die Grenze.

### 2.3 Infrastruktur

| Bereich | Empfehlung |
|---|---|
| Datenbank | Supabase (verwaltetes Postgres, kostenloser Tarif) |
| Auth | **Supabase Auth** — nicht selbst bauen |
| Hosting | Render oder Railway (beide: Docker + Cron + Env-Variablen) |
| Secrets | Umgebungsvariablen des Hosters. Nie im Git |
| Fehler-Monitoring | Sentry (kostenlos), ab Meilenstein 8 |

**Warum Supabase Auth und nicht selbst gebaut?** Registrierung, Login,
Passwort-Reset, E-Mail-Bestätigung, sicheres Passwort-Hashing, Token-Refresh —
das sind Wochen Arbeit und der Ort, an dem Anfängerprojekte Sicherheitslücken
haben. Supabase gibt der App ein JWT; dein FastAPI-Backend prüft nur noch die
Signatur und liest die User-ID heraus. Das ist etwa 30 Zeilen Code.

> ⚠️ **Wichtig beim Aufsetzen:** Supabase nutzt je nach Projektalter zwei
> unterschiedliche JWT-Verfahren (symmetrisch mit `JWT_SECRET` oder asymmetrisch
> über einen JWKS-Endpunkt). Prüfe in deinen Projekt-Einstellungen, welches
> aktiv ist, bevor du die Prüf-Logik schreibst.

> ⚠️ **Supabase + asyncpg Stolperfalle:** Nutzt du den Connection-Pooler im
> Transaction-Modus (Port 6543), musst du bei asyncpg
> `statement_cache_size=0` setzen — sonst gibt es sporadische Fehler zu
> „prepared statement already exists". Alternative: direkte Verbindung auf
> Port 5432. Schreib dir das auf, das kostet sonst einen Abend.

### 2.4 Claude-Modell, Kosten und Structured Output

**Modell: `claude-haiku-4-5`** — 1,00 $ pro Mio. Input-Token, 5,00 $ pro Mio.
Output-Token, 200K Kontext. Beide Aufgaben (Extraktion, kurzer Erklärtext) sind
einfach und gut abgegrenzt; das günstigste Modell reicht. Falls die Extraktion
bei komplizierten Sätzen zu ungenau wird, ist `claude-sonnet-5` der nächste
Schritt — aber erst messen, dann wechseln.

**Grobe Kostenschätzung pro Aufruf:**

| Aufgabe | ~Input | ~Output | Kosten |
|---|---|---|---|
| Sprache → Suchkriterien | 1.500 Tok | 200 Tok | ≈ 0,0025 $ |
| Angebots-Erklärung | 500 Tok | 150 Tok | ≈ 0,0013 $ |

Bei 1.000 Extraktionen im Monat: unter 3 $. Das ist nicht der Kostentreiber —
die Flugsuche ist es (siehe Risiko 8.3).

**Structured Output statt „bitte antworte in JSON":** Die Claude-API kann per
JSON-Schema erzwingen, dass die Antwort exakt deinem Schema entspricht. Im
Python-SDK definierst du dazu ein Pydantic-Modell und rufst
`client.messages.parse(...)` mit `output_config={"format": ...}` auf; du
bekommst ein validiertes Objekt zurück statt eines Strings, den du parsen
musst. Haiku 4.5 unterstützt das. Das ersetzt jede selbstgebaute
JSON-Extraktion mit Regex.

**Wichtig trotzdem:** Structured Output garantiert die *Form*, nicht die
*Richtigkeit*. „Oktober" könnte als `2025-10-01` statt `2026-10-01`
zurückkommen. Deshalb: eigene Plausibilitätsprüfung im Backend (Datum in der
Zukunft? Rückflug nach Hinflug? IATA-Code existiert? Preis > 0?) und bei
Verstoß eine verständliche Fehlermeldung an die App, kein 500er.

**Prompt Caching — ehrliche Einordnung:** Caching lohnt sich erst ab einer
Mindestlänge des zwischengespeicherten Prompt-Anfangs, und die ist
modellabhängig. Für **Haiku 4.5 liegt sie bei 4.096 Token**. Ein kurzer
Extraktions-Systemprompt erreicht das nicht — dort passiert schlicht nichts,
auch wenn du `cache_control` setzt (kein Fehler, nur kein Effekt). Caching wird
erst interessant, wenn du dem Systemprompt z. B. eine lange Flughafen-Liste
oder viele Beispielsätze beilegst. Vorgehen: erst normal bauen, dann in
`response.usage.cache_read_input_tokens` nachsehen, ob überhaupt gecacht wird.
Nicht vorab optimieren.

**Fehlerbehandlung ist Teil des Designs:** Claude ist bei uns *Beiwerk*. Wenn
der Anthropic-Aufruf fehlschlägt (Rate Limit `429`, kein Guthaben, Timeout),
darf das die Kernfunktion nicht stoppen:

- Extraktion schlägt fehl → App zeigt „Automatisches Ausfüllen gerade nicht
  verfügbar, bitte manuell eintragen" und öffnet das normale Formular.
- Erklärung schlägt fehl → das Backend nutzt einen fest programmierten
  deutschen Satz-Baukasten („Das Angebot liegt 33 % unter dem bisherigen
  Median."). Die Push-Nachricht geht trotzdem raus.

Genau dafür ist die Trennung „Statistik in Python, Text von Claude" da.

---

## 3. Datenbankmodell

Konventionen: IDs als `uuid`, Zeitpunkte als `timestamptz` (immer UTC),
Reisedaten als `date`, **Geldbeträge als `integer` in Cent** (niemals `float` —
Rundungsfehler bei Geld sind ein klassischer Anfängerfehler).

### 3.1 `users`

Spiegelt Supabases `auth.users`, damit du eigene Felder anhängen kannst.

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | identisch mit Supabase-User-ID |
| `email` | text | für Support; nicht in Logs schreiben |
| `created_at` | timestamptz | |
| `max_active_alerts` | int, default 5 | Kostenbremse pro Nutzer |
| `is_active` | bool, default true | Sperren ohne Löschen |

### 3.2 `price_alerts`

Das Herzstück — die Suchbedingung des Nutzers.

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK → users | `ON DELETE CASCADE` |
| `origin` | char(3) | IATA, z. B. `MUC` |
| `destination` | char(3) | IATA |
| `earliest_departure_date` | date | |
| `latest_return_date` | date | |
| `min_trip_duration_days` | int, nullable | z. B. 6 |
| `max_trip_duration_days` | int, nullable | z. B. 8 |
| `max_stops` | int, default 1 | 0 = nonstop |
| `max_price_cents` | int | |
| `currency` | char(3), default `EUR` | |
| `adults` | int, default 1 | |
| `include_checked_bag` | bool, default false | |
| `avoid_night_flights` | bool, default false | |
| `is_active` | bool, default true | Pausieren statt Löschen |
| `last_checked_at` | timestamptz, nullable | steuert den Scheduler |
| `check_interval_minutes` | int, default 360 | 6 h |
| `created_at` / `updated_at` | timestamptz | |

Index: `(is_active, last_checked_at)` — damit findet der Worker mit einer
Abfrage alle fälligen Alarme.

Constraints in der Datenbank, nicht nur in Python:
`CHECK (earliest_departure_date <= latest_return_date)`,
`CHECK (max_price_cents > 0)`, `CHECK (origin <> destination)`.

### 3.3 `flight_observations` — der Preisverlauf

**Ein Datenpunkt pro Prüflauf pro Alarm.** Speichert den *günstigsten*
gefundenen Preis, auch wenn er über dem Limit lag. Genau dieses „auch wenn zu
teuer" macht später die Median-Berechnung möglich.

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | |
| `price_alert_id` | uuid FK | |
| `observed_at` | timestamptz | |
| `min_price_cents` | int, nullable | `NULL` = nichts gefunden |
| `currency` | char(3) | |
| `origin` / `destination` | char(3) | **denormalisiert** — siehe unten |
| `departure_month` | char(7) | z. B. `2026-10`, denormalisiert |
| `offers_found` | int | wie viele Angebote der Lauf lieferte |
| `search_ok` | bool | false bei API-Fehler → nicht in Statistik zählen |

**Warum Origin/Destination/Monat doppelt?** Sonst kannst du nur *pro Alarm*
Statistik rechnen. Ein neuer Alarm für MUC→BCN hätte null Historie. Mit den
denormalisierten Feldern nutzt du die Beobachtungen *aller* Nutzer für dieselbe
Strecke und denselben Reisemonat. Index: `(origin, destination,
departure_month, observed_at)`.

### 3.4 `flight_offers` — konkrete Angebote

Ein Datensatz pro Angebot, das die Bedingungen erfüllt hat. Das ist, was die
Detailansicht anzeigt.

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | |
| `price_alert_id` | uuid FK | |
| `flight_observation_id` | uuid FK | aus welchem Lauf |
| `offer_hash` | text | Fingerabdruck: Route+Daten+Airline+Preis. Für Dedupe |
| `total_price_cents` | int | |
| `currency` | char(3) | |
| `validating_airline` | char(2) | z. B. `LH` |
| `outbound_departure_at` / `outbound_arrival_at` | timestamptz | |
| `inbound_departure_at` / `inbound_arrival_at` | timestamptz, nullable | |
| `outbound_stops` / `inbound_stops` | int | |
| `included_checked_bags` | int, nullable | `NULL` = unbekannt (siehe Risiko 8.2) |
| `segments` | jsonb | Flugnummern, Zeiten, Flughäfen pro Teilstrecke |
| `booking_url` | text | extern erzeugter Deep-Link (siehe Risiko 8.2) |
| `raw_payload` | jsonb | Amadeus-Rohantwort — Gold wert beim Debuggen |
| `found_at` | timestamptz | |

### 3.5 `device_tokens`

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK | |
| `token` | text, **unique** | APNs-Device-Token |
| `platform` | text, default `ios` | |
| `environment` | text | `sandbox` (Xcode-Build) oder `production` |
| `last_seen_at` | timestamptz | bei jedem App-Start aktualisieren |
| `is_active` | bool | auf false, wenn APNs `410 Unregistered` meldet |

`environment` ist kein Luxus: Ein Token aus einem Xcode-Debug-Build funktioniert
**nur** gegen den APNs-Sandbox-Server. Mischst du das, bekommst du `BadDeviceToken`
und suchst stundenlang.

### 3.6 `notification_logs`

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid PK | |
| `user_id` / `price_alert_id` / `flight_offer_id` | uuid FK | |
| `dedupe_key` | text, **unique** | siehe unten |
| `price_cents` | int | Preis zum Zeitpunkt der Meldung |
| `sent_at` | timestamptz | |
| `status` | text | `sent` / `failed` / `token_invalid` |
| `apns_status_code` / `apns_reason` | int / text | für Fehlersuche |

**Der `dedupe_key` ist die Schutzmauer gegen Spam.** Vorschlag:
`sha256(price_alert_id + offer_hash)`. Weil `dedupe_key` UNIQUE ist, kann
dieselbe Kombination physisch kein zweites Mal eingetragen werden — selbst wenn
zwei Worker gleichzeitig laufen. Das ist eine Datenbank-Garantie, keine
Programmlogik, die man vergessen kann.

Zusätzlich zwei Regeln im Code:
- **Abkühlphase:** pro Alarm höchstens eine Push in 6 Stunden.
- **Nur bei echter Verbesserung:** erneut melden nur, wenn der neue Preis
  mindestens 5 % unter dem zuletzt gemeldeten liegt.

---

## 4. Der Ablauf im Detail: vom Alarm zur Push

**① Registrierung / Login (App)**
Supabase Auth liefert ein JWT. Die App legt es im Keychain ab und schickt es
bei jedem Request als `Authorization: Bearer <token>`.

**② Push-Erlaubnis (App)**
Die App fragt die Benachrichtigungs-Erlaubnis an, bekommt von iOS ein
Device-Token und schickt es an `POST /device-tokens`. Das Backend speichert
oder aktualisiert es.

**③ Alarm anlegen (App → API)**
`POST /alerts` mit den Suchkriterien. Das Backend prüft **serverseitig**:
gültige IATA-Codes, Datum in der Zukunft, Rückflug ≥ Hinflug, Preis > 0,
Zeitraum ≤ 6 Monate, und ob der Nutzer sein Limit an aktiven Alarmen erreicht
hat. Antwort: `201` mit dem angelegten Alarm oder `422` mit einer *für Menschen
lesbaren* Fehlermeldung.

**④ Fälligkeit ermitteln (Worker, alle 5 Minuten)**
```sql
SELECT * FROM price_alerts
WHERE is_active
  AND (last_checked_at IS NULL
       OR last_checked_at < now() - make_interval(mins => check_interval_minutes))
ORDER BY last_checked_at NULLS FIRST
LIMIT 50
FOR UPDATE SKIP LOCKED;
```
`FOR UPDATE SKIP LOCKED` ist der saubere Weg, Doppelverarbeitung zu verhindern,
falls doch mal zwei Worker laufen.

**⑤ Suchraum aufbauen (Worker)**
Amadeus' Flight Offers Search braucht *ein konkretes* Hin- und Rückflugdatum.
Ein Alarm über 30 Tage mit Reisedauer 6–8 Tage ergäbe naiv ~90 Datumspaare =
90 API-Calls **pro Prüfung pro Alarm**. Das sprengt jedes Kontingent.

Lösung: ein **Datumsraster mit Stichproben**.
- Abflugdaten nur alle 3 Tage abtasten statt täglich.
- Nur die Ränder und die Mitte der erlaubten Reisedauer prüfen (z. B. 6 und 8
  Tage, nicht 6, 7, 8).
- Harte Obergrenze: **maximal 12 Suchanfragen pro Alarm und Lauf.**
- Der Startversatz des Rasters rotiert zwischen den Läufen (Lauf 1: Tag 0, 3,
  6…; Lauf 2: Tag 1, 4, 7…). Über mehrere Läufe wird so alles abgedeckt, ohne
  dass ein einzelner Lauf teuer wird.

**⑥ Suchen und normalisieren (Worker)**
Für jede Datumskombination Amadeus aufrufen, Ergebnisse auf ein eigenes
internes Modell abbilden (nicht die Amadeus-Struktur durchs ganze Programm
schleifen), nach `max_stops`, `include_checked_bag` und `avoid_night_flights`
filtern.

**⑦ Beobachtung speichern (Worker)**
Eine Zeile in `flight_observations` — auch wenn nichts gefunden wurde oder der
günstigste Preis über dem Limit lag. Der Preisverlauf braucht auch die
langweiligen Tage.

**⑧ Bewerten (Worker, rein deterministisch)**
```
qualifiziert = bester_preis <= max_price_cents
```
Zusätzlich für den Kontext, aus den letzten 90 Tagen Beobachtungen derselben
Strecke und desselben Reisemonats:
`median`, `minimum`, `abweichung_prozent = (preis − median) / median × 100`

**Wichtig:** Bei weniger als ~10 Beobachtungen ist der Median statistisch
wertlos. Dann keine Prozentaussage machen, sondern nur „Erster Treffer unter
deinem Limit von 150 €". Ehrlichkeit schlägt Scheingenauigkeit.

**⑨ Dedupe-Prüfung (Worker)**
`dedupe_key` berechnen → `INSERT ... ON CONFLICT DO NOTHING`. Kein Insert =
schon gemeldet = fertig, keine Push. Zusätzlich Abkühlphase und 5-%-Regel
prüfen.

**⑩ Erklärtext erzeugen (Worker, optional)**
Nur *jetzt* — wenn wirklich eine Push rausgeht — wird Claude gerufen, mit den
bereits berechneten Zahlen. Nie vorher, nie für jedes Suchergebnis. Bei Fehler:
Textbaustein-Fallback.

**⑪ Push senden (Worker → APNs)**
An alle aktiven Device-Tokens des Nutzers, mit passender APNs-Umgebung. Payload
enthält Titel, Preis, Strecke und die `flight_offer_id` als `custom data`.
Antwort protokollieren; bei `410 Unregistered` das Token auf `is_active = false`.

**⑫ Anzeigen (App)**
Tippt der Nutzer auf die Nachricht, öffnet die App über die mitgelieferte
`flight_offer_id` direkt die Detailansicht, lädt sie per `GET
/offers/{id}` und zeigt Airline, Zeiten, Stopps, Gepäck, Gesamtpreis und
Buchungslink.

---

## 5. Meilensteine

Jeder Meilenstein ist am Ende **lauffähig und testbar**. Nicht zum nächsten
gehen, bevor der aktuelle funktioniert.

| # | Ziel | Ergebnis / Abnahmekriterium |
|---|---|---|
| **M0** | Setup | Repo, `.gitignore`, `.env.example`, Docker-Compose mit lokalem Postgres, Xcode-Projekt, „Hello World" auf beiden Seiten |
| **M1** | Datenbank | Alle 6 Tabellen als Alembic-Migration. `alembic upgrade head` läuft auf leerer DB durch |
| **M2** | Auth-Kette | Supabase-Projekt steht. `GET /me` gibt mit gültigem JWT die User-ID zurück, ohne `401` |
| **M3** | Alarm-CRUD | `POST/GET/PATCH/DELETE /alerts` mit vollständiger serverseitiger Validierung. Getestet mit curl / der FastAPI-Doku |
| **M4** | iOS Grundgerüst | Login, Liste der Alarme, Anlegen-Formular. Lade-, Leer- und Fehlerzustand sind sichtbar implementiert |
| **M5** | Amadeus-Anbindung | Ein Python-Skript sucht MUC→BCN und gibt normalisierte Angebote aus. **Noch ohne Scheduler.** Antwort als Test-Fixture speichern |
| **M6** | Prüflauf | Worker + APScheduler. Ein Lauf schreibt `flight_observations` und `flight_offers`. Push noch nicht |
| **M7** | Statistik | Median/Min/Abweichung als **reine Funktionen** mit Unit-Tests. Inklusive Fall „zu wenig Daten" |
| **M8** | Push | APNs-Schlüssel, Token-Registrierung, echte Push auf ein **physisches Gerät**. Dedupe-Logik implementiert und getestet |
| **M9** | Ergebnisse in der App | Ergebnisliste + Detailansicht + Deep-Link aus der Benachrichtigung |
| **M10** | Claude-Erklärung | Erklärtext im Detail und in der Push. Inklusive Fallback-Test (API-Key absichtlich falsch → App funktioniert weiter) |
| **M11** | Claude-Spracheingabe | Freitextfeld → Structured Output → vorausgefülltes Formular, das der Nutzer **bestätigen muss** |
| **M12** | Härtung | Rate Limiting, Alarm-Limit, strukturiertes Logging ohne personenbezogene Daten, Sentry, Deployment auf Render/Railway |

M0–M4 sind ca. die Hälfte der Arbeit und fühlen sich langsam an. Das ist normal.

---

## 6. Ordnerstruktur

### 6.1 Backend

```
backend/
├── app/
│   ├── main.py                  # FastAPI-App, Router einbinden
│   ├── config.py                # Pydantic Settings, liest ENV
│   ├── db.py                    # Engine, Session-Factory
│   │
│   ├── models/                  # SQLAlchemy-Tabellen (DB-Sicht)
│   │   ├── user.py
│   │   ├── price_alert.py
│   │   ├── flight_observation.py
│   │   ├── flight_offer.py
│   │   ├── device_token.py
│   │   └── notification_log.py
│   │
│   ├── schemas/                 # Pydantic (API-Sicht) — bewusst getrennt!
│   │   ├── price_alert.py       # AlertCreate, AlertUpdate, AlertOut
│   │   ├── flight_offer.py
│   │   └── nlp.py               # Schema für Claudes Structured Output
│   │
│   ├── api/
│   │   ├── deps.py              # get_current_user, get_db, Rate-Limit
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── alerts.py
│   │       ├── offers.py
│   │       ├── device_tokens.py
│   │       └── nlp.py           # POST /parse-search
│   │
│   ├── services/                # Fachlogik — hier passiert das Denken
│   │   ├── amadeus_client.py    # nur HTTP + Mapping, keine Regeln
│   │   ├── search_planner.py    # baut das Datumsraster (Schritt ⑤)
│   │   ├── offer_filter.py      # Stopps, Gepäck, Nachtflüge
│   │   ├── price_stats.py       # Median/Min/Abweichung — reine Funktionen
│   │   ├── dedupe.py            # offer_hash, dedupe_key
│   │   ├── push_sender.py       # APNs
│   │   └── claude_service.py    # Extraktion + Erklärung + Fallbacks
│   │
│   ├── jobs/
│   │   ├── scheduler.py         # Worker-Einstiegspunkt
│   │   └── check_prices.py      # ein kompletter Prüflauf
│   │
│   └── core/
│       ├── security.py          # JWT-Prüfung
│       ├── rate_limit.py
│       └── logging.py           # strukturierte Logs, PII-frei
│
├── alembic/versions/
├── tests/
│   ├── unit/                    # price_stats, dedupe, offer_filter, planner
│   ├── integration/             # API-Endpunkte gegen Test-DB
│   └── fixtures/                # gespeicherte Amadeus-Antworten (JSON)
├── pyproject.toml
├── Dockerfile
└── .env.example
```

Die Trennung `models/` ↔ `schemas/` ist wichtig: Was in der Datenbank steht,
ist nicht dasselbe wie das, was die App sehen darf. `raw_payload` und
`user_id` gehören nie in eine API-Antwort.

`services/` enthält **keine** FastAPI- und keine SQLAlchemy-Importe, wo es
sich vermeiden lässt. Reine Funktionen sind trivial testbar.

### 6.2 iOS-App

```
FlugAlarm/
├── App/
│   ├── FlugAlarmApp.swift        # @main, AppDelegate für Push
│   └── AppEnvironment.swift      # Dependency Injection (einfach halten)
│
├── Core/
│   ├── Networking/
│   │   ├── APIClient.swift       # protocol APIClientProtocol + Live-Impl
│   │   ├── APIError.swift        # → nutzerfreundliche Texte
│   │   └── Endpoints.swift
│   ├── Auth/
│   │   ├── AuthService.swift
│   │   └── KeychainStore.swift
│   └── Push/
│       └── PushService.swift     # Erlaubnis, Token, Deep-Link
│
├── Models/                       # Codable-Spiegel der API-Schemas
│   ├── PriceAlert.swift
│   ├── FlightOffer.swift
│   └── SearchCriteria.swift
│
├── Features/                     # ein Ordner pro Bildschirm
│   ├── Auth/
│   │   ├── LoginView.swift
│   │   └── LoginViewModel.swift
│   ├── AlertList/
│   │   ├── AlertListView.swift
│   │   └── AlertListViewModel.swift
│   ├── AlertForm/
│   │   ├── AlertFormView.swift
│   │   ├── AlertFormViewModel.swift
│   │   └── NaturalLanguageInputView.swift
│   ├── OfferList/
│   └── OfferDetail/
│
├── DesignSystem/
│   ├── LoadingView.swift
│   ├── ErrorView.swift           # eine Stelle für alle Fehleranzeigen
│   └── EmptyStateView.swift
│
└── Tests/
    └── ViewModelTests/           # mit FakeAPIClient
```

Ein Ordner pro Feature (statt je einem großen `Views/` und `ViewModels/`)
skaliert besser — alles zu einem Bildschirm liegt beieinander.

---

## 7. Benötigte Konten und Zugänge

| # | Konto | Kosten | Wofür | Wann |
|---|---|---|---|---|
| 1 | **Apple Developer Program** | 99 €/Jahr | **Zwingend für Push.** Ohne Mitgliedschaft gibt es keine APNs-Schlüssel | vor M8 |
| 2 | Amadeus for Developers (Self-Service) | Test kostenlos | Flight Offers Search API | vor M5 |
| 3 | Supabase | kostenloser Tarif | Postgres + Auth | vor M1 |
| 4 | Anthropic Console | Guthaben aufladen | Claude API | vor M10 |
| 5 | Render **oder** Railway | kostenlos–7 $/Mon. | Hosting API + Worker | vor M12 |
| 6 | GitHub | kostenlos | Code, CI | ab M0 |
| 7 | Sentry | kostenlos | Fehler-Monitoring | M12 |
| 8 | Mac mit Xcode 16+ | vorhanden | | ab M0 |
| 9 | Physisches iPhone | vorhanden | **Push funktioniert nicht im Simulator** | ab M8 |

Konkret bei Apple brauchst du: eine **App ID / Bundle Identifier** mit
aktivierter Push-Notifications-Fähigkeit, einen **APNs Auth Key (`.p8`)** sowie
**Key ID** und **Team ID**. Der `.p8`-Schlüssel ist nur *einmal* herunterladbar
— sofort sicher ablegen. Token-basierte Authentifizierung ist gegenüber
Zertifikaten vorzuziehen: ein Schlüssel für alle Apps, kein jährliches Ablaufen.

> Die 99 € sind der einzige unvermeidbare Kostenpunkt. Ohne Developer Program
> kannst du die App auf dein eigenes Gerät laden (Signatur läuft nach 7 Tagen
> ab), aber **Push-Benachrichtigungen — das Kernfeature — funktionieren nicht.**
> Plane das früh ein.

---

## 8. Technische Risiken

Nach Auswirkung sortiert. Die ersten drei sind die, die Projekte kippen.

### 8.1 Amadeus-Testumgebung liefert keine echten Preise
Die Self-Service-Testumgebung arbeitet mit begrenzten, teils zwischen-
gespeicherten Daten. Preise und Verfügbarkeiten entsprechen nicht der Realität,
und nicht jede Strecke ist abgedeckt.
**Folge:** Deine Statistik ist im Test bedeutungslos.
**Umgang:** Nimm für die Entwicklung ein paar gut abgedeckte Strecken
(MUC→BCN, FRA→LHR). Erkläre die Einschränkung im Portfolio offen — dass du sie
kennst, ist selbst ein Qualitätsmerkmal. Der Wechsel auf Produktivschlüssel ist
später ein Konfigurations-, kein Code-Thema.

### 8.2 Kein Buchungslink und lückenhafte Gepäckdaten
Die Flight Offers Search API liefert **keine buchbare URL**. Deinen
„Buchungslink" musst du selbst als Deep-Link zu Google Flights, Skyscanner oder
der Airline-Website zusammenbauen. Ebenso ist die Freigepäck-Information
(`includedCheckedBags`) je nach Tarif nicht immer enthalten.
**Umgang:** `booking_url` selbst erzeugen und in der App als „Weiter zur Suche
bei …" beschriften — nicht als „Jetzt buchen". `included_checked_bags` darf
`NULL` sein; die UI zeigt dann „Gepäckinfo nicht verfügbar" statt „0 Gepäck-
stücke". Ein falsches „0" wäre schlimmer als ein ehrliches „unbekannt".

### 8.3 Explodierende Anzahl von Suchanfragen
Siehe Schritt ⑤. Naiv umgesetzt verbrennt ein einziger Nutzer mit einem
Alarm über zwei Monate dein gesamtes Monatskontingent an einem Tag.
**Umgang:** Datumsraster mit Stichproben, harte Obergrenze pro Lauf,
Alarm-Limit pro Nutzer, Prüfintervall auf 6 h. Zusätzlich einen Zähler der
täglichen API-Calls in der DB führen und bei Überschreitung Läufe aussetzen.

### 8.4 APNs-Einrichtung ist fehleranfällig
Häufigste Stolperfallen: Sandbox- gegen Produktions-Token verwechselt
(`BadDeviceToken`), falsche `apns-topic` (muss die Bundle-ID sein), abgelaufenes
JWT (max. 1 Stunde gültig, muss erneuert werden), Test im Simulator.
**Umgang:** `environment`-Spalte in `device_tokens` von Anfang an. Ein winziges
Testskript, das eine Push an ein festes Token schickt — damit isolierst du
Push-Probleme von App-Problemen.

### 8.5 Supabase-Pooler und asyncpg
Siehe Abschnitt 2.3. Sporadische, schwer nachvollziehbare DB-Fehler.
**Umgang:** `statement_cache_size=0` oder Direktverbindung. Früh entscheiden.

### 8.6 Zeitzonen und Datumsgrenzen
Ein Flug „am 3. Oktober" bedeutet Ortszeit am Abflughafen. Server laufen in
UTC. Ein Nutzer in München sieht ein anderes „heute" als der Server.
**Umgang:** Reisedaten strikt als `date` ohne Uhrzeit behandeln, alle
Zeitstempel als UTC speichern, Umrechnung nur in der Anzeigeschicht der App.
„Nachtflug vermeiden" gegen die **lokale Abflugzeit** prüfen (Amadeus liefert
lokale Zeiten) — Definition festlegen, z. B. Abflug zwischen 23:00 und 06:00.

### 8.7 Mehrfache oder ausbleibende Benachrichtigungen
**Umgang:** UNIQUE-Constraint auf `dedupe_key` (Datenbank-Garantie),
Abkühlphase, 5-%-Verbesserungsregel. Explizit testen, nicht nur hoffen.

### 8.8 Claude liefert plausible, aber falsche Struktur
„Im Oktober" → welches Jahr? „Barcelona" → `BCN` oder `BCN`-Umland?
**Umgang:** Structured Output für die Form, eigene Validierung für den Inhalt.
Und das Wichtigste: Das Ergebnis der Extraktion füllt nur das **Formular vor**;
der Nutzer bestätigt. Kein Alarm entsteht direkt aus Claudes Ausgabe.

### 8.9 Ein-Prozess-Scheduler
APScheduler + zwei Instanzen = doppelte Läufe.
**Umgang:** Worker-Replikat auf 1 begrenzen, `FOR UPDATE SKIP LOCKED` als
zweite Absicherung. Grenze dokumentieren.

### 8.10 Datenschutz (DSGVO)
Du speicherst E-Mail-Adressen, Reisewünsche und Device-Tokens — Reisewünsche
sind personenbezogen.
**Umgang:** Datenminimierung, keine E-Mails und Tokens in Logs (nur User-IDs),
eine Löschfunktion (`DELETE /me` mit `ON DELETE CASCADE`), Beobachtungen älter
als 12 Monate löschen. Für ein Lernprojekt ohne öffentliche Nutzer reicht das —
vor einer echten Veröffentlichung bräuchte es Datenschutzerklärung und AV-Verträge.

---

## 9. Teststrategie

Grundsatz: **Kein automatisierter Test ruft je eine echte externe API auf.**
Sonst sind Tests langsam, teuer und rot, wenn Amadeus mal hakt.

### 9.1 Backend — Unit-Tests (das Fundament, ~70 % der Tests)
Reine Funktionen ohne Datenbank und Netzwerk. Schnell, deshalb ständig
ausführbar.

| Was | Beispielhafte Fälle |
|---|---|
| `price_stats` | Median bei geraden/ungeraden Zahlen; **weniger als 10 Datenpunkte → keine Prozentaussage**; alle Preise gleich → 0 % |
| `dedupe` | Gleiches Angebot → gleicher Hash; Preis geändert → anderer Hash |
| `offer_filter` | 2 Stopps bei `max_stops=1` fliegt raus; Abflug 01:30 bei `avoid_night_flights` fliegt raus; unbekannte Gepäckinfo führt **nicht** zum Ausschluss |
| `search_planner` | Nie mehr als 12 Kombinationen; Raster-Versatz rotiert; Reisedauer wird eingehalten |

### 9.2 Backend — Contract-Tests gegen gespeicherte Antworten
In M5 speicherst du eine echte Amadeus-Antwort als JSON unter
`tests/fixtures/`. Alle Tests des Mappings laufen dagegen — mit `respx` als
httpx-Mock. Ändert Amadeus sein Format, brichst du beim Aktualisieren des
Fixtures kontrolliert.

### 9.3 Backend — Integrationstests
Gegen eine echte, aber lokale Postgres-Datenbank (Docker), pro Test frisch
migriert:
- `POST /alerts` mit ungültigen Daten → `422` mit lesbarer Meldung
- Alarm eines fremden Nutzers abrufen → `404` (nicht `403` — verrät weniger)
- Ohne Token → `401`
- Alarm-Limit überschritten → `409` mit Erklärung
- **Kompletter Prüflauf mit gemocktem Amadeus und gemocktem APNs:** einmal
  laufen lassen → 1 Push. Zweites Mal mit identischen Daten → **0 Pushes.**
  Das ist der wichtigste Test des ganzen Projekts.

### 9.4 Claude — Golden-Set statt exakter Textvergleich
Lege ~20 deutsche Beispielsätze mit erwarteter Struktur an. Prüfe **nicht** den
generierten Text (der variiert), sondern:
- `origin`/`destination` exakt
- Datumsfelder mit Toleranz (Monat/Jahr korrekt)
- `maximumPrice` exakt
- **Schema-Konformität immer** — dank Structured Output ohne Ausnahme

Läuft nicht in der normalen CI (kostet Geld), sondern manuell vor Änderungen am
Prompt. Für die Erklärungsfunktion: nur prüfen, dass ein nicht-leerer Text
zurückkommt und dass bei simuliertem API-Fehler der Fallback greift.

### 9.5 iOS
Die Netzwerkschicht liegt hinter einem `protocol APIClientProtocol`. Tests
nutzen `FakeAPIClient`, keine echten Requests.
- ViewModel-Tests: Laden → Erfolg, Laden → Fehler, leere Liste,
  Formularvalidierung
- SwiftUI-Previews für jeden Zustand (Laden / Fehler / leer / gefüllt) —
  eine Art visueller Test, kostenlos
- Ein UI-Test für den Hauptpfad: Login → Alarm anlegen → in der Liste sehen

### 9.6 Manuelle Prüfungen (unvermeidbar)
Push-Zustellung auf echtem Gerät, Deep-Link aus der Benachrichtigung,
App-Verhalten bei Flugmodus, Verhalten bei abgelehnter Push-Erlaubnis. Als
Checkliste führen, vor jedem Meilenstein-Abschluss durchgehen.

---

## 10. Wann ist das MVP fertig?

Das MVP ist fertig, wenn **alle** Punkte erfüllt sind. Kein „fast".

**Funktional**
- [ ] Registrierung, Login und Logout funktionieren
- [ ] Alarm anlegen mit allen Feldern: Start, Ziel, frühester Hinflug,
      spätester Rückflug, max. Stopps, max. Preis, optional Gepäckstück
- [ ] Aktive Alarme werden aufgelistet, lassen sich bearbeiten und löschen
- [ ] Das Backend prüft aktive Alarme **automatisch nach Zeitplan**, ohne dass
      die App geöffnet ist
- [ ] Jeder Lauf schreibt einen Datenpunkt in den Preisverlauf
- [ ] Ein Angebot unter dem Preislimit löst eine echte Push auf einem
      physischen Gerät aus
- [ ] Tipp auf die Push öffnet direkt die Detailansicht des Angebots
- [ ] Die Detailansicht zeigt: Airline, Flugzeiten, Zwischenstopps,
      Gepäckinfo (oder ehrliches „unbekannt"), Gesamtpreis, externen Link
- [ ] Claude erzeugt einen Erklärtext zum Angebot — und die App funktioniert
      vollständig weiter, wenn Claude nicht erreichbar ist
- [ ] Freitexteingabe erzeugt vorausgefüllte Suchkriterien, die der Nutzer
      bestätigt

**Qualität**
- [ ] Jeder Bildschirm hat sichtbare Lade-, Fehler- und Leerzustände
- [ ] Fehler erscheinen als verständlicher deutscher Text, nie als Statuscode
      oder Stacktrace
- [ ] Kein Netz → verständliche Meldung, kein Absturz
- [ ] Kein API-Schlüssel im iOS-Projekt (grep über das gesamte Repo)
- [ ] Auth-Token liegt im Keychain, nicht in `UserDefaults`
- [ ] Alle Eingaben werden **serverseitig** validiert
- [ ] Rate Limiting aktiv; Limit aktiver Alarme pro Nutzer greift
- [ ] Logs enthalten keine E-Mail-Adressen und keine Device-Tokens
- [ ] Der Dedupe-Test besteht: gleicher Fund zweimal → genau eine Push

**Betrieb**
- [ ] API und Worker laufen deployt, nicht nur lokal
- [ ] Alembic-Migrationen laufen sauber auf einer frischen Datenbank
- [ ] `README.md` erklärt Aufbau und lokale Einrichtung
- [ ] `.env.example` listet alle nötigen Variablen ohne echte Werte
- [ ] Backend-Testsuite ist grün und läuft in unter 30 Sekunden

**Ausdrücklich nicht Teil des MVP:** direkte Buchung, In-App-Käufe,
Affiliate-Tracking, Android, Web, weitere Flug-APIs, ML-Prognosen,
Entschädigungsprüfung, Flugstatus, Multi-Agent-Systeme, automatische Zielsuche,
App-Store-Veröffentlichung.

---

## Nächster Schritt

**Meilenstein M0.** Nicht mit dem Datenmodell in Code anfangen, nicht mit
Amadeus. Erst: Repo-Struktur, Docker-Compose mit Postgres, leeres
FastAPI-Projekt mit einem `/health`-Endpunkt, leeres Xcode-Projekt.

Wenn `curl localhost:8000/health` antwortet und die App startet, ist M0
abgeschlossen — und du hast eine Grundlage, auf der jeder weitere Schritt
sofort ausprobierbar ist.
