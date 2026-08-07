"""Der Prüflauf — hier wachsen Alarme und Flugsuche zu einer Anwendung zusammen.

Bis M5 gab es zwei Hälften, die sich nicht kannten: Der Nutzer konnte Alarme
anlegen (M3), und das Backend konnte bei Amadeus suchen (M5). Niemand hat die
Suche aber je aufgerufen. Genau das passiert hier.

Aufbau wie in `services/amadeus.py` — zwei klar getrennte Hälften:

1. **Reine Funktionen** (oben): Alarm → Suchanfragen, `offer_hash`,
   Fälligkeit, Zeitumrechnung. Keine Datenbank, kein Netz, direkt testbar.
2. **Die Orchestrierung** (unten): fällige Alarme holen, suchen lassen,
   Beobachtung und Angebote schreiben, `last_checked_at` setzen.

Die Suche kommt als Protokoll `Flugsuche` herein, nicht als `AmadeusClient`.
Deshalb kann der Test eine Attrappe einsetzen und **kein Test geht ins Netz**.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flight_observation import FlightObservation
from app.models.flight_offer import FlightOffer
from app.models.price_alert import PriceAlert
from app.schemas.flight_offer import Flugangebot, Teilstrecke
from app.services.amadeus import (
    AmadeusError,
    AmadeusRateLimited,
    AmadeusUnavailable,
    Flugsuche,
    Suchanfrage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reine Funktionen — keine Datenbank, kein Netz
# ---------------------------------------------------------------------------


def alarm_zu_suchanfragen(alert: PriceAlert) -> list[Suchanfrage]:
    """Aus einem Alarm die Suchanfragen bauen, die dieser Lauf stellen soll.

    **Gibt bewusst eine Liste zurück, obwohl vorerst genau ein Eintrag
    darin steht.** Der Alarm nennt einen *Zeitraum* („irgendwann zwischen dem
    1. und dem 20. Oktober"), die Amadeus-API will aber *ein* Datum. Richtig
    wäre, mehrere Termine im Zeitraum abzufragen (ein „Datums-Fächer").

    Das kostet pro Alarm ein Vielfaches an API-Anfragen und wird deshalb erst
    später gebaut. Damit das dann eine Änderung an **einer** Stelle ist und
    kein Umbau der Aufrufer, steht die Liste schon jetzt in der Signatur: Der
    Prüflauf iteriert bereits über mehrere Anfragen und fasst die Ergebnisse
    zusammen.

    Die eine Anfrage, die jetzt entsteht:

    * **Hinflug** = `earliest_departure_date`, der früheste erlaubte Tag.
    * **Rückflug** = frühester Hinflug + `min_trip_duration_days`, falls
      gesetzt — also die kürzeste vom Nutzer erlaubte Reise. Sonst
      `latest_return_date`, also das volle Fenster.
      In beiden Fällen gedeckelt auf `latest_return_date`.
    * Fällt der Rückflug auf den Hinflugtag oder davor, wird **einwegs**
      gesucht (`return_date=None`).
    """
    hinflug = alert.earliest_departure_date

    if alert.min_trip_duration_days is not None:
        rueckflug = hinflug + timedelta(days=alert.min_trip_duration_days)
    else:
        rueckflug = alert.latest_return_date

    rueckflug = min(rueckflug, alert.latest_return_date)

    return [
        Suchanfrage(
            origin=alert.origin,
            destination=alert.destination,
            departure_date=hinflug,
            return_date=rueckflug if rueckflug > hinflug else None,
            adults=alert.adults,
            max_stops=alert.max_stops,
            waehrung=alert.currency,
            max_price_cents=alert.max_price_cents,
        )
    ]


def ist_faellig(alert: PriceAlert, jetzt: datetime) -> bool:
    """Ist dieser Alarm dran?

    Pausierte Alarme nie. Ein noch nie geprüfter Alarm sofort — sonst müsste
    der Nutzer nach dem Anlegen erst ein Intervall lang warten.
    """
    if not alert.is_active:
        return False
    if alert.last_checked_at is None:
        return True

    zuletzt = alert.last_checked_at
    if zuletzt.tzinfo is None:
        # Die Spalte ist `timestamptz`, hier kann eigentlich nichts Naives
        # ankommen. Falls doch (Testdaten, SQL-Konsole): als UTC lesen, statt
        # beim Vergleich mit einer Ausnahme auszusteigen.
        zuletzt = zuletzt.replace(tzinfo=UTC)

    return jetzt - zuletzt >= timedelta(minutes=alert.check_interval_minutes)


def ortszeit_als_utc(ortszeit: datetime) -> datetime:
    """Naive Flughafen-Ortszeit als UTC kennzeichnen — **ohne umzurechnen**.

    Das ist eine bewusste Entscheidung mit einem bekannten Preis, deshalb der
    sperrige Name: Was hier herauskommt, ist **kein echter Zeitpunkt**.

    Amadeus liefert `"2026-09-06T09:15:00"` — ohne Zeitzonen-Offset, und der
    Offset ist aus der Antwort auch nicht ableitbar (siehe Modul-Doku von
    `schemas/flight_offer.py`). Die Spalten in `flight_offers` sind aber
    `timestamptz`, brauchen also *irgendeine* Zone.

    Die Alternative wäre eine Flughafen-Zeitzonentabelle (rund 5000 Einträge,
    mit Sommerzeit-Regeln, die sich jährlich ändern). Dafür ist es zu früh.

    Der Handel:

    * ✅ Die **Wanduhrzeit stimmt** — „09:15 ab München" wird als 09:15
      angezeigt, und genau das will der Reisende sehen.
    * ❌ Der **Zeitpunkt ist falsch** — 09:15 Ortszeit München ist im Sommer
      07:15 UTC. Zwei Zeiten aus verschiedenen Zeitzonen darf man deshalb
      **nicht voneinander abziehen**.
    * ➡️ Wer eine **Dauer** braucht, nimmt `dauer_minuten`. Die liefert
      Amadeus mit, und die ist zeitzonenfrei korrekt.
    """
    if ortszeit.tzinfo is not None:
        return ortszeit.astimezone(UTC)
    return ortszeit.replace(tzinfo=UTC)


def bilde_offer_hash(angebot: Flugangebot) -> str:
    """Stabile Kennung eines Angebots — aus Route, Zeiten, Airline und Preis.

    Wozu: `flight_offers` hat `UNIQUE (price_alert_id, offer_hash)`. Taucht
    dasselbe Angebot im nächsten Lauf wieder auf, wandert nur `last_seen_at`
    weiter, statt eine zweite Zeile anzulegen. Bei 6-Stunden-Takt wäre die
    Tabelle sonst nach einer Woche voller Dubletten.

    **Der Preis gehört mit hinein.** Ein billiger gewordener Flug ist ein
    neues Angebot — und damit wieder meldenswert.

    Amadeus' eigene `id` (`Flugangebot.anbieter_id`) taugt dafür nicht: Sie
    ist nur die laufende Nummer *innerhalb einer Antwort* und bezeichnet
    morgen einen ganz anderen Flug.

    SHA-256 als Hexadezimaltext ist exakt 64 Zeichen lang und passt damit
    genau in `flight_offers.offer_hash` (`String(64)`).
    """
    teile: list[str] = [
        angebot.waehrung,
        str(angebot.preis_cents),
        angebot.validierende_airline or "-",
    ]

    for strecke in (angebot.hinflug, angebot.rueckflug):
        if strecke is None:
            teile.append("-")  # Einwegflug: Platzhalter statt Auslassen …
            continue
        for segment in strecke.segmente:
            # … denn sonst könnte eine andere Segmentzahl dieselbe Zeichenkette
            # ergeben. Der Trenner "|" unten tut dasselbe für die Felder.
            teile.append(
                f"{segment.von}>{segment.nach}"
                f"@{segment.fluggesellschaft}{segment.flugnummer}"
                f"@{segment.abflug_lokal.isoformat()}"
                f"-{segment.ankunft_lokal.isoformat()}"
            )

    return hashlib.sha256("|".join(teile).encode("utf-8")).hexdigest()


def _segmente_als_json(strecke: Teilstrecke | None) -> list[dict[str, Any]]:
    """Teilstrecke für die JSONB-Spalte `flight_offers.segments` aufbereiten."""
    if strecke is None:
        return []
    return [segment.model_dump(mode="json") for segment in strecke.segmente]


def _zeiten_verwertbar(strecke: Teilstrecke) -> bool:
    """Liegt die Ankunfts-Ortszeit nach der Abflugs-Ortszeit?

    Fast immer ja — aber nicht bei Flügen über die Datumsgrenze nach Osten
    (Tokio 21:00 ab, Honolulu 09:00 an, **am selben Tag**). Als Wanduhrzeit
    ist das korrekt, als „Zeitpunkt" ergibt es eine negative Dauer. Genau das
    verbietet der CHECK `ck_offers_outbound_time_order` in der Datenbank.

    Solche Angebote werden übersprungen statt gespeichert — dieselbe Regel wie
    bei kaputten Angeboten in `normalisiere_antwort`: Ein Sonderfall darf nicht
    den ganzen Lauf kippen. Verschwindet mit einer echten Zeitzonentabelle.
    """
    return strecke.ankunft_lokal > strecke.abflug_lokal


@dataclass(frozen=True)
class LaufErgebnis:
    """Was bei einem Alarm herauskam — für Log, Tests und später den Push."""

    alarm_id: uuid.UUID
    search_ok: bool
    angebote_gefunden: int = 0
    angebote_gespeichert: int = 0
    min_preis_cents: int | None = None
    # true = Amadeus war nur gerade nicht verfügbar (Kontingent/5xx). Kein
    # Grund zur Sorge, der nächste Lauf versucht es erneut.
    spaeter_erneut: bool = False
    fehler: str | None = None


@dataclass
class LaufBericht:
    """Zusammenfassung eines kompletten Durchgangs über alle fälligen Alarme."""

    ergebnisse: list[LaufErgebnis] = field(default_factory=list)

    @property
    def geprueft(self) -> int:
        return len(self.ergebnisse)

    @property
    def erfolgreich(self) -> int:
        return sum(1 for e in self.ergebnisse if e.search_ok)

    @property
    def gespeicherte_angebote(self) -> int:
        return sum(e.angebote_gespeichert for e in self.ergebnisse)


# ---------------------------------------------------------------------------
# Orchestrierung — mit Datenbank
# ---------------------------------------------------------------------------


async def finde_faellige_alarme(
    session: AsyncSession, jetzt: datetime, limit: int = 20
) -> list[PriceAlert]:
    """Aktive Alarme, deren letzter Lauf länger her ist als ihr Intervall.

    Die Bedingung steht bewusst in **SQL** und nicht in Python: Bei 10 000
    Alarmen will man nicht alle laden, um 12 fällige zu finden. Der Index
    `ix_price_alerts_due` (`is_active`, `last_checked_at`) ist genau dafür da.

    Gerechnet wird als Sekunden-Differenz (`extract(epoch …)`), weil jeder
    Alarm sein **eigenes** `check_interval_minutes` hat — ein fester
    Zeitpunkt-Vergleich reicht dafür nicht.

    Am längsten Wartende zuerst, damit ein Alarm bei vollem `limit` nicht
    dauerhaft hinten runterfällt.

    Kein `FOR UPDATE SKIP LOCKED`: Laut `CLAUDE.md` läuft **eine**
    Worker-Instanz. Kämen zwei dazu, gehört die Sperre hierher — an genau
    diese eine Abfrage.
    """
    # `extract(epoch from <interval>)` → verstrichene Sekunden als Zahl.
    verstrichene_sekunden = func.extract(
        "epoch",
        literal(jetzt, DateTime(timezone=True)) - PriceAlert.last_checked_at,
    )

    result = await session.execute(
        select(PriceAlert)
        .where(
            PriceAlert.is_active.is_(True),
            or_(
                PriceAlert.last_checked_at.is_(None),
                verstrichene_sekunden >= PriceAlert.check_interval_minutes * 60,
            ),
        )
        .order_by(PriceAlert.last_checked_at.asc().nulls_first())
        .limit(limit)
    )
    return list(result.scalars().all())


async def pruefe_alarm(
    session: AsyncSession,
    alert: PriceAlert,
    suche: Flugsuche,
    jetzt: datetime | None = None,
) -> LaufErgebnis:
    """Ein kompletter Lauf für **einen** Alarm.

    Reihenfolge:

    1. Suchanfragen bauen und der Reihe nach stellen.
    2. **Immer** eine `flight_observation` schreiben — auch wenn nichts
       gefunden wurde oder die Suche scheiterte. Ohne die langweiligen Tage
       gibt es später keinen brauchbaren Median.
    3. Angebote unter dem Preislimit als `flight_offers` per Upsert ablegen.
    4. `last_checked_at` setzen — **auch nach einem Fehler**. Sonst bliebe der
       Alarm „fällig" und der Worker hämmerte im Minutentakt gegen eine
       Schnittstelle, die gerade ohnehin nicht will.

    Wirft nicht: Amadeus-Fehler landen im `LaufErgebnis`.
    """
    jetzt = jetzt or datetime.now(UTC)
    anfragen = alarm_zu_suchanfragen(alert)

    angebote: list[Flugangebot] = []
    search_ok = True
    spaeter_erneut = False
    fehler: str | None = None

    for anfrage in anfragen:
        try:
            angebote.extend(await suche.suche(anfrage))
        except (AmadeusRateLimited, AmadeusUnavailable) as exc:
            # Kein echter Fehler, nur schlechtes Timing: nächster Lauf erneut.
            search_ok = False
            spaeter_erneut = True
            fehler = str(exc)
            logger.info("Alarm %s: Suche später erneut — %s", alert.id, exc)
            break
        except AmadeusError as exc:
            search_ok = False
            fehler = str(exc)
            logger.warning("Alarm %s: Suche fehlgeschlagen — %s", alert.id, exc)
            break

    # `min_price_cents` ist der günstigste **gefundene** Preis, nicht der
    # günstigste passende. Auch ein Angebot über dem Limit ist ein
    # Datenpunkt für den Preisverlauf.
    preise = [a.preis_cents for a in angebote if a.waehrung == alert.currency]
    min_preis = min(preise) if preise else None

    beobachtung = FlightObservation(
        price_alert_id=alert.id,
        observed_at=jetzt,
        min_price_cents=min_preis,
        currency=alert.currency,
        origin=alert.origin,
        destination=alert.destination,
        departure_month=anfragen[0].departure_date.strftime("%Y-%m"),
        offers_found=len(angebote),
        search_ok=search_ok,
    )
    session.add(beobachtung)
    # Flush statt commit: Wir brauchen jetzt die erzeugte `id` als
    # Fremdschlüssel der Angebote, wollen aber alles in **einer** Transaktion
    # halten — entweder der ganze Lauf steht in der Datenbank oder keiner.
    await session.flush()

    gespeichert = await _speichere_angebote(session, alert, beobachtung.id, angebote, jetzt)

    alert.last_checked_at = jetzt
    await session.commit()

    return LaufErgebnis(
        alarm_id=alert.id,
        search_ok=search_ok,
        angebote_gefunden=len(angebote),
        angebote_gespeichert=gespeichert,
        min_preis_cents=min_preis,
        spaeter_erneut=spaeter_erneut,
        fehler=fehler,
    )


async def _speichere_angebote(
    session: AsyncSession,
    alert: PriceAlert,
    beobachtung_id: uuid.UUID,
    angebote: list[Flugangebot],
    jetzt: datetime,
) -> int:
    """Passende Angebote per Upsert ablegen; gibt die Anzahl zurück.

    „Passend" heißt: gleiche Währung wie der Alarm und Preis **nicht über**
    dem Limit. Amadeus filtert per `maxPrice` schon grob vor, aber gerundet
    auf ganze Euro — die genaue Grenze zieht erst diese Prüfung.
    """
    gespeichert = 0

    for angebot in angebote:
        werte = _angebot_als_zeile(alert, beobachtung_id, angebot, jetzt)
        if werte is None:
            continue

        stmt = pg_insert(FlightOffer).values(**werte)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_offers_alert_hash",
            set_={
                # Nur „zuletzt gesehen" wandert weiter. `found_at` bleibt der
                # Erstfund — sonst wüsste niemand mehr, wie lange es das
                # Angebot schon gibt.
                "last_seen_at": stmt.excluded.last_seen_at,
                "flight_observation_id": stmt.excluded.flight_observation_id,
                "raw_payload": stmt.excluded.raw_payload,
            },
        )
        await session.execute(stmt)
        gespeichert += 1

    return gespeichert


def _angebot_als_zeile(
    alert: PriceAlert,
    beobachtung_id: uuid.UUID,
    angebot: Flugangebot,
    jetzt: datetime,
) -> dict[str, Any] | None:
    """Ein `Flugangebot` in Spaltenwerte übersetzen — oder `None` zum Überspringen."""
    if angebot.waehrung != alert.currency:
        logger.warning(
            "Alarm %s: Angebot in %s statt %s — übersprungen.",
            alert.id,
            angebot.waehrung,
            alert.currency,
        )
        return None

    if angebot.preis_cents > alert.max_price_cents:
        return None

    if not _zeiten_verwertbar(angebot.hinflug):
        logger.warning("Alarm %s: Hinflug mit unbrauchbaren Ortszeiten — übersprungen.", alert.id)
        return None

    if angebot.rueckflug is not None and not _zeiten_verwertbar(angebot.rueckflug):
        logger.warning("Alarm %s: Rückflug mit unbrauchbaren Ortszeiten — übersprungen.", alert.id)
        return None

    rueckflug = angebot.rueckflug

    return {
        "price_alert_id": alert.id,
        "flight_observation_id": beobachtung_id,
        "offer_hash": bilde_offer_hash(angebot),
        "total_price_cents": angebot.preis_cents,
        "currency": angebot.waehrung,
        "validating_airline": angebot.validierende_airline,
        # Achtung: Ortszeit, nur als UTC etikettiert — siehe `ortszeit_als_utc`.
        "outbound_departure_at": ortszeit_als_utc(angebot.hinflug.abflug_lokal),
        "outbound_arrival_at": ortszeit_als_utc(angebot.hinflug.ankunft_lokal),
        "outbound_stops": angebot.hinflug.umstiege,
        "inbound_departure_at": (
            ortszeit_als_utc(rueckflug.abflug_lokal) if rueckflug is not None else None
        ),
        "inbound_arrival_at": (
            ortszeit_als_utc(rueckflug.ankunft_lokal) if rueckflug is not None else None
        ),
        "inbound_stops": rueckflug.umstiege if rueckflug is not None else None,
        "included_checked_bags": angebot.inkludierte_gepaeckstuecke,
        "segments": _segmente_als_json(angebot.hinflug) + _segmente_als_json(rueckflug),
        "raw_payload": angebot.rohdaten or None,
        "found_at": jetzt,
        "last_seen_at": jetzt,
    }


async def pruefe_faellige_alarme(
    session: AsyncSession,
    suche: Flugsuche,
    jetzt: datetime | None = None,
    limit: int = 20,
) -> LaufBericht:
    """Ein kompletter Durchgang: alle fälligen Alarme der Reihe nach prüfen.

    Nacheinander, nicht parallel — das Amadeus-Kontingent ist knapp und ein
    Prüflauf hat es nicht eilig.

    **Ein kaputter Alarm darf den Durchgang nicht beenden.** Deshalb fängt die
    Schleife alles ab, rollt die angefangene Transaktion zurück und macht mit
    dem nächsten Alarm weiter.
    """
    jetzt = jetzt or datetime.now(UTC)
    bericht = LaufBericht()

    alarme = await finde_faellige_alarme(session, jetzt, limit=limit)
    logger.info("Prüflauf: %d fällige Alarme.", len(alarme))

    # Nur die IDs merken und den Alarm gleich neu laden. Grund: Ein
    # `rollback()` im Fehlerfall setzt **alle** Objekte der Session auf
    # „abgelaufen". Der nächste Attributzugriff würde sie dann still
    # nachladen wollen — und stilles Nachladen ist im asynchronen Betrieb
    # nicht erlaubt (`MissingGreenlet`). Ein ausdrückliches `await` hier
    # macht das Nachladen sichtbar und legal.
    alarm_ids = [alert.id for alert in alarme]

    for alarm_id in alarm_ids:
        try:
            alert = await session.get(PriceAlert, alarm_id)
            if alert is None:
                # Der Nutzer hat den Alarm zwischen Abfrage und Lauf gelöscht.
                logger.info("Alarm %s ist verschwunden — übersprungen.", alarm_id)
                continue
            bericht.ergebnisse.append(await pruefe_alarm(session, alert, suche, jetzt))
        except Exception as exc:  # noqa: BLE001 — bewusst: Lauf weiterlaufen lassen
            logger.exception("Alarm %s: Lauf abgebrochen — %s", alarm_id, exc)
            await session.rollback()
            bericht.ergebnisse.append(
                LaufErgebnis(alarm_id=alarm_id, search_ok=False, fehler=str(exc))
            )

    return bericht
