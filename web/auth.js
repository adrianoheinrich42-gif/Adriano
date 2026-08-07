// Anmeldung gegen Supabase Auth — ohne Bibliothek, ohne CDN, ohne Node.
//
// Supabase bietet ein fertiges JavaScript-Paket an (`supabase-js`). Wir
// benutzen es bewusst NICHT: Es käme über ein fremdes CDN in die Seite, und
// die drei Dinge, die wir davon brauchen (registrieren, anmelden, Token
// erneuern), sind je ein `fetch`. Damit bleibt die Regel aus CLAUDE.md
// gewahrt: kein Framework, kein Node, keine fremde Abhängigkeit.
//
// ── Warum die App hier eine ZWEITE Adresse kennt ────────────────────────────
// Leitplanke 1 sagt: „Der Client kennt nur eine URL — das eigene Backend."
// Die Anmeldung ist die eine bewusste Ausnahme. Der Browser spricht dafür
// direkt mit Supabase, damit das Passwort **niemals** über unseren Server
// läuft. Würden wir den Login durch das Backend leiten, wäre genau das der
// Fall — und der Grund, überhaupt Supabase Auth zu nehmen (Passwörter sind
// fehleranfällig), wäre dahin.
//
// Alles andere — Alarme, Preise, Bewertungen — läuft weiterhin ausschließlich
// über das eigene Backend. Supabase kennt die App nur zum Anmelden.
//
// ── Warum der „anon key" im Browser stehen darf ─────────────────────────────
// Leitplanke 2 sagt: „Kein Schlüssel im Client." Gemeint sind Amadeus-,
// Anthropic- und VAPID-Schlüssel — mit denen könnte ein Fremder auf deine
// Rechnung einkaufen. Der Supabase-`anon`-Schlüssel ist etwas anderes: Er ist
// dafür gemacht, öffentlich zu sein, und erlaubt für sich genommen nichts
// außer „einen Anmeldeversuch stellen". Er steht in jeder Supabase-Web-App im
// Quelltext. Der `service_role`-Schlüssel dagegen darf NIE in den Browser —
// den brauchen wir gar nicht.

import { AppConfig } from "./config.js";

// Wo die Sitzung im Browser liegt. `localStorage` statt `sessionStorage`,
// damit man nach dem Schließen des Tabs angemeldet bleibt — bei einer App,
// die man alle paar Tage öffnet, ist alles andere lästig.
const SPEICHER_SCHLUESSEL = "flugalarm.sitzung";

// So viele Sekunden vor Ablauf wird das Token schon erneuert. Ohne diesen
// Puffer könnte ein Token zwar beim Absenden noch gültig sein, aber beim
// Ankommen im Backend abgelaufen — und der Nutzer sähe grundlos einen Fehler.
const ERNEUERN_AB_SEKUNDEN = 60;

export class AnmeldeFehler extends Error {}

function istEingerichtet() {
  return Boolean(AppConfig.supabaseUrl && AppConfig.supabaseAnonKey);
}

function authUrl(pfad) {
  return `${AppConfig.supabaseUrl.replace(/\/+$/, "")}/auth/v1${pfad}`;
}

// --- Sitzung speichern und lesen -------------------------------------------

function lade() {
  try {
    const roh = localStorage.getItem(SPEICHER_SCHLUESSEL);
    return roh ? JSON.parse(roh) : null;
  } catch {
    // Kaputter Eintrag (von Hand bearbeitet, alte Version): wie „nicht
    // angemeldet" behandeln, statt die ganze App scheitern zu lassen.
    return null;
  }
}

function speichere(antwort) {
  const sitzung = {
    access_token: antwort.access_token,
    refresh_token: antwort.refresh_token,
    // Supabase schickt `expires_at` als Sekunden seit 1970. Fehlt es, rechnen
    // wir es aus `expires_in` selbst aus.
    expires_at:
      antwort.expires_at ?? Math.floor(Date.now() / 1000) + (antwort.expires_in ?? 3600),
    email: antwort.user?.email ?? null,
  };
  localStorage.setItem(SPEICHER_SCHLUESSEL, JSON.stringify(sitzung));
  return sitzung;
}

function vergiss() {
  localStorage.removeItem(SPEICHER_SCHLUESSEL);
}

export function angemeldeteEmail() {
  return lade()?.email ?? null;
}

export function istAngemeldet() {
  return lade() !== null;
}

// --- Fehlertexte ------------------------------------------------------------

// Supabase antwortet auf Englisch und technisch. Der Nutzer sieht nie einen
// Statuscode und nie ein englisches Wort — Regel aus CLAUDE.md.
function uebersetzeFehler(status, koerper) {
  const meldung = (koerper?.error_description || koerper?.msg || koerper?.message || "")
    .toString()
    .toLowerCase();

  if (meldung.includes("invalid login credentials")) {
    return "E-Mail-Adresse oder Passwort stimmt nicht.";
  }
  if (meldung.includes("email not confirmed")) {
    return "Bitte bestätige zuerst den Link, den wir dir per E-Mail geschickt haben.";
  }
  if (meldung.includes("already registered") || meldung.includes("already been registered")) {
    return "Für diese E-Mail-Adresse gibt es schon ein Konto. Melde dich einfach an.";
  }
  if (meldung.includes("password") && meldung.includes("least")) {
    return "Das Passwort ist zu kurz — es braucht mindestens 6 Zeichen.";
  }
  if (meldung.includes("unable to validate email") || meldung.includes("invalid email")) {
    return "Diese E-Mail-Adresse sieht nicht richtig aus.";
  }
  if (status === 429) {
    return "Zu viele Versuche in kurzer Zeit. Bitte warte eine Minute.";
  }
  if (status >= 500) {
    return "Der Anmeldedienst antwortet gerade nicht. Bitte versuche es später noch einmal.";
  }
  return "Anmeldung fehlgeschlagen. Bitte prüfe deine Eingaben.";
}

async function rufeAuf(pfad, daten, zusatzKopf = {}) {
  if (!istEingerichtet()) {
    throw new AnmeldeFehler(
      "Die App ist noch nicht mit Supabase verbunden. Trage supabaseUrl und " +
        "supabaseAnonKey in web/config.js ein (Anleitung: docs/SUPABASE-EINRICHTEN.md).",
    );
  }

  let antwort;
  try {
    antwort = await fetch(authUrl(pfad), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: AppConfig.supabaseAnonKey,
        ...zusatzKopf,
      },
      body: JSON.stringify(daten),
    });
  } catch {
    // `fetch` wirft nur bei Netzproblemen — nicht bei HTTP-Fehlercodes.
    throw new AnmeldeFehler(
      "Keine Verbindung zum Anmeldedienst. Bist du mit dem Internet verbunden?",
    );
  }

  const koerper = await antwort.json().catch(() => null);

  if (!antwort.ok) {
    throw new AnmeldeFehler(uebersetzeFehler(antwort.status, koerper));
  }
  return koerper;
}

// --- Die vier Dinge, die die App braucht ------------------------------------

export async function registriere(email, passwort) {
  const antwort = await rufeAuf("/signup", { email, password: passwort });

  // Steht in Supabase „E-Mail bestätigen" an, gibt es hier noch kein Token.
  // Dann ist das Konto angelegt, aber die Anmeldung kommt erst nach dem Klick
  // in der E-Mail — der Nutzer muss das erfahren.
  if (!antwort?.access_token) {
    return { bestaetigungNoetig: true };
  }

  speichere(antwort);
  return { bestaetigungNoetig: false };
}

export async function melde_an(email, passwort) {
  const antwort = await rufeAuf("/token?grant_type=password", {
    email,
    password: passwort,
  });
  speichere(antwort);
}

export async function melde_ab() {
  const sitzung = lade();

  // Erst lokal vergessen, dann Supabase Bescheid geben. Andersherum bliebe
  // der Nutzer bei einem Netzfehler angemeldet, obwohl er auf „Abmelden"
  // geklickt hat — und das ist die Erwartung, die man nicht enttäuschen darf.
  vergiss();

  if (sitzung?.access_token) {
    await rufeAuf("/logout", {}, { Authorization: `Bearer ${sitzung.access_token}` }).catch(
      () => {},
    );
  }
}

/**
 * Ein gültiges Zugriffs-Token — oder `null`, wenn niemand angemeldet ist.
 *
 * Erneuert das Token selbstständig, kurz bevor es abläuft. Schlägt das fehl,
 * gilt die Sitzung als beendet: Ein abgelaufenes Token weiterzureichen würde
 * beim Backend nur in einem 401 enden.
 */
export async function holeToken() {
  const sitzung = lade();
  if (!sitzung) return null;

  const jetzt = Math.floor(Date.now() / 1000);
  if (sitzung.expires_at - ERNEUERN_AB_SEKUNDEN > jetzt) {
    return sitzung.access_token;
  }

  try {
    const antwort = await rufeAuf("/token?grant_type=refresh_token", {
      refresh_token: sitzung.refresh_token,
    });
    return speichere(antwort).access_token;
  } catch {
    vergiss();
    return null;
  }
}
