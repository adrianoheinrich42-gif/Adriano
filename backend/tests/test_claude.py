"""Der Claude-Texter (M10) — ohne Datenbank und **ohne Netz**.

Der wichtigste Teil ist nicht der Erfolgsfall. Es ist die Zusicherung aus
Leitplanke 3: *Fällt Claude aus, funktioniert die Kernfunktion per Fallback
weiter.* Ein Versprechen, das nicht getestet ist, ist keins — deshalb steht
hier jeder Weg, auf dem der Aufruf schiefgehen kann, einzeln als Test.

Der zweite Schwerpunkt ist `pruefe_text()`: Structured Output garantiert die
Form der Antwort, nicht ihre Richtigkeit. Eine erfundene Prozentzahl in einer
Push-Nachricht sieht aus wie eine Tatsache.

Für den echten `ClaudeTexter` wird ein `httpx.MockTransport` untergeschoben.
Damit ist auch der Fall „falscher API-Schlüssel" geprüft, den der Projektplan
als Abnahmekriterium für M10 nennt — und trotzdem geht kein Test ins Netz.
"""

import httpx
import pytest

from app.config import Settings
from app.services.claude import (
    MAX_TEXT_ZEICHEN,
    MAX_TITEL_ZEICHEN,
    ClaudeTexter,
    Erklaerfakten,
    Erklaertext,
    baue_fakten,
    baue_nutzertext,
    pruefe_text,
)
from app.services.price_stats import Einordnung, Preisbewertung
from app.services.push import (
    QUELLE_BAUKASTEN,
    QUELLE_CLAUDE,
    erzeuge_nachricht,
    formuliere_einordnungssatz,
    formuliere_nachricht,
)
from tests.attrappen import TexterAttrappe, baue_alarm, baue_angebot

GUENSTIG = Preisbewertung(
    preis_cents=18950,
    einordnung=Einordnung.GUENSTIG,
    datenpunkte=24,
    median_cents=25000,
    minimum_cents=17000,
    abweichung_prozent=-24.2,
)

ZU_WENIG = Preisbewertung(
    preis_cents=18950,
    einordnung=Einordnung.ZU_WENIG_DATEN,
    datenpunkte=3,
)


def fakten_guenstig() -> Erklaerfakten:
    return baue_fakten(baue_alarm(), baue_angebot(preis_cents=18950), GUENSTIG)


# --- Was Claude zu sehen bekommt -------------------------------------------


def test_fakten_enthalten_die_berechneten_zahlen():
    fakten = fakten_guenstig()

    assert fakten.von == "MUC"
    assert fakten.nach == "BCN"
    assert fakten.preis_text == "189,50 €"
    assert fakten.limit_text == "250,00 €"
    assert fakten.median_text == "250,00 €"
    assert fakten.abweichung_prozent == -24.2


def test_fakten_enthalten_keine_nutzerdaten():
    """Ein Sprachmodell braucht für „schreib einen netten Satz" keine IDs.

    Der Test hängt an den Feldnamen des Datenklassen-Objekts: Wer später eine
    `user_id` oder E-Mail hineinreicht, bringt ihn zum Scheitern.
    """
    fakten = fakten_guenstig()
    verboten = {"user_id", "email", "alarm_id", "id"}

    assert verboten.isdisjoint(vars(fakten).keys())


def test_prompt_nennt_bei_zu_wenig_daten_keinen_vergleichspreis():
    """Der heikelste Fall: Ohne Datenbasis darf keine Prozentzahl entstehen.

    Der Prompt muss das ausdrücklich verbieten — sonst füllt ein Sprachmodell
    die Lücke bereitwillig mit einer plausiblen Zahl.
    """
    fakten = baue_fakten(baue_alarm(), baue_angebot(preis_cents=18950), ZU_WENIG)

    text = baue_nutzertext(fakten)

    assert "KEINE Prozentzahl" in text
    assert "250,00 €" in text  # das Limit darf genannt werden
    assert "Median" not in text


def test_prompt_nennt_median_und_abweichung_wenn_es_sie_gibt():
    text = baue_nutzertext(fakten_guenstig())

    assert "24 Prozent unter" in text
    assert "250,00 €" in text
    assert "24 Beobachtungen" in text


# --- Die Nachprüfung der Antwort -------------------------------------------


def test_guter_text_wird_angenommen():
    fakten = fakten_guenstig()
    erklaerung = Erklaertext(
        titel="MUC → BCN für 189,50 €",
        text="24 % unter dem üblichen Preis von 250 € — ein guter Moment zum Buchen.",
    )

    assert pruefe_text(erklaerung, fakten) is None


def test_erfundene_zahl_wird_verworfen():
    """Der eigentliche Grund für die Nachprüfung.

    „33 %" steht in keiner Faktenzeile. Ein Sprachmodell, das sich beim
    Umformulieren verrechnet, würde sonst eine falsche Zahl in eine Nachricht
    schreiben, die wie eine Tatsache aussieht.
    """
    fakten = fakten_guenstig()
    erklaerung = Erklaertext(titel="MUC → BCN für 189,50 €", text="Ganze 33 % günstiger als sonst.")

    grund = pruefe_text(erklaerung, fakten)

    assert grund is not None
    assert "33" in grund


def test_gerundete_zahlen_sind_erlaubt():
    """„189,50 €" darf als „190 €" geschrieben werden — das ist kein Erfinden."""
    fakten = fakten_guenstig()
    erklaerung = Erklaertext(titel="MUC → BCN für 190 €", text="Rund 24 % unter dem Üblichen.")

    assert pruefe_text(erklaerung, fakten) is None


def test_abweichung_darf_auf_oder_abgerundet_werden():
    """−24,2 % darf „24 %" oder „25 %" heißen, aber nicht „30 %"."""
    fakten = fakten_guenstig()

    assert pruefe_text(Erklaertext(titel="A", text="24 % billiger."), fakten) is None
    assert pruefe_text(Erklaertext(titel="A", text="25 % billiger."), fakten) is None
    assert pruefe_text(Erklaertext(titel="A", text="30 % billiger."), fakten) is not None


def test_zu_langer_text_wird_verworfen():
    fakten = fakten_guenstig()
    erklaerung = Erklaertext(titel="MUC → BCN", text="x" * (MAX_TEXT_ZEICHEN + 1))

    assert pruefe_text(erklaerung, fakten) is not None


def test_zu_langer_titel_wird_verworfen():
    fakten = fakten_guenstig()
    erklaerung = Erklaertext(titel="x" * (MAX_TITEL_ZEICHEN + 1), text="Kurz.")

    assert pruefe_text(erklaerung, fakten) is not None


def test_leerer_titel_wird_verworfen():
    assert pruefe_text(Erklaertext(titel="   ", text="Kurz."), fakten_guenstig()) is not None


# --- Der Rückfall auf den Baukasten ----------------------------------------


async def test_ohne_texter_formuliert_der_baukasten():
    alarm, angebot = baue_alarm(), baue_angebot(preis_cents=18950)

    nachricht, quelle = await erzeuge_nachricht(alarm, angebot, GUENSTIG, None)

    assert quelle == QUELLE_BAUKASTEN
    assert nachricht == formuliere_nachricht(alarm, angebot, GUENSTIG)


async def test_claude_text_wird_uebernommen():
    alarm, angebot = baue_alarm(), baue_angebot(preis_cents=18950)
    texter = TexterAttrappe(
        Erklaertext(titel="MUC → BCN für 189,50 €", text="24 % unter dem üblichen Preis.")
    )

    nachricht, quelle = await erzeuge_nachricht(alarm, angebot, GUENSTIG, texter)

    assert quelle == QUELLE_CLAUDE
    assert nachricht.text == "24 % unter dem üblichen Preis."
    # Die Ziel-Adresse ist Technik, kein Text — die kommt immer vom Baukasten.
    assert nachricht.url == f"/#alarm={alarm.id}"


@pytest.mark.parametrize(
    "fehler",
    [
        TimeoutError("Zeitüberschreitung"),
        ValueError("Antwort ohne verwertbaren Inhalt."),
        RuntimeError("irgendetwas Unerwartetes"),
    ],
    ids=["zeitueberschreitung", "leere_antwort", "unerwartet"],
)
async def test_jeder_fehler_endet_im_baukasten(fehler: Exception):
    """Leitplanke 3, als Test: Die Nachricht geht raus, egal was passiert."""
    alarm, angebot = baue_alarm(), baue_angebot(preis_cents=18950)
    texter = TexterAttrappe(fehler=fehler)

    nachricht, quelle = await erzeuge_nachricht(alarm, angebot, GUENSTIG, texter)

    assert quelle == QUELLE_BAUKASTEN
    assert nachricht == formuliere_nachricht(alarm, angebot, GUENSTIG)


async def test_unbelegte_zahl_fuehrt_zum_baukasten():
    """Ein antwortender, aber rechnender Claude ist gefährlicher als ein toter."""
    alarm, angebot = baue_alarm(), baue_angebot(preis_cents=18950)
    texter = TexterAttrappe(Erklaertext(titel="Super Deal", text="Spare 77 % gegenüber sonst!"))

    nachricht, quelle = await erzeuge_nachricht(alarm, angebot, GUENSTIG, texter)

    assert quelle == QUELLE_BAUKASTEN
    assert "77" not in nachricht.text


# --- Der echte Client, ohne Netz -------------------------------------------


def texter_mit_antwort(handler: object) -> ClaudeTexter:
    """Ein echter `ClaudeTexter`, dessen HTTP-Schicht ins Leere greift."""
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    settings = Settings(anthropic_api_key="sk-ant-attrappe", anthropic_max_retries=0)
    return ClaudeTexter(settings, http_client=httpx.AsyncClient(transport=transport))


async def test_falscher_schluessel_stoppt_die_benachrichtigung_nicht():
    """Das Abnahmekriterium aus dem Projektplan für M10.

    „API-Key absichtlich falsch → App funktioniert weiter." Hier mit einer
    echten 401-Antwort der Anthropic-API — nachgestellt per `MockTransport`,
    also ohne einen einzigen Netzwerkzugriff.
    """

    def antworte_401(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid"}},
        )

    alarm, angebot = baue_alarm(), baue_angebot(preis_cents=18950)
    texter = texter_mit_antwort(antworte_401)

    nachricht, quelle = await erzeuge_nachricht(alarm, angebot, GUENSTIG, texter)

    assert quelle == QUELLE_BAUKASTEN
    assert nachricht == formuliere_nachricht(alarm, angebot, GUENSTIG)
    await texter.aclose()


async def test_client_schickt_modell_und_schema_mit():
    """Belegt, dass wirklich Structured Output benutzt wird, kein „bitte JSON"."""
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
                            '{"titel": "MUC → BCN für 189,50 €", '
                            '"text": "24 % unter dem üblichen Preis."}'
                        ),
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 200, "output_tokens": 40},
            },
        )

    texter = texter_mit_antwort(antworte)

    erklaerung = await texter.erklaere(fakten_guenstig())

    assert erklaerung.titel == "MUC → BCN für 189,50 €"
    assert gesehen["model"] == "claude-haiku-4-5"
    # Das Schema wird mitgeschickt — daran hängt die Formgarantie.
    assert "output_config" in gesehen or "output_format" in gesehen
    assert "Verwende AUSSCHLIESSLICH die Zahlen" in str(gesehen["system"])
    await texter.aclose()


# --- Der Baukasten für die Detailansicht -----------------------------------


def test_einordnungssatz_ohne_datenlage_nennt_keine_prozente():
    satz = formuliere_einordnungssatz(ZU_WENIG)

    assert "3 Beobachtungen" in satz
    assert "%" not in satz


def test_einordnungssatz_bestpreis_geht_vor():
    """Ein Bestpreis ist die stärkere Aussage als „günstig"."""
    bestpreis = Preisbewertung(
        preis_cents=16000,
        einordnung=Einordnung.GUENSTIG,
        datenpunkte=24,
        median_cents=25000,
        minimum_cents=17000,
        abweichung_prozent=-36.0,
    )

    assert "Günstigster Preis" in formuliere_einordnungssatz(bestpreis)


def test_einordnungssatz_guenstig_nennt_median_und_abweichung():
    satz = formuliere_einordnungssatz(GUENSTIG)

    assert "24 %" in satz
    assert "250,00 €" in satz
