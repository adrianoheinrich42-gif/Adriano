import Foundation

/// Spiegel der Antwort von `GET /health`.
///
/// Beispiel:
/// ```json
/// {"status":"ok","database":"ok","version":"0.1.0","environment":"local"}
/// ```
struct HealthStatus: Decodable, Equatable {
    let status: String       // "ok" | "degraded"
    let database: String     // "ok" | "unavailable"
    let version: String
    let environment: String

    var isHealthy: Bool { status == "ok" }
    var isDatabaseReachable: Bool { database == "ok" }
}
