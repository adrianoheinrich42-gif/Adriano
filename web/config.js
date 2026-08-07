// Zentrale Konfiguration der Web-App.
//
// Hier steht bewusst nur die Adresse des eigenen Backends — genau wie zuvor
// in AppConfig.swift. Kein Amadeus-, Anthropic- oder Push-Schlüssel im
// Browser; die App kennt nur deinen Server. Siehe Projektplan, Leitplanke 2.

export const AppConfig = {
  // Basis-URL des Backends.
  //
  // - Auf DEINEM Lenovo im Browser: "http://127.0.0.1:8000" passt.
  // - Auf dem iPhone (späteres Testen): Das Handy kennt deinen Laptop nicht
  //   als "localhost". Trage dann die WLAN-IP des Lenovo ein, z. B.
  //   "http://192.168.1.42:8000". Die IP findest du unter Windows mit:
  //       ipconfig      (Zeile "IPv4-Adresse")
  //   Wichtig: Das Backend muss dann mit --host 0.0.0.0 laufen (siehe
  //   web/README.md), sonst ist es vom Handy aus nicht erreichbar.
  // - Ab dem Deployment: die öffentliche HTTPS-Adresse deines Hosters.
  apiBaseURL: "http://127.0.0.1:8000",

  // --- Supabase (nur zum Anmelden) -----------------------------------------
  //
  // Diese beiden Werte findest du im Supabase-Dashboard unter
  //   Project Settings → API
  // Schritt für Schritt erklärt in `docs/SUPABASE-EINRICHTEN.md`.
  //
  // Warum das kein Widerspruch zu Leitplanke 2 („kein Schlüssel im Client")
  // ist: Der `anon`-Schlüssel ist dafür gemacht, öffentlich zu sein, und
  // erlaubt für sich allein nichts außer einem Anmeldeversuch. Er steht in
  // jeder Supabase-Web-App im Quelltext. Ausführlich in `auth.js`.
  //
  // ⚠️ Der `service_role`-Schlüssel gehört NIEMALS hierher. Der steht direkt
  // daneben im Dashboard und sieht fast gleich aus — er darf alles und gehört
  // ausschließlich in Backend-Umgebungsvariablen.
  supabaseUrl: "",
  supabaseAnonKey: "",
};
