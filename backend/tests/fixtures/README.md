# Test-Fixtures

Gespeicherte Antworten externer Dienste. Sie machen die Tests **offline
lauffähig** und halten sie schnell: Kein Test darf ins echte Netz gehen.

## `amadeus_flight_offers_muc_bcn.json`

Antwort auf `GET /v2/shopping/flight-offers` für MUC→BCN,
06.09.2026 – 13.09.2026, 1 Erwachsener, EUR.

> **Herkunft — bitte lesen.** Diese Datei ist **kein Mitschnitt einer echten
> Antwort**. Sie wurde aus der offiziellen OpenAPI-Spezifikation
> (`amadeus4dev/amadeus-open-api-specification`,
> `FlightOffersSearch_v2_swagger_specification.json`) nachgebaut, weil beim
> Erstellen keine Amadeus-Zugangsdaten vorlagen. Feldnamen, Verschachtelung
> und Datentypen entsprechen der Spezifikation; die Flüge und Preise sind
> plausibel erfunden.
>
> **Sobald Zugangsdaten da sind:** einmal echt suchen (siehe unten), die
> Antwort hierher schreiben und die Tests laufen lassen. Weichen sie ab, ist
> die Normalisierung anzupassen — dafür sind die Tests da.
>
> ```
> uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06 --rueckflug 2026-09-13 --roh \
>   > tests/fixtures/amadeus_flight_offers_muc_bcn.json
> ```

Die drei Angebote decken absichtlich unterschiedliche Fälle ab:

| ID | Umstiege hin | Besonderheit |
|----|--------------|--------------|
| 1  | 0            | Gepäck als Stückzahl (`quantity: 1`), `grandTotal == total` |
| 2  | 1            | Gepäck nur als **Gewicht** → Stückzahl bleibt „unbekannt"; `grandTotal` (189,50) liegt **über** `total` (185,00) |
| 3  | 2            | wird bei `max_stops = 1` herausgefiltert; `fareDetailsBySegment` deckt nicht alle Segmente ab |
