// Die Detailansicht eines Alarms (M9): Einordnung, Preisverlauf, Angebote.
//
// Bis M8 steckte die Bewertung aus M7 nur im Log des Workers und in der
// Push-Nachricht. Hier wird sie zum ersten Mal sichtbar.
//
// **Der Client rechnet nichts** (Leitplanke 1). „günstig", „−21 %", die
// Aufteilung in Hin- und Rückflug, die Flugdauern — all das kommt fertig vom
// Backend. Diese Datei ordnet es nur an.

import { Api } from "./api.js";
import {
  centNachEuro,
  dauerLesbar,
  datumLesbar,
  strecke,
  tagKurz,
  uhrzeitLesbar,
  umstiegeLesbar,
} from "./format.js";

const $ = (id) => document.getElementById(id);

// Wie die vier Einordnungen aus `price_stats.py` heißen sollen. Der Nutzer
// liest „günstig", nicht `guenstig`.
const BADGE = {
  guenstig: { text: "günstig", klasse: "badge--gut" },
  normal: { text: "normal", klasse: "badge--neutral" },
  teuer: { text: "eher teuer", klasse: "badge--warn" },
  zu_wenig_daten: { text: "noch kein Vergleich", klasse: "badge--neutral" },
};

/**
 * Der erklärende Satz unter dem Preis.
 *
 * Der Fall `zu_wenig_daten` ist der wichtigste: Dann **keine Prozentzahl**,
 * sondern die ehrliche Auskunft, dass die Datenlage noch nichts hergibt.
 * Genau dafür schickt das Backend dort `null` statt 0.
 */
function bewertungssatz(bewertung) {
  if (bewertung.ist_bestpreis) {
    return "Günstigster Preis, den wir für diese Strecke bisher gesehen haben.";
  }
  if (bewertung.einordnung === "zu_wenig_daten") {
    return (
      `Für einen Vergleich fehlen noch Daten (${bewertung.datenpunkte} Beobachtungen). ` +
      "Sobald genug zusammengekommen ist, siehst du hier, ob der Preis gut ist."
    );
  }

  const median = centNachEuro(bewertung.median_cents);
  const abweichung = Math.abs(Math.round(bewertung.abweichung_prozent));

  if (bewertung.einordnung === "guenstig") {
    return `${abweichung} % unter dem üblichen Preis für diese Strecke (sonst etwa ${median}).`;
  }
  if (bewertung.einordnung === "teuer") {
    return `${abweichung} % über dem üblichen Preis (sonst etwa ${median}) — aber unter deinem Limit.`;
  }
  return `Etwa im üblichen Rahmen für diese Strecke (Median ${median}).`;
}

/**
 * Der Preisverlauf als kleine SVG-Kurve.
 *
 * Von Hand gezeichnet statt mit einer Diagramm-Bibliothek: Es sind zwanzig
 * Zeilen, und eine Bibliothek wäre die erste externe Abhängigkeit im Frontend
 * (CLAUDE.md: kein Framework, kein Node).
 *
 * Erzeugt wird echtes SVG über `createElementNS` — kein `innerHTML`, dieselbe
 * Regel wie im Rest der App.
 */
function zeichneVerlauf(punkte) {
  const NS = "http://www.w3.org/2000/svg";
  const breite = 320;
  const hoehe = 90;
  const rand = 6;

  const preise = punkte.map((p) => p.min_price_cents);
  const min = Math.min(...preise);
  const max = Math.max(...preise);
  // Ein flacher Verlauf (alle Preise gleich) hätte Spannweite 0 — dann durch
  // null geteilt. In dem Fall zeichnen wir die Linie mittig.
  const spanne = max - min || 1;

  const x = (i) =>
    punkte.length === 1 ? breite / 2 : rand + (i * (breite - 2 * rand)) / (punkte.length - 1);
  const y = (preis) => hoehe - rand - ((preis - min) / spanne) * (hoehe - 2 * rand);

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${breite} ${hoehe}`);
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `Preisverlauf: ${punkte.length} Tage, günstigster Wert ` +
      `${centNachEuro(min)}, teuerster ${centNachEuro(max)}.`,
  );

  const punktliste = punkte.map((p, i) => `${x(i)},${y(p.min_price_cents)}`).join(" ");

  // Erst die Fläche darunter, dann die Linie darüber.
  const flaeche = document.createElementNS(NS, "polygon");
  flaeche.setAttribute(
    "points",
    `${x(0)},${hoehe} ${punktliste} ${x(punkte.length - 1)},${hoehe}`,
  );
  flaeche.setAttribute("class", "verlauf__flaeche");

  const linie = document.createElementNS(NS, "polyline");
  linie.setAttribute("points", punktliste);
  linie.setAttribute("class", "verlauf__linie");

  svg.append(flaeche, linie);

  // Den günstigsten Tag markieren — das ist der Punkt, den man sucht.
  const besterIndex = preise.indexOf(min);
  const marke = document.createElementNS(NS, "circle");
  marke.setAttribute("cx", String(x(besterIndex)));
  marke.setAttribute("cy", String(y(min)));
  marke.setAttribute("r", "4");
  marke.setAttribute("class", "verlauf__marke");
  svg.append(marke);

  return svg;
}

function verlaufsBeschriftung(punkte) {
  const preise = punkte.map((p) => p.min_price_cents);
  const zeile = document.createElement("p");
  zeile.className = "fussnote verlauf__achse";
  zeile.textContent =
    `${datumLesbar(punkte[0].tag)} – ${datumLesbar(punkte[punkte.length - 1].tag)} · ` +
    `${centNachEuro(Math.min(...preise))} bis ${centNachEuro(Math.max(...preise))}`;
  return zeile;
}

function zeichneAngebot(angebot) {
  const eintrag = document.createElement("li");
  eintrag.className = "karte angebot";

  const preis = document.createElement("span");
  preis.className = "angebot__preis";
  preis.textContent = centNachEuro(angebot.total_price_cents, angebot.currency);

  const airline = document.createElement("span");
  airline.className = "hinweis";
  airline.textContent = angebot.validating_airline ?? "";

  const kopf = document.createElement("div");
  kopf.className = "angebot__kopf";
  kopf.append(preis, airline);
  eintrag.append(kopf);

  eintrag.append(
    flugzeile("Hin", angebot.outbound_segments, angebot.outbound_duration_minutes, angebot.outbound_stops),
  );
  if (angebot.inbound_segments.length > 0) {
    eintrag.append(
      flugzeile("Zurück", angebot.inbound_segments, angebot.inbound_duration_minutes, angebot.inbound_stops),
    );
  }

  const fuss = document.createElement("p");
  fuss.className = "fussnote";
  const gepaeck =
    angebot.included_checked_bags && angebot.included_checked_bags > 0
      ? `${angebot.included_checked_bags} Gepäckstück inklusive`
      : "ohne aufgegebenes Gepäck";
  fuss.textContent = gepaeck;
  eintrag.append(fuss);

  if (angebot.booking_url) {
    const link = document.createElement("a");
    link.className = "btn btn--primaer";
    link.href = angebot.booking_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Zum Angebot";
    eintrag.append(link);
  }

  return eintrag;
}

function flugzeile(richtung, segmente, dauer, stops) {
  const erstes = segmente[0];
  const letztes = segmente[segmente.length - 1];

  const zeile = document.createElement("p");
  zeile.className = "angebot__flug";
  zeile.textContent =
    `${richtung}: ${tagKurz(erstes.abflug_lokal)} · ` +
    `${uhrzeitLesbar(erstes.abflug_lokal)} ${erstes.von} → ` +
    `${uhrzeitLesbar(letztes.ankunft_lokal)} ${letztes.nach} · ` +
    `${dauerLesbar(dauer)} · ${umstiegeLesbar(stops)}`;
  return zeile;
}

/**
 * Die Detailansicht füllen. `alarm` ist die schon geladene Alarmzeile.
 *
 * Verlauf und Angebote werden **parallel** geholt: Zwei unabhängige Aufrufe
 * nacheinander zu machen, würde die Anzeige ohne Grund verdoppeln.
 */
export async function zeigeDetail(alarm, beiFehler) {
  $("detailTitel").textContent = strecke(alarm);
  $("detailZeitraum").textContent =
    `${datumLesbar(alarm.earliest_departure_date)} – ` +
    `${datumLesbar(alarm.latest_return_date)} · ` +
    `Limit ${centNachEuro(alarm.max_price_cents, alarm.currency)}`;

  $("detailLaedt").hidden = false;
  $("bewertungKarte").hidden = true;
  $("angebotListe").hidden = true;
  $("angeboteLeer").hidden = true;
  $("detailFehler").hidden = true;

  let verlauf;
  let angebote;
  try {
    [verlauf, angebote] = await Promise.all([Api.verlauf(alarm.id), Api.angebote(alarm.id)]);
  } catch (fehler) {
    $("detailLaedt").hidden = true;
    beiFehler(fehler);
    return;
  }

  $("detailLaedt").hidden = true;
  zeichneBewertung(verlauf);
  zeichneAngebote(angebote);
}

function zeichneBewertung(verlauf) {
  const karte = $("bewertungKarte");
  const badge = $("bewertungBadge");
  const bild = $("verlaufBild");
  bild.replaceChildren();

  if (!verlauf.bewertung) {
    // Noch kein einziger Treffer — dann gibt es nichts einzuordnen.
    karte.hidden = verlauf.punkte.length === 0;
    $("bewertungPreis").textContent = "Noch kein Treffer";
    badge.hidden = true;
    $("bewertungText").textContent =
      "Der Prüflauf hat bisher nichts unter deinem Limit gefunden.";
  } else {
    karte.hidden = false;
    badge.hidden = false;
    $("bewertungPreis").textContent = centNachEuro(verlauf.aktueller_preis_cents);

    const stil = BADGE[verlauf.bewertung.einordnung] ?? BADGE.normal;
    badge.textContent = verlauf.bewertung.ist_bestpreis ? "Bestpreis" : stil.text;
    badge.className = `badge ${verlauf.bewertung.ist_bestpreis ? "badge--gut" : stil.klasse}`;
    $("bewertungText").textContent = bewertungssatz(verlauf.bewertung);
  }

  // Eine Kurve aus einem einzigen Punkt sagt nichts — dann lieber nichts.
  const figur = $("verlaufFigur");
  figur.hidden = verlauf.punkte.length < 2;
  if (!figur.hidden) {
    bild.append(zeichneVerlauf(verlauf.punkte), verlaufsBeschriftung(verlauf.punkte));
  }
}

function zeichneAngebote(angebote) {
  const liste = $("angebotListe");
  liste.replaceChildren();

  if (angebote.length === 0) {
    $("angeboteLeer").hidden = false;
    liste.hidden = true;
    return;
  }

  $("angeboteLeer").hidden = true;
  liste.hidden = false;
  for (const angebot of angebote) {
    liste.append(zeichneAngebot(angebot));
  }
}
