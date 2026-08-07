"""Die Melde-Logik (M8) — reine Funktionen, ohne Datenbank und ohne Netz.

Die drei Bremsen gegen Nachrichten-Spam sind der Inhalt dieser Datei. Zwei
davon (Abkühlphase, 5-%-Regel) stehen hier; die dritte — Dedupe — ist eine
Datenbank-Garantie und deshalb in `tests/integration/test_push.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.services.price_stats import Einordnung, Preisbewertung
from app.services.push import (
    LetzteMeldung,
    Nachricht,
    PushFehler,
    bilde_dedupe_key,
    darf_melden,
    formuliere_nachricht,
)
from tests.attrappen import baue_alarm, baue_angebot

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
ABKUEHLPHASE = 6
MINDEST_VERBESSERUNG = 5.0


def melden(preis_cents: int, letzte: LetzteMeldung | None, jetzt: datetime = JETZT) -> bool:
    return darf_melden(preis_cents, letzte, jetzt, ABKUEHLPHASE, MINDEST_VERBESSERUNG)


def bewertung(
    einordnung: Einordnung = Einordnung.GUENSTIG,
    preis_cents: int = 18000,
    median_cents: int | None = 24000,
    abweichung: float | None = -25.0,
    minimum_cents: int | None = 17000,
) -> Preisbewertung:
    return Preisbewertung(
        preis_cents=preis_cents,
        einordnung=einordnung,
        datenpunkte=0 if einordnung is Einordnung.ZU_WENIG_DATEN else 12,
        median_cents=median_cents,
        minimum_cents=minimum_cents,
        abweichung_prozent=abweichung,
    )


# --- Dedupe-Schlüssel -------------------------------------------------------


def test_dedupe_key_ist_64_zeichen_lang():
    """Sonst passt er nicht in `notification_logs.dedupe_key` (String(64))."""
    assert len(bilde_dedupe_key(uuid.uuid4(), "a" * 64)) == 64


def test_gleicher_alarm_und_angebot_ergibt_denselben_schluessel():
    alarm_id = uuid.uuid4()

    assert bilde_dedupe_key(alarm_id, "hash-a") == bilde_dedupe_key(alarm_id, "hash-a")


def test_anderes_angebot_ergibt_anderen_schluessel():
    alarm_id = uuid.uuid4()

    assert bilde_dedupe_key(alarm_id, "hash-a") != bilde_dedupe_key(alarm_id, "hash-b")


def test_zwei_nutzer_bekommen_beide_ihre_meldung():
    """Der Schlüssel enthält den Alarm, nicht nur das Angebot.

    Sonst würde die Meldung an den zweiten Nutzer als „schon gemeldet"
    verworfen, nur weil ein Fremder denselben Flug beobachtet.
    """
    assert bilde_dedupe_key(uuid.uuid4(), "hash-a") != bilde_dedupe_key(uuid.uuid4(), "hash-a")


# --- Abkühlphase und 5-%-Regel ---------------------------------------------


def test_erste_meldung_geht_immer_raus():
    assert melden(20000, None) is True


def test_nach_der_abkuehlphase_darf_wieder_gemeldet_werden():
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=ABKUEHLPHASE), price_cents=20000)

    assert melden(20000, letzte) is True


def test_innerhalb_der_abkuehlphase_bleibt_es_still():
    """Der eigentliche Zweck: nicht alle sechs Stunden dieselbe Nachricht."""
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=1), price_cents=20000)

    assert melden(19900, letzte) is False


def test_deutlich_besserer_preis_durchbricht_die_abkuehlphase():
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=1), price_cents=20000)

    assert melden(18000, letzte) is True  # −10 %


def test_genau_fuenf_prozent_besser_reicht():
    """Die Schwelle ist inklusiv — sonst fiele der Grenzfall stillschweigend weg."""
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=1), price_cents=20000)

    assert melden(19000, letzte) is True


def test_knapp_unter_fuenf_prozent_reicht_nicht():
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=1), price_cents=20000)

    assert melden(19100, letzte) is False  # −4,5 %


def test_teurer_gewordener_preis_meldet_nicht_erneut():
    letzte = LetzteMeldung(sent_at=JETZT - timedelta(hours=1), price_cents=20000)

    assert melden(21000, letzte) is False


def test_naive_zeit_aus_der_datenbank_bricht_nicht():
    """`timestamptz` sollte nie naiv ankommen — aber Testdaten und die
    SQL-Konsole können es. Dann als UTC lesen statt aussteigen."""
    letzte = LetzteMeldung(sent_at=datetime(2026, 8, 7, 11, 0), price_cents=20000)

    assert melden(19900, letzte) is False


# --- Der Textbaukasten ------------------------------------------------------


def test_titel_nennt_strecke_und_preis():
    nachricht = formuliere_nachricht(
        baue_alarm(origin="MUC", destination="BCN"),
        baue_angebot(preis_cents=18900),
        bewertung(),
    )

    assert nachricht.titel == "MUC → BCN für 189,00 €"


def test_guenstiges_angebot_nennt_die_prozentzahl():
    nachricht = formuliere_nachricht(
        baue_alarm(), baue_angebot(preis_cents=18000), bewertung(abweichung=-25.0)
    )

    assert "25 % unter dem üblichen Preis" in nachricht.text


def test_ohne_genug_daten_wird_keine_prozentzahl_erfunden():
    """Die wichtigste Regel aus M7 muss bis in den Nachrichtentext durchhalten."""
    nachricht = formuliere_nachricht(
        baue_alarm(max_price_cents=20000),
        baue_angebot(preis_cents=18000),
        bewertung(
            einordnung=Einordnung.ZU_WENIG_DATEN,
            median_cents=None,
            abweichung=None,
            minimum_cents=None,
        ),
    )

    assert "erster Treffer unter deinem Limit von 200,00 €" in nachricht.text
    assert "%" not in nachricht.text


def test_bestpreis_wird_hervorgehoben():
    nachricht = formuliere_nachricht(
        baue_alarm(),
        baue_angebot(preis_cents=16000),
        bewertung(preis_cents=16000, minimum_cents=17000),
    )

    assert "günstigster Preis" in nachricht.text


def test_teures_angebot_unter_dem_limit_wird_ehrlich_benannt():
    """Unter dem Limit, aber über dem Median — das darf man nicht verschweigen."""
    nachricht = formuliere_nachricht(
        baue_alarm(),
        baue_angebot(preis_cents=26000),
        bewertung(
            einordnung=Einordnung.TEUER,
            preis_cents=26000,
            abweichung=12.0,
            minimum_cents=17000,
        ),
    )

    assert "unter deinem Limit" in nachricht.text
    assert "12 % über dem üblichen Preis" in nachricht.text


def test_normaler_preis_bekommt_einen_nuechternen_satz():
    nachricht = formuliere_nachricht(
        baue_alarm(),
        baue_angebot(preis_cents=24000),
        bewertung(
            einordnung=Einordnung.NORMAL, preis_cents=24000, abweichung=1.0, minimum_cents=17000
        ),
    )

    assert "im üblichen Rahmen" in nachricht.text


def test_umstiege_und_airline_stehen_im_text():
    nachricht = formuliere_nachricht(baue_alarm(), baue_angebot(airline="LH"), bewertung())

    assert "LH" in nachricht.text
    assert "Umstieg" in nachricht.text or "Direktflug" in nachricht.text


def test_nachricht_wird_als_json_verpackt():
    """Der Service Worker im Browser liest genau diese drei Felder."""
    import json

    roh = json.loads(Nachricht(titel="Titel", text="Text", url="/x").als_json())

    assert roh == {"titel": "Titel", "text": "Text", "url": "/x"}


def test_umlaute_bleiben_im_json_lesbar():
    roh = Nachricht(titel="München → Zürich", text="günstig").als_json()

    assert "München" in roh


# --- Fehlerbewertung --------------------------------------------------------


def test_410_bedeutet_ziel_ist_tot():
    """Erlaubnis entzogen oder App entfernt — nie wieder senden."""
    assert PushFehler("weg", status_code=410).ziel_ist_tot is True


def test_404_bedeutet_ziel_ist_tot():
    assert PushFehler("weg", status_code=404).ziel_ist_tot is True


def test_503_ist_nur_voruebergehend():
    """Der Push-Dienst hat gerade Schluckauf — das Ziel bleibt gültig."""
    assert PushFehler("später", status_code=503).ziel_ist_tot is False


def test_netzfehler_ohne_statuscode_legt_kein_ziel_still():
    assert PushFehler("Zeitüberschreitung").ziel_ist_tot is False
