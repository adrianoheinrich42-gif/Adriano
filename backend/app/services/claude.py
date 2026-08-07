"""Claude formuliert den Erklärtext (M10).

Leitplanke 3 aus `CLAUDE.md`, wörtlich: **Claude entscheidet nicht, Claude
formuliert.** Ob ein Preis gut ist, hat `price_stats.py` in Python
ausgerechnet — deterministisch, nachvollziehbar, testbar. Hier wird aus den
fertigen Zahlen nur noch ein freundlicher deutscher Satz.

Damit ist Claude in diesem Projekt **Beiwerk**. Fällt der Aufruf aus (kein
Guthaben, Rate Limit, Zeitüberschreitung, falscher Schlüssel), passiert genau
nichts Schlimmes: `formuliere_nachricht()` in `push.py` liefert denselben
Inhalt in etwas hölzernerem Deutsch, und die Benachrichtigung geht trotzdem
raus. Das ist kein nachträglicher Notnagel, sondern die Reihenfolge, in der
gebaut wurde — den Baukasten gab es seit M8, Claude kommt jetzt obendrauf.

## Aufbau — wie in den anderen Diensten zwei Hälften

1. **Reine Funktionen** (oben): Fakten sammeln, Prompt bauen, Antwort prüfen.
   Ohne Netz, ohne Datenbank, direkt testbar.
2. **Der Aufruf** (unten) hinter dem Protokoll `Texter`. Dieselbe Bauart wie
   `Flugsuche` und `PushVersand` — deshalb setzen die Tests eine Attrappe ein
   und **kein Test geht ins Netz**.

## Warum die Antwort nachgeprüft wird

Structured Output garantiert die **Form** der Antwort (zwei Felder, beide
Text), nicht ihre **Richtigkeit**. Ein Sprachmodell darf sich beim Umschreiben
nicht verrechnen: „18 % günstiger" statt der berechneten 21 % wäre eine
erfundene Zahl in einer Nachricht, die nach Tatsache aussieht.

`pruefe_text()` prüft deshalb jede Zahl im erzeugten Text gegen die Zahlen,
die Claude überhaupt bekommen hat. Passt eine nicht, wird der ganze Text
verworfen und der Baukasten übernimmt. Das ist absichtlich streng: Ein
verworfener guter Text kostet nichts, eine durchgerutschte falsche Zahl das
Vertrauen in die App.
"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.models.price_alert import PriceAlert
from app.schemas.flight_offer import Flugangebot
from app.services.price_stats import Einordnung, Preisbewertung

logger = logging.getLogger(__name__)

# Auf dem Sperrbildschirm ist wenig Platz. Was länger ist, wird ohnehin
# abgeschnitten — dann lieber gleich der kürzere Baukasten-Satz.
MAX_TITEL_ZEICHEN = 80
MAX_TEXT_ZEICHEN = 180


# ---------------------------------------------------------------------------
# Reine Funktionen — keine Datenbank, kein Netz
# ---------------------------------------------------------------------------


class Erklaertext(BaseModel):
    """Das Schema, an das die Antwort gebunden wird (Structured Output).

    Zwei Felder, weil die Benachrichtigung zwei hat. Die Beschreibungen sind
    Teil des Prompts — das Modell sieht sie im JSON-Schema, deshalb steht die
    eigentliche Anweisung hier und nicht noch einmal im Fließtext.
    """

    titel: str = Field(
        description=(
            "Kurze Kopfzeile, höchstens 60 Zeichen. Enthält Strecke und Preis, "
            "zum Beispiel: 'MUC → BCN für 189,50 €'."
        )
    )
    text: str = Field(
        description=(
            "Ein bis zwei kurze deutsche Sätze, höchstens 160 Zeichen, die "
            "erklären, warum dieses Angebot gemeldet wird."
        )
    )


@dataclass(frozen=True)
class Erklaerfakten:
    """Alles, was Claude wissen darf — und nichts darüber hinaus.

    Bewusst eine eigene, flache Struktur statt der Datenbankobjekte: So ist an
    einer Stelle sichtbar, was das Modell zu sehen bekommt. Es steht hier
    keine E-Mail-Adresse und keine Nutzer-ID; ein Sprachmodell braucht für
    „schreib einen netten Satz" keine personenbezogenen Daten.
    """

    von: str
    nach: str
    preis_text: str
    limit_text: str
    einordnung: Einordnung
    ist_bestpreis: bool
    umstiege: int
    airline: str | None
    median_text: str | None
    abweichung_prozent: float | None
    datenpunkte: int
    gepaeckstuecke: int | None

    @property
    def erlaubte_zahlen(self) -> set[str]:
        """Jede Zahl, die im erzeugten Text vorkommen darf.

        Grundlage für `pruefe_text()`. Enthält bewusst mehrere Schreibweisen
        derselben Zahl — „189,50", „189" und „190" meinen denselben Preis, und
        ein gerundeter Betrag ist kein erfundener.
        """
        erlaubt: set[str] = {"0", "1", "2"}  # Umstiege, Gepäckstücke, Satzzahlen

        for text in (self.preis_text, self.limit_text, self.median_text):
            if text:
                erlaubt.update(_zahlen_im_text(text))
                erlaubt.update(_rundungsvarianten(text))

        erlaubt.add(str(self.umstiege))
        erlaubt.add(str(self.datenpunkte))
        if self.gepaeckstuecke is not None:
            erlaubt.add(str(self.gepaeckstuecke))
        if self.abweichung_prozent is not None:
            wert = abs(self.abweichung_prozent)
            # Auf- und abgerundet, weil „20,4 %" als „20 %" oder „21 %"
            # geschrieben werden darf.
            erlaubt.update({str(int(wert)), str(int(wert) + 1), f"{wert:.1f}".replace(".", ",")})

        return erlaubt


def _zahlen_im_text(text: str) -> set[str]:
    """Alle Zahlen einer Zeichenkette, deutsche Schreibweise („189,50")."""
    return set(re.findall(r"\d+(?:,\d+)?", text))


def _rundungsvarianten(betrag: str) -> set[str]:
    """„189,50 €" → {„189", „190"} — gerundete Beträge sind erlaubt."""
    varianten: set[str] = set()
    for zahl in re.findall(r"(\d+),(\d+)", betrag):
        ganz = int(zahl[0])
        varianten.update({str(ganz), str(ganz + 1)})
    return varianten


def baue_fakten(
    alert: PriceAlert, angebot: Flugangebot, bewertung: Preisbewertung
) -> Erklaerfakten:
    """Aus Alarm, Angebot und Bewertung wird der Wissensstand des Modells."""
    from app.services.push import _euro  # zyklische Einfuhr vermeiden

    return Erklaerfakten(
        von=alert.origin,
        nach=alert.destination,
        preis_text=_euro(angebot.preis_cents, angebot.waehrung),
        limit_text=_euro(alert.max_price_cents, alert.currency),
        einordnung=bewertung.einordnung,
        ist_bestpreis=bewertung.ist_bestpreis,
        umstiege=angebot.maximale_umstiege,
        airline=angebot.validierende_airline,
        median_text=(
            _euro(bewertung.median_cents, angebot.waehrung)
            if bewertung.median_cents is not None
            else None
        ),
        abweichung_prozent=bewertung.abweichung_prozent,
        datenpunkte=bewertung.datenpunkte,
        gepaeckstuecke=angebot.inkludierte_gepaeckstuecke,
    )


SYSTEM_PROMPT = """\
Du formulierst kurze Push-Benachrichtigungen für eine deutsche Flugpreis-App.

Der Nutzer hat einen Preisalarm gestellt und bekommt jetzt eine Nachricht,
weil ein passendes Angebot gefunden wurde.

Regeln, die alle gelten:

1. Deutsch, per „du", freundlich und sachlich. Keine Werbesprache, keine
   Ausrufezeichen, kein „unglaublich" oder „Schnäppchen des Jahres".
2. Verwende AUSSCHLIESSLICH die Zahlen, die dir unten genannt werden.
   Rechne nichts aus, schätze nichts, erfinde keine Ersparnis und keinen
   Vergleichspreis. Runden ist erlaubt.
3. Behaupte nichts über die Datenlage, was nicht dasteht. Steht dort „für
   einen Vergleich fehlen noch Daten", dann sage genau das — schreibe nicht
   „besonders günstig".
4. Der Titel nennt Strecke und Preis. Der Text erklärt in ein bis zwei
   Sätzen, warum das Angebot gemeldet wird.
5. Keine Emojis. Sie sehen auf dem Sperrbildschirm gedrängt aus und lesen
   sich mit Bildschirmvorlesern schlecht.
"""


def baue_nutzertext(fakten: Erklaerfakten) -> str:
    """Die Fakten als schlichte Liste.

    Bewusst ohne JSON und ohne Beispieldialoge: Das Modell soll die Zahlen
    lesen, nicht ein Format nachahmen. Und je kürzer der Prompt, desto
    weniger Token — bei rund 500 Token pro Aufruf kostet eine Meldung etwa
    einen Zehntelcent.
    """
    zeilen = [
        f"Strecke: {fakten.von} nach {fakten.nach}",
        f"Gefundener Preis: {fakten.preis_text}",
        f"Preislimit des Nutzers: {fakten.limit_text}",
        f"Umstiege (schlechtere Richtung): {fakten.umstiege}",
    ]

    if fakten.airline:
        zeilen.append(f"Fluggesellschaft: {fakten.airline}")
    if fakten.gepaeckstuecke is not None:
        zeilen.append(f"Inkludierte Gepäckstücke: {fakten.gepaeckstuecke}")

    if fakten.ist_bestpreis:
        zeilen.append(
            "Einordnung: Das ist der günstigste Preis, der auf dieser Strecke "
            "bisher beobachtet wurde."
        )
    elif fakten.einordnung is Einordnung.ZU_WENIG_DATEN:
        zeilen.append(
            f"Einordnung: Für einen Vergleich fehlen noch Daten (bisher "
            f"{fakten.datenpunkte} Beobachtungen). Es ist der erste Treffer "
            f"unter dem Limit. Nenne KEINEN Vergleichspreis und KEINE Prozentzahl."
        )
    elif fakten.abweichung_prozent is not None and fakten.median_text is not None:
        richtung = "unter" if fakten.abweichung_prozent < 0 else "über"
        zeilen.append(
            f"Einordnung: {abs(fakten.abweichung_prozent):.0f} Prozent {richtung} "
            f"dem üblichen Preis dieser Strecke (üblich sind etwa "
            f"{fakten.median_text}, aus {fakten.datenpunkte} Beobachtungen)."
        )

    zeilen.append("Formuliere daraus Titel und Text.")
    return "\n".join(zeilen)


def pruefe_text(erklaerung: Erklaertext, fakten: Erklaerfakten) -> str | None:
    """Die Antwort gegenlesen. Gibt den Ablehnungsgrund zurück — oder `None`.

    Drei Dinge werden geprüft, alle drei sind schon einmal irgendwo schiefgegangen:

    * **Leer.** Ein leerer Titel wäre eine Benachrichtigung ohne Kopfzeile.
    * **Zu lang.** Der Sperrbildschirm schneidet ab; ein abgeschnittener Satz
      ist schlechter als ein kurzer vollständiger.
    * **Erfundene Zahlen.** Der eigentliche Punkt (siehe Modulkopf). Jede Zahl
      im Text muss aus den Fakten stammen.
    """
    if not erklaerung.titel.strip() or not erklaerung.text.strip():
        return "leeres Feld"

    if len(erklaerung.titel) > MAX_TITEL_ZEICHEN:
        return f"Titel zu lang ({len(erklaerung.titel)} Zeichen)"
    if len(erklaerung.text) > MAX_TEXT_ZEICHEN:
        return f"Text zu lang ({len(erklaerung.text)} Zeichen)"

    erlaubt = fakten.erlaubte_zahlen
    for zahl in _zahlen_im_text(f"{erklaerung.titel} {erklaerung.text}"):
        if zahl not in erlaubt:
            return f"nicht belegte Zahl „{zahl}“"

    return None


# ---------------------------------------------------------------------------
# Der Aufruf — austauschbar, damit kein Test ins Netz geht
# ---------------------------------------------------------------------------


class Texter(Protocol):
    """Was die Melde-Logik vom Textdienst braucht — mehr nicht.

    Dasselbe Muster wie `Flugsuche` und `PushVersand`: Ein Protokoll mit genau
    einer Methode. Im Betrieb steckt `ClaudeTexter` dahinter, im Test eine
    Attrappe.
    """

    async def erklaere(self, fakten: Erklaerfakten) -> Erklaertext: ...


class ClaudeTexter:
    """Der echte Aufruf der Anthropic-API.

    Zwei Dinge sind hier absichtlich so und nicht anders:

    * **Structured Output** (`output_format=Erklaertext`) statt „bitte
      antworte in JSON". Das Modell wird an das Pydantic-Schema gebunden; es
      kommt ein fertiges Objekt zurück, kein String, den wir mit einem
      regulären Ausdruck aufbrechen müssten.
    * **Kurzes Zeitlimit.** Der Text ist Beiwerk; er darf den Prüflauf nicht
      aufhalten. Läuft die Zeit ab, greift der Baukasten — der Nutzer bekommt
      seine Nachricht ein paar Sekunden früher statt gar nicht.

    Der Schlüssel kommt aus der Umgebung (Leitplanke 2) und steht nirgends im
    Code oder im Repository.
    """

    def __init__(self, settings: Settings, http_client: object | None = None) -> None:
        from anthropic import AsyncAnthropic

        self._settings = settings
        # `http_client` ist die Naht für den Test: Damit lässt sich ein
        # `httpx.MockTransport` unterschieben und der Fehlerfall („falscher
        # Schlüssel") prüfen, ohne dass irgendetwas ins Netz geht.
        zusatz = {"http_client": http_client} if http_client is not None else {}
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.anthropic_timeout_seconds,
            max_retries=settings.anthropic_max_retries,
            **zusatz,  # type: ignore[arg-type]
        )

    async def erklaere(self, fakten: Erklaerfakten) -> Erklaertext:
        antwort = await self._client.messages.parse(
            model=self._settings.anthropic_model,
            max_tokens=self._settings.anthropic_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": baue_nutzertext(fakten)}],
            output_format=Erklaertext,
        )
        ergebnis = antwort.parsed_output
        if ergebnis is None:
            raise ValueError("Antwort ohne verwertbaren Inhalt.")
        return ergebnis

    async def aclose(self) -> None:
        await self._client.close()
