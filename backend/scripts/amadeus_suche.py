"""Einmalige Flugsuche von Hand — der Abnahmetest für M5.

Kein Scheduler, keine Datenbank: Das Skript fragt Amadeus einmal, normalisiert
die Antwort und zeigt sie an. Damit lässt sich prüfen, ob die Zugangsdaten
stimmen und ob die echte Antwort zur Normalisierung passt.

    uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06
    uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06 --rueckflug 2026-09-13
    uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06 --max-stopps 0 --max-preis 250

Mit `--roh` kommt die unveränderte Amadeus-Antwort heraus — genau das, was in
`tests/fixtures/` gehört:

    uv run python -m scripts.amadeus_suche MUC BCN 2026-09-06 --rueckflug 2026-09-13 --roh \\
      > tests/fixtures/amadeus_flight_offers_muc_bcn.json
"""

import argparse
import asyncio
import json
import sys
from datetime import date, datetime

from app.config import get_settings
from app.schemas.flight_offer import Flugangebot, Teilstrecke
from app.services.amadeus import (
    AmadeusClient,
    AmadeusError,
    Suchanfrage,
    normalisiere_antwort,
)


def _datum(wert: str) -> date:
    try:
        return datetime.strptime(wert, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Datum bitte als JJJJ-MM-TT, nicht {wert!r}") from exc


def _argumente() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Einmalige Amadeus-Suche.")
    parser.add_argument("origin", help="Startflughafen, IATA-Code (z. B. MUC)")
    parser.add_argument("destination", help="Zielflughafen, IATA-Code (z. B. BCN)")
    parser.add_argument("hinflug", type=_datum, help="Hinflugdatum JJJJ-MM-TT")
    parser.add_argument("--rueckflug", type=_datum, default=None, help="Rückflugdatum JJJJ-MM-TT")
    parser.add_argument("--erwachsene", type=int, default=1)
    parser.add_argument("--max-stopps", type=int, default=1)
    parser.add_argument("--max-preis", type=int, default=None, help="Höchstpreis in **Euro**")
    parser.add_argument("--anzahl", type=int, default=10, help="Wie viele Angebote maximal")
    parser.add_argument(
        "--roh",
        action="store_true",
        help="Unveränderte Amadeus-Antwort ausgeben (für tests/fixtures/)",
    )
    return parser.parse_args()


def _zeit(wert: datetime) -> str:
    return wert.strftime("%d.%m. %H:%M")


def _strecke(strecke: Teilstrecke, titel: str) -> str:
    stunden, minuten = divmod(strecke.dauer_minuten, 60)
    umstiege = "direkt" if strecke.umstiege == 0 else f"{strecke.umstiege} Umstieg(e)"
    fluege = " → ".join(
        f"{s.von}–{s.nach} {s.fluggesellschaft}{s.flugnummer}" for s in strecke.segmente
    )
    return (
        f"  {titel}: {_zeit(strecke.abflug_lokal)} → {_zeit(strecke.ankunft_lokal)}"
        f"  ({stunden}h{minuten:02d}, {umstiege})\n"
        f"    {fluege}"
    )


def _zeige(angebot: Flugangebot, nummer: int) -> None:
    gepaeck = (
        "unbekannt"
        if angebot.inkludierte_gepaeckstuecke is None
        else f"{angebot.inkludierte_gepaeckstuecke} Stück"
    )
    print(
        f"\n[{nummer}] {angebot.preis_cents / 100:.2f} {angebot.waehrung}"
        f"   Airline: {angebot.validierende_airline or '?'}"
        f"   Gepäck: {gepaeck}"
    )
    print(_strecke(angebot.hinflug, "Hin  "))
    if angebot.rueckflug is not None:
        print(_strecke(angebot.rueckflug, "Zurück"))


async def _main() -> int:
    args = _argumente()

    anfrage = Suchanfrage(
        origin=args.origin.upper(),
        destination=args.destination.upper(),
        departure_date=args.hinflug,
        return_date=args.rueckflug,
        adults=args.erwachsene,
        max_stops=args.max_stopps,
        max_price_cents=args.max_preis * 100 if args.max_preis else None,
        max_ergebnisse=args.anzahl,
    )

    async with AmadeusClient(get_settings()) as client:
        try:
            if args.roh:
                # Unverändert, inklusive `meta` und `dictionaries` — so wie
                # die Datei in tests/fixtures/ aussehen soll.
                antwort = await client.suche_roh(anfrage)
                print(json.dumps(antwort, indent=2, ensure_ascii=False))

                # Zur Kontrolle auf stderr, damit die Umleitung in eine Datei
                # sauber bleibt.
                anzahl = len(normalisiere_antwort(antwort))
                print(f"\n({anzahl} Angebote ließen sich normalisieren)", file=sys.stderr)
                return 0

            angebote = await client.suche(anfrage)
        except AmadeusError as exc:
            # Verständlicher Text statt Stacktrace — das Skript benutzt ein Mensch.
            print(f"Suche fehlgeschlagen: {exc}", file=sys.stderr)
            return 1

    if not angebote:
        print("Keine Angebote gefunden, die zu den Bedingungen passen.")
        return 0

    print(
        f"{len(angebote)} Angebot(e) für {anfrage.origin} → {anfrage.destination} "
        f"am {anfrage.departure_date:%d.%m.%Y}"
        + (f", zurück am {anfrage.return_date:%d.%m.%Y}" if anfrage.return_date else "")
    )
    for nummer, angebot in enumerate(sorted(angebote, key=lambda a: a.preis_cents), start=1):
        _zeige(angebot, nummer)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
