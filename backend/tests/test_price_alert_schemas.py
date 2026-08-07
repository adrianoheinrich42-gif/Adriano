"""Tests der Eingabevalidierung für Alarme — **ohne Datenbank**.

Hier wird nur geprüft, was Pydantic entscheidet: Welche Eingabe ist gültig,
welche nicht, und wird sie richtig normalisiert. Die Fachlogik (Besitz,
Limit) steht in `tests/integration/test_price_alerts.py`.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.price_alert import PriceAlertCreate, PriceAlertUpdate

HEUTE = date.today()
IN_30_TAGEN = HEUTE + timedelta(days=30)
IN_45_TAGEN = HEUTE + timedelta(days=45)


def basis(**overrides: object) -> dict[str, object]:
    """Eine gültige Eingabe, aus der einzelne Felder verbogen werden."""
    daten: dict[str, object] = {
        "origin": "MUC",
        "destination": "BCN",
        "earliest_departure_date": IN_30_TAGEN,
        "latest_return_date": IN_45_TAGEN,
        "max_price_cents": 25000,
    }
    daten.update(overrides)
    return daten


# --- Gültige Eingaben ------------------------------------------------------


def test_minimale_eingabe_bekommt_sinnvolle_standardwerte():
    alarm = PriceAlertCreate(**basis())  # type: ignore[arg-type]

    assert alarm.max_stops == 1
    assert alarm.currency == "EUR"
    assert alarm.adults == 1
    assert alarm.include_checked_bag is False
    assert alarm.check_interval_minutes == 360


def test_kleinschreibung_wird_normalisiert():
    alarm = PriceAlertCreate(**basis(origin=" muc ", destination="bcn", currency="eur"))  # type: ignore[arg-type]

    assert alarm.origin == "MUC"
    assert alarm.destination == "BCN"
    assert alarm.currency == "EUR"


def test_unbekanntes_feld_wird_abgelehnt():
    # `extra="forbid"`: Ein Tippfehler im Feldnamen soll auffallen und nicht
    # stillschweigend ignoriert werden.
    with pytest.raises(ValidationError):
        PriceAlertCreate(**basis(max_preis_cents=25000))  # type: ignore[arg-type]


# --- Einzelne Felder -------------------------------------------------------


@pytest.mark.parametrize(
    "feld,wert",
    [
        ("origin", "MUCH"),  # zu lang
        ("origin", "M1C"),  # Ziffer
        ("max_price_cents", 0),  # Preis muss positiv sein
        ("max_price_cents", -100),
        ("max_stops", -1),
        ("adults", 0),
        ("adults", 10),  # Amadeus erlaubt höchstens 9
        ("check_interval_minutes", 14),  # Untergrenze wie in der Datenbank
        ("min_trip_duration_days", 0),
    ],
)
def test_ungueltige_einzelwerte_werden_abgelehnt(feld, wert):
    with pytest.raises(ValidationError):
        PriceAlertCreate(**basis(**{feld: wert}))  # type: ignore[arg-type]


# --- Regeln über mehrere Felder -------------------------------------------


def test_gleicher_start_und_zielflughafen_wird_abgelehnt():
    with pytest.raises(ValidationError, match="nicht gleich"):
        PriceAlertCreate(**basis(destination="MUC"))  # type: ignore[arg-type]


def test_rueckreise_vor_hinflug_wird_abgelehnt():
    with pytest.raises(ValidationError, match="Rückreisedatum"):
        PriceAlertCreate(  # type: ignore[arg-type]
            **basis(earliest_departure_date=IN_45_TAGEN, latest_return_date=IN_30_TAGEN)
        )


def test_mindestdauer_groesser_als_hoechstdauer_wird_abgelehnt():
    with pytest.raises(ValidationError, match="Mindestreisedauer"):
        PriceAlertCreate(**basis(min_trip_duration_days=10, max_trip_duration_days=5))  # type: ignore[arg-type]


def test_reisedauer_passt_nicht_in_den_zeitraum():
    # Fenster ist 16 Tage, gewünscht sind 20 — der Alarm könnte nie auslösen.
    with pytest.raises(ValidationError, match="Höchstreisedauer"):
        PriceAlertCreate(**basis(max_trip_duration_days=20))  # type: ignore[arg-type]


def test_vergangener_zeitraum_wird_abgelehnt():
    gestern = HEUTE - timedelta(days=1)
    with pytest.raises(ValidationError, match="Vergangenheit"):
        PriceAlertCreate(  # type: ignore[arg-type]
            **basis(
                earliest_departure_date=gestern - timedelta(days=10),
                latest_return_date=gestern,
            )
        )


# --- PATCH-Schema ----------------------------------------------------------


def test_update_merkt_sich_nur_geschickte_felder():
    aenderung = PriceAlertUpdate(max_price_cents=19900)

    # Genau der Unterschied, auf den es bei PATCH ankommt: Nicht geschickte
    # Felder dürfen nicht als "auf null setzen" durchgehen.
    assert aenderung.gesetzte_felder() == {"max_price_cents": 19900}


def test_update_normalisiert_ebenfalls():
    aenderung = PriceAlertUpdate(origin="txl")

    assert aenderung.gesetzte_felder() == {"origin": "TXL"}


def test_update_prueft_einzelne_felder_weiterhin():
    with pytest.raises(ValidationError):
        PriceAlertUpdate(max_price_cents=0)


def test_update_erlaubt_pausieren():
    assert PriceAlertUpdate(is_active=False).gesetzte_felder() == {"is_active": False}


def test_update_verbietet_fremde_felder():
    # `user_id` darf sich niemand selbst setzen.
    with pytest.raises(ValidationError):
        PriceAlertUpdate(user_id="11111111-2222-3333-4444-555555555555")  # type: ignore[call-arg]
