// Der Service Worker — das einzige Stück Code, das läuft, wenn die App
// geschlossen ist.
//
// Genau darum geht es bei Push: Die Nachricht kommt an, während der Browser
// vielleicht gar nicht offen ist. Der Service Worker ist ein kleines
// Hintergrundprogramm, das der Browser für unsere Seite gestartet hält und
// bei einer eintreffenden Nachricht aufweckt.
//
// **Er hat keinen Zugriff auf die Seite** — kein `document`, kein `window`,
// keine Variablen aus `app.js`. Deshalb steht hier alles noch einmal, was er
// braucht, und deshalb ist es so wenig wie möglich.
//
// Wichtig: Diese Datei muss im **Wurzelverzeichnis** der Seite liegen. Ein
// Service Worker darf nur den Pfad kontrollieren, in dem er selbst liegt —
// unter `js/sw.js` bekäme er nur `/js/` zu sehen.

// Beim Erhöhen dieser Zahl holt der Browser den Service Worker neu. Nötig,
// wenn sich unten etwas ändert: Sonst läuft beim Nutzer wochenlang die alte
// Fassung weiter.
const VERSION = "v1";

self.addEventListener("install", () => {
  // Ohne `skipWaiting` würde die neue Fassung erst aktiv, wenn alle Tabs der
  // Seite geschlossen wurden — bei einer App, die man offen lässt, quasi nie.
  self.skipWaiting();
});

self.addEventListener("activate", (ereignis) => {
  // Bestehende Tabs sofort übernehmen, statt auf ein Neuladen zu warten.
  ereignis.waitUntil(self.clients.claim());
});

// --- Eine Nachricht kommt an -----------------------------------------------

self.addEventListener("push", (ereignis) => {
  // Das Backend schickt JSON mit genau drei Feldern (siehe
  // `Nachricht.als_json()` in backend/app/services/push.py).
  let daten = {};
  try {
    daten = ereignis.data ? ereignis.data.json() : {};
  } catch {
    // Kaputte oder fremde Nutzlast: lieber eine schlichte Nachricht als gar
    // keine. Eine Push zu verschlucken sieht für den Nutzer aus wie ein Fehler
    // der App.
    daten = {};
  }

  const titel = daten.titel || "Flugalarm";
  const optionen = {
    body: daten.text || "Es gibt ein neues Angebot für einen deiner Alarme.",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    lang: "de",
    // `tag` sorgt dafür, dass eine neue Meldung die vorige ersetzt, statt sich
    // zu stapeln. `renotify` lässt das Gerät trotzdem noch einmal vibrieren.
    tag: "flugalarm-treffer",
    renotify: true,
    data: { url: daten.url || "/" },
  };

  // `waitUntil` ist Pflicht: Ohne das darf der Browser den Service Worker
  // sofort nach dem Ereignis beenden — mitten im Anzeigen der Nachricht.
  ereignis.waitUntil(self.registration.showNotification(titel, optionen));
});

// --- Der Nutzer tippt auf die Nachricht ------------------------------------

self.addEventListener("notificationclick", (ereignis) => {
  ereignis.notification.close();
  const ziel = ereignis.notification.data?.url || "/";

  ereignis.waitUntil(
    (async () => {
      const fenster = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });

      // Ist die App schon offen, diesen Tab nach vorn holen — statt einen
      // zweiten aufzumachen. Nichts ist lästiger als zehn Tabs derselben App.
      //
      // Vorher aber **hinnavigieren**: Der Nutzer hat auf eine Nachricht über
      // einen bestimmten Alarm getippt und erwartet genau den, nicht die
      // Liste, die zufällig gerade offen war (M9, Deep-Link).
      for (const client of fenster) {
        if ("focus" in client) {
          if ("navigate" in client) {
            try {
              await client.navigate(ziel);
            } catch {
              // `navigate` scheitert, wenn der Tab gerade lädt. Dann ist ein
              // fokussiertes Fenster immer noch besser als gar keins.
            }
          }
          await client.focus();
          return;
        }
      }
      if (self.clients.openWindow) await self.clients.openWindow(ziel);
    })(),
  );
});

// --- Das Abonnement läuft ab ------------------------------------------------

self.addEventListener("pushsubscriptionchange", () => {
  // Push-Dienste erneuern Subscriptions gelegentlich von sich aus. Sauber wäre,
  // hier direkt neu zu abonnieren und das Backend zu benachrichtigen — dafür
  // bräuchte der Service Worker aber das Anmelde-Token, das nur die Seite hat.
  //
  // Stattdessen genügt der einfache Weg: `push.js` meldet die Subscription bei
  // **jedem** Seitenaufruf erneut an (das Backend macht daraus einen Upsert).
  // Spätestens beim nächsten Öffnen der App ist alles wieder richtig.
  console.info(`[${VERSION}] Subscription wurde erneuert — wird beim nächsten Start gemeldet.`);
});
