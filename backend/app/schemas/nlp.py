"""Ein- und Ausgabe der Freitext-Auswertung (M11).

Bewusst getrennt von `schemas/price_alert.py`: Ein **Entwurf** ist etwas
anderes als ein Alarm. Er darf unvollständig sein, er darf Hinweise tragen,
und aus ihm entsteht nichts, solange der Nutzer nicht auf „Alarm anlegen"
drückt (Projektplan 8.8).
"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.services.nlp import MAX_EINGABE_ZEICHEN


class EntwurfRequest(BaseModel):
    """Der Satz, den der Nutzer getippt hat."""

    text: Annotated[str, Field(min_length=3, max_length=MAX_EINGABE_ZEICHEN)] = Field(
        description="Reisewunsch in Alltagssprache, z. B. „im Oktober nach Lissabon, max 250 €“."
    )


class EntwurfResponse(BaseModel):
    """Vorschlag fürs Formular — kein Alarm.

    `felder` trägt bereits die API-Namen und -Einheiten (`max_price_cents` in
    Cent). Der Client setzt die Werte nur ein; gerechnet wird im Backend
    (Leitplanke 1).

    `hinweise` sind fertige deutsche Sätze. Sie sagen, was **nicht** übernommen
    wurde und warum — ein leeres Feld ohne Erklärung wäre für den Nutzer nicht
    von „hat er nicht erwähnt" zu unterscheiden.
    """

    felder: dict[str, object]
    hinweise: list[str]

    # Ob die fünf Pflichtfelder beisammen sind. Der Client entscheidet daran,
    # ob er „Bitte noch ergänzen" anzeigt — rechnen muss er dafür nicht.
    vollstaendig: bool
