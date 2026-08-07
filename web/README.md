# Web-Frontend (M4)

Die Web-App: anmelden, Preisalarme ansehen, anlegen, pausieren und löschen.

Bewusst **ohne Framework**: reines HTML, CSS und JavaScript. Der Browser lädt
die Dateien direkt, es gibt keinen Build-Schritt und **du brauchst kein
Node.js**, um zu starten. Auch die Anmeldung kommt ohne Bibliothek aus —
warum, steht oben in `auth.js`.

## Vorher: Supabase einrichten

Ohne Anmeldedienst geht nichts. Die Anleitung dafür setzt kein Vorwissen
voraus und dauert etwa 15 Minuten:

→ **[`../docs/SUPABASE-EINRICHTEN.md`](../docs/SUPABASE-EINRICHTEN.md)**

Danach müssen `supabaseUrl` und `supabaseAnonKey` in `config.js` stehen und
`SUPABASE_URL` / `SUPABASE_JWT_SECRET` in `backend/.env`.

## Starten

Drei Fenster:

```powershell
# 1 — Datenbank
docker compose up -d db

# 2 — Backend (aus backend/)
uv run uvicorn app.main:app --reload

# 3 — Frontend ausliefern (Python hast du schon!)
cd web
python -m http.server 3000
```

Dann im Browser öffnen: <http://localhost:3000>

> **Warum nicht die Datei per Doppelklick öffnen?** Dann wäre die Herkunft der
> Seite `file://`, und der Browser blockt den Abruf zum Backend (CORS). Über
> `http://localhost:3000` ausgeliefert, ist die Herkunft erlaubt — das Backend
> lässt `localhost:3000` bereits zu.

## Die Dateien

| Datei | Wofür |
|---|---|
| `index.html` | Das Gerüst: Anmeldung, Liste, Formular-Dialog |
| `config.js` | **Die einzige Datei, die du anfassen musst** — Adressen und Schlüssel |
| `auth.js` | Anmeldung gegen Supabase; verwaltet das Token und erneuert es |
| `api.js` | Alle Aufrufe ans eigene Backend; macht aus Statuscodes deutsche Sätze |
| `format.js` | Geld (Cent ↔ Euro), Datum, „vor 5 Minuten" |
| `app.js` | Ansichten umschalten und die Liste zeichnen |
| `styles.css` | Aussehen, hell und dunkel |

Die Aufteilung folgt einer Regel: **Nur `api.js` ruft `fetch` auf das eigene
Backend auf.** Dadurch gibt es genau eine Stelle, die das Token anhängt, ein
Zeitlimit setzt und Fehler übersetzt.

## Was die App bewusst *nicht* tut

Sie **bewertet nichts**. Ob ein Preis gut ist, ob ein Alarm fällig ist, ob ein
Angebot gemeldet wird — all das entscheidet das Backend (Leitplanke 1 in
`CLAUDE.md`). Der Client zeigt an und schickt Formulare. Die einzige Rechnung,
die er selbst macht, ist „249,99 € → 24999 Cent" — und die nur, weil das
Eingabefeld Euro will und die API Cent.

## Später auf dem iPhone 15 testen

1. Lenovo und iPhone im **selben WLAN**.
2. WLAN-IP des Lenovo herausfinden: `ipconfig` → Zeile „IPv4-Adresse".
3. In `config.js` `apiBaseURL` auf `http://<diese-IP>:8000` setzen.
4. Backend mit `--host 0.0.0.0` starten, damit es von außen erreichbar ist.
5. Beide Adressen in `CORS_ORIGINS` des Backends eintragen.

Für **Push-Benachrichtigungen** (M8) reicht das nicht mehr: Das iPhone
verlangt dafür HTTPS und dass die Seite über „Zum Home-Bildschirm" installiert
wurde. Details in `../docs/PLATTFORM-WEB.md`.
