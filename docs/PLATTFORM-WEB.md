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

## Bereits erledigt

- **M0-Spiegel fürs Web** steht im Ordner `web/`: eine Seite, die den
  Backend-Status abruft und in drei Zuständen (Laden/Erfolg/Fehler) anzeigt.
  Verifiziert gegen das laufende Backend inklusive CORS-Freigabe.
- Der alte `ios/`-Ordner wurde entfernt; er liegt weiterhin in der
  Git-Historie (Commit `def9ae6`), falls je ein Blick nötig ist.
