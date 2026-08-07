// Benachrichtigungen einschalten — die Seite des Browsers.
//
// Der Ablauf hat vier Schritte, und jeder kann scheitern:
//
//   1. Service Worker registrieren   (`sw.js`)
//   2. Den Nutzer um Erlaubnis bitten
//   3. Beim Push-Dienst abonnieren   (braucht den VAPID-Schlüssel)
//   4. Die Subscription ans eigene Backend schicken
//
// Alles, was hier schiefgeht, wird zu einem deutschen Satz — nie zu einem
// Fehlercode. Vor allem der iPhone-Fall braucht eine Erklärung, weil er
// aussieht wie ein Fehler, aber keiner ist.

import { Api } from "./api.js";

export class PushFehler extends Error {}

/** Läuft die Seite als installierte App (vom Home-Bildschirm gestartet)? */
function alsAppInstalliert() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // Safari auf iOS kennt `display-mode` nicht und meldet es hier.
    window.navigator.standalone === true
  );
}

function istApple() {
  return /iPhone|iPad|iPod/.test(navigator.userAgent);
}

/**
 * Kann dieser Browser überhaupt Push? Gibt `null` zurück, wenn ja — sonst den
 * Grund als deutschen Satz.
 *
 * Der iPhone-Fall ist der wichtigste: Safari kann Web-Push **nur**, wenn die
 * Seite über „Zum Home-Bildschirm" installiert wurde. Im normalen Safari-Tab
 * fehlt die Schnittstelle einfach — und der Nutzer soll erfahren, was zu tun
 * ist, statt einen kaputten Knopf zu sehen.
 */
export function warumNichtVerfuegbar() {
  if (!("serviceWorker" in navigator)) {
    return "Dieser Browser unterstützt keine Benachrichtigungen.";
  }
  if (!("PushManager" in window) || !("Notification" in window)) {
    if (istApple() && !alsAppInstalliert()) {
      return (
        "Auf dem iPhone gehen Benachrichtigungen nur, wenn du die Seite zum " +
        "Home-Bildschirm hinzufügst: unten auf „Teilen“ tippen und „Zum " +
        "Home-Bildschirm“ wählen. Danach die App von dort öffnen."
      );
    }
    return "Dieser Browser unterstützt keine Benachrichtigungen.";
  }
  if (window.isSecureContext === false) {
    return "Benachrichtigungen brauchen eine sichere Verbindung (HTTPS).";
  }
  return null;
}

export function erlaubnisStatus() {
  if (!("Notification" in window)) return "nicht_moeglich";
  return Notification.permission; // "granted" | "denied" | "default"
}

/**
 * Gibt es tatsächlich ein Abonnement?
 *
 * **Nicht dasselbe wie „Erlaubnis erteilt".** Die Erlaubnis kann längst
 * vorliegen, ohne dass ein Abonnement besteht — nach dem Abschalten in dieser
 * App, auf einem zweiten Gerät, oder wenn der Browser die Daten der Seite
 * gelöscht hat. Wer nur `Notification.permission` prüft, zeigt dann „ist an"
 * an, obwohl nichts ankommen würde.
 */
export async function istAbonniert() {
  if (warumNichtVerfuegbar() || erlaubnisStatus() !== "granted") return false;

  try {
    const registrierung = await navigator.serviceWorker.getRegistration();
    return Boolean(await registrierung?.pushManager.getSubscription());
  } catch {
    return false;
  }
}

/**
 * Der VAPID-Schlüssel kommt als base64url-Text, `subscribe()` will Bytes.
 *
 * base64url benutzt `-` und `_` statt `+` und `/` und lässt die
 * `=`-Auffüllzeichen weg — `atob` versteht das nicht und muss beides
 * zurückübersetzt bekommen.
 */
function schluesselAlsBytes(base64url) {
  const auffuellung = "=".repeat((4 - (base64url.length % 4)) % 4);
  const base64 = (base64url + auffuellung).replace(/-/g, "+").replace(/_/g, "/");
  const roh = atob(base64);
  return Uint8Array.from(roh, (zeichen) => zeichen.charCodeAt(0));
}

async function registriereServiceWorker() {
  try {
    await navigator.serviceWorker.register("sw.js");
  } catch {
    throw new PushFehler("Der Hintergrunddienst ließ sich nicht starten.");
  }

  // **`register()` allein genügt nicht.** Es kehrt zurück, sobald die
  // Registrierung angelegt ist — der Service Worker ist zu dem Zeitpunkt aber
  // womöglich noch im Zustand „installing". Ein `subscribe()` scheitert dann
  // mit „no active Service Worker", und zwar genau beim **ersten** Besuch,
  // wo der Nutzer den Knopf zum ersten Mal drückt.
  //
  // `navigator.serviceWorker.ready` wartet, bis wirklich ein aktiver Worker da
  // ist. Der Zeitgeber verhindert, dass der Knopf ewig hängt, falls das nie
  // passiert.
  return await Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, ablehnen) =>
      setTimeout(
        () => ablehnen(new PushFehler("Der Hintergrunddienst startet gerade nicht.")),
        10000,
      ),
    ),
  ]);
}

/**
 * Benachrichtigungen einschalten. Wirft `PushFehler` mit deutschem Text.
 *
 * Muss aus einem Klick heraus aufgerufen werden — Browser verweigern die
 * Erlaubnisabfrage, wenn keine Nutzeraktion dahintersteckt.
 */
export async function schalteEin() {
  const hindernis = warumNichtVerfuegbar();
  if (hindernis) throw new PushFehler(hindernis);

  const config = await Api.pushConfig();
  if (!config.aktiviert) {
    throw new PushFehler(
      "Der Server verschickt gerade keine Benachrichtigungen — es fehlt sein " +
        "VAPID-Schlüsselpaar.",
    );
  }

  const registrierung = await registriereServiceWorker();

  const erlaubnis = await Notification.requestPermission();
  if (erlaubnis === "denied") {
    throw new PushFehler(
      "Du hast Benachrichtigungen abgelehnt. Das lässt sich nur in den " +
        "Browser-Einstellungen dieser Seite wieder ändern.",
    );
  }
  if (erlaubnis !== "granted") {
    throw new PushFehler("Ohne deine Erlaubnis können wir dir nichts schicken.");
  }

  // `userVisibleOnly` ist Pflicht und bedeutet: Jede Push führt zu einer
  // sichtbaren Nachricht. Stille Hintergrund-Pushes erlauben die Browser nicht.
  let subscription;
  try {
    subscription = await registrierung.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: schluesselAlsBytes(config.public_key),
    });
  } catch {
    // Hier landen Fehler des Push-Dienstes selbst — kein Netz, Dienst
    // blockiert, oder ein Schlüssel, den der Browser nicht akzeptiert. Der
    // Nutzer bekommt einen Satz, keinen `AbortError`.
    throw new PushFehler(
      "Der Push-Dienst des Browsers hat das Abonnement abgelehnt. " +
        "Bist du online? Sonst später noch einmal versuchen.",
    );
  }

  await Api.pushAnmelden(subscription.toJSON());
  return subscription;
}

/** Benachrichtigungen wieder abschalten. */
export async function schalteAus() {
  if (!("serviceWorker" in navigator)) return;

  const registrierung = await navigator.serviceWorker.getRegistration();
  const subscription = await registrierung?.pushManager.getSubscription();
  if (!subscription) return;

  // Erst dem Backend Bescheid geben, dann lokal abbestellen: Andersherum
  // kennten wir den Endpoint nicht mehr, den wir abmelden wollen.
  await Api.pushAbmelden({ endpoint: subscription.endpoint });
  await subscription.unsubscribe();
}

/**
 * Beim Start aufräumen: Ist der Nutzer angemeldet und hat schon erlaubt,
 * die Subscription still erneuern.
 *
 * Der Grund steht in `sw.js`: Push-Dienste erneuern Subscriptions gelegentlich
 * von sich aus. Weil das Backend daraus einen Upsert macht, kostet das
 * Wiederanmelden nichts und hält die Adresse aktuell.
 */
export async function frischeAuf() {
  if (warumNichtVerfuegbar() || erlaubnisStatus() !== "granted") return false;

  try {
    const registrierung = await registriereServiceWorker();
    const vorhanden = await registrierung.pushManager.getSubscription();
    if (!vorhanden) return false;

    await Api.pushAnmelden(vorhanden.toJSON());
    return true;
  } catch {
    // Beim Start darf nichts scheitern, was der Nutzer nicht angefordert hat.
    return false;
  }
}
