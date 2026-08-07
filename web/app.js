// M0-Spiegel fürs Web: fragt den Backend-Status ab und zeigt ihn an.
//
// Das ist das Web-Gegenstück zum früheren HealthViewModel + ContentView.
// Bewusst ohne Framework: reines JavaScript, das der Browser direkt lädt.
// Sobald die Formulare (Alarm anlegen, Liste) komplexer werden, führen wir
// hier ein Framework ein — jetzt noch nicht.

import { AppConfig } from "./config.js";

// --- kleine Helfer -----------------------------------------------------------

const $ = (id) => document.getElementById(id);

function show(zustand) {
  // Genau eine der drei Karten sichtbar machen.
  for (const id of ["loading", "success", "error"]) {
    $(id).hidden = id !== zustand;
  }
}

// Übersetzt technische Fehler in einen Satz, den man anzeigen kann —
// wie zuvor APIError.userMessage in Swift.
function fehlermeldung(error) {
  if (error?.name === "AbortError") {
    return "Der Server antwortet gerade nicht. Bitte später erneut versuchen.";
  }
  if (error instanceof TypeError) {
    // fetch wirft TypeError bei Netzfehler, falscher Adresse oder — im
    // Cross-Device-Test — geblockter CORS-Freigabe.
    return (
      "Das Backend ist nicht erreichbar. Läuft der Server, stimmt die Adresse " +
      "in config.js, und ist die CORS-Freigabe gesetzt? Details siehe web/README.md."
    );
  }
  if (typeof error?.status === "number") {
    if (error.status === 401) return "Deine Sitzung ist abgelaufen. Bitte neu anmelden.";
    if (error.status >= 500) return "Auf dem Server ist etwas schiefgelaufen.";
    return "Die Anfrage konnte nicht bearbeitet werden.";
  }
  return "Unbekannter Fehler.";
}

// --- der eigentliche Abruf ---------------------------------------------------

async function ladeStatus() {
  show("loading");

  // Eigener Timeout: fetch selbst bricht sonst sehr spät ab.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const antwort = await fetch(`${AppConfig.apiBaseURL}/health`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });

    if (!antwort.ok) {
      throw { status: antwort.status };
    }

    const status = await antwort.json();
    zeigeStatus(status);
  } catch (error) {
    $("errorMessage").textContent = fehlermeldung(error);
    show("error");
  } finally {
    clearTimeout(timeout);
  }
}

function zeigeStatus(status) {
  const gesund = status.status === "ok";
  const dbOk = status.database === "ok";

  $("statusIcon").textContent = gesund ? "✓" : "⚠︎";
  $("statusIcon").classList.toggle("icon--warn", !gesund);
  $("statusTitle").textContent = gesund ? "Backend erreichbar" : "Backend eingeschränkt";

  const hint = $("statusHint");
  if (!dbOk) {
    hint.textContent = "Die Datenbank antwortet nicht. Läuft „docker compose up -d db"?";
    hint.hidden = false;
  } else {
    hint.hidden = true;
  }

  $("dbValue").textContent = status.database ?? "–";
  $("versionValue").textContent = status.version ?? "–";
  $("envValue").textContent = status.environment ?? "–";

  show("success");
}

// --- Verdrahtung -------------------------------------------------------------

// Ein Listener für beide „Erneut"-Knöpfe (Erfolg und Fehler).
document.addEventListener("click", (event) => {
  if (event.target.matches("[data-action='reload']")) {
    ladeStatus();
  }
});

ladeStatus();
