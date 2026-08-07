// Die Web-App: anmelden, Alarme anzeigen, Alarm anlegen und löschen.
//
// Aufbau bewusst schlicht — kein Framework, kein Node (CLAUDE.md). Die App
// hat genau zwei Ansichten (angemeldet / nicht angemeldet) und rendert die
// Liste bei jeder Änderung neu. Bei fünf Alarmen ist das schnell genug, und
// es gibt keinen Zustand, der auseinanderlaufen kann.
//
// **Der Client bewertet nichts.** Er zeigt an, was das Backend schickt, und
// schickt Formulare hin — Leitplanke 1. Ob ein Preis gut ist, entscheidet
// `services/price_stats.py`, nicht diese Datei.

import { Api, ApiFehler, SitzungAbgelaufen } from "./api.js";
import {
  AnmeldeFehler,
  angemeldeteEmail,
  istAngemeldet,
  melde_ab,
  melde_an,
  registriere,
} from "./auth.js";
import {
  centNachEuro,
  datumLesbar,
  euroNachCent,
  strecke,
  umstiegeLesbar,
  zeitpunktLesbar,
} from "./format.js";
import {
  PushFehler,
  erlaubnisStatus,
  frischeAuf,
  istAbonniert,
  schalteAus,
  schalteEin,
  warumNichtVerfuegbar,
} from "./push.js";

const $ = (id) => document.getElementById(id);

// --- Ansichten umschalten ---------------------------------------------------

function zeigeAnsicht(name) {
  $("ansichtLaden").hidden = name !== "laden";
  $("ansichtAnmeldung").hidden = name !== "anmeldung";
  $("ansichtAlarme").hidden = name !== "alarme";
  $("kopf").hidden = name !== "alarme";
}

function zeigeFehler(element, text) {
  element.textContent = text;
  element.hidden = !text;
}

/**
 * Fehler einheitlich behandeln.
 *
 * Eine abgelaufene Sitzung ist kein Fehler zum Anzeigen, sondern ein Grund
 * zurück zur Anmeldung — sonst starrt der Nutzer auf eine leere Liste und
 * eine Meldung, mit der er nichts anfangen kann.
 */
function behandle(fehler, ziel) {
  if (fehler instanceof SitzungAbgelaufen) {
    zeigeAnmeldung(fehler.message);
    return;
  }
  if (
    fehler instanceof ApiFehler ||
    fehler instanceof AnmeldeFehler ||
    fehler instanceof PushFehler
  ) {
    zeigeFehler(ziel, fehler.message);
    return;
  }
  // Unerwartetes nicht verschlucken: in der Konsole für die Entwicklung, als
  // allgemeiner Satz für den Nutzer.
  console.error(fehler);
  zeigeFehler(ziel, "Da ist etwas schiefgelaufen. Bitte lade die Seite neu.");
}

// --- Anmeldung --------------------------------------------------------------

function zeigeAnmeldung(meldung = "") {
  zeigeAnsicht("anmeldung");
  zeigeFehler($("anmeldeFehler"), meldung);
  $("anmeldeHinweis").hidden = true;
  pruefeServer();
}

/**
 * Vor dem Login einmal `/health` abfragen.
 *
 * Der häufigste Anfängerfehler ist ein nicht gestartetes Backend. Dann sagt
 * die Seite das hier direkt, statt den Nutzer erst am Login scheitern zu
 * lassen — wo die Meldung nach einem falschen Passwort aussähe.
 */
async function pruefeServer() {
  const ziel = $("serverStatus");
  ziel.textContent = "Prüfe Verbindung zum Server …";
  try {
    const status = await Api.status();
    ziel.textContent =
      status.database === "ok"
        ? "Server erreichbar."
        : "Server erreichbar, aber ohne Datenbank — Anmelden wird nicht klappen.";
  } catch (fehler) {
    ziel.textContent =
      fehler instanceof ApiFehler ? fehler.message : "Server nicht erreichbar.";
  }
}

async function beiAnmelden(ereignis) {
  ereignis.preventDefault();
  const knopf = $("anmeldenKnopf");
  zeigeFehler($("anmeldeFehler"), "");
  $("anmeldeHinweis").hidden = true;
  knopf.disabled = true;

  try {
    await melde_an($("email").value.trim(), $("passwort").value);
    await zeigeAlarme();
  } catch (fehler) {
    behandle(fehler, $("anmeldeFehler"));
  } finally {
    knopf.disabled = false;
  }
}

async function beiRegistrieren() {
  const knopf = $("registrierenKnopf");
  zeigeFehler($("anmeldeFehler"), "");
  $("anmeldeHinweis").hidden = true;
  knopf.disabled = true;

  try {
    const { bestaetigungNoetig } = await registriere(
      $("email").value.trim(),
      $("passwort").value,
    );

    if (bestaetigungNoetig) {
      const hinweis = $("anmeldeHinweis");
      hinweis.textContent =
        "Konto angelegt. Bitte klicke auf den Link in der E-Mail, die wir dir " +
        "geschickt haben — danach kannst du dich anmelden.";
      hinweis.hidden = false;
      return;
    }
    await zeigeAlarme();
  } catch (fehler) {
    behandle(fehler, $("anmeldeFehler"));
  } finally {
    knopf.disabled = false;
  }
}

async function beiAbmelden() {
  await melde_ab();
  zeigeAnmeldung();
}

// --- Benachrichtigungen -----------------------------------------------------

/**
 * Die Push-Karte an den tatsächlichen Zustand anpassen.
 *
 * Vier Zustände, und jeder braucht einen anderen Satz:
 *
 * * **Geht hier nicht** — z. B. iPhone-Safari ohne Installation. Dann kein
 *   Knopf, sondern die Erklärung, was zu tun ist.
 * * **Abgelehnt** — der Browser fragt nicht noch einmal; ein Knopf wäre eine
 *   Lüge. Also der Hinweis auf die Einstellungen.
 * * **Abonniert** — Knopf zum Abschalten.
 * * **Sonst** — Knopf zum Einschalten.
 *
 * Der vorletzte Fall hängt am **tatsächlichen Abonnement**, nicht an der
 * Erlaubnis: Beides kann auseinanderfallen (siehe `istAbonniert`), und dann
 * stünde hier „ist an", obwohl nie eine Nachricht ankäme.
 */
async function zeichnePushKarte() {
  const karte = $("pushKarte");
  const titel = $("pushTitel");
  const hinweis = $("pushHinweis");
  const knopf = $("pushKnopf");

  karte.hidden = false;
  knopf.disabled = false;

  const hindernis = warumNichtVerfuegbar();
  if (hindernis) {
    titel.textContent = "Benachrichtigungen hier nicht möglich";
    hinweis.textContent = hindernis;
    knopf.hidden = true;
    return;
  }

  knopf.hidden = false;
  const status = erlaubnisStatus();

  if (await istAbonniert()) {
    titel.textContent = "Benachrichtigungen sind an";
    hinweis.textContent = "Wir melden uns, sobald ein Preis unter dein Limit fällt.";
    knopf.textContent = "Ausschalten";
    knopf.className = "btn btn--schlicht";
  } else if (status === "denied") {
    titel.textContent = "Benachrichtigungen sind blockiert";
    hinweis.textContent =
      "Du hast sie abgelehnt. Das lässt sich nur in den Browser-Einstellungen " +
      "dieser Seite wieder ändern.";
    knopf.hidden = true;
  } else {
    titel.textContent = "Benachrichtigungen einschalten";
    hinweis.textContent = "Sonst musst du selbst nachsehen, ob ein Preis gefallen ist.";
    knopf.textContent = "Einschalten";
    knopf.className = "btn btn--primaer";
  }
}

async function beiPushKnopf() {
  const knopf = $("pushKnopf");
  zeigeFehler($("listenFehler"), "");
  knopf.disabled = true;

  try {
    if (await istAbonniert()) {
      await schalteAus();
      await zeichnePushKarte();
      // Die Browser-Erlaubnis selbst kann eine Webseite nicht zurücknehmen —
      // nur das Abonnement. Die Karte steht danach wieder auf „einschalten",
      // und dieser Satz erklärt, dass das Abschalten trotzdem gewirkt hat.
      $("pushHinweis").textContent =
        "Abgemeldet. Es kommen keine Nachrichten mehr, bis du sie wieder einschaltest.";
    } else {
      await schalteEin();
      await zeichnePushKarte();
    }
  } catch (fehler) {
    behandle(fehler, $("listenFehler"));
  } finally {
    knopf.disabled = false;
  }
}

// --- Alarmliste -------------------------------------------------------------

async function zeigeAlarme() {
  zeigeAnsicht("alarme");
  $("kopfEmail").textContent = angemeldeteEmail() ?? "";
  zeigeFehler($("listenFehler"), "");
  void zeichnePushKarte();
  // Still im Hintergrund: Push-Dienste erneuern Subscriptions gelegentlich
  // von sich aus. Das Backend macht daraus einen Upsert, kostet also nichts.
  void frischeAuf();

  $("listeLaedt").hidden = false;
  $("listeLeer").hidden = true;
  $("alarmListe").hidden = true;

  try {
    const alarme = await Api.alarme();
    zeichneListe(alarme);
  } catch (fehler) {
    $("listeLaedt").hidden = true;
    behandle(fehler, $("listenFehler"));
  }
}

function zeichneListe(alarme) {
  const liste = $("alarmListe");
  $("listeLaedt").hidden = true;
  liste.replaceChildren();

  if (alarme.length === 0) {
    $("listeLeer").hidden = false;
    liste.hidden = true;
    return;
  }

  $("listeLeer").hidden = true;
  liste.hidden = false;

  for (const alarm of alarme) {
    liste.append(zeichneAlarm(alarm));
  }
}

function zeichneAlarm(alarm) {
  const eintrag = document.createElement("li");
  eintrag.className = "karte alarm";
  if (!alarm.is_active) eintrag.classList.add("alarm--pausiert");

  // `textContent` statt `innerHTML`: Alles hier kommt zwar aus dem eigenen
  // Backend, aber HTML aus Daten zusammenzukleben ist die Gewohnheit, aus der
  // später Sicherheitslücken werden.
  const titel = document.createElement("h2");
  titel.textContent = strecke(alarm);

  const preis = document.createElement("span");
  preis.className = "alarm__preis";
  preis.textContent = `bis ${centNachEuro(alarm.max_price_cents, alarm.currency)}`;

  const kopf = document.createElement("div");
  kopf.className = "alarm__kopf";
  kopf.append(titel, preis);

  const zeitraum = document.createElement("p");
  zeitraum.className = "hinweis";
  zeitraum.textContent =
    `${datumLesbar(alarm.earliest_departure_date)} – ` +
    `${datumLesbar(alarm.latest_return_date)} · ` +
    `${umstiegeLesbar(alarm.max_stops)} · ` +
    `${alarm.adults} ${alarm.adults === 1 ? "Reisender" : "Reisende"}`;

  const geprueft = document.createElement("p");
  geprueft.className = "fussnote";
  geprueft.textContent = alarm.is_active
    ? `Zuletzt geprüft: ${zeitpunktLesbar(alarm.last_checked_at)}`
    : "Pausiert — wird gerade nicht geprüft.";

  const pause = document.createElement("button");
  pause.className = "btn btn--schlicht";
  pause.type = "button";
  pause.textContent = alarm.is_active ? "Pausieren" : "Fortsetzen";
  pause.addEventListener("click", () => schalteAlarm(alarm));

  const loeschen = document.createElement("button");
  loeschen.className = "btn btn--gefahr";
  loeschen.type = "button";
  loeschen.textContent = "Löschen";
  loeschen.addEventListener("click", () => loescheAlarm(alarm));

  const knoepfe = document.createElement("div");
  knoepfe.className = "alarm__knoepfe";
  knoepfe.append(pause, loeschen);

  eintrag.append(kopf, zeitraum, geprueft, knoepfe);
  return eintrag;
}

async function schalteAlarm(alarm) {
  try {
    await Api.alarmAendern(alarm.id, { is_active: !alarm.is_active });
    await zeigeAlarme();
  } catch (fehler) {
    behandle(fehler, $("listenFehler"));
  }
}

async function loescheAlarm(alarm) {
  // Löschen ist nicht rückgängig zu machen — einmal nachfragen.
  if (!confirm(`Alarm ${strecke(alarm)} wirklich löschen?`)) return;

  try {
    await Api.alarmLoeschen(alarm.id);
    await zeigeAlarme();
  } catch (fehler) {
    behandle(fehler, $("listenFehler"));
  }
}

// --- Neuen Alarm anlegen ----------------------------------------------------

function oeffneDialog() {
  zeigeFehler($("formularFehler"), "");
  $("alarmFormular").reset();
  $("alarmDialog").showModal();
}

/**
 * Das Formular in genau die Felder übersetzen, die das Backend erwartet.
 *
 * Nur hier wird aus „200,00" der Wert 20000 und aus „6 Stunden" 360 Minuten.
 * Leere Felder werden **weggelassen** statt als `null` geschickt: Das Backend
 * setzt dann seine eigenen Standardwerte.
 */
function formularAlsAlarm() {
  const zahlOderNichts = (id) => {
    const wert = $(id).value.trim();
    return wert === "" ? undefined : Number(wert);
  };

  const daten = {
    origin: $("origin").value.trim().toUpperCase(),
    destination: $("destination").value.trim().toUpperCase(),
    earliest_departure_date: $("earliest").value,
    latest_return_date: $("latest").value,
    max_price_cents: euroNachCent($("preis").value),
    max_stops: Number($("stops").value),
    adults: Number($("adults").value || 1),
    check_interval_minutes: Number($("intervall").value || 6) * 60,
    include_checked_bag: $("gepaeck").checked,
    avoid_night_flights: $("nachtflug").checked,
  };

  const minTage = zahlOderNichts("minTage");
  const maxTage = zahlOderNichts("maxTage");
  if (minTage !== undefined) daten.min_trip_duration_days = minTage;
  if (maxTage !== undefined) daten.max_trip_duration_days = maxTage;

  return daten;
}

async function beiSpeichern(ereignis) {
  ereignis.preventDefault();
  const knopf = $("speichernKnopf");
  zeigeFehler($("formularFehler"), "");

  let daten;
  try {
    // Der Preis ist das einzige Feld, das die App selbst prüft — weil sie es
    // umrechnen muss. Alles andere prüft das Backend, und zwar gründlicher.
    daten = formularAlsAlarm();
  } catch (fehler) {
    zeigeFehler($("formularFehler"), fehler.message);
    return;
  }

  knopf.disabled = true;
  try {
    await Api.alarmAnlegen(daten);
    $("alarmDialog").close();
    await zeigeAlarme();
  } catch (fehler) {
    if (fehler instanceof SitzungAbgelaufen) {
      $("alarmDialog").close();
    }
    behandle(fehler, $("formularFehler"));
  } finally {
    knopf.disabled = false;
  }
}

// --- Start ------------------------------------------------------------------

function verdrahte() {
  $("anmeldeFormular").addEventListener("submit", beiAnmelden);
  $("registrierenKnopf").addEventListener("click", beiRegistrieren);
  $("abmeldenKnopf").addEventListener("click", beiAbmelden);
  $("neuKnopf").addEventListener("click", oeffneDialog);
  $("pushKnopf").addEventListener("click", beiPushKnopf);
  $("alarmFormular").addEventListener("submit", beiSpeichern);
  $("abbrechenKnopf").addEventListener("click", () => $("alarmDialog").close());
}

async function start() {
  verdrahte();

  // Beim Laden entscheidet allein, ob eine Sitzung im Browser liegt. Ob sie
  // noch gültig ist, zeigt der erste Aufruf — läuft das Token ab, landet der
  // Nutzer über `SitzungAbgelaufen` von selbst wieder bei der Anmeldung.
  if (istAngemeldet()) {
    await zeigeAlarme();
  } else {
    zeigeAnmeldung();
  }
}

start();
