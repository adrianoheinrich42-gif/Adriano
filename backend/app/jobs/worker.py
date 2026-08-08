"""Der Worker-Prozess: ruft den Prüflauf im Zeittakt auf.

Die Aufgabenteilung ist bewusst eng:

* **`services/pruflauf.py`** weiß, *was* zu tun ist (suchen, speichern).
* **Dieses Modul** weiß nur, *wann* — und dass es dabei niemals sterben darf.

Der Takt hier ist nicht das Prüfintervall des Nutzers. Der Worker sieht alle
`pruflauf_intervall_minuten` **nach**, welche Alarme fällig sind; wie oft ein
einzelner Alarm drankommt, steht in dessen `check_interval_minutes`. Ein
kurzer Worker-Takt kostet also fast nichts (eine schlanke SQL-Abfrage), macht
aber neue Alarme schnell scharf.

Starten: `uv run python -m app.jobs.worker`
"""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.core.logging import richte_logging_ein
from app.db import SessionFactory, engine
from app.services.amadeus import AmadeusClient, Flugsuche
from app.services.aufraeumen import loesche_alte_daten
from app.services.claude import ClaudeTexter, Texter
from app.services.pruflauf import LaufBericht, pruefe_faellige_alarme
from app.services.push import PushVersand, WebPushVersand

# Wie in `app/main.py`: der Formatierer aus `core/logging.py` schwärzt
# E-Mail-Adressen, Push-Endpoints und Token. Gerade der Worker ist die
# Stelle, an der solche Werte im Log landen könnten — er hantiert mit
# Push-Zielen.
richte_logging_ein(get_settings().log_format, get_settings().log_level)
logger = logging.getLogger(__name__)

JOB_ID = "pruflauf"
AUFRAEUM_JOB_ID = "aufraeumen"


async def fuehre_lauf_aus(
    suche: Flugsuche,
    limit: int,
    versand: PushVersand | None,
    settings: Settings,
    texter: Texter | None,
) -> LaufBericht:
    """Ein Durchgang in einer eigenen Datenbank-Session."""
    async with SessionFactory() as session:
        return await pruefe_faellige_alarme(
            session, suche, limit=limit, versand=versand, settings=settings, texter=texter
        )


async def lauf_sicher(
    suche: Flugsuche,
    limit: int,
    versand: PushVersand | None,
    settings: Settings,
    texter: Texter | None = None,
) -> None:
    """Wie `fuehre_lauf_aus`, aber wirft garantiert nicht.

    Der Grund ist der wichtigste Satz dieses Moduls: **Eine Ausnahme im Job
    darf den Scheduler nie beenden.** Eine kaputte Datenbankverbindung um
    03:00 Uhr soll den nächsten Lauf um 03:05 nicht verhindern — der Fehler
    gehört ins Log, nicht in den Prozessabbruch.

    `pruefe_faellige_alarme` fängt bereits Fehler *einzelner* Alarme ab. Hier
    geht es um alles davor und danach: Verbindungsaufbau, Abfrage, Commit.
    """
    try:
        bericht = await fuehre_lauf_aus(suche, limit, versand, settings, texter)
    except Exception:  # noqa: BLE001 — bewusst: der Scheduler muss weiterlaufen
        logger.exception("Prüflauf abgebrochen — der nächste Takt versucht es erneut.")
        return

    logger.info(
        "Prüflauf fertig: %d Alarme geprüft, %d erfolgreich, %d Angebote gespeichert, "
        "%d Meldungen verschickt.",
        bericht.geprueft,
        bericht.erfolgreich,
        bericht.gespeicherte_angebote,
        bericht.meldungen,
    )


async def aufraeumen_sicher(settings: Settings) -> None:
    """Alte Daten löschen — und dabei genauso wenig sterben wie der Prüflauf.

    Eigener Job statt eines Anhängsels am Prüflauf: Der Prüflauf läuft alle
    fünf Minuten, das Aufräumen einmal am Tag. Zusammengelegt liefe entweder
    das Löschen 288-mal zu oft oder der Prüflauf 288-mal zu selten.
    """
    try:
        async with SessionFactory() as session:
            await loesche_alte_daten(session, settings.aufbewahrung_tage)
    except Exception:  # noqa: BLE001 — bewusst: der Scheduler muss weiterlaufen
        logger.exception("Aufräumen abgebrochen — der nächste Takt versucht es erneut.")


def erstelle_scheduler(
    suche: Flugsuche,
    settings: Settings,
    versand: PushVersand | None = None,
    texter: Texter | None = None,
) -> AsyncIOScheduler:
    """Scheduler mit genau einem Job bauen (starten muss der Aufrufer).

    Zwei Einstellungen, die man leicht vergisst und dann teuer bezahlt:

    * `max_instances=1` — dauert ein Lauf länger als der Takt, wird der
      nächste **nicht** parallel gestartet. Sonst würden sich bei einer
      langsamen Amadeus-Antwort die Läufe überlagern und dieselben Alarme
      doppelt abfragen.
    * `coalesce=True` — hat der Prozess mehrere Takte verschlafen (Neustart,
      Deployment), wird **einmal** nachgeholt statt fünfmal hintereinander.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        lauf_sicher,
        trigger="interval",
        minutes=settings.pruflauf_intervall_minuten,
        args=[suche, settings.pruflauf_max_alarme_pro_lauf, versand, settings, texter],
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        aufraeumen_sicher,
        trigger="interval",
        hours=settings.aufraeumen_intervall_stunden,
        args=[settings],
        id=AUFRAEUM_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


async def main() -> None:
    settings = get_settings()

    logger.info(
        "Worker startet — Takt: alle %d min, höchstens %d Alarme pro Lauf.",
        settings.pruflauf_intervall_minuten,
        settings.pruflauf_max_alarme_pro_lauf,
    )

    client = AmadeusClient(settings)

    # Ohne VAPID-Schlüsselpaar läuft der Worker weiter, es geht nur nichts
    # raus. Das ist Absicht: Die Kernfunktion (suchen, aufzeichnen, bewerten)
    # darf nicht daran hängen, dass ein Schlüssel hinterlegt wurde.
    versand: PushVersand | None = WebPushVersand(settings) if settings.push_aktiviert else None
    if versand is None:
        logger.warning(
            "Kein VAPID-Schlüsselpaar hinterlegt — es werden KEINE Benachrichtigungen "
            "verschickt. Erzeugen mit: uv run python -m scripts.vapid_schluessel"
        )

    # Ohne Anthropic-Schlüssel formuliert der Baukasten. Auch das ist Absicht
    # und derselbe Gedanke wie beim VAPID-Paar: Die Kernfunktion darf an
    # keinem hinterlegten Schlüssel hängen (Leitplanke 3).
    texter: Texter | None = ClaudeTexter(settings) if settings.claude_aktiviert else None
    if texter is None:
        logger.info(
            "Kein Anthropic-Schlüssel hinterlegt — die Benachrichtigungen formuliert "
            "der eingebaute Satz-Baukasten. Das ist voll funktionsfähig, nur weniger schön."
        )

    scheduler = erstelle_scheduler(client, settings, versand, texter)

    # Ohne dieses Ereignis müsste `main()` in einer Endlosschleife pollen.
    # SIGTERM kommt vom Hoster beim Deployment, SIGINT von Strg-C.
    beenden = asyncio.Event()
    schleife = asyncio.get_running_loop()
    for signalnummer in (signal.SIGINT, signal.SIGTERM):
        schleife.add_signal_handler(signalnummer, beenden.set)

    scheduler.start()
    # Einmal sofort loslegen, statt den ersten Takt abzuwarten.
    await lauf_sicher(client, settings.pruflauf_max_alarme_pro_lauf, versand, settings, texter)

    try:
        await beenden.wait()
    finally:
        logger.info("Worker fährt herunter …")
        scheduler.shutdown(wait=False)
        await client.aclose()
        if isinstance(texter, ClaudeTexter):
            await texter.aclose()
        await engine.dispose()
        logger.info("Beendet.")


if __name__ == "__main__":
    asyncio.run(main())
