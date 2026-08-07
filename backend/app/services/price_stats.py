"""Preisstatistik — aus „unter dem Limit" wird „gutes Angebot".

Bis M6 wusste die Anwendung nur, ob ein Preis unter dem Limit des Nutzers
liegt. Das ist wenig: 380 € für MUC→BCN sind unter einem 400-€-Limit, aber
trotzdem teuer, wenn die Strecke sonst 190 € kostet. Dieses Modul liefert den
fehlenden Vergleich.

**Hier rechnet Python, nicht Claude** (Leitplanke 3 in `CLAUDE.md`). Die
Einordnung ist deterministisch und nachvollziehbar; Claude formuliert später
höchstens den Satz dazu (M10), er entscheidet nichts.

Aufbau wie in `amadeus.py` und `pruflauf.py` — zwei Hälften:

1. **Reine Funktionen** (oben): Median, Abweichung, Einordnung. Eingabe ist
   eine Liste von Zahlen, kein Datenbankobjekt. Ohne DB testbar.
2. **Die Abfrage** (unten): holt die Vergleichspreise aus
   `flight_observations`.

Der wichtigste Satz des Moduls steht in `bewerte_preis`: **Bei zu wenigen
Datenpunkten wird keine Prozentaussage gemacht.** Ehrlichkeit schlägt
Scheingenauigkeit.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation

logger = logging.getLogger(__name__)

# Unter so vielen Beobachtungen ist ein Median statistisch wertlos — drei
# zufällige Preise ergeben keine „übliche" Höhe. Dann sagt die App lieber
# „erster Treffer unter deinem Limit" als eine erfundene Prozentzahl.
# Der Wert stammt aus `docs/PROJEKTPLAN.md` §4 ⑧.
MINDEST_DATENPUNKTE = 10

# Wie weit muss ein Preis vom Median abweichen, damit es der Rede wert ist?
# 10 % ist eine bewusste Setzung, keine Wissenschaft: klein genug, um echte
# Schnäppchen zu erkennen, groß genug, um normales Rauschen zu ignorieren.
GUENSTIG_AB_PROZENT = -10.0
TEUER_AB_PROZENT = 10.0

# Nur die jüngere Vergangenheit vergleichen. Flugpreise von vor einem Jahr
# sagen wenig über heute — und ein Reisemonat rückt mit der Zeit näher, was
# die Preise systematisch verschiebt.
VERGLEICHSFENSTER_TAGE = 90


class Einordnung(StrEnum):
    """Wie steht dieser Preis zur bisherigen Historie?"""

    ZU_WENIG_DATEN = "zu_wenig_daten"
    GUENSTIG = "guenstig"
    NORMAL = "normal"
    TEUER = "teuer"


@dataclass(frozen=True)
class Preisbewertung:
    """Das Ergebnis der Einordnung — mit allem, was ein Text daraus braucht.

    `median_cents`, `minimum_cents` und `abweichung_prozent` sind `None`,
    solange es zu wenige Datenpunkte gibt. Das ist Absicht: Wer sie benutzen
    will, muss sich mit dem Fall „keine Aussage möglich" auseinandersetzen,
    statt versehentlich eine 0 anzuzeigen.
    """

    preis_cents: int
    einordnung: Einordnung
    datenpunkte: int
    median_cents: int | None = None
    minimum_cents: int | None = None
    abweichung_prozent: float | None = None

    @property
    def hat_aussage(self) -> bool:
        """Reichen die Daten für eine Prozentaussage?"""
        return self.einordnung is not Einordnung.ZU_WENIG_DATEN

    @property
    def ist_bestpreis(self) -> bool:
        """Günstiger als alles, was im Vergleichsfenster je beobachtet wurde?

        Für M8 interessant: Ein neuer Tiefstpreis ist auch dann meldenswert,
        wenn die Abweichung vom Median unspektakulär aussieht.
        """
        return self.minimum_cents is not None and self.preis_cents < self.minimum_cents


# ---------------------------------------------------------------------------
# Reine Funktionen — keine Datenbank
# ---------------------------------------------------------------------------


def median_cents(preise: Sequence[int]) -> int:
    """Der mittlere Preis — bei gerader Anzahl der Durchschnitt der beiden mittleren.

    **Median statt Durchschnitt**, weil ein einzelner Ausreißer den
    Durchschnitt kippt: Bei 190, 195, 200, 205 und 2000 € liegt der
    Durchschnitt bei 558 € und der Median bei 200 €. Nur der Median beschreibt,
    was man üblicherweise zahlt.

    Gerundet wird über `Decimal`, nicht mit `round()`: Geld ist im ganzen
    Projekt eine ganze Zahl in Cent, und `round()` rundet in Python zur
    geraden Zahl (`round(0.5)` ist 0, nicht 1) — das überrascht.
    """
    if not preise:
        raise ValueError("Median von einer leeren Liste ist nicht definiert.")

    sortiert = sorted(preise)
    mitte = len(sortiert) // 2

    if len(sortiert) % 2 == 1:
        return sortiert[mitte]

    summe = sortiert[mitte - 1] + sortiert[mitte]
    return int((Decimal(summe) / 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def abweichung_prozent(preis_cents: int, vergleich_cents: int) -> float:
    """Wie weit liegt der Preis über (+) oder unter (−) dem Vergleichswert?

    Auf eine Nachkommastelle gerundet — mehr wäre Scheingenauigkeit bei
    Preisen, die sich stündlich ändern.
    """
    if vergleich_cents <= 0:
        raise ValueError("Vergleichspreis muss positiv sein.")

    return round((preis_cents - vergleich_cents) / vergleich_cents * 100, 1)


def bewerte_preis(preis_cents: int, vergleichspreise: Sequence[int]) -> Preisbewertung:
    """Einen Preis gegen die bisherige Historie einordnen.

    **Bei weniger als `MINDEST_DATENPUNKTE` Beobachtungen gibt es keine
    Prozentaussage** — nur `ZU_WENIG_DATEN` und die Anzahl. Das ist die
    wichtigste Regel hier: Ein Median aus drei Werten sieht aus wie eine
    Aussage, ist aber geraten. Die App sagt dann lieber „erster Treffer unter
    deinem Limit von 150 €", und das ist ehrlich.
    """
    datenpunkte = len(vergleichspreise)

    if datenpunkte < MINDEST_DATENPUNKTE:
        return Preisbewertung(
            preis_cents=preis_cents,
            einordnung=Einordnung.ZU_WENIG_DATEN,
            datenpunkte=datenpunkte,
        )

    median = median_cents(vergleichspreise)
    abweichung = abweichung_prozent(preis_cents, median)

    if abweichung <= GUENSTIG_AB_PROZENT:
        einordnung = Einordnung.GUENSTIG
    elif abweichung >= TEUER_AB_PROZENT:
        einordnung = Einordnung.TEUER
    else:
        einordnung = Einordnung.NORMAL

    return Preisbewertung(
        preis_cents=preis_cents,
        einordnung=einordnung,
        datenpunkte=datenpunkte,
        median_cents=median,
        minimum_cents=min(vergleichspreise),
        abweichung_prozent=abweichung,
    )


# ---------------------------------------------------------------------------
# Die Abfrage — mit Datenbank
# ---------------------------------------------------------------------------


async def hole_vergleichspreise(
    session: AsyncSession,
    origin: str,
    destination: str,
    departure_month: str,
    jetzt: datetime,
    fenster_tage: int = VERGLEICHSFENSTER_TAGE,
    bis: datetime | None = None,
) -> list[int]:
    """Die beobachteten Tiefstpreise derselben Strecke im selben Reisemonat.

    **Über alle Nutzer hinweg** — genau dafür stehen `origin`, `destination`
    und `departure_month` denormalisiert in `flight_observations` (siehe
    Modul-Doku dort). Ein brandneuer Alarm für MUC→BCN im Oktober startet
    dadurch nicht bei null, sondern erbt die Historie aller anderen.

    Zwei Zeilenarten werden ausgeschlossen:

    * `search_ok = false` — die Amadeus-Anfrage schlug fehl. Solche Zeilen in
      die Statistik zu lassen hieße, einen API-Ausfall als „an dem Tag gab es
      nichts" zu lesen.
    * `min_price_cents IS NULL` — an dem Tag wurde nichts gefunden. Das ist
      kein Preis und darf den Median nicht verschieben.

    **`bis` schneidet die jüngsten Beobachtungen ab.** Das braucht die
    Detailansicht (M9): Sie ordnet einen Preis ein, der *gerade eben*
    beobachtet wurde — läge diese Beobachtung im Vergleichsmaterial, vergliche
    sich der Preis gegen sich selbst. `ist_bestpreis` wäre dann nie wahr, weil
    das Minimum immer schon der eigene Preis ist.

    Der Prüflauf braucht `bis` nicht: Er holt die Vergleichspreise, *bevor* er
    seine eigene Beobachtung schreibt. Zwei Wege zum selben Grundsatz — eine
    Messung wird nie gegen sich selbst gehalten.
    """
    bedingungen = [
        FlightObservation.origin == origin,
        FlightObservation.destination == destination,
        FlightObservation.departure_month == departure_month,
        FlightObservation.search_ok.is_(True),
        FlightObservation.min_price_cents.is_not(None),
        FlightObservation.observed_at >= jetzt - timedelta(days=fenster_tage),
    ]
    if bis is not None:
        bedingungen.append(FlightObservation.observed_at < bis)

    result = await session.execute(select(FlightObservation.min_price_cents).where(*bedingungen))
    # `is_not(None)` oben garantiert, dass hier kein None mehr ankommt; mypy
    # weiß das nicht, deshalb die ausdrückliche Prüfung.
    return [preis for preis in result.scalars().all() if preis is not None]


async def bewerte_angebot(
    session: AsyncSession,
    preis_cents: int,
    origin: str,
    destination: str,
    departure_month: str,
    jetzt: datetime,
) -> Preisbewertung:
    """Vergleichspreise holen und den Preis einordnen — die übliche Kombination."""
    vergleichspreise = await hole_vergleichspreise(
        session, origin, destination, departure_month, jetzt
    )
    return bewerte_preis(preis_cents, vergleichspreise)
