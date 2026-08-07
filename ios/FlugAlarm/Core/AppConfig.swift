import Foundation

/// Zentrale Stelle für Umgebungswerte der App.
///
/// Hier steht bewusst **nur die Adresse des eigenen Backends**.
/// Es gibt keinen Amadeus-, Anthropic- oder APNs-Schlüssel in der App —
/// die App kennt keine externen Dienste. Siehe Projektplan, Leitplanke 2.
enum AppConfig {

    /// Basis-URL des Backends.
    ///
    /// - **Simulator:** `127.0.0.1` zeigt auf deinen Mac. Passt so.
    /// - **Echtes iPhone:** Das Gerät kennt deinen Mac nicht als `localhost`.
    ///   Trage hier die WLAN-IP deines Macs ein, z. B.
    ///   `http://192.168.1.42:8000`. Die IP findest du mit:
    ///   `ipconfig getifaddr en0`
    /// - **Ab M12:** die öffentliche HTTPS-Adresse deines Hosters.
    static let apiBaseURL = URL(string: "http://127.0.0.1:8000")!
}
