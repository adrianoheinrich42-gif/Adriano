import Foundation

/// Fehler der Netzwerkschicht — jeweils mit einem Text, den man einem
/// Menschen zeigen kann. Statuscodes und Stacktraces gehören nie in die UI.
enum APIError: Error, Equatable {
    /// Kein Netz, Backend nicht gestartet, falsche Adresse.
    case notReachable
    /// Zeitüberschreitung.
    case timeout
    /// Server hat mit einem Fehlercode geantwortet (4xx / 5xx).
    case server(statusCode: Int)
    /// Antwort kam an, ließ sich aber nicht in unser Modell übersetzen.
    case decoding

    /// Text für die Anzeige.
    var userMessage: String {
        switch self {
        case .notReachable:
            "Das Backend ist nicht erreichbar. Läuft der Server, und stimmt die Adresse?"
        case .timeout:
            "Der Server antwortet gerade nicht. Bitte später erneut versuchen."
        case .server(let code) where code == 401:
            "Deine Sitzung ist abgelaufen. Bitte melde dich erneut an."
        case .server(let code) where (500...599).contains(code):
            "Auf dem Server ist etwas schiefgelaufen. Bitte später erneut versuchen."
        case .server:
            "Die Anfrage konnte nicht bearbeitet werden."
        case .decoding:
            "Die Antwort des Servers war unerwartet. Läuft dort die richtige Version?"
        }
    }
}
