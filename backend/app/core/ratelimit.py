"""Rate Limiting (M12) — wie oft darf jemand anklopfen?

Ohne Bremse ist jeder Endpunkt eine offene Rechnung. `POST /alerts/entwurf`
ruft Claude auf, `POST /alerts` schreibt in die Datenbank, und ein Skript, das
in einer Schleife läuft, merkt von beidem nichts.

## Bewusst im Arbeitsspeicher, nicht in Redis

Dieselbe Entscheidung wie beim Scheduler in M6: **einfach anfangen, wachsen,
wenn nötig.** Ein Wörterbuch im Prozess braucht keine zusätzliche
Infrastruktur, kein Deployment und keine Konfiguration.

Der Preis dafür ist bekannt und muss benannt werden:

* **Bei zwei API-Instanzen zählt jede für sich.** Aus „10 pro Stunde" werden
  faktisch 20. Solange genau ein Prozess läuft — und das ist beim geplanten
  Hoster der Fall — stimmt die Zahl.
* **Ein Neustart setzt alle Zähler zurück.** Wer ein Deployment abwartet,
  bekommt ein frisches Kontingent.

Beides ist für ein Lernprojekt in Ordnung, und beides wäre mit Redis gelöst.
Der Umbau beträfe genau dieses Modul: `Zaehler` bekäme eine andere Ablage,
die Endpunkte merken nichts davon.

## Was gezählt wird

Ein **gleitendes Fenster**: Zu jedem Schlüssel steht eine Liste von
Zeitpunkten; abgelaufene fallen vorne heraus. Das ist genauer als das
einfachere „feste Fenster", bei dem jemand an der Stundengrenze das doppelte
Kontingent bekäme (59 Anfragen um 10:59, 59 weitere um 11:00).

Gezählt wird nach **Nutzer**, nicht nach IP-Adresse. Eine IP kann ein ganzes
Studentenwohnheim sein; die Nutzer-ID trifft genau den, der es übertreibt.
Für unangemeldete Anfragen gibt es hier nichts zu begrenzen — sie kommen
ohnehin nicht an den Endpunkten vorbei.
"""

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, status

from app.api.deps import CurrentUser


class Zaehler:
    """Ein gleitendes Fenster je Schlüssel.

    Absichtlich ohne Hintergrundaufräumer: Alte Zeitpunkte werden **beim
    Nachsehen** verworfen. Ein zusätzlicher Timer wäre ein zweiter Ort, an dem
    etwas schiefgehen kann, für eine Datenmenge, die im Bereich weniger
    tausend Zahlen liegt.

    Was wirklich wachsen kann, ist die Zahl der *Schlüssel* — bei sehr vielen
    Nutzern also der Speicher. `aufraeumen()` entfernt leere Einträge; der
    Aufrufer entscheidet, wann.
    """

    def __init__(self, grenze: int, fenster_sekunden: float) -> None:
        self.grenze = grenze
        self.fenster = fenster_sekunden
        self._treffer: dict[str, list[float]] = defaultdict(list)

    def darf(self, schluessel: str, jetzt: float | None = None) -> bool:
        """Ist noch Kontingent übrig? Zählt den Versuch gleich mit.

        Gibt `False` zurück, **ohne** den Versuch zu zählen: Sonst könnte sich
        niemand mehr freischwimmen, der einmal über die Grenze gekommen ist —
        jeder abgelehnte Aufruf würde das Fenster erneut verlängern.
        """
        jetzt = time.monotonic() if jetzt is None else jetzt
        grenze_zeit = jetzt - self.fenster

        zeitpunkte = self._treffer[schluessel]
        # Abgelaufene vorne abschneiden. Die Liste ist aufsteigend sortiert,
        # weil immer nur hinten angehängt wird.
        while zeitpunkte and zeitpunkte[0] <= grenze_zeit:
            zeitpunkte.pop(0)

        if len(zeitpunkte) >= self.grenze:
            return False

        zeitpunkte.append(jetzt)
        return True

    def wartezeit_sekunden(self, schluessel: str, jetzt: float | None = None) -> int:
        """Wie lange, bis wieder etwas frei wird? Für den `Retry-After`-Kopf.

        Aufgerundet: Lieber eine Sekunde zu viel warten lassen, als den
        Aufrufer exakt in den nächsten abgelehnten Versuch zu schicken.
        """
        zeitpunkte = self._treffer.get(schluessel)
        if not zeitpunkte:
            return 0
        jetzt = time.monotonic() if jetzt is None else jetzt
        rest = zeitpunkte[0] + self.fenster - jetzt
        return max(1, int(rest) + 1) if rest > 0 else 0

    def aufraeumen(self, jetzt: float | None = None) -> int:
        """Leere Schlüssel entfernen. Gibt die Zahl der entfernten zurück."""
        jetzt = time.monotonic() if jetzt is None else jetzt
        grenze_zeit = jetzt - self.fenster
        leer = [
            schluessel
            for schluessel, zeitpunkte in self._treffer.items()
            if not zeitpunkte or zeitpunkte[-1] <= grenze_zeit
        ]
        for schluessel in leer:
            del self._treffer[schluessel]
        return len(leer)

    def zuruecksetzen(self) -> None:
        """Nur für Tests — im Betrieb setzt allein ein Neustart zurück."""
        self._treffer.clear()


# Zwei Zähler mit sehr verschiedenen Grenzen, und der Unterschied hat einen
# Grund: Die normale Nutzung kostet uns fast nichts, ein Claude-Aufruf kostet
# Geld. Eine einzige gemeinsame Grenze müsste sich am teuersten Endpunkt
# orientieren und wäre für den Rest lästig.
allgemein = Zaehler(grenze=120, fenster_sekunden=60)
teuer = Zaehler(grenze=15, fenster_sekunden=3600)


def begrenze(zaehler: Zaehler, name: str) -> Callable[[CurrentUser], None]:
    """Baut eine Dependency, die einen Zähler bewacht.

    Als Fabrik statt fester Funktionen, damit ein weiterer Endpunkt mit
    eigener Grenze eine Zeile ist und keine Kopie.

    HTTP **429** mit `Retry-After` — das ist der Statuscode, den Clients und
    Zwischenschichten für „zu oft" erwarten. Der Text ist deutsch und nennt
    die Wartezeit, damit der Nutzer nicht raten muss.
    """

    def pruefe(user: CurrentUser) -> None:
        schluessel = f"{name}:{user.id}"
        if zaehler.darf(schluessel):
            return

        warten = zaehler.wartezeit_sekunden(schluessel)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Anfragen. Bitte warte etwa {_lesbar(warten)} und versuche es erneut.",
            headers={"Retry-After": str(warten)},
        )

    return pruefe


def _lesbar(sekunden: int) -> str:
    """`90` → „2 Minuten". Niemand rechnet gern Sekunden in Minuten um."""
    if sekunden < 60:
        return f"{sekunden} Sekunden"
    minuten = (sekunden + 59) // 60
    if minuten == 1:
        return "eine Minute"
    if minuten < 60:
        return f"{minuten} Minuten"
    stunden = (minuten + 59) // 60
    return "eine Stunde" if stunden == 1 else f"{stunden} Stunden"
