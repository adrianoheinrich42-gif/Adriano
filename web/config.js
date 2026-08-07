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
};
