# Flugpreis-Alarm

Lern- und Portfolioprojekt: native iOS-App (SwiftUI), die Flugpreis-Alarme
verwaltet, plus ein Python-Backend (FastAPI), das die Preise zeitgesteuert
überwacht und bei passenden Angeboten eine Push-Benachrichtigung schickt.

## Stand

Planungsphase — noch kein Produktivcode.

📄 **[docs/PROJEKTPLAN.md](docs/PROJEKTPLAN.md)** — Architektur, Technologie-
auswahl, Datenmodell, Ablauf, Meilensteine, Risiken, Teststrategie und
Fertigstellungskriterien.

## Geplanter Aufbau

| Teil | Technologie |
|---|---|
| App | Swift 6, SwiftUI, MVVM, async/await, iOS 17+ |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Datenbank | PostgreSQL (Supabase) |
| Auth | Supabase Auth (JWT) |
| Flugdaten | Amadeus Flight Offers Search |
| Push | Apple Push Notification Service (APNs) |
| KI | Claude API (`claude-haiku-4-5`) — nur Sprachverarbeitung und Erklärtexte |

## Grundregeln

1. Die App ruft niemals selbst Flugpreis-APIs auf — das macht ausschließlich
   das Backend.
2. API-Schlüssel liegen ausschließlich in Umgebungsvariablen des Backends,
   niemals im Client.
3. Die Bewertung „günstiges Angebot?" ist deterministische Statistik in Python.
   Claude formuliert nur die Erklärung dazu.

## Nächster Schritt

Meilenstein M0 (Setup) — siehe Projektplan.
