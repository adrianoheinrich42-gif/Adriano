# Plattform-Änderung: von iOS zu Web (PWA)

**Entscheidung vom 07.08.2026.** Der Client wird nicht mehr als native
iOS-App in Swift gebaut, sondern als **Progressive Web App (PWA)**.

Dieses Dokument hält fest, *warum* und *was sich dadurch ändert*. Der große
Projektplan (`docs/PROJEKTPLAN.md`) bleibt in Architektur, Datenmodell und
Backend-Entscheidungen gültig — nur alles rund um den Client und den
Push-Versand wird durch dieses Dokument ersetzt.

---

## Warum

- **Kein Mac vorhanden.** Xcode läuft nur auf macOS; native iOS-Entwicklung
  ist auf dem vorhandenen Lenovo (Windows) nicht möglich.
- **Eine Windows-App wäre die falsche Lösung.** Eine Flugpreis-App ist nur
  nützlich, wenn die Benachrichtigung dich unterwegs erreicht — auf dem
  iPhone 15 in der Tasche, nicht auf dem PC zu Hause.
- **Eine PWA nutzt beide vorhandenen Geräte.** Entwickelt auf dem Lenovo,
  installiert auf dem iPhone 15. Seit **iOS 16.4 (2023)** unterstützt Safari
  **Web-Push** für zum Home-Bildschirm hinzugefügte Web-Apps. Das iPhone 15
  läuft auf iOS 17+, also funktioniert das.
- **Günstiger:** Web-Push nutzt selbst erzeugte, kostenlose VAPID-Schlüssel.
  Das **Apple Developer Program (99 €/Jahr) entfällt** ersatzlos.

## Was sich NICHT ändert

Das Backend bleibt zu über 95 % identisch. FastAPI, PostgreSQL/Supabase,
SQLAlchemy, Alembic, der zeitgesteuerte Worker, Amadeus, Claude, die gesamte
Statistik- und Dedupe-Logik, das Datenmodell — alles unverändert. Auch die
Meilensteine M1–M3, M5–M7, M10–M12 auf der Backend-Seite bleiben, wie sie sind.

## Was sich ändert — die Deltas zum Projektplan

### Technologie (ersetzt Abschnitt 2.1)

| Bereich | vorher (iOS) | jetzt (Web) |
|---|---|---|
| Sprache | Swift | HTML, CSS, JavaScript |
| UI | SwiftUI | reines DOM, kein Framework (vorerst) |
| Netzwerk | URLSession | `fetch` |
| Zustand/Logik | MVVM, `@Observable` | kleine JS-Module |
| Entwicklung auf | nur Mac | Lenovo, jeder Browser |
| Dev-Server | Xcode | `python -m http.server` (kein Node nötig) |
| Token-Speicher | Keychain | `localStorage` (für ein Lernprojekt vertretbar; Details unten) |

Ein Framework (z. B. React) führen wir erst ein, wenn die Formulare es
verlangen — nicht vorher. Gleiche Haltung wie beim Scheduler: einfach starten,
wachsen, wenn nötig.

### Push-Versand (ersetzt aioapns / APNs im Abschnitt 2.2)

| | vorher | jetzt |
|---|---|---|
| Dienst | Apple Push Notification Service (APNs) | Web-Push (VAPID) |
| Backend-Bibliothek | `aioapns` | `pywebpush` |
| Schlüssel | `.p8` von Apple, Key-ID, Team-ID | selbst erzeugtes VAPID-Schlüsselpaar (kostenlos) |
| Kosten | 99 €/Jahr | 0 € |
| Zieladresse | APNs-Device-Token | Push-Subscription (Endpoint-URL + zwei Schlüssel) |

### Datenmodell — kleine Anpassung an `device_tokens`

Die Tabelle heißt konzeptionell weiter „das Ziel einer Push". Statt eines
APNs-Tokens speichert sie künftig eine **Web-Push-Subscription**: eine
`endpoint`-URL plus die beiden Schlüssel `p256dh` und `auth`. Das ist eine
Schema-Änderung, die als eigene Alembic-Migration im Push-Meilenstein kommt —
**nicht jetzt**, damit M1 nicht rückwirkend angefasst wird. Die `environment`-
Spalte (sandbox/production) entfällt dann, weil Web-Push das nicht kennt.

### Entwicklerkonten (ersetzt Zeile 1 der Tabelle in Abschnitt 7)

- **Apple Developer Program (99 €/Jahr): entfällt.**
- Neu, aber kostenlos: ein selbst erzeugtes **VAPID-Schlüsselpaar**
  (ein Einzeiler mit `pywebpush` oder der `py-vapid`-CLI).
- Zum Testen von Push auf dem iPhone brauchst du **HTTPS** — entweder über
  einen Entwickler-Tunnel mit HTTPS oder direkt über das Deployment.

### Risiken — geändert

- **Risiko 8.4 (APNs-Einrichtung) entfällt** in seiner alten Form. An seine
  Stelle tritt: **Web-Push auf iOS ist an Bedingungen geknüpft.** Es funktioniert
  nur, wenn (a) die Seite über HTTPS läuft, (b) der Nutzer die App zum
  Home-Bildschirm hinzugefügt hat und (c) er die Benachrichtigungserlaubnis
  erteilt. Web-Push auf iOS gilt zudem als etwas weniger zuverlässig als natives
  APNs. Für ein Lernprojekt ist das in Ordnung; ehrlich im Portfolio benennen.
- **Neues kleines Risiko: Token-Speicherung im Browser.** `localStorage` ist
  nicht so geschützt wie der iOS-Keychain und theoretisch für XSS angreifbar.
  Gegenmaßnahmen: keine eigenen Fremd-Skripte einbinden, Inhalte sauber
  escapen. Für ein Lernprojekt ohne echte Nutzer vertretbar; vor einer echten
  Veröffentlichung neu bewerten.

### Teststrategie (ersetzt Abschnitt 9.5)

- Statt Swift-ViewModel-Tests: die JS-Logik (Fehlerübersetzung, Statuswechsel)
  in kleinen, isolierten Funktionen halten und im Browser prüfen.
- Der Backend-Teil der Teststrategie (Unit-, Contract-, Integrationstests)
  bleibt **unverändert** — er ist ohnehin der wichtigere Teil.

---

## Meilensteine — Auswirkung

Die iOS-spezifischen Meilensteine werden zu Web-Meilensteinen. Inhaltlich
ändert sich wenig, nur die Technik:

| # | vorher | jetzt |
|---|---|---|
| M4 | iOS-Grundgerüst (SwiftUI) | Web-Grundgerüst: Login, Alarm-Liste, Formular als HTML/JS |
| M8 | Push über APNs | Push über Web-Push/VAPID; App installierbar machen (Manifest + Service Worker) |
| M9 | Ergebnisanzeige in SwiftUI | Ergebnisliste + Detailansicht im Browser |
| M11 (Client-Teil) | SwiftUI-Freitextfeld | HTML-Freitextfeld |

Alle übrigen Meilensteine sind unberührt.

## Nachtrag M4: die eine bewusste Ausnahme von Leitplanke 1

Leitplanke 1 sagt: „Der Client kennt nur *eine* URL — das eigene Backend."
Mit der Anmeldung kennt er jetzt **zwei**: zusätzlich die Supabase-Adresse.

Das ist Absicht und betrifft ausschließlich das Anmelden. Der Grund: Würde der
Login durch unser Backend laufen, ginge das **Passwort im Klartext über
unseren Server**. Genau das will man nicht — und es wäre auch der Grund
zunichte, überhaupt Supabase Auth zu nehmen (Entscheidung aus M2: Login,
Zurücksetzen und Hashing sind fehleranfällig).

Der Handel:

* ✅ Das Passwort sieht nur Supabase, nie unser Code.
* ✅ Alle **Daten** — Alarme, Preise, Bewertungen — laufen weiterhin
  ausschließlich über das eigene Backend. Supabase kennt keinen einzigen
  Alarm.
* ❌ Der Client hat eine zweite Abhängigkeit; ist Supabase weg, kann sich
  niemand neu anmelden. Bereits Angemeldete arbeiten weiter, bis ihr Token
  abläuft.

**`supabase-js` wird trotzdem nicht benutzt.** Die Bibliothek käme über ein
fremdes CDN in die Seite; die drei Dinge, die wir brauchen (registrieren,
anmelden, Token erneuern), sind je ein `fetch` gegen die Supabase-REST-API.
Damit bleibt es bei „kein Framework, kein Node, keine fremde Abhängigkeit" —
und es gibt kein CDN, das ausfallen oder mitlesen kann.

Der **`anon`-Schlüssel** in `web/config.js` ist kein Verstoß gegen
Leitplanke 2. Er ist dafür gemacht, öffentlich zu sein, und erlaubt für sich
allein nur einen Anmeldeversuch. Gemeint sind mit Leitplanke 2 die
Amadeus-, Anthropic- und VAPID-Schlüssel — und der `service_role`-Schlüssel,
der niemals in den Browser gehört. Ausführlich kommentiert in `web/auth.js`.

## Bereits erledigt

- **M0-Spiegel fürs Web** steht im Ordner `web/`: eine Seite, die den
  Backend-Status abruft und in drei Zuständen (Laden/Erfolg/Fehler) anzeigt.
  Verifiziert gegen das laufende Backend inklusive CORS-Freigabe.
- **M4** — Anmeldung, Alarmliste und Anlege-Formular. Im echten Chromium
  gegen das echte Backend geprüft (11 Schritte). Einrichtung von Supabase:
  `docs/SUPABASE-EINRICHTEN.md`.
- **M8** — Web-Push statt APNs, wie in diesem Dokument geplant. Umgesetzt:
  `device_tokens` auf Subscription umgestellt (Migration `22e16687014f`,
  `environment` entfallen), `pywebpush`, selbst erzeugtes VAPID-Paar
  (`scripts/vapid_schluessel.py`), PWA-Manifest, Service Worker, Icons.
  Im echten Chromium geprüft (12 Schritte) — inklusive echter Verschlüsselung
  und VAPID-Signatur. **Offen: Test auf echter iPhone-Hardware**, dafür fehlt
  HTTPS.
- **M9** — Detailansicht statt SwiftUI-Ergebnisliste, wie in der
  Meilenstein-Tabelle oben geplant. Der „Deep-Link aus der Benachrichtigung"
  ist ein **Anker** (`/#alarm=<id>`) statt eines Pfads: Eine reine
  HTML-Auslieferung ohne Server-Umschreibung kann `/alarm/<id>` nicht
  auflösen, ein Anker dagegen schon. Der Preisverlauf ist selbst gezeichnetes
  SVG — eine Diagramm-Bibliothek wäre die erste externe Abhängigkeit im
  Frontend gewesen.
- **M10** — Die Erklärtexte kommen jetzt aus dem Backend statt aus
  `detail.js`. Der Client-Anteil dieses Meilensteins ist damit ein *Rückbau*:
  Der Satz unter dem Preis wurde bis M9 im Browser zusammengesetzt, was
  Leitplanke 1 widersprach. Neu ist nur eine kleine Fußzeile „von Claude
  formuliert", damit erkennbar bleibt, wer geschrieben hat.
- Der alte `ios/`-Ordner wurde entfernt; er liegt weiterhin in der
  Git-Historie (Commit `def9ae6`), falls je ein Blick nötig ist.
