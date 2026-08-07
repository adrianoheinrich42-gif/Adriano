import SwiftUI

/// M0-Bildschirm: beweist, dass App → Backend → Datenbank durchgängig
/// funktioniert. Wird ab M4 durch die Alarm-Liste ersetzt.
///
/// Die drei Zustände (Laden / Fehler / Erfolg) sind hier absichtlich schon
/// ausformuliert — genau das verlangt der Projektplan von jedem Bildschirm.
struct ContentView: View {

    @State private var viewModel = HealthViewModel()

    var body: some View {
        NavigationStack {
            Group {
                switch viewModel.state {
                case .idle, .loading:
                    ProgressView("Verbinde mit dem Backend …")

                case .loaded(let status):
                    successView(status)

                case .failed(let message):
                    failureView(message)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("Flugalarm")
            .task { await viewModel.load() }
        }
    }

    // MARK: - Erfolgsfall

    private func successView(_ status: HealthStatus) -> some View {
        VStack(spacing: 24) {
            Image(systemName: status.isHealthy
                  ? "checkmark.circle.fill"
                  : "exclamationmark.triangle.fill")
                .font(.system(size: 56))
                .foregroundStyle(status.isHealthy ? .green : .orange)

            VStack(spacing: 8) {
                Text(status.isHealthy ? "Backend erreichbar" : "Backend eingeschränkt")
                    .font(.title2.bold())

                if !status.isDatabaseReachable {
                    Text("Die Datenbank antwortet nicht. Läuft `docker compose up -d db`?")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }

            VStack(spacing: 4) {
                LabeledContent("Datenbank", value: status.database)
                LabeledContent("Version", value: status.version)
                LabeledContent("Umgebung", value: status.environment)
            }
            .font(.footnote.monospaced())
            .padding()
            .background(.quaternary, in: .rect(cornerRadius: 12))

            Button("Erneut prüfen") {
                Task { await viewModel.load() }
            }
            .buttonStyle(.bordered)
        }
        .padding()
    }

    // MARK: - Fehlerfall

    private func failureView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Keine Verbindung", systemImage: "wifi.exclamationmark")
        } description: {
            Text(message)
        } actions: {
            Button("Erneut versuchen") {
                Task { await viewModel.load() }
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

// MARK: - Previews
//
// Previews rendern jeden Zustand ohne laufenden Server — die billigste Form
// von visuellem Test. Möglich, weil das ViewModel gegen ein Protokoll läuft.

private struct StubClient: APIClientProtocol {
    let result: Result<HealthStatus, APIError>

    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        switch result {
        case .success(let status):
            guard let typed = status as? T else { throw APIError.decoding }
            return typed
        case .failure(let error):
            throw error
        }
    }
}

#Preview("Alles läuft") {
    let vm = HealthViewModel(client: StubClient(result: .success(
        HealthStatus(status: "ok", database: "ok", version: "0.1.0", environment: "local")
    )))
    return ContentView(viewModel: vm)
}

#Preview("Datenbank weg") {
    let vm = HealthViewModel(client: StubClient(result: .success(
        HealthStatus(status: "degraded", database: "unavailable",
                     version: "0.1.0", environment: "local")
    )))
    return ContentView(viewModel: vm)
}

#Preview("Backend aus") {
    let vm = HealthViewModel(client: StubClient(result: .failure(.notReachable)))
    return ContentView(viewModel: vm)
}

extension ContentView {
    /// Nur für Previews und Tests.
    init(viewModel: HealthViewModel) {
        self._viewModel = State(initialValue: viewModel)
    }
}
