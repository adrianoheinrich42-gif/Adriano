"""Ein- und Ausgabeformate für Preisalarme.

Drei Klassen, weil drei verschiedene Dinge gemeint sind:
  * `PriceAlertCreate`   — was der Client beim Anlegen schicken **darf**
  * `PriceAlertUpdate`   — was er nachträglich ändern darf (alles optional)
  * `PriceAlertResponse` — was er zurückbekommt

Bewusst nicht **ein** Schema für alles: Beim Anlegen darf niemand `id` oder
`last_checked_at` mitschicken, und beim Antworten wollen wir Felder zeigen,
die es in der Eingabe gar nicht gibt.

Die Regeln hier spiegeln die CHECK-Constraints aus
`app/models/price_alert.py`. Doppelt gemoppelt ist Absicht: Pydantic liefert
dem Nutzer eine **verständliche Fehlermeldung**, die Datenbank ist die letzte
Verteidigungslinie für alles, was an der API vorbeikommt.
"""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Wiederverwendbare Feldtypen. `pattern` prüft erst *nach* dem Validator,
# der auf Großbuchstaben normalisiert — "muc" wird also angenommen und als
# "MUC" gespeichert.
IataCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
CurrencyCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]

# Felder, die auf Großbuchstaben normalisiert werden.
_CODE_FELDER = ("origin", "destination", "currency")


def _nach_grossbuchstaben(wert: object) -> object:
    """`" muc "` → `"MUC"`.

    Nutzerfreundlich statt pedantisch: Groß-/Kleinschreibung ist kein Grund,
    ein Formular abzulehnen.
    """
    if isinstance(wert, str):
        return wert.strip().upper()
    return wert


def pruefe_feldkombination(
    *,
    origin: str,
    destination: str,
    earliest_departure_date: date,
    latest_return_date: date,
    min_trip_duration_days: int | None,
    max_trip_duration_days: int | None,
) -> None:
    """Regeln, die **mehrere** Felder zugleich betreffen.

    Als eigene Funktion, weil sie zweimal gebraucht wird: beim Anlegen prüft
    Pydantic die eingehenden Werte, beim Ändern (PATCH) muss der Dienst das
    **Ergebnis nach dem Zusammenführen** prüfen — ein einzelnes geändertes
    Feld kann für sich genommen gültig sein und trotzdem nicht zum Rest passen.

    Wirft `ValueError` mit deutschem Text.
    """
    if origin == destination:
        raise ValueError("Start- und Zielflughafen dürfen nicht gleich sein.")

    if earliest_departure_date > latest_return_date:
        raise ValueError("Das späteste Rückreisedatum darf nicht vor dem frühesten Hinflug liegen.")

    if (
        min_trip_duration_days is not None
        and max_trip_duration_days is not None
        and min_trip_duration_days > max_trip_duration_days
    ):
        raise ValueError("Die Mindestreisedauer darf nicht größer als die Höchstreisedauer sein.")

    if max_trip_duration_days is not None:
        # Eine Reise kann nicht länger sein als das Fenster, in dem sie
        # stattfinden soll — sonst sucht der Worker dauerhaft ins Leere.
        fenster_tage = (latest_return_date - earliest_departure_date).days + 1
        if max_trip_duration_days > fenster_tage:
            raise ValueError(
                f"Die Höchstreisedauer ({max_trip_duration_days} Tage) passt nicht in den "
                f"gewählten Zeitraum ({fenster_tage} Tage)."
            )


class PriceAlertCreate(BaseModel):
    """Alarm anlegen."""

    model_config = ConfigDict(extra="forbid")

    origin: IataCode
    destination: IataCode
    earliest_departure_date: date
    latest_return_date: date

    min_trip_duration_days: int | None = Field(default=None, ge=1, le=365)
    max_trip_duration_days: int | None = Field(default=None, ge=1, le=365)

    max_stops: int = Field(default=1, ge=0, le=3)
    max_price_cents: int = Field(
        ...,
        gt=0,
        le=100_000_00,  # 100.000 € — reine Tippfehler-Bremse
        description="Höchstpreis in **Cent** (2500 € = 250000). Nie als Kommazahl.",
    )
    currency: CurrencyCode = "EUR"

    # Amadeus erlaubt höchstens 9 Reisende pro Anfrage.
    adults: int = Field(default=1, ge=1, le=9)
    include_checked_bag: bool = False
    avoid_night_flights: bool = False

    # Untergrenze wie in der Datenbank: schützt das Amadeus-Kontingent.
    # Obergrenze: eine Woche — darüber ist ein Alarm praktisch nutzlos.
    check_interval_minutes: int = Field(default=360, ge=15, le=10_080)

    @field_validator(*_CODE_FELDER, mode="before")
    @classmethod
    def _grossbuchstaben(cls, wert: object) -> object:
        return _nach_grossbuchstaben(wert)

    @model_validator(mode="after")
    def _pruefe_regeln(self) -> "PriceAlertCreate":
        pruefe_feldkombination(
            origin=self.origin,
            destination=self.destination,
            earliest_departure_date=self.earliest_departure_date,
            latest_return_date=self.latest_return_date,
            min_trip_duration_days=self.min_trip_duration_days,
            max_trip_duration_days=self.max_trip_duration_days,
        )

        # Nur beim Anlegen: Ein Alarm für einen vergangenen Zeitraum kann nie
        # auslösen. Beim Ändern wird das **nicht** geprüft — sonst ließe sich
        # ein länger laufender Alarm irgendwann nicht mehr bearbeiten.
        if self.latest_return_date < date.today():
            raise ValueError("Der gewählte Zeitraum liegt vollständig in der Vergangenheit.")

        return self


class PriceAlertUpdate(BaseModel):
    """Alarm ändern — alle Felder optional (HTTP PATCH).

    Absichtlich **keine** gemeinsame Basisklasse mit `PriceAlertCreate`: Dort
    haben Felder Standardwerte, und die würden hier bestehende Werte
    überschreiben. Was der Client nicht schickt, bleibt unangetastet.
    """

    model_config = ConfigDict(extra="forbid")

    origin: IataCode | None = None
    destination: IataCode | None = None
    earliest_departure_date: date | None = None
    latest_return_date: date | None = None
    min_trip_duration_days: int | None = Field(default=None, ge=1, le=365)
    max_trip_duration_days: int | None = Field(default=None, ge=1, le=365)
    max_stops: int | None = Field(default=None, ge=0, le=3)
    max_price_cents: int | None = Field(default=None, gt=0, le=100_000_00)
    currency: CurrencyCode | None = None
    adults: int | None = Field(default=None, ge=1, le=9)
    include_checked_bag: bool | None = None
    avoid_night_flights: bool | None = None
    check_interval_minutes: int | None = Field(default=None, ge=15, le=10_080)

    # Pausieren statt löschen — der Preisverlauf bleibt erhalten.
    is_active: bool | None = None

    @field_validator(*_CODE_FELDER, mode="before")
    @classmethod
    def _grossbuchstaben(cls, wert: object) -> object:
        return _nach_grossbuchstaben(wert)

    def gesetzte_felder(self) -> dict[str, object]:
        """Nur die Felder, die der Client wirklich geschickt hat.

        `exclude_unset` unterscheidet „Feld weggelassen" von „Feld
        ausdrücklich auf null gesetzt" — genau der Unterschied, auf den es
        bei PATCH ankommt.
        """
        return self.model_dump(exclude_unset=True)


class PriceAlertResponse(BaseModel):
    """Was der Client über einen Alarm erfährt.

    `user_id` fehlt bewusst: Der Client bekommt ohnehin nur seine eigenen
    Alarme, der Wert wäre in jeder Zeile derselbe.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    origin: str
    destination: str
    earliest_departure_date: date
    latest_return_date: date
    min_trip_duration_days: int | None
    max_trip_duration_days: int | None
    max_stops: int
    max_price_cents: int
    currency: str
    adults: int
    include_checked_bag: bool
    avoid_night_flights: bool
    is_active: bool
    check_interval_minutes: int
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
