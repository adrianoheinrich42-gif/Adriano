import Foundation

/// Vertrag der Netzwerkschicht.
///
/// Warum ein Protokoll statt einer konkreten Klasse? Damit ViewModels in Tests
/// gegen eine Attrappe laufen können, ohne echte Requests zu schicken.
/// Siehe Projektplan, Abschnitt 9.5.
protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T
}

/// Echte Implementierung auf Basis von URLSession + async/await.
struct APIClient: APIClientProtocol {

    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder

    init(baseURL: URL = AppConfig.apiBaseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session

        let decoder = JSONDecoder()
        // Das Backend liefert snake_case (z. B. max_price_cents),
        // Swift schreibt camelCase. Diese Zeile übersetzt automatisch.
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let url = baseURL.appending(path: path)

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        // Ab M2 kommt hier der Authorization-Header aus dem Keychain dazu.

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            throw error.code == .timedOut ? APIError.timeout : APIError.notReachable
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.notReachable
        }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.server(statusCode: http.statusCode)
        }

        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding
        }
    }
}
