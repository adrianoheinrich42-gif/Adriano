"""Strukturiertes Logging ohne personenbezogene Daten (M12).

Zwei Anforderungen aus dem Projektplan, die zusammengehören:

* **8.10 (DSGVO):** „keine E-Mails und Tokens in Logs (nur User-IDs)".
* **Checkliste:** „Logs enthalten keine E-Mail-Adressen und keine
  Device-Tokens".

## Warum eine Sperre und nicht nur Disziplin

Man *könnte* sich einfach vornehmen, keine E-Mail zu loggen. Nur reicht das
nicht: Ein `logger.exception(...)` schreibt den Text einer Ausnahme mit, und
in dem steht bei einem Datenbankfehler gern die komplette fehlgeschlagene
Anweisung — samt Adresse. Niemand hat diese Zeile geschrieben, und trotzdem
steht sie im Log.

Deshalb sitzt die Sperre im **Formatierer**, also an der letzten Stelle vor
der Ausgabe. Was dort durchgeht, ist geprüft, unabhängig davon, wer es
geschrieben hat.

## Was ersetzt wird

* **E-Mail-Adressen** → `<email>`
* **Push-Endpoints** (die URL des Push-Dienstes, sie identifiziert ein Gerät)
  → `<push-endpoint>`
* **`Bearer …`-Token** → `Bearer <token>`
* **Schlüssel, die wie Anthropic-/Amadeus-Schlüssel aussehen** → `<key>`

Nutzer-**IDs** bleiben stehen, und das ist Absicht: Ohne sie ließe sich ein
Fehlerbericht keinem Vorgang mehr zuordnen. Eine UUID allein sagt nichts über
einen Menschen — sie wird erst mit der Datenbank daneben zu einer Person.

## Warum JSON

Im Betrieb liest kein Mensch Logs zeilenweise, sondern sucht darin. Ein
Hoster (Render, Railway) und ein Fehlerdienst wie Sentry können JSON-Zeilen
filtern; bei Fließtext bliebe nur Volltextsuche. Lokal ist Fließtext
angenehmer, deshalb entscheidet `LOG_FORMAT` — Standard ist der lesbare.
"""

import json
import logging
import re
import sys
from typing import Any

# Die Muster sind absichtlich großzügig. Ein zu breites Muster schwärzt
# gelegentlich etwas Harmloses; ein zu enges lässt eine Adresse durch. Der
# erste Fehler ist der bessere.
MUSTER: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    # Push-Endpoints identifizieren ein Gerät so eindeutig wie ein Token.
    (re.compile(r"https://[\w.-]*(?:push|fcm|notify)[\w.-]*\.[\w.]+/\S+"), "<push-endpoint>"),
    (re.compile(r"[Bb]earer\s+[\w\-.]+"), "Bearer <token>"),
    (re.compile(r"sk-ant-[\w\-]+"), "<key>"),
    # Der VAPID-Privatschlüssel und Amadeus-Geheimnisse sind lange
    # base64url-Ketten. Ab 40 Zeichen ohne Leerzeichen ist das kein Wort mehr.
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "<key>"),
)


def entferne_personenbezug(text: str) -> str:
    """Die eigentliche Sperre — als reine Funktion, damit sie testbar ist.

    Wird auf **jede** Logzeile angewandt, auch auf Ausnahmetexte. Sie ist die
    letzte Stelle vor der Ausgabe.
    """
    for muster, ersatz in MUSTER:
        text = muster.sub(ersatz, text)
    return text


class SauberFormatter(logging.Formatter):
    """Lesbarer Fließtext — aber durch die Sperre."""

    def format(self, record: logging.LogRecord) -> str:
        return entferne_personenbezug(super().format(record))


class JsonFormatter(logging.Formatter):
    """Eine JSON-Zeile je Ereignis, ebenfalls durch die Sperre.

    Bewusst ohne Zusatzpaket: Es sind zwölf Zeilen, und `structlog` oder
    `python-json-logger` wären eine weitere Abhängigkeit für genau das hier.
    """

    def format(self, record: logging.LogRecord) -> str:
        eintrag: dict[str, Any] = {
            "zeit": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "stufe": record.levelname,
            "quelle": record.name,
            "text": entferne_personenbezug(record.getMessage()),
        }
        if record.exc_info:
            eintrag["ausnahme"] = entferne_personenbezug(self.formatException(record.exc_info))

        # `ensure_ascii=False`: Deutsche Umlaute sollen im Log lesbar sein,
        # nicht als ä.
        return json.dumps(eintrag, ensure_ascii=False)


def richte_logging_ein(format_name: str = "text", stufe: str = "INFO") -> None:
    """Einmal beim Start aufrufen — API und Worker gleichermaßen.

    Ersetzt die Handler des Wurzel-Loggers **vollständig**. Sonst liefe neben
    dem geprüften Formatierer noch der von `logging.basicConfig()`, und die
    Sperre hätte ein Loch, durch das alles doppelt und ungefiltert liefe.
    """
    formatierer: logging.Formatter = (
        JsonFormatter()
        if format_name == "json"
        else SauberFormatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatierer)

    wurzel = logging.getLogger()
    wurzel.handlers = [handler]
    wurzel.setLevel(stufe.upper())

    # uvicorn bringt eigene Handler mit und würde sonst zusätzlich und
    # ungefiltert schreiben. `propagate` schickt seine Zeilen stattdessen
    # durch unseren Formatierer.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.handlers = []
        log.propagate = True
