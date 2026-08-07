"""Tests der Amadeus-Normalisierung — **ohne Netz und ohne Datenbank**.

Grundlage ist die gespeicherte Antwort in `tests/fixtures/`. Zur Herkunft
dieser Datei siehe `tests/fixtures/README.md` — sie ist nachgebaut, nicht
mitgeschnitten, solange keine Zugangsdaten vorliegen.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.amadeus import (
    AmadeusError,
    dauer_zu_minuten,
    filtere_nach_umstiegen,
    normalisiere_antwort,
    preis_zu_cent,
)

FIXTURE = Path(__file__).parent / "fixtures" / "amadeus_flight_offers_muc_bcn.json"


@pytest.fixture(scope="module")
def antwort() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- Preise ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,erwartet",
    [
        ("249.90", 24990),
        ("129.00", 12900),
        ("0.01", 1),
        ("1000", 100000),
        ("99.99", 9999),
    ],
)
def test_preis_wird_exakt_in_cent_umgerechnet(text, erwartet):
    assert preis_zu_cent(text) == erwartet


def test_preis_umrechnung_hat_keinen_fliesskomma_fehler():
    """Der eigentliche Grund für `Decimal`.

    `1.15 * 100` ergibt in Fließkomma-Arithmetik 114.99999999999999, nach
    `int()` also 114 — ein Cent zu wenig. Nicht jeder Betrag ist betroffen,
    was die Sache heimtückisch macht: `249.90` geht zufällig gut.
    """
    assert int(1.15 * 100) == 114  # so sähe der Fehler aus
    assert preis_zu_cent("1.15") == 115  # so ist es richtig


def test_unlesbarer_preis_wird_gemeldet():
    with pytest.raises(AmadeusError, match="Preis"):
        preis_zu_cent("teuer")


# --- Dauer ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,minuten",
    [
        ("PT2H10M", 130),
        ("PT14H15M", 855),
        ("PT45M", 45),
        ("PT3H", 180),
        ("P1DT2H30M", 1590),
    ],
)
def test_dauer_wird_in_minuten_umgerechnet(text, minuten):
    assert dauer_zu_minuten(text) == minuten


def test_unlesbare_dauer_wird_gemeldet():
    with pytest.raises(AmadeusError, match="Dauer"):
        dauer_zu_minuten("zwei Stunden")


# --- Ganze Antwort --------------------------------------------------------


def test_alle_angebote_werden_uebersetzt(antwort):
    angebote = normalisiere_antwort(antwort)

    assert len(angebote) == 3
    assert [a.anbieter_id for a in angebote] == ["1", "2", "3"]


def test_direktflug_wird_korrekt_uebersetzt(antwort):
    angebot = normalisiere_antwort(antwort)[0]

    assert angebot.preis_cents == 24990
    assert angebot.waehrung == "EUR"
    assert angebot.validierende_airline == "LH"
    assert angebot.buchbare_plaetze == 7
    assert angebot.inkludierte_gepaeckstuecke == 1

    assert angebot.hinflug.umstiege == 0
    assert angebot.hinflug.von == "MUC"
    assert angebot.hinflug.nach == "BCN"
    assert angebot.hinflug.dauer_minuten == 130
    # Lokale Flughafenzeit, ohne erfundene Zeitzone.
    assert angebot.hinflug.abflug_lokal == datetime(2026, 9, 6, 9, 15)
    assert angebot.hinflug.abflug_lokal.tzinfo is None

    assert angebot.ist_hin_und_rueckflug
    assert angebot.rueckflug is not None
    assert angebot.rueckflug.von == "BCN"
    assert angebot.rueckflug.ankunft_lokal == datetime(2026, 9, 13, 14, 15)


def test_umstieg_wird_als_ein_stopp_gezaehlt(antwort):
    angebot = normalisiere_antwort(antwort)[1]

    # Zwei Segmente = ein Umstieg.
    assert len(angebot.hinflug.segmente) == 2
    assert angebot.hinflug.umstiege == 1
    assert angebot.hinflug.von == "MUC"
    assert angebot.hinflug.nach == "BCN"
    assert [s.nach for s in angebot.hinflug.segmente] == ["FRA", "BCN"]
    # Rückflug ist direkt — maßgeblich ist die schlechtere Richtung.
    assert angebot.rueckflug is not None
    assert angebot.rueckflug.umstiege == 0
    assert angebot.maximale_umstiege == 1


def test_endpreis_schlaegt_zwischensumme(antwort):
    # Angebot 2 hat total 185,00 und grandTotal 189,50. Zählen muss der
    # Betrag, den der Nutzer wirklich zahlt.
    angebot = normalisiere_antwort(antwort)[1]

    assert angebot.preis_cents == 18950


def test_gepaeck_nur_als_gewicht_bleibt_unbekannt(antwort):
    # Angebot 2 nennt 23 kg statt einer Stückzahl. Daraus lässt sich keine
    # Anzahl ableiten — dann lieber "unbekannt" als geraten.
    angebot = normalisiere_antwort(antwort)[1]

    assert angebot.inkludierte_gepaeckstuecke is None


def test_null_gepaeckstuecke_ist_nicht_unbekannt(antwort):
    # Wichtige Unterscheidung: 0 ist eine Aussage, None ist keine.
    angebot = normalisiere_antwort(antwort)[2]

    assert angebot.inkludierte_gepaeckstuecke == 0


def test_rohdaten_bleiben_erhalten(antwort):
    angebot = normalisiere_antwort(antwort)[0]

    # M6 schreibt das als `flight_offers.raw_payload` weg.
    assert angebot.rohdaten["id"] == "1"
    assert angebot.rohdaten["price"]["grandTotal"] == "249.90"


# --- Filtern und Fehlerfälle ----------------------------------------------


def test_zu_viele_umstiege_werden_gefiltert(antwort):
    angebote = normalisiere_antwort(antwort)

    assert [a.anbieter_id for a in filtere_nach_umstiegen(angebote, 0)] == ["1"]
    assert [a.anbieter_id for a in filtere_nach_umstiegen(angebote, 1)] == ["1", "2"]
    assert len(filtere_nach_umstiegen(angebote, 2)) == 3


def test_kaputtes_angebot_wird_uebersprungen_statt_alles_zu_kippen(antwort):
    kaputt = {"type": "flight-offer", "id": "999", "itineraries": []}
    gemischt = {"data": [kaputt, *antwort["data"]]}

    angebote = normalisiere_antwort(gemischt)

    # Die drei gültigen kommen durch, das kaputte fehlt.
    assert [a.anbieter_id for a in angebote] == ["1", "2", "3"]


def test_leere_antwort_ergibt_leere_liste():
    assert normalisiere_antwort({"data": []}) == []
    assert normalisiere_antwort({}) == []


def test_einwegflug_hat_keinen_rueckflug(antwort):
    nur_hin = dict(antwort["data"][0])
    nur_hin["itineraries"] = nur_hin["itineraries"][:1]

    angebot = normalisiere_antwort({"data": [nur_hin]})[0]

    assert angebot.rueckflug is None
    assert angebot.ist_hin_und_rueckflug is False
    assert angebot.maximale_umstiege == 0
