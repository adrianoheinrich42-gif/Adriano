"""Alle Tabellen-Modelle.

Dieses Modul importiert jedes Modell, damit `Base.metadata` vollständig ist.
Alembic vergleicht gegen genau diese Metadaten — fehlt hier ein Import,
"vergisst" die automatische Migrationserzeugung stillschweigend eine Tabelle.
"""

from app.models.device_token import DeviceToken
from app.models.flight_observation import FlightObservation
from app.models.flight_offer import FlightOffer
from app.models.notification_log import NotificationLog
from app.models.price_alert import PriceAlert
from app.models.user import User

__all__ = [
    "DeviceToken",
    "FlightObservation",
    "FlightOffer",
    "NotificationLog",
    "PriceAlert",
    "User",
]
