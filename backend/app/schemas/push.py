"""Ein- und Ausgabe der Push-Endpunkte.

Die Form von `PushSubscriptionCreate` ist **nicht frei gewählt**: Sie ist
exakt das, was der Browser bei `subscription.toJSON()` ausspuckt. Dadurch
kann der Client das Objekt unverändert weiterreichen, statt es umzubauen —
und beim Umbauen entstehen die Fehler.
"""

from pydantic import BaseModel, ConfigDict, Field


class PushKeys(BaseModel):
    """Die beiden Schlüssel des Geräts, base64url-kodiert."""

    model_config = ConfigDict(extra="ignore")

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(BaseModel):
    # `extra="ignore"` statt `forbid`: Der Browser hängt Felder wie
    # `expirationTime` an, die uns nicht interessieren. Die abzulehnen wäre
    # pedantisch und würde die App bei der nächsten Browser-Version brechen.
    model_config = ConfigDict(extra="ignore")

    # Kein `HttpUrl`: Das zöge eine Normalisierung nach sich (Schrägstrich am
    # Ende, Klein-/Großschreibung), und der Endpoint muss **zeichengenau**
    # erhalten bleiben — er ist ein Schlüssel, keine Adresse zum Anzeigen.
    endpoint: str = Field(min_length=1, max_length=2000)
    keys: PushKeys


class PushSubscriptionDelete(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1, max_length=2000)


class PushConfigResponse(BaseModel):
    """Was der Browser zum Abonnieren braucht."""

    # Leer, wenn im Backend kein VAPID-Schlüsselpaar hinterlegt ist. Der
    # Client zeigt dann gar nicht erst einen Knopf an, statt den Nutzer nach
    # einer Erlaubnis zu fragen, die zu nichts führt.
    public_key: str
    aktiviert: bool


class PushSubscriptionResponse(BaseModel):
    aktiv: bool
