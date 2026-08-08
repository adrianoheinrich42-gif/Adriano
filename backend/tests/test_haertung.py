"""Rate Limiting und Logging ohne personenbezogene Daten (M12).

Ohne Datenbank, ohne Netz — beides sind reine Funktionen.

Der Logging-Teil ist der wichtigere. Eine E-Mail-Adresse im Log ist kein
Absturz und kein roter Test; sie fällt niemandem auf, bis jemand die Logs
liest. Genau solche Fehler brauchen einen Test, der sie *behauptet*.
"""

import logging
import time

import pytest

from app.core.logging import (
    JsonFormatter,
    SauberFormatter,
    entferne_personenbezug,
    richte_logging_ein,
)
from app.core.ratelimit import Zaehler, _lesbar

# --- Rate Limiting ---------------------------------------------------------


def test_bis_zur_grenze_ist_alles_erlaubt():
    zaehler = Zaehler(grenze=3, fenster_sekunden=60)

    assert [zaehler.darf("a", jetzt=100) for _ in range(3)] == [True, True, True]


def test_ueber_der_grenze_wird_abgelehnt():
    zaehler = Zaehler(grenze=2, fenster_sekunden=60)
    zaehler.darf("a", jetzt=100)
    zaehler.darf("a", jetzt=100)

    assert zaehler.darf("a", jetzt=100) is False


def test_abgelehnte_versuche_verlaengern_das_fenster_nicht():
    """Sonst käme niemand mehr frei, der einmal übertrieben hat.

    Würde jeder abgelehnte Aufruf mitgezählt, schöbe ein Skript in der
    Schleife das Fenster endlos vor sich her — und der Nutzer wäre praktisch
    dauerhaft gesperrt, obwohl er längst aufgehört hat.
    """
    zaehler = Zaehler(grenze=1, fenster_sekunden=10)
    zaehler.darf("a", jetzt=100)

    for versuch in range(5):
        assert zaehler.darf("a", jetzt=101 + versuch) is False

    # Genau 10 Sekunden nach dem **ersten** Versuch ist wieder frei.
    assert zaehler.darf("a", jetzt=111) is True


def test_das_fenster_gleitet():
    zaehler = Zaehler(grenze=2, fenster_sekunden=10)
    zaehler.darf("a", jetzt=100)
    zaehler.darf("a", jetzt=105)

    assert zaehler.darf("a", jetzt=109) is False
    # Der erste Treffer ist jetzt älter als 10 Sekunden und fällt heraus.
    assert zaehler.darf("a", jetzt=111) is True


def test_jeder_schluessel_zaehlt_fuer_sich():
    """Ein Vielnutzer darf keinen anderen aussperren."""
    zaehler = Zaehler(grenze=1, fenster_sekunden=60)
    zaehler.darf("nutzer-a", jetzt=100)

    assert zaehler.darf("nutzer-b", jetzt=100) is True


def test_wartezeit_zeigt_auf_den_aeltesten_treffer():
    zaehler = Zaehler(grenze=1, fenster_sekunden=60)
    zaehler.darf("a", jetzt=100)

    # 60 - 10 = 50 Sekunden Rest, aufgerundet.
    assert zaehler.wartezeit_sekunden("a", jetzt=110) == 51


def test_wartezeit_ohne_treffer_ist_null():
    assert Zaehler(grenze=1, fenster_sekunden=60).wartezeit_sekunden("unbekannt") == 0


def test_aufraeumen_entfernt_abgelaufene_schluessel():
    """Sonst wächst der Speicher mit der Zahl der Nutzer, nicht mit der Last."""
    zaehler = Zaehler(grenze=5, fenster_sekunden=10)
    zaehler.darf("alt", jetzt=100)
    zaehler.darf("neu", jetzt=200)

    entfernt = zaehler.aufraeumen(jetzt=205)

    assert entfernt == 1
    assert zaehler.darf("neu", jetzt=205) is True


def test_echte_zeit_funktioniert_auch():
    """Ohne `jetzt` nimmt der Zähler die Uhr — der Betriebsfall."""
    zaehler = Zaehler(grenze=1, fenster_sekunden=60)

    assert zaehler.darf("a") is True
    assert zaehler.darf("a") is False
    assert zaehler.wartezeit_sekunden("a") > 0
    assert time.monotonic() > 0  # nur zur Sicherheit: die Uhr läuft


@pytest.mark.parametrize(
    ("sekunden", "erwartet"),
    [(5, "5 Sekunden"), (60, "eine Minute"), (90, "2 Minuten"), (3600, "eine Stunde")],
)
def test_wartezeit_wird_lesbar_formuliert(sekunden: int, erwartet: str):
    """Niemand rechnet gern 3600 Sekunden in Stunden um."""
    assert _lesbar(sekunden) == erwartet


# --- Logging ohne personenbezogene Daten -----------------------------------


def test_email_wird_geschwaerzt():
    text = entferne_personenbezug("Nutzer max.mustermann+test@beispiel.de angelegt")

    assert "beispiel.de" not in text
    assert "<email>" in text


def test_push_endpoint_wird_geschwaerzt():
    """Ein Push-Endpoint identifiziert ein Gerät so eindeutig wie ein Token."""
    text = entferne_personenbezug(
        "Versand an https://fcm.googleapis.com/fcm/send/abc123XYZ fehlgeschlagen"
    )

    assert "abc123XYZ" not in text
    assert "<push-endpoint>" in text


def test_bearer_token_wird_geschwaerzt():
    text = entferne_personenbezug("Kopf: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6")

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6" not in text
    assert "Bearer <token>" in text


def test_anthropic_schluessel_wird_geschwaerzt():
    text = entferne_personenbezug("Aufruf mit sk-ant-api03-GEHEIM-XYZ gescheitert")

    assert "GEHEIM" not in text


def test_nutzer_id_bleibt_stehen():
    """Ohne sie ließe sich ein Fehlerbericht keinem Vorgang mehr zuordnen.

    Eine UUID allein sagt nichts über einen Menschen — sie wird erst mit der
    Datenbank daneben zu einer Person. Genau deshalb steht in
    `docs/PROJEKTPLAN.md` 8.10 „nur User-IDs".
    """
    kennung = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    assert kennung in entferne_personenbezug(f"Alarm von Nutzer {kennung} geprüft")


def test_normaler_text_bleibt_unveraendert():
    """Die Muster sind breit — sie dürfen trotzdem keine Logzeile zerlegen."""
    text = "Prüflauf fertig: 3 Alarme geprüft, 2 erfolgreich, 5 Angebote gespeichert."

    assert entferne_personenbezug(text) == text


def test_die_sperre_greift_auch_im_ausnahmetext():
    """Der eigentliche Grund, warum die Sperre im Formatierer sitzt.

    Diese Zeile hat niemand geschrieben: Der Text stammt aus der Ausnahme,
    und die kann alles Mögliche enthalten. Disziplin beim Loggen hilft hier
    nicht — der Formatierer ist die letzte Stelle vor der Ausgabe.
    """
    formatierer = SauberFormatter("%(message)s")
    try:
        raise ValueError("INSERT INTO users (email) VALUES ('geheim@beispiel.de')")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "test", logging.ERROR, "x", 1, "Fehler beim Anlegen", None, sys.exc_info()
        )

    ausgabe = formatierer.format(record)

    assert "geheim@beispiel.de" not in ausgabe
    assert "<email>" in ausgabe


def test_json_formatierer_erzeugt_eine_lesbare_zeile():
    import json

    record = logging.LogRecord(
        "app.test", logging.INFO, "x", 1, "Alarm für %s geprüft", ("küste@beispiel.de",), None
    )

    eintrag = json.loads(JsonFormatter().format(record))

    assert eintrag["stufe"] == "INFO"
    assert eintrag["quelle"] == "app.test"
    assert "<email>" in eintrag["text"]
    assert "beispiel.de" not in eintrag["text"]


def test_einrichten_ersetzt_bestehende_handler():
    """Sonst liefe ein ungefilterter Handler daneben weiter — ein Loch in der Sperre."""
    wurzel = logging.getLogger()
    alte_handler = wurzel.handlers[:]
    alte_stufe = wurzel.level
    try:
        wurzel.addHandler(logging.StreamHandler())
        richte_logging_ein("json", "WARNING")

        assert len(wurzel.handlers) == 1
        assert isinstance(wurzel.handlers[0].formatter, JsonFormatter)
        assert wurzel.level == logging.WARNING
    finally:
        wurzel.handlers = alte_handler
        wurzel.setLevel(alte_stufe)
