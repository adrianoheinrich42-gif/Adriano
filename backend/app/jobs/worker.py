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
from app.db import SessionFactory, engine
from app.services.amadeus import AmadeusClient, Flugsuche
from app.services.pruflauf import LaufBericht, pruefe_faellige_alarme

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

JOB_ID = "pruflauf"


async def fuehre_lauf_aus(suche: Flugsuche, limit: int) -> LaufBericht:
    """Ein Durchgang in einer eigenen Datenbank-Session."""
    async with SessionFactory() as session:
        return await pruefe_faellige_alarme(session, suche, limit=limit)


async def lauf_sicher(suche: Flugsuche, limit: int) -> None:
    """Wie `fuehre_lauf_aus`, aber wirft garantiert nicht.

    Der Grund ist der wichtigste Satz dieses Moduls: **Eine Ausnahme im Job
    darf den Scheduler nie beenden.** Eine kaputte Datenbankverbindung um
    03:00 Uhr soll den nächsten Lauf um 03:05 nicht verhindern — der Fehler
    gehört ins Log, nicht in den Prozessabbruch.

    `pruefe_faellige_alarme` fängt bereits Fehler *einzelner* Alarme ab. Hier
    geht es um alles davor und danach: Verbindungsaufbau, Abfrage, Commit.
    """
    try:
        bericht = await fuehre_lauf_aus(suche, limit)
    except Exception:  # noqa: BLE001 — bewusst: der Scheduler muss weiterlaufen
        logger.exception("Prüflauf abgebrochen — der nächste Takt versucht es erneut.")
        return

    logger.info(
        "Prüflauf fertig: %d Alarme geprüft, %d erfolgreich, %d Angebote gespeichert.",
        bericht.geprueft,
        bericht.erfolgreich,
        bericht.gespeicherte_angebote,
    )


def erstelle_scheduler(suche: Flugsuche, settings: Settings) -> AsyncIOScheduler:
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
        args=[suche, settings.pruflauf_max_alarme_pro_lauf],
        id=JOB_ID,
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
    scheduler = erstelle_scheduler(client, settings)

    # Ohne dieses Ereignis müsste `main()` in einer Endlosschleife pollen.
    # SIGTERM kommt vom Hoster beim Deployment, SIGINT von Strg-C.
    beenden = asyncio.Event()
    schleife = asyncio.get_running_loop()
    for signalnummer in (signal.SIGINT, signal.SIGTERM):
        schleife.add_signal_handler(signalnummer, beenden.set)

    scheduler.start()
    # Einmal sofort loslegen, statt den ersten Takt abzuwarten.
    await lauf_sicher(client, settings.pruflauf_max_alarme_pro_lauf)

    try:
        await beenden.wait()
    finally:
        logger.info("Worker fährt herunter …")
        scheduler.shutdown(wait=False)
        await client.aclose()
        await engine.dispose()
        logger.info("Beendet.")


if __name__ == "__main__":
    asyncio.run(main())
