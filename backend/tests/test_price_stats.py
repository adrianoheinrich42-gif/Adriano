"""Die Preisstatistik (M7) — reine Funktionen, ohne Datenbank.

Der wichtigste Test hier ist `test_zu_wenig_daten_ergibt_keine_prozentaussage`.
Alles andere ist Rechnen; das ist die Stelle, an der die Anwendung ehrlich
bleibt statt Scheingenauigkeit zu liefern.
"""

import pytest

from app.services.price_stats import (
    GUENSTIG_AB_PROZENT,
    MINDEST_DATENPUNKTE,
    TEUER_AB_PROZENT,
    Einordnung,
    abweichung_prozent,
    bewerte_preis,
    median_cents,
)


def preise(anzahl: int, wert: int = 20000) -> list[int]:
    """`anzahl` gleiche Preise — genug Datenpunkte, damit eine Aussage entsteht."""
    return [wert] * anzahl


GENUG = MINDEST_DATENPUNKTE


# --- Median ----------------------------------------------------------------


def test_median_bei_ungerader_anzahl_ist_der_mittlere_wert():
    assert median_cents([19000, 20000, 21000]) == 20000


def test_median_bei_gerader_anzahl_mittelt_die_beiden_mittleren():
    assert median_cents([19000, 20000, 21000, 22000]) == 20500


def test_median_rundet_kaufmaennisch():
    """`round()` rundet in Python zur geraden Zahl — deshalb Decimal."""
    assert median_cents([20000, 20001]) == 20001


def test_median_braucht_keine_sortierte_eingabe():
    assert median_cents([21000, 19000, 20000]) == 20000


def test_median_eines_einzelnen_preises_ist_dieser_preis():
    assert median_cents([18950]) == 18950


def test_median_einer_leeren_liste_ist_ein_fehler():
    """Lieber laut scheitern als still eine 0 liefern, die wie ein Preis aussieht."""
    with pytest.raises(ValueError):
        median_cents([])


def test_median_ist_unempfindlich_gegen_ausreisser():
    """Der Grund, warum es Median heißt und nicht Durchschnitt.

    Ein einziger absurder Preis (Business-Class-Tarif, Fehler bei Amadeus)
    würde den Durchschnitt auf über 55 000 Cent ziehen.
    """
    mit_ausreisser = [19000, 19500, 20000, 20500, 200000]

    assert median_cents(mit_ausreisser) == 20000


# --- Abweichung ------------------------------------------------------------


def test_abweichung_nach_unten_ist_negativ():
    assert abweichung_prozent(18000, 20000) == -10.0


def test_abweichung_nach_oben_ist_positiv():
    assert abweichung_prozent(22000, 20000) == 10.0


def test_gleicher_preis_weicht_nicht_ab():
    assert abweichung_prozent(20000, 20000) == 0.0


def test_abweichung_wird_auf_eine_nachkommastelle_gerundet():
    """Mehr wäre Scheingenauigkeit bei stündlich wechselnden Preisen."""
    # 20123 / 20000 → +0,615 %
    assert abweichung_prozent(20123, 20000) == 0.6


def test_abweichung_gegen_null_ist_ein_fehler():
    with pytest.raises(ValueError):
        abweichung_prozent(20000, 0)


# --- Einordnung ------------------------------------------------------------


def test_zu_wenig_daten_ergibt_keine_prozentaussage():
    """**Die wichtigste Regel des Moduls.**

    Ein Median aus wenigen Werten sieht aus wie eine Aussage, ist aber
    geraten. Dann gibt es weder Median noch Prozentzahl — die App sagt
    stattdessen „erster Treffer unter deinem Limit".
    """
    bewertung = bewerte_preis(18000, preise(MINDEST_DATENPUNKTE - 1))

    assert bewertung.einordnung is Einordnung.ZU_WENIG_DATEN
    assert bewertung.hat_aussage is False
    assert bewertung.median_cents is None
    assert bewertung.abweichung_prozent is None
    assert bewertung.minimum_cents is None
    assert bewertung.datenpunkte == MINDEST_DATENPUNKTE - 1


def test_ganz_ohne_daten_ist_kein_sonderfall():
    """Der erste Lauf einer brandneuen Strecke darf nicht abstürzen."""
    bewertung = bewerte_preis(18000, [])

    assert bewertung.einordnung is Einordnung.ZU_WENIG_DATEN
    assert bewertung.datenpunkte == 0


def test_genau_die_mindestanzahl_reicht_fuer_eine_aussage():
    bewertung = bewerte_preis(20000, preise(MINDEST_DATENPUNKTE))

    assert bewertung.hat_aussage is True
    assert bewertung.median_cents == 20000


def test_deutlich_unter_dem_median_ist_guenstig():
    bewertung = bewerte_preis(16000, preise(GENUG))  # −20 %

    assert bewertung.einordnung is Einordnung.GUENSTIG
    assert bewertung.abweichung_prozent == -20.0


def test_deutlich_ueber_dem_median_ist_teuer():
    bewertung = bewerte_preis(24000, preise(GENUG))  # +20 %

    assert bewertung.einordnung is Einordnung.TEUER


def test_nahe_am_median_ist_normal():
    bewertung = bewerte_preis(20500, preise(GENUG))  # +2,5 %

    assert bewertung.einordnung is Einordnung.NORMAL


def test_genau_auf_der_guenstig_schwelle_zaehlt_als_guenstig():
    """Die Schwellen sind inklusiv — sonst fiele der Grenzfall auf „normal"."""
    grenzpreis = int(20000 * (1 + GUENSTIG_AB_PROZENT / 100))

    assert bewerte_preis(grenzpreis, preise(GENUG)).einordnung is Einordnung.GUENSTIG


def test_genau_auf_der_teuer_schwelle_zaehlt_als_teuer():
    grenzpreis = int(20000 * (1 + TEUER_AB_PROZENT / 100))

    assert bewerte_preis(grenzpreis, preise(GENUG)).einordnung is Einordnung.TEUER


def test_alle_preise_gleich_ergibt_null_prozent():
    """Ein flacher Markt ist kein Fehlerfall."""
    bewertung = bewerte_preis(20000, preise(GENUG))

    assert bewertung.abweichung_prozent == 0.0
    assert bewertung.einordnung is Einordnung.NORMAL


def test_bewertung_meldet_das_bisherige_minimum():
    vergleich = [*preise(GENUG - 1), 15000]

    bewertung = bewerte_preis(18000, vergleich)

    assert bewertung.minimum_cents == 15000


def test_neuer_tiefstpreis_wird_erkannt():
    """Für M8: Ein Rekordpreis ist auch dann meldenswert, wenn die Abweichung
    vom Median unspektakulär aussieht."""
    vergleich = [*preise(GENUG - 1), 15000]

    assert bewerte_preis(14000, vergleich).ist_bestpreis is True


def test_preis_auf_hoehe_des_minimums_ist_kein_neuer_bestpreis():
    vergleich = [*preise(GENUG - 1), 15000]

    assert bewerte_preis(15000, vergleich).ist_bestpreis is False


def test_ohne_ausreichende_daten_gibt_es_keinen_bestpreis():
    """Ohne Historie lässt sich „Rekord" nicht behaupten."""
    assert bewerte_preis(10000, preise(3)).ist_bestpreis is False


def test_bewertung_merkt_sich_den_bewerteten_preis():
    assert bewerte_preis(18950, preise(GENUG)).preis_cents == 18950
