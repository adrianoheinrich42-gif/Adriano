# Flugpreis-Alarm

Lern- und Portfolioprojekt: native iOS-App (SwiftUI), die Flugpreis-Alarme
verwaltet, plus ein Python-Backend (FastAPI), das die Preise zeitgesteuert
überwacht und bei passenden Angeboten eine Push-Benachrichtigung schickt.

**Stand: M0 (Setup) und M1 (Datenbankmodell) abgeschlossen.**
Backend läuft, das vollständige Schema ist migriert, App zeigt den
Backend-Status an.

📄 Planungsgrundlage: **[docs/PROJEKTPLAN.md](docs/PROJEKTPLAN.md)** —
Architektur, Datenmodell, Ablauf, alle Meilensteine, Risiken, Teststrategie.

---

## In fünf Minuten zum Laufen

Voraussetzungen: Docker, [uv](https://docs.astral.sh/uv/), Xcode 16+.

```bash
# 1. Datenbank starten
docker compose up -d db

# 2. Backend einrichten, Schema anlegen, starten
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Prüfen:

```console
$ curl -s localhost:8000/health
{"status":"ok","database":"ok","version":"0.1.0","environment":"local"}
```

Steht dort `"database":"ok"`, ist die ganze Kette Backend → Postgres bewiesen.

```bash
# 3. App starten
open ios/FlugAlarm.xcodeproj     # Schema FlugAlarm, Simulator, ⌘R
```

Die App zeigt einen grünen Haken und darunter Datenbankstatus, Version und
Umgebung.

Alle Befehle sind auch als `make`-Ziele hinterlegt — `make help` zeigt sie an.

---

## Was bisher entstanden ist

```
.
├── docker-compose.yml       Postgres 16 (+ optional die API im Container)
├── Makefile                 Kurzbefehle für den Alltag — `make help`
├── docs/PROJEKTPLAN.md      Die vollständige Planung
├── backend/                 FastAPI, siehe backend/README.md
│   ├── app/models/          die sechs Tabellen des MVP
│   ├── alembic/versions/    Migrationen
│   └── tests/               18 Tests (2 ohne DB, 16 Integrationstests)
└── ios/                     SwiftUI-App, siehe ios/README.md
    └── FlugAlarm/           App, APIClient, ViewModel, Modelle
```

**M0** — Der `/health`-Endpunkt ist bewusst mehr als „Hello World": Er prüft
die Datenbankverbindung und antwortet auch dann, wenn sie fehlt. Die App stellt
Lade-, Erfolgs- und Fehlerzustand schon jetzt getrennt dar — genau das Muster,
das ab M4 jeder Bildschirm bekommt.

**M1** — Das Schema enthält nicht nur Spalten, sondern die Regeln selbst:
Startflughafen ≠ Zielflughafen, Rückflug nicht vor Hinflug, IATA-Codes in
Großbuchstaben, Prüfintervall mindestens 15 Minuten. Und der UNIQUE-Index auf
`notification_logs.dedupe_key` — der Schutz vor doppelten Push-Nachrichten —
ist eine Datenbank-Garantie, keine Programmlogik, die man vergessen kann.
16 Integrationstests belegen das; ohne laufende Datenbank überspringen sie sich
selbst, statt rot zu werden.

## Geplanter Aufbau

| Teil | Technologie |
|---|---|
| App | Swift, SwiftUI, MVVM mit `@Observable`, async/await, iOS 17+ |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Datenbank | PostgreSQL — lokal via Docker, später Supabase |
| Auth | Supabase Auth (JWT) |
| Flugdaten | Amadeus Flight Offers Search |
| Push | Apple Push Notification Service (APNs) |
| KI | Claude API (`claude-haiku-4-5`) — nur Sprachverarbeitung und Erklärtexte |

## Grundregeln

1. Die App ruft niemals selbst Flugpreis-APIs auf — das macht ausschließlich
   das Backend.
2. API-Schlüssel liegen ausschließlich in Umgebungsvariablen des Backends,
   niemals im Client. In der App steht genau eine Adresse: die des Backends.
3. Die Bewertung „günstiges Angebot?" ist deterministische Statistik in Python.
   Claude formuliert nur die Erklärung dazu.

## Nächster Schritt

**M2 — Auth-Kette.** Supabase-Projekt anlegen, JWT-Prüfung im Backend,
`GET /me` gibt mit gültigem Token die User-ID zurück.
