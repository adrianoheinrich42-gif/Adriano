// Umrechnen und Anzeigen — Geld, Datum, Zeitpunkte.
//
// Eigene Datei, weil hier die eine Regel wohnt, die im ganzen Projekt gilt:
// **Geld ist immer eine ganze Zahl in Cent, niemals eine Kommazahl.**
// Der Nutzer tippt trotzdem „249,99" — die Übersetzung passiert genau hier.

/**
 * „249,99" → 24999. Wirft bei Unsinn.
 *
 * Bewusst mit Zeichenketten gerechnet statt mit `parseFloat(...) * 100`:
 * Letzteres ergibt für 249,99 den Wert 24998.999999999996, und daraus würde
 * beim Abrunden ein Cent zu wenig. Rundungsfehler bei Geld sind genau die
 * Sorte Fehler, die man erst spät und teuer bemerkt.
 */
export function euroNachCent(eingabe) {
  const text = String(eingabe).trim().replace(/\s/g, "").replace(",", ".");

  if (!/^\d+(\.\d{1,2})?$/.test(text)) {
    throw new Error("Bitte einen Betrag wie 249,99 eingeben.");
  }

  const [euro, cent = ""] = text.split(".");
  return Number(euro) * 100 + Number(cent.padEnd(2, "0"));
}

/** 24999 → „249,99 €" */
export function centNachEuro(cents, waehrung = "EUR") {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: waehrung,
  }).format(cents / 100);
}

/** „2026-09-06" → „6. Sep. 2026" */
export function datumLesbar(isoDatum) {
  if (!isoDatum) return "–";
  const [jahr, monat, tag] = isoDatum.split("-").map(Number);
  return new Intl.DateTimeFormat("de-DE", {
    day: "numeric",
    month: "short",
    year: "numeric",
    // Ohne Zeitzone rechnen: Ein reines Datum hat keine Uhrzeit, und
    // `new Date("2026-09-06")` läge in Deutschland sonst um zwei Stunden
    // daneben — im schlimmsten Fall am Vortag.
    timeZone: "UTC",
  }).format(new Date(Date.UTC(jahr, monat - 1, tag)));
}

/**
 * Ein Zeitpunkt aus dem Backend als „vor 5 Minuten".
 *
 * Anders als bei den Reisedaten ist das hier ein echter Zeitpunkt in UTC —
 * der Browser rechnet ihn selbst in die Zeitzone des Nutzers um.
 */
export function zeitpunktLesbar(isoZeitpunkt) {
  if (!isoZeitpunkt) return "noch nie";

  const dann = new Date(isoZeitpunkt);
  const sekunden = Math.round((Date.now() - dann.getTime()) / 1000);

  const stufen = [
    [60, "Sekunde", 1],
    [3600, "Minute", 60],
    [86400, "Stunde", 3600],
    [2592000, "Tag", 86400],
  ];

  const formatierer = new Intl.RelativeTimeFormat("de-DE", { numeric: "auto" });

  for (const [grenze, einheit, teiler] of stufen) {
    if (sekunden < grenze) {
      const einheitEn = { Sekunde: "second", Minute: "minute", Stunde: "hour", Tag: "day" }[
        einheit
      ];
      return formatierer.format(-Math.floor(sekunden / teiler), einheitEn);
    }
  }
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(dann);
}

/** „MUC" → „MUC → BCN" mit Pfeil, für Überschriften. */
export function strecke(alarm) {
  return `${alarm.origin} → ${alarm.destination}`;
}

/**
 * „2026-09-06T09:15:00+00:00" → „09:15"
 *
 * **Ohne Zeitzonenumrechnung.** Diese Zeiten sind Flughafen-Ortszeiten, die
 * das Backend als UTC ablegt (siehe `ortszeit_als_utc` im Prüflauf). „09:15 ab
 * München" soll als 09:15 erscheinen — `toLocaleTimeString()` würde daraus in
 * Deutschland 11:15 machen, also die falsche Zeit.
 */
export function uhrzeitLesbar(isoZeitpunkt) {
  if (!isoZeitpunkt) return "–";
  return isoZeitpunkt.slice(11, 16);
}

/** „2026-09-06T09:15:00+00:00" → „6. Sep." (kurz, für Flugzeilen) */
export function tagKurz(isoZeitpunkt) {
  if (!isoZeitpunkt) return "–";
  return datumLesbar(isoZeitpunkt.slice(0, 10)).replace(/ \d{4}$/, "");
}

/** 130 → „2 Std. 10 Min." */
export function dauerLesbar(minuten) {
  if (minuten === null || minuten === undefined) return "–";
  const stunden = Math.floor(minuten / 60);
  const rest = minuten % 60;
  if (stunden === 0) return `${rest} Min.`;
  if (rest === 0) return `${stunden} Std.`;
  return `${stunden} Std. ${rest} Min.`;
}

/** „1 Umstieg" / „direkt" / „bis 2 Umstiege" */
export function umstiegeLesbar(maxStops) {
  if (maxStops === 0) return "nur Direktflug";
  if (maxStops === 1) return "höchstens 1 Umstieg";
  return `höchstens ${maxStops} Umstiege`;
}
