"""Push-Benachrichtigungen — der letzte fehlende Teil der Kernfunktion.

Bis M7 fand die Anwendung gute Angebote, aber niemand erfuhr davon. Hier
passiert der Rest: entscheiden, *ob* gemeldet wird, den Text bauen und die
Nachricht rausschicken.

Aufbau wie in `amadeus.py`, `pruflauf.py` und `price_stats.py` — zwei Hälften:

1. **Reine Funktionen** (oben): Dedupe-Schlüssel, Textbaukasten, die Frage
   „darf jetzt gemeldet werden?". Ohne Datenbank, ohne Netz, direkt testbar.
2. **Versand und Protokoll** (unten): Ziele registrieren, Zeile schreiben,
   senden.

Der Versand steckt hinter dem Protokoll `PushVersand` — genau wie die
Flugsuche hinter `Flugsuche`. Dadurch prüfen die Tests die komplette
Melde-Logik mit einer Attrappe, und **kein Test geht ins Netz**.

## Drei Bremsen gegen Nachrichten-Spam

Ein Alarm mit großzügigem Limit fände bei jedem Prüflauf einen Treffer. Ohne
Bremsen käme alle sechs Stunden dieselbe Nachricht, und der Nutzer schaltet
die App stumm. Deshalb:

1. **Dedupe** — dasselbe Angebot wird nie zweimal gemeldet. Das ist eine
   **Datenbank-Garantie** (`UNIQUE` auf `dedupe_key`), keine Programmlogik:
   Selbst zwei gleichzeitige Läufe können physisch nur einmal einfügen.
2. **Abkühlphase** — höchstens eine Meldung je Alarm in sechs Stunden.
3. **5-%-Regel** — die Ausnahme davon: Ist der Preis deutlich besser als bei
   der letzten Meldung, darf die Abkühlphase übergangen werden.

Die Reihenfolge ist wichtig: Die Zeile in `notification_logs` wird
geschrieben, **bevor** gesendet wird (Status `pending`). Andernfalls klaffte
zwischen Versand und Protokoll eine Lücke, in der ein zweiter Lauf dieselbe
Nachricht noch einmal verschicken könnte.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import desc, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.device_token import DeviceToken
from app.models.notification_log import NotificationLog
from app.models.price_alert import PriceAlert
from app.schemas.flight_offer import Flugangebot
from app.services.claude import Texter, baue_fakten, pruefe_text
from app.services.price_stats import Einordnung, Preisbewertung

logger = logging.getLogger(__name__)

# Werte der Spalte `notification_logs.text_quelle`.
QUELLE_CLAUDE = "claude"
QUELLE_BAUKASTEN = "baukasten"


# ---------------------------------------------------------------------------
# Reine Funktionen — keine Datenbank, kein Netz
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Nachricht:
    """Was auf dem Sperrbildschirm erscheint."""

    titel: str
    text: str
    # Wohin der Klick führt (M9). Der Anker statt eines Pfads, weil die App
    # eine einzige HTML-Seite ist: Ein Pfad wie `/alarm/<id>` bräuchte einen
    # Server, der ihn auf `index.html` umschreibt — der Anker funktioniert
    # auch bei `python -m http.server`.
    url: str = "/"

    def als_json(self) -> str:
        return json.dumps(
            {"titel": self.titel, "text": self.text, "url": self.url}, ensure_ascii=False
        )


@dataclass(frozen=True)
class LetzteMeldung:
    """Die vorige Meldung dieses Alarms — Grundlage für die beiden Bremsen."""

    sent_at: datetime
    price_cents: int


def bilde_dedupe_key(price_alert_id: uuid.UUID, offer_hash: str) -> str:
    """Die Kennung, die ein zweites Melden desselben Angebots verhindert.

    Aus Alarm **und** Angebot, nicht nur aus dem Angebot: Zwei Nutzer, die
    beide MUC→BCN beobachten, sollen beide ihre Nachricht bekommen.

    Der `offer_hash` enthält bereits den Preis (siehe `bilde_offer_hash` in
    `pruflauf.py`). Wird derselbe Flug billiger, ist er damit automatisch ein
    neuer Fund — und wieder meldenswert.

    SHA-256 als Hex ist 64 Zeichen lang und passt genau in
    `notification_logs.dedupe_key` (`String(64)`).
    """
    return hashlib.sha256(f"{price_alert_id}|{offer_hash}".encode()).hexdigest()


def darf_melden(
    preis_cents: int,
    letzte: LetzteMeldung | None,
    jetzt: datetime,
    abkuehlphase_stunden: int,
    mindest_verbesserung_prozent: float,
) -> bool:
    """Abkühlphase und 5-%-Regel — die zweite und dritte Bremse.

    * Noch nie gemeldet → immer melden.
    * Abkühlphase vorbei → melden.
    * Noch in der Abkühlphase → nur, wenn der Preis deutlich besser ist.

    „Deutlich" heißt: mindestens `mindest_verbesserung_prozent` unter dem
    zuletzt gemeldeten Preis. 2 € weniger sind keine zweite Nachricht wert,
    40 € weniger schon.
    """
    if letzte is None:
        return True

    seit = letzte.sent_at
    if seit.tzinfo is None:
        # Die Spalte ist `timestamptz`; hier kann eigentlich nichts Naives
        # ankommen. Falls doch (Testdaten, SQL-Konsole): als UTC lesen, statt
        # beim Vergleich mit einer Ausnahme auszusteigen.
        seit = seit.replace(tzinfo=UTC)

    if jetzt - seit >= timedelta(hours=abkuehlphase_stunden):
        return True

    if letzte.price_cents <= 0:
        return False

    verbesserung = (letzte.price_cents - preis_cents) / letzte.price_cents * 100
    return verbesserung >= mindest_verbesserung_prozent


def _euro(cents: int, waehrung: str = "EUR") -> str:
    """1899 → „18,99 €". Bewusst ohne `locale` — das hängt vom Betriebssystem ab."""
    zeichen = {"EUR": "€", "USD": "$", "GBP": "£"}.get(waehrung, waehrung)
    return f"{cents // 100},{cents % 100:02d} {zeichen}"


def formuliere_nachricht(
    alert: PriceAlert, angebot: Flugangebot, bewertung: Preisbewertung
) -> Nachricht:
    """Der deterministische Satz-Baukasten.

    **Hier formuliert Python, nicht Claude** (Leitplanke 3). Seit M10 schreibt
    Claude den Text im Normalfall schöner — und genau dieser Baukasten ist
    dann der Rückfall, wenn der Anthropic-Aufruf scheitert. Die Push geht
    immer raus, notfalls mit diesem Text.

    Der Ton richtet sich nach der Einordnung aus M7. Wichtig ist der Fall
    `ZU_WENIG_DATEN`: Dann wird **keine Prozentzahl erfunden**, sondern
    ehrlich gesagt, dass es der erste Treffer unter dem Limit ist.
    """
    preis = _euro(angebot.preis_cents, angebot.waehrung)
    titel = f"{alert.origin} → {alert.destination} für {preis}"

    if bewertung.ist_bestpreis:
        kern = f"{preis} — günstigster Preis, den wir für diese Strecke gesehen haben."
    elif bewertung.einordnung is Einordnung.ZU_WENIG_DATEN:
        limit = _euro(alert.max_price_cents, alert.currency)
        kern = f"{preis} — erster Treffer unter deinem Limit von {limit}."
    elif bewertung.einordnung is Einordnung.GUENSTIG:
        assert bewertung.abweichung_prozent is not None  # hat_aussage garantiert das
        kern = f"{preis} — {abs(bewertung.abweichung_prozent):.0f} % unter dem üblichen Preis."
    elif bewertung.einordnung is Einordnung.TEUER:
        assert bewertung.abweichung_prozent is not None
        kern = (
            f"{preis} — unter deinem Limit, aber "
            f"{bewertung.abweichung_prozent:.0f} % über dem üblichen Preis."
        )
    else:
        kern = f"{preis} — etwa im üblichen Rahmen für diese Strecke."

    # Ein, zwei harte Fakten dazu; auf dem Sperrbildschirm ist wenig Platz.
    teile: list[str] = []
    if angebot.maximale_umstiege == 0:
        teile.append("Direktflug")
    elif angebot.maximale_umstiege == 1:
        teile.append("1 Umstieg")
    else:
        teile.append(f"{angebot.maximale_umstiege} Umstiege")

    if angebot.validierende_airline:
        teile.append(angebot.validierende_airline)

    return Nachricht(
        titel=titel,
        text=f"{kern} {' · '.join(teile)}",
        # Tippt der Nutzer auf die Nachricht, landet er direkt bei diesem
        # Alarm — nicht auf einer Liste, in der er ihn erst suchen muss.
        url=f"/#alarm={alert.id}",
    )


def formuliere_einordnungssatz(bewertung: Preisbewertung, waehrung: str = "EUR") -> str:
    """Derselbe Baukasten für die Detailansicht (M10).

    Bis M9 baute `web/detail.js` diesen Satz im Browser zusammen. Das war ein
    Riss in Leitplanke 1 („der Client bewertet nichts") und außerdem eine
    zweite Stelle, an der dieselbe Aussage in anderen Worten stand. Jetzt
    kommt der Satz aus dem Backend — und derselbe Text kann von Claude
    stammen, wenn zu diesem Preis schon einmal gemeldet wurde.

    Ohne Preisangabe, anders als in der Push: In der Detailansicht steht der
    Preis bereits groß darüber.
    """
    if bewertung.ist_bestpreis:
        return "Günstigster Preis, den wir für diese Strecke bisher gesehen haben."

    if bewertung.einordnung is Einordnung.ZU_WENIG_DATEN:
        return (
            f"Für einen Vergleich fehlen noch Daten ({bewertung.datenpunkte} Beobachtungen). "
            "Sobald genug zusammengekommen ist, siehst du hier, ob der Preis gut ist."
        )

    assert bewertung.median_cents is not None  # hat_aussage garantiert das
    assert bewertung.abweichung_prozent is not None
    median = _euro(bewertung.median_cents, waehrung)
    abweichung = abs(bewertung.abweichung_prozent)

    if bewertung.einordnung is Einordnung.GUENSTIG:
        return (
            f"{abweichung:.0f} % unter dem üblichen Preis für diese Strecke (sonst etwa {median})."
        )
    if bewertung.einordnung is Einordnung.TEUER:
        return (
            f"{abweichung:.0f} % über dem üblichen Preis (sonst etwa {median}) — "
            "aber unter deinem Limit."
        )
    return f"Etwa im üblichen Rahmen für diese Strecke (Median {median})."


async def erzeuge_nachricht(
    alert: PriceAlert,
    angebot: Flugangebot,
    bewertung: Preisbewertung,
    texter: Texter | None,
) -> tuple[Nachricht, str]:
    """Den Text besorgen — von Claude, sonst aus dem Baukasten.

    Gibt die Nachricht und die Quelle zurück (`claude` oder `baukasten`).

    **Diese Funktion wirft nicht.** Das ist ihr eigentlicher Zweck: Sie ist
    die Stelle, an der Leitplanke 3 („fällt Claude aus, funktioniert die
    Kernfunktion per Fallback weiter") durchgesetzt wird. Jeder denkbare
    Fehler — kein Guthaben, falscher Schlüssel, Rate Limit, Zeitüberschreitung,
    kaputtes JSON, erfundene Zahl — endet hier im selben Zweig: Baukasten,
    Logzeile, weiter.

    Deshalb steht hier ein nacktes `except Exception`. Sonst müsste jede
    Ausnahmeklasse des SDK einzeln aufgezählt werden, und die eine vergessene
    wäre genau die, die nachts um drei die Benachrichtigung verschluckt.

    Titel und Ziel-Adresse übernimmt bewusst **immer** der Baukasten für den
    Fall, dass Claude ausfällt — die URL ist Technik, kein Text, und der
    Baukasten-Titel ist der garantierte Rückfall.
    """
    baukasten = formuliere_nachricht(alert, angebot, bewertung)
    if texter is None:
        return baukasten, QUELLE_BAUKASTEN

    fakten = baue_fakten(alert, angebot, bewertung)
    try:
        erklaerung = await texter.erklaere(fakten)
    except Exception as exc:  # noqa: BLE001 — siehe Docstring: absichtlich alles
        logger.warning("Claude-Text nicht verfügbar (%s) — Baukasten übernimmt.", exc)
        return baukasten, QUELLE_BAUKASTEN

    grund = pruefe_text(erklaerung, fakten)
    if grund is not None:
        logger.warning("Claude-Text verworfen (%s) — Baukasten übernimmt.", grund)
        return baukasten, QUELLE_BAUKASTEN

    return (
        Nachricht(titel=erklaerung.titel, text=erklaerung.text, url=baukasten.url),
        QUELLE_CLAUDE,
    )


# ---------------------------------------------------------------------------
# Der Versand — austauschbar, damit kein Test ins Netz geht
# ---------------------------------------------------------------------------


class PushFehler(Exception):
    """Versand fehlgeschlagen. `status_code` ist die Antwort des Push-Dienstes."""

    def __init__(self, meldung: str, status_code: int | None = None) -> None:
        super().__init__(meldung)
        self.status_code = status_code

    @property
    def ziel_ist_tot(self) -> bool:
        """404/410 heißt: Erlaubnis entzogen oder App entfernt — nie wieder senden."""
        return self.status_code in (404, 410)


class PushVersand(Protocol):
    """Was der Prüflauf vom Versand braucht — mehr nicht.

    Dasselbe Muster wie `Flugsuche`: Die Melde-Logik kennt nur diese eine
    Methode, deshalb kann der Test eine Attrappe einsetzen.
    """

    async def sende(self, ziel: DeviceToken, nachricht: Nachricht) -> None: ...


class WebPushVersand:
    """Der echte Versand über `pywebpush`.

    Zwei Dinge, die man wissen muss:

    * **Wir schicken nie direkt ans Gerät.** Die Nachricht geht an den
      Push-Dienst des Browserherstellers (die `endpoint`-URL), der sie
      weiterreicht. Verschlüsselt mit `p256dh` und `auth`, sodass der Dienst
      den Inhalt nicht mitlesen kann.
    * **`pywebpush` ist synchron** (es benutzt `requests`). Ein direkter
      Aufruf würde die komplette Ereignisschleife des Workers blockieren,
      solange die Anfrage läuft. Deshalb landet er über
      `anyio.to_thread.run_sync` in einem Hintergrund-Thread.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def sende(self, ziel: DeviceToken, nachricht: Nachricht) -> None:
        import anyio
        from pywebpush import WebPushException, webpush

        subscription = {
            "endpoint": ziel.endpoint,
            "keys": {"p256dh": ziel.p256dh, "auth": ziel.auth},
        }

        def _senden() -> None:
            webpush(
                subscription_info=subscription,
                data=nachricht.als_json(),
                vapid_private_key=self._settings.vapid_private_key,
                vapid_claims={"sub": self._settings.vapid_subject},
                timeout=10,
            )

        try:
            await anyio.to_thread.run_sync(_senden)
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            raise PushFehler(str(exc), status_code=status) from exc
        except Exception as exc:  # noqa: BLE001 — Netzfehler dürfen den Lauf nicht killen
            raise PushFehler(f"Versand fehlgeschlagen: {exc}") from exc


# ---------------------------------------------------------------------------
# Datenbank: Ziele verwalten und melden
# ---------------------------------------------------------------------------


async def registriere_ziel(
    session: AsyncSession, user_id: uuid.UUID, endpoint: str, p256dh: str, auth: str
) -> DeviceToken:
    """Eine Subscription anlegen oder auffrischen.

    Per Upsert auf `endpoint`, weil der Browser dieselbe Subscription bei
    jedem Seitenaufruf erneut anbietet. Ohne Upsert stünde dasselbe Gerät nach
    einer Woche zwanzigmal in der Tabelle — und jede Meldung käme zwanzigmal an.

    Der `user_id` wandert bewusst mit: Ein Gerät kann den Besitzer wechseln
    (geteilter Laptop). Und `is_active` wird wieder auf `true` gesetzt — wer
    neu abonniert, will offensichtlich wieder Nachrichten.
    """
    jetzt = datetime.now(UTC)
    stmt = (
        pg_insert(DeviceToken)
        .values(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            platform="web",
            last_seen_at=jetzt,
            is_active=True,
        )
        .on_conflict_do_update(
            constraint="uq_tokens_endpoint",
            set_={
                "user_id": user_id,
                "p256dh": p256dh,
                "auth": auth,
                "last_seen_at": jetzt,
                "is_active": True,
            },
        )
        .returning(DeviceToken)
    )
    # `populate_existing`: Kennt die Session dieselbe Zeile schon (weil sie in
    # diesem Request bereits geladen oder geändert wurde), gäbe SQLAlchemy
    # sonst das **alte** Objekt aus der Identity Map zurück — mit dem alten
    # `is_active`, obwohl in der Datenbank längst der neue Wert steht. Genau
    # das ist beim Wiederanmelden eines stillgelegten Ziels aufgefallen.
    ergebnis = await session.execute(stmt, execution_options={"populate_existing": True})
    await session.commit()
    return ergebnis.scalar_one()


async def entferne_ziel(session: AsyncSession, user_id: uuid.UUID, endpoint: str) -> bool:
    """Abbestellen. Gibt zurück, ob überhaupt etwas passiert ist.

    `user_id` steht in der WHERE-Klausel, nicht in einer nachgelagerten
    Prüfung — dieselbe Regel wie bei den Alarmen: Fremdes ist unsichtbar,
    nicht verboten.
    """
    ergebnis = await session.execute(
        update(DeviceToken)
        .where(DeviceToken.user_id == user_id, DeviceToken.endpoint == endpoint)
        .values(is_active=False)
        .returning(DeviceToken.id)
    )
    getroffen = ergebnis.scalar_one_or_none() is not None
    await session.commit()
    return getroffen


async def hole_letzte_meldung(
    session: AsyncSession, price_alert_id: uuid.UUID
) -> LetzteMeldung | None:
    """Die jüngste Meldung dieses Alarms — für Abkühlphase und 5-%-Regel.

    `pending` zählt mit: Eine Zeile, die gerade erst beansprucht wurde, ist so
    gut wie gesendet. Nur `failed` zählt nicht — was nie ankam, darf die
    nächste Meldung nicht blockieren.
    """
    ergebnis = await session.execute(
        select(NotificationLog.sent_at, NotificationLog.price_cents)
        .where(
            NotificationLog.price_alert_id == price_alert_id,
            NotificationLog.status.in_(("pending", "sent")),
        )
        .order_by(desc(NotificationLog.sent_at))
        .limit(1)
    )
    zeile = ergebnis.first()
    return None if zeile is None else LetzteMeldung(sent_at=zeile[0], price_cents=zeile[1])


@dataclass
class MeldeErgebnis:
    """Was bei einem Meldeversuch herauskam."""

    gemeldet: bool
    grund: str
    zugestellt: int = 0
    fehlgeschlagen: int = 0


async def melde_treffer(
    session: AsyncSession,
    alert: PriceAlert,
    angebot: Flugangebot,
    offer_hash: str,
    flight_offer_id: uuid.UUID,
    bewertung: Preisbewertung,
    versand: PushVersand,
    settings: Settings,
    jetzt: datetime | None = None,
    texter: Texter | None = None,
) -> MeldeErgebnis:
    """Ein Treffer wird zur Nachricht — oder eben nicht.

    Die Reihenfolge ist der eigentliche Inhalt dieser Funktion:

    1. Abkühlphase und 5-%-Regel prüfen (billig, im Speicher).
    2. Zeile mit Status `pending` einfügen — `ON CONFLICT DO NOTHING`.
       **Kommt keine Zeile zurück, war das Angebot schon gemeldet.** Das ist
       die Dedupe-Mauer, und sie steht in der Datenbank, nicht hier.
    3. Erst *danach* den Text holen (M10: Claude) und senden. Beides ist
       langsam und geht über das Netz — der Platz im UNIQUE-Index muss vorher
       belegt sein, sonst könnte ein paralleler Lauf in dieser Lücke dieselbe
       Nachricht ein zweites Mal verschicken.
    4. Ergebnis und Text nachtragen.

    Ohne `texter` verhält sich alles wie in M8/M9: Der Baukasten formuliert.

    Wirft nicht: Versandfehler landen im Protokoll und im Rückgabewert.
    """
    jetzt = jetzt or datetime.now(UTC)

    letzte = await hole_letzte_meldung(session, alert.id)
    if not darf_melden(
        angebot.preis_cents,
        letzte,
        jetzt,
        settings.push_abkuehlphase_stunden,
        settings.push_mindest_verbesserung_prozent,
    ):
        return MeldeErgebnis(gemeldet=False, grund="abkuehlphase")

    dedupe_key = bilde_dedupe_key(alert.id, offer_hash)

    stmt = (
        pg_insert(NotificationLog)
        .values(
            user_id=alert.user_id,
            price_alert_id=alert.id,
            flight_offer_id=flight_offer_id,
            dedupe_key=dedupe_key,
            price_cents=angebot.preis_cents,
            sent_at=jetzt,
            status="pending",
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(NotificationLog.id)
    )
    ergebnis = await session.execute(stmt)
    log_id = ergebnis.scalar_one_or_none()

    if log_id is None:
        return MeldeErgebnis(gemeldet=False, grund="schon_gemeldet")

    # Den Platz sofort festschreiben — vor dem langsamen Teil.
    await session.commit()

    nachricht, quelle = await erzeuge_nachricht(alert, angebot, bewertung, texter)
    zugestellt, fehlgeschlagen, letzter_fehler, letzter_code = await _sende_an_alle_ziele(
        session, alert.user_id, nachricht, versand
    )

    if zugestellt > 0:
        status = "sent"
    elif fehlgeschlagen == 0:
        # Niemand hat Benachrichtigungen erlaubt — kein Fehler, nur nichts zu tun.
        status = "failed"
        letzter_fehler = "Kein Gerät für Benachrichtigungen registriert."
    else:
        status = "token_invalid" if letzter_code in (404, 410) else "failed"

    await session.execute(
        update(NotificationLog)
        .where(NotificationLog.id == log_id)
        .values(
            status=status,
            push_status_code=letzter_code,
            push_error=letzter_fehler,
            # Der Text wird auch dann festgehalten, wenn niemand ihn bekommen
            # hat: Beim Nachforschen ist gerade die *nicht* zugestellte
            # Nachricht die interessante.
            title=nachricht.titel[:120],
            body=nachricht.text[:400],
            text_quelle=quelle,
        )
    )
    await session.commit()

    logger.info(
        "Alarm %s: Meldung %s (%s) — %d zugestellt, %d fehlgeschlagen.",
        alert.id,
        status,
        quelle,
        zugestellt,
        fehlgeschlagen,
    )
    return MeldeErgebnis(
        gemeldet=zugestellt > 0,
        grund=status,
        zugestellt=zugestellt,
        fehlgeschlagen=fehlgeschlagen,
    )


async def _sende_an_alle_ziele(
    session: AsyncSession,
    user_id: uuid.UUID,
    nachricht: Nachricht,
    versand: PushVersand,
) -> tuple[int, int, str | None, int | None]:
    """An jedes aktive Gerät des Nutzers senden; tote Ziele stilllegen."""
    ergebnis = await session.execute(
        select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True))
    )
    ziele = list(ergebnis.scalars().all())

    zugestellt = 0
    fehlgeschlagen = 0
    letzter_fehler: str | None = None
    letzter_code: int | None = None

    for ziel in ziele:
        try:
            await versand.sende(ziel, nachricht)
            zugestellt += 1
        except PushFehler as exc:
            fehlgeschlagen += 1
            letzter_fehler = str(exc)[:500]
            letzter_code = exc.status_code

            if exc.ziel_ist_tot:
                # Der Nutzer hat die Erlaubnis entzogen oder die App entfernt.
                # Weiterversuchen wäre sinnlos und würde bei jedem Lauf Zeit
                # kosten.
                ziel.is_active = False
                logger.info("Ziel %s stillgelegt (%s).", ziel.id, exc.status_code)
            else:
                logger.warning("Push an %s fehlgeschlagen: %s", ziel.id, exc)

    return zugestellt, fehlgeschlagen, letzter_fehler, letzter_code
