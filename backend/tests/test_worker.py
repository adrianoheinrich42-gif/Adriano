"""Der Worker-Prozess (M6) — ohne Datenbank, ohne Netz, ohne Wartezeit.

Der Worker ist bewusst dünn: Er weiß nur, *wann* geprüft wird, nicht *wie*.
Entsprechend wenig gibt es zu prüfen — aber diese Punkte sind wichtig, weil
ein Fehler hier nachts um drei niemandem auffällt:

* Eine Ausnahme im Job darf den Scheduler **nie** beenden.
* Läufe dürfen sich nicht überlagern und nicht nachgeholt aufstauen.
"""

from typing import Any

import pytest

from app.jobs.worker import JOB_ID, erstelle_scheduler, lauf_sicher
from app.services.pruflauf import LaufBericht, LaufErgebnis
from tests.attrappen import FlugsucheAttrappe
from tests.test_auth import make_settings


def test_scheduler_bekommt_genau_einen_job():
    scheduler = erstelle_scheduler(FlugsucheAttrappe(), make_settings())

    jobs = scheduler.get_jobs()
    assert [job.id for job in jobs] == [JOB_ID]


def test_takt_kommt_aus_den_einstellungen():
    scheduler = erstelle_scheduler(FlugsucheAttrappe(), make_settings(pruflauf_intervall_minuten=7))

    job = scheduler.get_jobs()[0]
    assert job.trigger.interval.total_seconds() == 7 * 60


def test_laeufe_ueberlagern_sich_nicht_und_stauen_sich_nicht_auf():
    """`max_instances=1` verhindert Parallelläufe, `coalesce` das Nachholen.

    Ohne das erste würden sich bei einer langsamen Amadeus-Antwort die Läufe
    überlagern und dieselben Alarme doppelt abfragen. Ohne das zweite würde
    ein Neustart nach längerer Pause alle verpassten Takte hintereinander
    nachholen — genau dann, wenn ohnehin gerade alles fällig ist.
    """
    job = erstelle_scheduler(FlugsucheAttrappe(), make_settings()).get_jobs()[0]

    assert job.max_instances == 1
    assert job.coalesce is True


def test_limit_wird_an_den_lauf_durchgereicht():
    job = erstelle_scheduler(
        FlugsucheAttrappe(), make_settings(pruflauf_max_alarme_pro_lauf=3)
    ).get_jobs()[0]

    assert job.args[1] == 3


async def test_lauf_sicher_meldet_das_ergebnis(monkeypatch: pytest.MonkeyPatch, caplog: Any):
    async def erfolgreicher_lauf(suche: Any, limit: int) -> LaufBericht:
        import uuid

        return LaufBericht(
            ergebnisse=[LaufErgebnis(alarm_id=uuid.uuid4(), search_ok=True, angebote_gespeichert=2)]
        )

    monkeypatch.setattr("app.jobs.worker.fuehre_lauf_aus", erfolgreicher_lauf)

    with caplog.at_level("INFO"):
        await lauf_sicher(FlugsucheAttrappe(), 20)

    assert "1 Alarme geprüft" in caplog.text
    assert "2 Angebote gespeichert" in caplog.text


async def test_ausnahme_beendet_den_scheduler_nicht(monkeypatch: pytest.MonkeyPatch, caplog: Any):
    """Der wichtigste Test dieses Moduls.

    Eine kaputte Datenbankverbindung um 03:00 Uhr darf den Lauf um 03:05 nicht
    verhindern. Also: Fehler ins Log, aber keine Ausnahme nach außen.
    """

    async def kaputter_lauf(suche: Any, limit: int) -> LaufBericht:
        raise ConnectionError("Datenbank weg")

    monkeypatch.setattr("app.jobs.worker.fuehre_lauf_aus", kaputter_lauf)

    with caplog.at_level("ERROR"):
        await lauf_sicher(FlugsucheAttrappe(), 20)  # darf nicht werfen

    assert "Datenbank weg" in caplog.text
