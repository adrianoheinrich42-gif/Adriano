// Alle Aufrufe an das **eigene** Backend an einer Stelle.
//
// Der Rest der App ruft nie selbst `fetch` auf. Dadurch gibt es genau einen
// Ort, der das Token anhängt, Zeitüberschreitungen abfängt und aus einem
// Statuscode einen deutschen Satz macht — Regel aus CLAUDE.md: Der Nutzer
// sieht nie eine Zahl wie „422".

import { AppConfig } from "./config.js";
import { holeToken } from "./auth.js";

// Ohne eigenen Zeitgeber wartet `fetch` sehr lange, wenn der Server zwar
// erreichbar ist, aber nicht antwortet. 15 Sekunden sind großzügig.
const ZEITLIMIT_MS = 15000;

/** Die Sitzung ist abgelaufen — die App muss zurück zur Anmeldung. */
export class SitzungAbgelaufen extends Error {}

/** Alles andere, was schiefgehen kann. `text` ist bereits deutsch. */
export class ApiFehler extends Error {}

function feldFehlerLesbar(detail) {
  // FastAPI schickt bei 422 eine Liste. Es gibt zwei Sorten Eintrag:
  //
  //  a) Ein einzelnes Feld passt nicht:
  //       {loc: ["body", "origin"], msg: "String should have at least 3 ..."}
  //     Die Meldung ist Pydantics englischer Standardtext — unbrauchbar. Wir
  //     benennen stattdessen das Feld auf Deutsch.
  //
  //  b) Die Kombination passt nicht (`model_validator` im Backend):
  //       {loc: ["body"], msg: "Value error, Start- und Zielflughafen ..."}
  //     Hier steht der fertige deutsche Satz schon drin — den nehmen wir,
  //     denn „prüfe das Feld body" hilft niemandem.
  const namen = {
    origin: "Abflughafen",
    destination: "Zielflughafen",
    earliest_departure_date: "frühester Hinflug",
    latest_return_date: "spätester Rückflug",
    min_trip_duration_days: "Mindestdauer",
    max_trip_duration_days: "Höchstdauer",
    max_price_cents: "Höchstpreis",
    max_stops: "Umstiege",
    adults: "Reisende",
    currency: "Währung",
    check_interval_minutes: "Prüfintervall",
  };

  if (!Array.isArray(detail) || detail.length === 0) return null;

  // Fall b) hat Vorrang: Ein fertiger Satz schlägt jede Feldaufzählung.
  const ganzesFormular = detail.find(
    (eintrag) => Array.isArray(eintrag?.loc) && eintrag.loc.length <= 1 && eintrag?.msg,
  );
  if (ganzesFormular) {
    // Pydantic stellt „Value error, " voran — das will der Nutzer nicht lesen.
    return ganzesFormular.msg.replace(/^Value error,\s*/i, "");
  }

  const felder = [
    ...new Set(
      detail
        .map((eintrag) => eintrag?.loc?.[eintrag.loc.length - 1])
        .filter((feld) => typeof feld === "string" && feld !== "body")
        .map((feld) => namen[feld] ?? feld),
    ),
  ];

  if (felder.length === 0) return null;
  if (felder.length === 1) return `Bitte prüfe das Feld „${felder[0]}".`;
  return `Bitte prüfe diese Felder: ${felder.join(", ")}.`;
}

async function fehlerAusAntwort(antwort) {
  const koerper = await antwort.json().catch(() => null);
  const detail = koerper?.detail;

  if (antwort.status === 422) {
    // Das Backend schickt bei zusammengesetzten Regeln (z. B. „Rückflug liegt
    // vor dem Hinflug") einen fertigen deutschen Satz als Text.
    if (typeof detail === "string") return new ApiFehler(detail);
    return new ApiFehler(feldFehlerLesbar(detail) ?? "Die Eingaben passen so nicht zusammen.");
  }
  if (antwort.status === 409) {
    return new ApiFehler(
      typeof detail === "string"
        ? detail
        : "Du hast bereits die höchstmögliche Zahl aktiver Alarme.",
    );
  }
  if (antwort.status === 404) {
    return new ApiFehler("Dieser Alarm existiert nicht mehr.");
  }
  if (antwort.status >= 500) {
    return new ApiFehler("Auf dem Server ist etwas schiefgelaufen. Bitte später erneut.");
  }
  return new ApiFehler("Die Anfrage hat nicht geklappt. Bitte versuche es noch einmal.");
}

/**
 * Ein Aufruf an das Backend — mit Token, Zeitlimit und deutschen Fehlern.
 *
 * `ohneToken` ist für `/health`: Der Endpunkt braucht keine Anmeldung, und
 * der Verbindungstest soll auch vor dem Login funktionieren.
 */
async function rufeAuf(pfad, { methode = "GET", daten = null, ohneToken = false } = {}) {
  const kopf = { Accept: "application/json" };

  if (!ohneToken) {
    const token = await holeToken();
    if (!token) throw new SitzungAbgelaufen("Bitte melde dich erneut an.");
    kopf.Authorization = `Bearer ${token}`;
  }
  if (daten !== null) kopf["Content-Type"] = "application/json";

  const abbruch = new AbortController();
  const zeitgeber = setTimeout(() => abbruch.abort(), ZEITLIMIT_MS);

  let antwort;
  try {
    antwort = await fetch(`${AppConfig.apiBaseURL}${pfad}`, {
      method: methode,
      headers: kopf,
      body: daten === null ? undefined : JSON.stringify(daten),
      signal: abbruch.signal,
    });
  } catch (fehler) {
    if (fehler.name === "AbortError") {
      throw new ApiFehler("Der Server antwortet gerade nicht. Bitte versuche es noch einmal.");
    }
    // Auch eine fehlende CORS-Freigabe landet hier — deshalb der Hinweis.
    throw new ApiFehler(
      "Keine Verbindung zum Server. Läuft das Backend, und stimmt die Adresse in config.js?",
    );
  } finally {
    clearTimeout(zeitgeber);
  }

  if (antwort.status === 401) {
    throw new SitzungAbgelaufen("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
  }
  if (!antwort.ok) {
    throw await fehlerAusAntwort(antwort);
  }
  if (antwort.status === 204) return null;

  return antwort.json();
}

// --- Die Endpunkte, die die App benutzt -------------------------------------

export const Api = {
  status: () => rufeAuf("/health", { ohneToken: true }),
  ich: () => rufeAuf("/me"),
  alarme: () => rufeAuf("/alerts"),
  alarmAnlegen: (daten) => rufeAuf("/alerts", { methode: "POST", daten }),
  alarmAendern: (id, daten) => rufeAuf(`/alerts/${id}`, { methode: "PATCH", daten }),
  alarmLoeschen: (id) => rufeAuf(`/alerts/${id}`, { methode: "DELETE" }),
};
