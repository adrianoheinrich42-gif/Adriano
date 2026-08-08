"""Claude versteht einen Satz (M11) — aus Sprache werden Suchkriterien.

„Im Oktober für zwei Wochen nach Lissabon, höchstens 250 €" soll das
Alarmformular ausfüllen, statt dass der Nutzer acht Felder von Hand tippt.

Der Unterschied zu `services/claude.py` steckt schon in den Modulnamen: Dort
**formuliert** Claude, hier **versteht** er. Das ist die zweite und letzte
Aufgabe, die er im Projekt bekommt (Leitplanke 3), und sie ist die heiklere —
denn eine falsch verstandene Jahreszahl legt einen Alarm auf einen Zeitraum,
in dem der Nutzer gar nicht reisen will.

## Die eine Regel, an der alles hängt

**Kein Alarm entsteht direkt aus Claudes Ausgabe.** Das Ergebnis füllt das
Formular nur *vor*; anlegen muss der Nutzer selbst, mit einem Blick auf die
Felder. So steht es in `docs/PROJEKTPLAN.md` 8.8, und deshalb heißt der
Endpunkt `POST /alerts/entwurf` und nicht `POST /alerts`.

Das ist keine Bequemlichkeit, sondern die Antwort auf ein echtes Problem:
Structured Output erzwingt die **Form** („`von` ist ein Text mit drei
Buchstaben"), sagt aber nichts über die **Richtigkeit**. „Barcelona" könnte
als `BCN` kommen — richtig — oder als `BAR`, was es nicht gibt. „Im Oktober"
könnte das falsche Jahr treffen.

## Aufbau — wie überall zwei Hälften

1. **Reine Funktionen** (oben): Prompt bauen, Antwort auf Plausibilität
   prüfen, in Formularfelder übersetzen. Ohne Netz, direkt testbar.
2. **Der Aufruf** (unten) hinter dem Protokoll `Auswerter`. Deshalb geht
   **kein Test ins Netz**.

## Was die Prüfung leisten kann — und was nicht

Sie prüft **Plausibilität**, nicht Existenz: Ist das Datum in der Zukunft?
Liegt der Rückflug nach dem Hinflug? Hat der Code drei Großbuchstaben? Ist der
Preis positiv? Was sie *nicht* kann, ist nachzusehen, ob es den Flughafen
`XQZ` wirklich gibt — dafür bräuchte es eine Flughafentabelle. Genau deshalb
bestätigt am Ende der Mensch.

Was nicht plausibel ist, wird **weggelassen statt geraten**, und der Nutzer
bekommt dazu einen Satz. Ein leeres Feld sieht man; eine still erfundene Zahl
nicht.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.services.claude import baue_anthropic_client

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Grenzen der Plausibilitätsprüfung. Bewusst großzügig — sie sollen Unsinn
# abfangen, nicht den Nutzer bevormunden.
MAX_VORLAUF_TAGE = 400  # Amadeus verkauft kaum weiter als ein Jahr im Voraus
MAX_PREIS_EURO = 20_000
MAX_UMSTIEGE = 3
MAX_REISENDE = 9
MAX_EINGABE_ZEICHEN = 500

IATA_MUSTER = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Reine Funktionen — kein Netz, keine Datenbank
# ---------------------------------------------------------------------------


class Suchkriterien(BaseModel):
    """Das Schema, an das Claudes Antwort gebunden wird (Structured Output).

    **Jedes Feld darf `None` sein**, und das ist der wichtigste Zug an diesem
    Schema. „Nach Lissabon, höchstens 250 €" nennt keinen Zeitraum — dann soll
    das Modell den Zeitraum weglassen und nicht einen erfinden, damit das
    Formular voll aussieht. Ein leeres Feld ist eine ehrliche Antwort.

    Die `description`-Texte stehen im JSON-Schema, das Claude sieht. Sie sind
    damit Teil des Prompts; deshalb steht die eigentliche Anweisung zum
    einzelnen Feld hier und nicht noch einmal im Fließtext.
    """

    von: str | None = Field(
        default=None,
        description=(
            "IATA-Code des Startflughafens, drei Großbuchstaben, z. B. 'MUC' für "
            "München. Nur setzen, wenn der Text einen Startort nennt."
        ),
    )
    nach: str | None = Field(
        default=None,
        description="IATA-Code des Zielflughafens, drei Großbuchstaben, z. B. 'LIS' für Lissabon.",
    )
    frueheste_hinreise: date | None = Field(
        default=None,
        description=(
            "Frühester Abflugtag als YYYY-MM-DD. Bei 'im Oktober' der 1. Oktober "
            "des nächsten Oktobers, der in der Zukunft liegt."
        ),
    )
    spaeteste_rueckreise: date | None = Field(
        default=None,
        description=(
            "Spätester Rückreisetag als YYYY-MM-DD. Bei 'im Oktober' der letzte Tag des Monats."
        ),
    )
    hoechstpreis_euro: int | None = Field(
        default=None,
        description="Preisobergrenze in ganzen Euro für die gesamte Reise, z. B. 250.",
    )
    max_umstiege: int | None = Field(
        default=None,
        description="0 bei 'nur Direktflug'. Nur setzen, wenn der Text etwas dazu sagt.",
    )
    reisende: int | None = Field(
        default=None, description="Anzahl Erwachsener. Nur setzen, wenn genannt."
    )
    mindestens_tage: int | None = Field(
        default=None,
        description="Kürzeste gewünschte Reisedauer in Tagen, z. B. 14 bei 'zwei Wochen'.",
    )
    hoechstens_tage: int | None = Field(
        default=None, description="Längste gewünschte Reisedauer in Tagen."
    )
    gepaeck_noetig: bool | None = Field(
        default=None, description="True, wenn aufgegebenes Gepäck enthalten sein soll."
    )
    keine_nachtfluege: bool | None = Field(
        default=None, description="True, wenn Nachtflüge vermieden werden sollen."
    )


@dataclass
class Entwurf:
    """Das Ergebnis: geprüfte Formularfelder plus ehrliche Hinweise.

    `felder` benutzt bereits die **Namen und Einheiten der API** (also
    `max_price_cents` in Cent, nicht `hoechstpreis_euro`). Der Client soll die
    Werte nur eintragen, nicht umrechnen — Leitplanke 1.
    """

    felder: dict[str, object] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)

    @property
    def vollstaendig(self) -> bool:
        """Reicht das schon, um auf „Alarm anlegen" zu drücken?

        Genau die fünf Felder, die `PriceAlertCreate` verlangt. Der Client
        blendet daran seine Meldung auf („noch zwei Felder fehlen").
        """
        pflicht = {
            "origin",
            "destination",
            "earliest_departure_date",
            "latest_return_date",
            "max_price_cents",
        }
        return pflicht.issubset(self.felder.keys())


SYSTEM_PROMPT = """\
Du wandelst deutsche Reisewünsche in strukturierte Suchkriterien für eine
Flugpreis-App um.

Regeln:

1. Trage NUR ein, was im Text steht oder eindeutig daraus folgt. Was nicht
   dasteht, bleibt leer. Ein leeres Feld ist richtig — der Nutzer füllt es
   selbst aus. Erfinde nichts, um das Formular voll aussehen zu lassen.
2. Städtenamen werden zu IATA-Codes des Hauptflughafens: München = MUC,
   Berlin = BER, Wien = VIE, Zürich = ZRH, Hamburg = HAM, Frankfurt = FRA,
   Barcelona = BCN, Lissabon = LIS, Rom = FCO, Mailand = MXP, London = LHR,
   Paris = CDG, Madrid = MAD, Amsterdam = AMS, New York = JFK.
   Kennst du den Code nicht sicher, lass das Feld leer.
3. Zeitangaben rechnest du in konkrete Daten um, ausgehend vom heutigen
   Datum, das dir unten genannt wird. Ein Monat ohne Jahr meint immer das
   NÄCHSTE Vorkommen in der Zukunft. Datumsangaben in der Vergangenheit sind
   immer falsch.
4. „Zwei Wochen" ist eine Reisedauer (mindestens_tage = 14), kein Zeitraum.
   Zeitraum und Dauer sind zwei verschiedene Dinge: Der Zeitraum sagt, WANN
   gereist wird, die Dauer, WIE LANGE.
5. Der Preis ist immer der Gesamtpreis der Reise in Euro, ohne Nachkommastellen.
"""


def baue_nutzertext(eingabe: str, heute: date) -> str:
    """Der Reisewunsch plus das heutige Datum.

    Ohne das Datum kann kein Modell „im Oktober" auflösen — es weiß nicht, ob
    heute September oder November ist. Das ist die häufigste Ursache für
    Alarme im falschen Jahr.

    Der Wochentag steht dabei, weil „nächstes Wochenende" sonst nicht
    ausrechenbar ist.
    """
    wochentage = (
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    )
    return (
        f"Heute ist {wochentage[heute.weekday()]}, der {heute.strftime('%d.%m.%Y')}.\n\n"
        f"Reisewunsch des Nutzers:\n{eingabe.strip()}"
    )


def pruefe_kriterien(kriterien: Suchkriterien, heute: date) -> Entwurf:
    """Claudes Antwort gegenlesen und in Formularfelder übersetzen.

    Der Kern von Risiko 8.8 aus dem Projektplan: Structured Output garantiert
    die Form, nicht den Inhalt. Was hier durchfällt, wird **weggelassen** —
    nie stillschweigend korrigiert und nie geraten. Der Nutzer sieht das leere
    Feld und den Hinweis daneben.

    Zwei Ausnahmen von „weglassen": Umstiege und Reisendenzahl werden
    **gekappt** statt verworfen. Wer „mit 40 Leuten" schreibt, meint erkennbar
    eine Gruppe; neun Reisende sind näher an seinem Wunsch als ein leeres Feld.
    """
    entwurf = Entwurf()
    hinweise = entwurf.hinweise

    # --- Flughäfen -------------------------------------------------------
    von = _als_iata(kriterien.von)
    nach = _als_iata(kriterien.nach)

    if kriterien.von and not von:
        hinweise.append(
            f"„{kriterien.von}“ ist kein gültiges Flughafen-Kürzel — bitte selbst eintragen."
        )
    if kriterien.nach and not nach:
        hinweise.append(
            f"„{kriterien.nach}“ ist kein gültiges Flughafen-Kürzel — bitte selbst eintragen."
        )

    if von and nach and von == nach:
        # Passiert bei Sätzen wie „von Berlin nach Berlin-Schönefeld".
        hinweise.append("Start und Ziel waren identisch — bitte das Ziel selbst eintragen.")
        nach = None

    if von:
        entwurf.felder["origin"] = von
    if nach:
        entwurf.felder["destination"] = nach

    # --- Zeitraum --------------------------------------------------------
    frueh = kriterien.frueheste_hinreise
    spaet = kriterien.spaeteste_rueckreise
    grenze = heute + timedelta(days=MAX_VORLAUF_TAGE)

    if frueh and frueh < heute:
        # Der klassische Jahresfehler: „im Oktober" wird zum vergangenen Oktober.
        hinweise.append("Der erkannte Hinflug lag in der Vergangenheit — bitte Datum prüfen.")
        frueh = spaet = None
    if frueh and frueh > grenze:
        hinweise.append("Der Zeitraum liegt zu weit in der Zukunft — bitte Datum prüfen.")
        frueh = spaet = None
    if frueh and spaet and spaet < frueh:
        hinweise.append("Rückreise lag vor der Hinreise — bitte den Zeitraum selbst eintragen.")
        frueh = spaet = None

    if frueh:
        entwurf.felder["earliest_departure_date"] = frueh.isoformat()
    if spaet:
        entwurf.felder["latest_return_date"] = spaet.isoformat()

    # --- Preis -----------------------------------------------------------
    preis = kriterien.hoechstpreis_euro
    if preis is not None:
        if 0 < preis <= MAX_PREIS_EURO:
            # Die eine Umrechnung, die der Client nicht machen soll.
            entwurf.felder["max_price_cents"] = preis * 100
        else:
            hinweise.append("Der erkannte Höchstpreis war unplausibel — bitte selbst eintragen.")

    # --- Zahlen, die gekappt statt verworfen werden ----------------------
    if kriterien.max_umstiege is not None:
        entwurf.felder["max_stops"] = _gekappt(kriterien.max_umstiege, 0, MAX_UMSTIEGE)
    if kriterien.reisende is not None:
        entwurf.felder["adults"] = _gekappt(kriterien.reisende, 1, MAX_REISENDE)

    # --- Reisedauer ------------------------------------------------------
    mind = kriterien.mindestens_tage
    hoechst = kriterien.hoechstens_tage
    if mind is not None and hoechst is not None and mind > hoechst:
        hinweise.append("Mindest- und Höchstdauer passten nicht zusammen — beide weggelassen.")
        mind = hoechst = None

    if mind is not None and mind > 0:
        entwurf.felder["min_trip_duration_days"] = mind
    if hoechst is not None and hoechst > 0:
        entwurf.felder["max_trip_duration_days"] = hoechst

    # --- Schalter --------------------------------------------------------
    if kriterien.gepaeck_noetig is not None:
        entwurf.felder["include_checked_bag"] = kriterien.gepaeck_noetig
    if kriterien.keine_nachtfluege is not None:
        entwurf.felder["avoid_night_flights"] = kriterien.keine_nachtfluege

    if not entwurf.vollstaendig:
        hinweise.append("Bitte die leeren Pflichtfelder ergänzen, bevor du den Alarm anlegst.")

    return entwurf


def _als_iata(wert: str | None) -> str | None:
    """`" muc "` → `"MUC"`, alles andere → `None`.

    Prüft die **Form**, nicht die Existenz: Ob es den Flughafen `XQZ` gibt,
    ließe sich nur mit einer Flughafentabelle beantworten. Deshalb bestätigt
    am Ende der Nutzer.
    """
    if not wert:
        return None
    code = wert.strip().upper()
    return code if IATA_MUSTER.match(code) else None


def _gekappt(wert: int, unten: int, oben: int) -> int:
    return max(unten, min(oben, wert))


# ---------------------------------------------------------------------------
# Der Aufruf — austauschbar, damit kein Test ins Netz geht
# ---------------------------------------------------------------------------


class NichtVerfuegbar(Exception):
    """Claude konnte nicht antworten.

    Eigene Klasse statt eines `None`-Rückgabewerts, weil der Endpunkt daraus
    einen anderen HTTP-Status macht: Der Nutzer soll „gerade nicht verfügbar,
    bitte von Hand" lesen und nicht ein leeres Formular ohne Erklärung.
    """


class Auswerter(Protocol):
    """Was der Endpunkt vom Sprachverständnis braucht — mehr nicht."""

    async def werte_aus(self, eingabe: str, heute: date) -> Suchkriterien: ...


class ClaudeAuswerter:
    """Der echte Aufruf, mit Structured Output auf `Suchkriterien`.

    Dasselbe Muster wie `ClaudeTexter` in `services/claude.py`, mit einem
    wichtigen Unterschied: **Dieser Aufruf hängt an einer Nutzeranfrage**, der
    andere lief im Worker. Ein Mensch wartet also zu — deshalb ist das
    Zeitlimit hier die spürbare Größe, nicht die Kosten.
    """

    def __init__(self, settings: Settings, http_client: object | None = None) -> None:
        self._settings = settings
        self._client: AsyncAnthropic = baue_anthropic_client(settings, http_client)

    async def werte_aus(self, eingabe: str, heute: date) -> Suchkriterien:
        antwort = await self._client.messages.parse(
            model=self._settings.anthropic_model,
            max_tokens=self._settings.anthropic_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": baue_nutzertext(eingabe, heute)}],
            output_format=Suchkriterien,
        )
        ergebnis = antwort.parsed_output
        if ergebnis is None:
            raise ValueError("Antwort ohne verwertbaren Inhalt.")
        return ergebnis

    async def aclose(self) -> None:
        await self._client.close()


async def erzeuge_entwurf(eingabe: str, auswerter: Auswerter, heute: date) -> Entwurf:
    """Aus einem Satz wird ein geprüfter Formularentwurf.

    Wirft `NichtVerfuegbar`, wenn Claude nicht antwortet — und **nur** dann.
    Anders als beim Erklärtext in M10 gibt es hier keinen Fallback, den man
    einsetzen könnte: Einen deutschen Satz kann ein Baukasten schreiben, einen
    Satz *verstehen* kann er nicht. Der Rückfall ist deshalb das ganz normale
    leere Formular — die Kernfunktion bleibt vollständig erreichbar, sie
    kostet nur mehr Tippen.

    Das nackte `except Exception` ist wie in `push.erzeuge_nachricht()`
    Absicht: Jede SDK-Ausnahmeklasse einzeln aufzuzählen hieße, dass die eine
    vergessene den Nutzer einen HTTP 500 sehen lässt statt eines erklärenden
    Satzes.
    """
    text = eingabe.strip()
    if not text:
        raise NichtVerfuegbar("Leere Eingabe.")
    if len(text) > MAX_EINGABE_ZEICHEN:
        # Nicht aus Höflichkeit, sondern gegen Kosten: Der Prompt geht sonst
        # mit beliebig viel fremdem Text an einen kostenpflichtigen Dienst.
        text = text[:MAX_EINGABE_ZEICHEN]

    try:
        kriterien = await auswerter.werte_aus(text, heute)
    except Exception as exc:  # noqa: BLE001 — siehe Docstring: absichtlich alles
        logger.warning("Freitext-Auswertung fehlgeschlagen: %s", exc)
        raise NichtVerfuegbar(str(exc)) from exc

    return pruefe_kriterien(kriterien, heute)
