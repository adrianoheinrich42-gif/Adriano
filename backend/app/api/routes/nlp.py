"""Freitext zu Formularentwurf (M11).

Ein einziger Endpunkt: `POST /alerts/entwurf`.

**Er legt nichts an.** Der Name sagt das absichtlich — er heißt `entwurf` und
nicht `parse` oder `auto`, damit beim Lesen der Routenliste klar ist, dass
hier kein Alarm entsteht. Aus Claudes Ausgabe wird ein Vorschlag; anlegen muss
der Nutzer über den ganz normalen `POST /alerts`, der unverändert die volle
serverseitige Prüfung fährt (Projektplan 8.8).

Der Endpunkt hängt bewusst unter `/alerts`, obwohl er in keiner Weise zum CRUD
gehört: Für den Client ist es „das Formular vorausfüllen", und dort sucht man
ihn.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser
from app.config import Settings, get_settings
from app.schemas.nlp import EntwurfRequest, EntwurfResponse
from app.services.nlp import Auswerter, ClaudeAuswerter, NichtVerfuegbar, erzeuge_entwurf

router = APIRouter(prefix="/alerts", tags=["alarme"])

AktuelleSettings = Annotated[Settings, Depends(get_settings)]

# Der Satz, den der Nutzer bei einem Ausfall liest. Kein Statuscode, kein
# „Anthropic" — das interessiert ihn nicht. Was er braucht, ist der nächste
# Schritt, und der lautet: von Hand ausfüllen, das geht immer.
NICHT_VERFUEGBAR = (
    "Automatisches Ausfüllen ist gerade nicht verfügbar. Bitte trage die Felder von Hand ein."
)


def hole_auswerter(settings: AktuelleSettings) -> Auswerter:
    """Der Auswerter als Dependency — austauschbar wie alles Externe.

    Genau deshalb kann der Test ihn per `dependency_overrides` durch eine
    Attrappe ersetzen und **es geht kein Test ins Netz**. Ohne hinterlegten
    Schlüssel gibt es gar keinen Auswerter; der Endpunkt antwortet dann
    denselben Satz wie bei einem Ausfall — für den Nutzer ist beides dasselbe.
    """
    if not settings.claude_aktiviert:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NICHT_VERFUEGBAR
        )
    return ClaudeAuswerter(settings)


@router.post(
    "/entwurf",
    response_model=EntwurfResponse,
    summary="Freitext in einen Formularvorschlag umwandeln (legt nichts an)",
)
async def erstelle_entwurf(
    anfrage: EntwurfRequest,
    user: CurrentUser,
    auswerter: Annotated[Auswerter, Depends(hole_auswerter)],
) -> EntwurfResponse:
    """Aus „im Oktober nach Lissabon, max 250 €" wird ein vorausgefülltes Formular.

    `user` steht in der Signatur, obwohl der Entwurf niemandem gehört und
    nichts gespeichert wird. Der Grund ist trotzdem zwingend: Ohne Anmeldung
    wäre das ein offener Endpunkt, über den jeder unsere Anthropic-Rechnung
    hochtreiben könnte.

    **Claude sieht keine Nutzerdaten** — nur den Satz und das heutige Datum.
    """
    try:
        entwurf = await erzeuge_entwurf(anfrage.text, auswerter, datetime.now(UTC).date())
    except NichtVerfuegbar as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NICHT_VERFUEGBAR
        ) from exc

    return EntwurfResponse(
        felder=entwurf.felder,
        hinweise=entwurf.hinweise,
        vollstaendig=entwurf.vollstaendig,
    )
