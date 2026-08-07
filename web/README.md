# Web-Frontend (M0)

Eine schlanke Web-App (PWA-Kandidat), die den Backend-Status anzeigt. Sie
beweist, dass die Kette **Browser → API → Datenbank** durchgängig funktioniert
— das Web-Gegenstück zur früheren iOS-App.

Bewusst **ohne Framework**: reines HTML, CSS und JavaScript. Der Browser lädt
die Dateien direkt, es gibt keinen Build-Schritt und **du brauchst kein
Node.js**, um zu starten.

## Starten (auf deinem Lenovo)

Du brauchst zwei Terminals — eines fürs Backend, eines fürs Frontend.

```powershell
# Terminal 1 — Backend (siehe backend/README.md)
cd backend
uv run uvicorn app.main:app --reload

# Terminal 2 — Frontend ausliefern (Python hast du schon!)
cd web
python -m http.server 3000
```

Dann im Browser öffnen: <http://localhost:3000>

Du solltest einen grünen Haken sehen und darunter Datenbankstatus, Version und
Umgebung. Läuft die Datenbank nicht, zeigt die Seite „Backend eingeschränkt" —
was ebenfalls korrekt ist.

> **Warum nicht die Datei direkt per Doppelklick öffnen?** Dann wäre die
> Herkunft der Seite `file://`, und der Browser blockt den Abruf zum Backend
> (CORS). Über `http://localhost:3000` ausgeliefert, ist die Herkunft erlaubt —
> das Backend lässt `localhost:3000` bereits zu.

## Später auf dem iPhone 15 testen

Für die reine Statusanzeige (dieser Stand) genügt:

1. Lenovo und iPhone im **selben WLAN**.
2. Backend **nach außen** öffnen: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
   und das Frontend ebenso: `python -m http.server 3000 --bind 0.0.0.0`
3. Die **IPv4-Adresse deines Lenovo** herausfinden: in PowerShell `ipconfig`,
   Zeile „IPv4-Adresse", z. B. `192.168.1.42`.
4. In `web/config.js` die `apiBaseURL` auf `http://192.168.1.42:8000` ändern.
5. Dem Backend erlauben, Anfragen von dieser Herkunft anzunehmen — beim Start
   die Umgebungsvariable setzen:
   `CORS_ORIGINS=["http://192.168.1.42:3000"]`
6. Am iPhone im Safari `http://192.168.1.42:3000` öffnen.

> ⚠️ **Push kommt später — und braucht dann HTTPS.** Die Statusanzeige läuft
> über einfaches `http`. Web-Push auf dem iPhone verlangt aber `https` (außer
> auf `localhost`) und dass die App zum Home-Bildschirm hinzugefügt wurde. Das
> ist der Web-Gegenpart zur früheren APNs-Sandbox-Komplexität und wird im
> Push-Meilenstein gelöst (Tunnel mit HTTPS oder Deployment). Für jetzt reicht
> `http` völlig.

## Dateien

| Datei | Zweck |
|---|---|
| `index.html` | Gerüst mit drei Zuständen: Laden / Erfolg / Fehler |
| `app.js` | Ruft `GET /health` ab und schaltet den passenden Zustand sichtbar |
| `config.js` | **Einzige** Konfiguration: die Backend-Adresse |
| `styles.css` | Schlichtes, mobil-zuerst gedachtes Stylesheet, Hell-/Dunkelmodus |

## Was noch fehlt (kommt in späteren Meilensteinen)

- `manifest.webmanifest` + Icons → macht die App „installierbar" (Home-Bildschirm)
- `service-worker.js` → Grundlage für Web-Push
- Web-Push-Anmeldung mit VAPID-Schlüssel → die eigentliche Benachrichtigung
- Login-Bildschirm, Alarm-Liste, Alarm-Formular, Detailansicht

Die vollständige Neuausrichtung von iOS auf Web steht in
`docs/PLATTFORM-WEB.md`.
