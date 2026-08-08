"""Freitext zu Suchkriterien (M11) — ohne Datenbank und **ohne Netz**.

Zwei Schwerpunkte, beide aus dem Projektplan:

* **Risiko 8.8 („Claude liefert plausible, aber falsche Struktur")** — die
  Plausibilitätsprüfung. Jeder Weg, auf dem eine Antwort falsch sein kann,
  steht hier als eigener Test.
* **Teststrategie 9.4 („Golden-Set statt exakter Textvergleich")** — deutsche
  Beispielsätze mit erwarteter Struktur. Geprüft wird nicht *der Text*, den
  Claude erzeugt, sondern was aus einer gegebenen Antwort wird.

Wichtig zum Verständnis: Das Golden-Set prüft hier die **Übersetzung**
(Kriterien → Formularfelder), nicht Claudes Sprachverständnis. Letzteres
ließe sich nur mit einem echten Schlüssel messen und kostet Geld — laut
Projektplan 9.4 gehört das ausdrücklich nicht in die normale Testreihe.
"""

from datetime import date

import httpx
import pytest

from app.config import Settings
from app.services.nlp import (
    MAX_EINGABE_ZEICHEN,
    MAX_PREIS_EURO,
    MAX_VORLAUF_TAGE,
    ClaudeAuswerter,
    NichtVerfuegbar,
    Suchkriterien,
    baue_nutzertext,
    erzeuge_entwurf,
    pruefe_kriterien,
)
from tests.attrappen import AuswerterAttrappe

HEUTE = date(2026, 8, 7)


def kriterien(**felder: object) -> Suchkriterien:
    """Eine Antwort, wie Claude sie geliefert haben könnte."""
    return Suchkriterien(**felder)  # type: ignore[arg-type]


VOLLSTAENDIG = {
    "von": "MUC",
    "nach": "LIS",
    "frueheste_hinreise": date(2026, 10, 1),
    "spaeteste_rueckreise": date(2026, 10, 31),
    "hoechstpreis_euro": 250,
}


# --- Was Claude zu sehen bekommt -------------------------------------------


def test_prompt_nennt_das_heutige_datum():
    """Ohne heutiges Datum kann kein Modell „im Oktober" auflösen.

    Es weiß dann nicht, ob gerade September oder November ist — und das ist
    die häufigste Ursache für einen Alarm im falschen Jahr.
    """
    text = baue_nutzertext("im Oktober nach Lissabon", HEUTE)

    assert "07.08.2026" in text
    assert "Freitag" in text  # für „nächstes Wochenende"
    assert "im Oktober nach Lissabon" in text


def test_prompt_verbietet_erfundene_felder():
    from app.services.nlp import SYSTEM_PROMPT

    # Zeilenumbrüche im Prompt normalisieren — geprüft wird der Inhalt.
    prompt = " ".join(SYSTEM_PROMPT.split())
    assert "Was nicht dasteht, bleibt leer" in prompt
    assert "Erfinde nichts" in prompt


# --- Golden-Set: Kriterien werden zu Formularfeldern ------------------------


def test_vollstaendiger_wunsch_fuellt_alle_pflichtfelder():
    entwurf = pruefe_kriterien(kriterien(**VOLLSTAENDIG), HEUTE)

    assert entwurf.vollstaendig
    assert entwurf.felder == {
        "origin": "MUC",
        "destination": "LIS",
        "earliest_departure_date": "2026-10-01",
        "latest_return_date": "2026-10-31",
        # Die eine Umrechnung, die der Client nicht machen soll: Euro → Cent.
        "max_price_cents": 25000,
    }


def test_reisedauer_und_zeitraum_sind_zwei_verschiedene_dinge():
    """„Im Oktober für zwei Wochen" — beides muss nebeneinander stehen."""
    entwurf = pruefe_kriterien(kriterien(**VOLLSTAENDIG, mindestens_tage=14), HEUTE)

    assert entwurf.felder["earliest_departure_date"] == "2026-10-01"
    assert entwurf.felder["min_trip_duration_days"] == 14


def test_nur_direktflug_wird_uebernommen():
    entwurf = pruefe_kriterien(kriterien(**VOLLSTAENDIG, max_umstiege=0), HEUTE)

    assert entwurf.felder["max_stops"] == 0


def test_schalter_werden_uebernommen():
    entwurf = pruefe_kriterien(
        kriterien(**VOLLSTAENDIG, gepaeck_noetig=True, keine_nachtfluege=True), HEUTE
    )

    assert entwurf.felder["include_checked_bag"] is True
    assert entwurf.felder["avoid_night_flights"] is True


def test_nicht_genannte_felder_bleiben_weg():
    """Ein leeres Feld ist eine ehrliche Antwort, kein Mangel.

    Der Client soll nichts eintragen, was der Nutzer nicht gesagt hat — sonst
    steht plötzlich „1 Reisender" da, obwohl er zu zweit fliegt.
    """
    entwurf = pruefe_kriterien(kriterien(nach="LIS"), HEUTE)

    assert entwurf.felder == {"destination": "LIS"}
    assert not entwurf.vollstaendig


def test_unvollstaendiger_entwurf_sagt_das_auch():
    entwurf = pruefe_kriterien(kriterien(nach="LIS"), HEUTE)

    assert any("Pflichtfelder" in h for h in entwurf.hinweise)


# --- Risiko 8.8: plausibel, aber falsch ------------------------------------


def test_datum_in_der_vergangenheit_wird_verworfen():
    """Der klassische Jahresfehler: „im Oktober" wird zum vergangenen Oktober.

    Er ist besonders tückisch, weil das Ergebnis völlig plausibel aussieht —
    ein gültiges Datum, nur eben zwölf Monate daneben.
    """
    entwurf = pruefe_kriterien(
        kriterien(
            **{**VOLLSTAENDIG, "frueheste_hinreise": date(2025, 10, 1)},
        ),
        HEUTE,
    )

    assert "earliest_departure_date" not in entwurf.felder
    assert "latest_return_date" not in entwurf.felder
    assert any("Vergangenheit" in h for h in entwurf.hinweise)


def test_zu_weit_in_der_zukunft_wird_verworfen():
    from datetime import timedelta

    zu_spaet = HEUTE + timedelta(days=MAX_VORLAUF_TAGE + 1)
    entwurf = pruefe_kriterien(kriterien(frueheste_hinreise=zu_spaet), HEUTE)

    assert "earliest_departure_date" not in entwurf.felder


def test_rueckreise_vor_hinreise_wird_verworfen():
    entwurf = pruefe_kriterien(
        kriterien(frueheste_hinreise=date(2026, 10, 20), spaeteste_rueckreise=date(2026, 10, 5)),
        HEUTE,
    )

    assert "earliest_departure_date" not in entwurf.felder
    assert "latest_return_date" not in entwurf.felder
    assert any("vor der Hinreise" in h for h in entwurf.hinweise)


@pytest.mark.parametrize("code", ["BAR", "Lissabon", "LI", "LISB", "12A", ""])
def test_ungueltige_flughafen_kuerzel(code: str):
    """Geprüft wird die **Form**, nicht die Existenz.

    Dass „BAR" durchgeht, ist kein Fehler des Tests, sondern eine bewusste
    Grenze: Ob es den Flughafen gibt, ließe sich nur mit einer
    Flughafentabelle beantworten. Genau deshalb bestätigt am Ende der Nutzer.
    """
    entwurf = pruefe_kriterien(kriterien(nach=code), HEUTE)

    if code == "BAR":
        assert entwurf.felder["destination"] == "BAR"  # formal gültig
    else:
        assert "destination" not in entwurf.felder


def test_kleinschreibung_wird_normalisiert():
    entwurf = pruefe_kriterien(kriterien(von=" muc "), HEUTE)

    assert entwurf.felder["origin"] == "MUC"


def test_start_gleich_ziel_laesst_das_ziel_leer():
    entwurf = pruefe_kriterien(kriterien(von="BER", nach="BER"), HEUTE)

    assert entwurf.felder["origin"] == "BER"
    assert "destination" not in entwurf.felder
    assert any("identisch" in h for h in entwurf.hinweise)


@pytest.mark.parametrize("preis", [0, -50, MAX_PREIS_EURO + 1])
def test_unplausibler_preis_wird_verworfen(preis: int):
    entwurf = pruefe_kriterien(kriterien(hoechstpreis_euro=preis), HEUTE)

    assert "max_price_cents" not in entwurf.felder
    assert any("Höchstpreis" in h for h in entwurf.hinweise)


def test_widerspruechliche_reisedauer_wird_verworfen():
    entwurf = pruefe_kriterien(kriterien(mindestens_tage=20, hoechstens_tage=5), HEUTE)

    assert "min_trip_duration_days" not in entwurf.felder
    assert "max_trip_duration_days" not in entwurf.felder


@pytest.mark.parametrize(
    ("eingang", "erwartet"), [(9, 3), (-1, 0), (2, 2)], ids=["zu_viel", "negativ", "normal"]
)
def test_umstiege_werden_gekappt_statt_verworfen(eingang: int, erwartet: int):
    """Zwei Felder werden gekappt statt weggelassen — mit Grund.

    Wer „mit 40 Leuten" schreibt, meint erkennbar eine Gruppe; neun Reisende
    sind näher an seinem Wunsch als ein leeres Feld. Bei einem *Datum* wäre
    dieselbe Logik falsch, deshalb gilt sie nur hier.
    """
    entwurf = pruefe_kriterien(kriterien(max_umstiege=eingang), HEUTE)

    assert entwurf.felder["max_stops"] == erwartet


def test_reisendenzahl_wird_gekappt():
    assert pruefe_kriterien(kriterien(reisende=40), HEUTE).felder["adults"] == 9
    assert pruefe_kriterien(kriterien(reisende=0), HEUTE).felder["adults"] == 1


# --- Der Weg drumherum -----------------------------------------------------


async def test_das_heutige_datum_wird_mitgeschickt():
    auswerter = AuswerterAttrappe(kriterien(nach="LIS"))

    await erzeuge_entwurf("nach Lissabon", auswerter, HEUTE)

    assert auswerter.anfragen == [("nach Lissabon", HEUTE)]


async def test_zu_lange_eingabe_wird_gekuerzt():
    """Nicht aus Höflichkeit, sondern gegen Kosten.

    Ohne Deckel ginge beliebig viel fremder Text an einen kostenpflichtigen
    Dienst — ein Textfeld ohne Grenze ist eine offene Rechnung.
    """
    auswerter = AuswerterAttrappe()

    await erzeuge_entwurf("x" * (MAX_EINGABE_ZEICHEN + 500), auswerter, HEUTE)

    assert len(auswerter.anfragen[0][0]) == MAX_EINGABE_ZEICHEN


async def test_leere_eingabe_erreicht_claude_gar_nicht():
    auswerter = AuswerterAttrappe()

    with pytest.raises(NichtVerfuegbar):
        await erzeuge_entwurf("   ", auswerter, HEUTE)

    assert auswerter.anfragen == []


@pytest.mark.parametrize(
    "fehler",
    [TimeoutError("weg"), ValueError("kaputtes JSON"), RuntimeError("unerwartet")],
    ids=["zeitueberschreitung", "kaputte_antwort", "unerwartet"],
)
async def test_jeder_fehler_wird_zu_nicht_verfuegbar(fehler: Exception):
    """Anders als in M10 gibt es hier **keinen Fallback** — und das ist richtig.

    Einen deutschen Satz kann ein Baukasten schreiben; einen Satz *verstehen*
    kann er nicht. Der Rückfall ist deshalb das ganz normale leere Formular:
    Die Kernfunktion bleibt vollständig erreichbar, sie kostet nur mehr Tippen.
    """
    with pytest.raises(NichtVerfuegbar):
        await erzeuge_entwurf("nach Lissabon", AuswerterAttrappe(fehler=fehler), HEUTE)


# --- Der echte Client, ohne Netz -------------------------------------------


async def test_falscher_schluessel_endet_in_nicht_verfuegbar():
    """Wie in M10: eine echte 401 der Anthropic-API, nachgestellt per MockTransport."""

    def antworte_401(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid"}},
        )

    auswerter = ClaudeAuswerter(
        Settings(anthropic_api_key="sk-ant-attrappe", anthropic_max_retries=0),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(antworte_401)),
    )

    with pytest.raises(NichtVerfuegbar):
        await erzeuge_entwurf("im Oktober nach Lissabon", auswerter, HEUTE)

    await auswerter.aclose()


async def test_client_bindet_die_antwort_an_das_schema():
    gesehen: dict[str, object] = {}

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        import json

        gesehen.update(json.loads(anfrage.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"von": "MUC", "nach": "LIS", '
                            '"frueheste_hinreise": "2026-10-01", '
                            '"spaeteste_rueckreise": "2026-10-31", '
                            '"hoechstpreis_euro": 250}'
                        ),
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 300, "output_tokens": 60},
            },
        )

    auswerter = ClaudeAuswerter(
        Settings(anthropic_api_key="sk-ant-attrappe", anthropic_max_retries=0),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(antworte)),
    )

    entwurf = await erzeuge_entwurf("im Oktober nach Lissabon, max 250 €", auswerter, HEUTE)

    assert entwurf.vollstaendig
    assert entwurf.felder["max_price_cents"] == 25000
    assert gesehen["model"] == "claude-haiku-4-5"
    assert "output_config" in gesehen or "output_format" in gesehen
    await auswerter.aclose()
