import Foundation
import Observation

/// Das erste ViewModel des Projekts — bewusst klein, aber mit genau dem
/// Zustandsmuster, das später jeder Bildschirm nutzt:
/// **idle → loading → loaded | failed**.
///
/// `@Observable` (ab iOS 17) ersetzt `ObservableObject` + `@Published`.
/// Die View beobachtet automatisch die Eigenschaften, die sie liest.
@Observable
@MainActor
final class HealthViewModel {

    enum State: Equatable {
        case idle
        case loading
        case loaded(HealthStatus)
        case failed(String)
    }

    private(set) var state: State = .idle

    private let client: APIClientProtocol

    /// Der Client wird hereingereicht, nicht selbst erzeugt.
    /// Im Test übergibt man hier eine Attrappe.
    init(client: APIClientProtocol = APIClient()) {
        self.client = client
    }

    func load() async {
        state = .loading
        do {
            let status = try await client.get("/health", as: HealthStatus.self)
            state = .loaded(status)
        } catch let error as APIError {
            state = .failed(error.userMessage)
        } catch {
            state = .failed("Unbekannter Fehler.")
        }
    }
}
