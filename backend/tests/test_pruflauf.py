"""Die reinen Funktionen des Prüflaufs — ohne Datenbank, ohne Netz.

Hier steht das Verhalten, das man beim Nachdenken über M6 verstehen will:
Welche Suche entsteht aus einem Alarm? Wann ist ein Alarm fällig? Wann sind
zwei Angebote „dasselbe"? Der Rest (Speichern, Reihenfolge, Upsert) braucht
eine Datenbank und steht in `tests/integration/test_pruflauf.py`.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.pruflauf import (
    LaufBericht,
    LaufErgebnis,
    _angebot_als_zeile,
    alarm_zu_suchanfragen,
    bilde_offer_hash,
    ist_faellig,
    ortszeit_als_utc,
)
from tests.attrappen import baue_alarm, baue_angebot, baue_segment

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


# --- Alarm → Suchanfrage ---------------------------------------------------


def test_alarm_ergibt_eine_liste_von_suchanfragen():
    """Bewusst eine Liste, auch wenn vorerst nur ein Eintrag darin steht.

    Der Datums-Fächer über den ganzen Zeitraum kommt später. Dass die
    Signatur schon jetzt eine Liste liefert, macht ihn zu einer Änderung an
    genau einer Stelle statt zu einem Umbau aller Aufrufer.
    """
    anfragen = alarm_zu_suchanfragen(baue_alarm())

    assert isinstance(anfragen, list)
    assert len(anfragen) == 1


def test_suchanfrage_uebernimmt_strecke_und_bedingungen():
    anfrage = alarm_zu_suchanfragen(
        baue_alarm(origin="HAM", destination="LIS", adults=3, max_stops=0, max_price_cents=19900)
    )[0]

    assert anfrage.origin == "HAM"
    assert anfrage.destination == "LIS"
    assert anfrage.adults == 3
    assert anfrage.max_stops == 0
    assert anfrage.waehrung == "EUR"


def test_preislimit_wird_nicht_an_amadeus_geschickt():
    """Sonst wäre der Preisverlauf abgeschnitten und der Median zu niedrig.

    Mit `maxPrice` liefert Amadeus an teuren Tagen gar nichts — die
    Beobachtung bekäme `min_price_cents = NULL` statt „der günstigste war
    380 €". Die Statistik sähe dann nur die guten Tage. Gefiltert wird
    deshalb erst lokal in `_angebot_als_zeile`.
    """
    anfrage = alarm_zu_suchanfragen(baue_alarm(max_price_cents=19900))[0]

    assert anfrage.max_price_cents is None


def test_hinflug_ist_der_frueheste_erlaubte_tag():
    anfrage = alarm_zu_suchanfragen(baue_alarm(earliest_departure_date=date(2026, 10, 1)))[0]

    assert anfrage.departure_date == date(2026, 10, 1)


def test_ohne_mindestdauer_wird_das_volle_fenster_gesucht():
    anfrage = alarm_zu_suchanfragen(
        baue_alarm(
            earliest_departure_date=date(2026, 10, 1),
            latest_return_date=date(2026, 10, 20),
            min_trip_duration_days=None,
        )
    )[0]

    assert anfrage.return_date == date(2026, 10, 20)


def test_mindestdauer_bestimmt_den_rueckflug():
    anfrage = alarm_zu_suchanfragen(
        baue_alarm(
            earliest_departure_date=date(2026, 10, 1),
            latest_return_date=date(2026, 10, 20),
            min_trip_duration_days=7,
        )
    )[0]

    assert anfrage.return_date == date(2026, 10, 8)


def test_rueckflug_wird_auf_das_ende_des_zeitraums_gedeckelt():
    """Eine Mindestdauer darf nie über den Zeitraum des Nutzers hinausschießen."""
    anfrage = alarm_zu_suchanfragen(
        baue_alarm(
            earliest_departure_date=date(2026, 10, 1),
            latest_return_date=date(2026, 10, 5),
            min_trip_duration_days=30,
        )
    )[0]

    assert anfrage.return_date == date(2026, 10, 5)


def test_eintagesfenster_ergibt_eine_einwegsuche():
    """Hin- und Rückflug am selben Tag ist kein Rückflug, sondern ein Einweg."""
    anfrage = alarm_zu_suchanfragen(
        baue_alarm(
            earliest_departure_date=date(2026, 10, 1),
            latest_return_date=date(2026, 10, 1),
        )
    )[0]

    assert anfrage.return_date is None


# --- Fälligkeit ------------------------------------------------------------


def test_neuer_alarm_ist_sofort_faellig():
    """Sonst müsste der Nutzer nach dem Anlegen erst sechs Stunden warten."""
    assert ist_faellig(baue_alarm(last_checked_at=None), JETZT) is True


def test_pausierter_alarm_ist_nie_faellig():
    assert ist_faellig(baue_alarm(is_active=False, last_checked_at=None), JETZT) is False


def test_innerhalb_des_intervalls_nicht_faellig():
    alert = baue_alarm(
        check_interval_minutes=360,
        last_checked_at=JETZT - timedelta(minutes=359),
    )

    assert ist_faellig(alert, JETZT) is False


def test_nach_ablauf_des_intervalls_faellig():
    alert = baue_alarm(
        check_interval_minutes=360,
        last_checked_at=JETZT - timedelta(minutes=360),
    )

    assert ist_faellig(alert, JETZT) is True


def test_naiver_zeitstempel_wird_als_utc_gelesen():
    """Aus der Spalte kommt `timestamptz`. Falls doch etwas Naives auftaucht
    (Testdaten, SQL-Konsole), soll der Vergleich nicht mit einer Ausnahme
    aussteigen."""
    alert = baue_alarm(
        check_interval_minutes=60,
        last_checked_at=datetime(2026, 8, 7, 10, 0),  # ohne Zeitzone
    )

    assert ist_faellig(alert, JETZT) is True


# --- Zeitumrechnung --------------------------------------------------------


def test_ortszeit_behaelt_die_wanduhrzeit():
    """Der Kern der Entscheidung: 09:15 bleibt 09:15, es wird nicht verschoben."""
    ergebnis = ortszeit_als_utc(datetime(2026, 9, 6, 9, 15))

    assert ergebnis == datetime(2026, 9, 6, 9, 15, tzinfo=UTC)
    assert ergebnis.tzinfo is UTC


def test_bereits_gesetzte_zeitzone_wird_umgerechnet():
    """Kommt doch einmal ein Offset mit, gilt der echte Zeitpunkt."""
    from datetime import timezone

    mit_offset = datetime(2026, 9, 6, 9, 15, tzinfo=timezone(timedelta(hours=2)))

    assert ortszeit_als_utc(mit_offset) == datetime(2026, 9, 6, 7, 15, tzinfo=UTC)


# --- offer_hash ------------------------------------------------------------


def test_offer_hash_passt_in_die_spalte():
    """`flight_offers.offer_hash` ist `String(64)` — SHA-256 hex ist genau so lang."""
    hash_wert = bilde_offer_hash(baue_angebot())

    assert len(hash_wert) == 64
    assert all(zeichen in "0123456789abcdef" for zeichen in hash_wert)


def test_gleiches_angebot_ergibt_gleichen_hash():
    """Sonst gäbe es bei jedem Lauf eine neue Zeile statt eines Upserts."""
    assert bilde_offer_hash(baue_angebot()) == bilde_offer_hash(baue_angebot())


def test_anderer_preis_ergibt_anderen_hash():
    """Ein billiger gewordener Flug ist ein neues, wieder meldenswertes Angebot."""
    assert bilde_offer_hash(baue_angebot(preis_cents=18950)) != bilde_offer_hash(
        baue_angebot(preis_cents=17900)
    )


def test_andere_abflugzeit_ergibt_anderen_hash():
    frueher = baue_angebot(segmente=[baue_segment(abflug=datetime(2026, 9, 6, 6, 30))])
    spaeter = baue_angebot(segmente=[baue_segment(abflug=datetime(2026, 9, 6, 9, 15))])

    assert bilde_offer_hash(frueher) != bilde_offer_hash(spaeter)


def test_andere_fluggesellschaft_ergibt_anderen_hash():
    lufthansa = baue_angebot(segmente=[baue_segment(fluggesellschaft="LH")])
    austrian = baue_angebot(segmente=[baue_segment(fluggesellschaft="OS")])

    assert bilde_offer_hash(lufthansa) != bilde_offer_hash(austrian)


def test_einweg_und_rueckflug_sind_unterscheidbar():
    """Der Platzhalter für die fehlende Rückstrecke ist genau dafür da."""
    assert bilde_offer_hash(baue_angebot(mit_rueckflug=False)) != bilde_offer_hash(
        baue_angebot(mit_rueckflug=True)
    )


def test_hash_unterscheidet_umsteigeverbindung_von_direktflug():
    """Zwei Segmente dürfen nicht zufällig dieselbe Zeichenkette ergeben wie eines."""
    direkt = baue_angebot(segmente=[baue_segment(von="MUC", nach="BCN")])
    umsteigen = baue_angebot(
        segmente=[
            baue_segment(von="MUC", nach="FRA", dauer_minuten=65),
            baue_segment(
                von="FRA", nach="BCN", abflug=datetime(2026, 9, 6, 9, 10), dauer_minuten=115
            ),
        ]
    )

    assert bilde_offer_hash(direkt) != bilde_offer_hash(umsteigen)


# --- Angebot → Datenbankzeile ----------------------------------------------


def test_angebot_ueber_dem_limit_wird_nicht_gespeichert():
    alert = baue_alarm(max_price_cents=15000)

    zeile = _angebot_als_zeile(alert, alert.id, baue_angebot(preis_cents=18950), JETZT)

    assert zeile is None


def test_angebot_genau_auf_dem_limit_wird_gespeichert():
    """Amadeus rundet `maxPrice` auf ganze Euro ab — die genaue Grenze zieht erst hier."""
    alert = baue_alarm(max_price_cents=18950)

    zeile = _angebot_als_zeile(alert, alert.id, baue_angebot(preis_cents=18950), JETZT)

    assert zeile is not None


def test_angebot_in_fremder_waehrung_wird_uebersprungen():
    """Cent mit Cent zu vergleichen ist nur bei gleicher Währung sinnvoll."""
    alert = baue_alarm(currency="EUR", max_price_cents=25000)

    zeile = _angebot_als_zeile(alert, alert.id, baue_angebot(waehrung="USD"), JETZT)

    assert zeile is None


def test_flug_ueber_die_datumsgrenze_wird_uebersprungen():
    """Tokio 21:00 ab, Honolulu 09:00 an — am selben Tag.

    Als Wanduhrzeit korrekt, als Zeitpunkt eine negative Dauer. Genau das
    verbietet der CHECK `ck_offers_outbound_time_order`. Ein solcher Sonderfall
    darf den Lauf nicht kippen, also wird er übersprungen.
    """
    rueckwaerts = baue_segment(
        von="HND", nach="HNL", abflug=datetime(2026, 9, 6, 21, 0), dauer_minuten=-720
    )
    alert = baue_alarm()

    zeile = _angebot_als_zeile(alert, alert.id, baue_angebot(segmente=[rueckwaerts]), JETZT)

    assert zeile is None


def test_zeile_uebernimmt_die_felder_des_angebots():
    alert = baue_alarm(max_price_cents=25000)
    angebot = baue_angebot(preis_cents=18950, gepaeckstuecke=1, airline="LH")

    zeile = _angebot_als_zeile(alert, alert.id, angebot, JETZT)

    assert zeile is not None
    assert zeile["total_price_cents"] == 18950
    assert zeile["currency"] == "EUR"
    assert zeile["validating_airline"] == "LH"
    assert zeile["included_checked_bags"] == 1
    assert zeile["outbound_stops"] == 0
    assert zeile["inbound_stops"] == 0
    # Wanduhrzeit erhalten, nur als UTC etikettiert.
    assert zeile["outbound_departure_at"] == datetime(2026, 9, 6, 9, 15, tzinfo=UTC)
    # Hin- und Rückstrecke landen zusammen in `segments`.
    assert len(zeile["segments"]) == 2
    assert zeile["segments"][0]["von"] == "MUC"


def test_einwegflug_laesst_die_rueckflugspalten_leer():
    alert = baue_alarm()

    zeile = _angebot_als_zeile(alert, alert.id, baue_angebot(mit_rueckflug=False), JETZT)

    assert zeile is not None
    assert zeile["inbound_departure_at"] is None
    assert zeile["inbound_arrival_at"] is None
    assert zeile["inbound_stops"] is None


# --- Bericht ---------------------------------------------------------------


def test_laufbericht_zaehlt_zusammen():
    import uuid

    bericht = LaufBericht(
        ergebnisse=[
            LaufErgebnis(alarm_id=uuid.uuid4(), search_ok=True, angebote_gespeichert=2),
            LaufErgebnis(alarm_id=uuid.uuid4(), search_ok=True, angebote_gespeichert=1),
            LaufErgebnis(alarm_id=uuid.uuid4(), search_ok=False, fehler="Kontingent"),
        ]
    )

    assert bericht.geprueft == 3
    assert bericht.erfolgreich == 2
    assert bericht.gespeicherte_angebote == 3


@pytest.mark.parametrize("leer", [LaufBericht()])
def test_leerer_bericht_ist_kein_sonderfall(leer: LaufBericht):
    assert leer.geprueft == 0
    assert leer.gespeicherte_angebote == 0
