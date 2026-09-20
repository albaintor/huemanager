import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: HomeSyncModel

    var body: some View {
        NavigationStack {
            Form {
                connectionSection
                syncSection
                proposedMovesSection
            }
            .navigationTitle("HueManager Home Sync")
            .task {
                model.start()
            }
        }
    }

    private var connectionSection: some View {
        Section("Connexion") {
            TextField("URL HueManager", text: $model.serverURL)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .autocorrectionDisabled()

            TextField("Profil Bridge Hue", text: $model.bridgeProfile)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            Picker("Maison Apple", selection: $model.selectedHomeID) {
                if model.homes.isEmpty {
                    Text(model.homeKitLoaded ? "Aucune maison disponible" : "Chargement…")
                        .tag("")
                }
                ForEach(model.homes, id: \.uniqueIdentifier) { home in
                    Text(home.name).tag(home.uniqueIdentifier.uuidString)
                }
            }

            LabeledContent("Autorisation Maison", value: model.homeKitAuthorization)
            LabeledContent(
                "Chargement HomeKit",
                value: model.homeKitLoaded ? "Terminé" : "En cours"
            )
            LabeledContent("Maisons détectées", value: "\(model.homes.count)")

            Button("Actualiser les données Maison") {
                model.reloadHomeKit()
            }

            Text(model.homeKitDiagnostic)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            Button("Tester HueManager") {
                Task { await model.testConnection() }
            }
        }
    }

    private var syncSection: some View {
        Section("Synchronisation") {
            Button("Publier l’inventaire Maison") {
                Task { await model.publishInventory() }
            }

            Button("Analyser Hue ↔ Maison") {
                Task { await model.loadPlan() }
            }

            Button("Appliquer les déplacements") {
                Task { await model.applyPlan() }
            }
            .disabled(model.pendingMoves == 0)

            Toggle("Synchronisation automatique sûre", isOn: $model.automaticSyncEnabled)

            Text(
                "Le mode automatique ne déplace que les accessoires dont le matching " +
                "et la pièce cible dépassent les seuils de confiance. Les cas ambigus " +
                "restent en attente."
            )
            .font(.caption)
            .foregroundStyle(.secondary)

            statusView

            if let summary = model.planSummary {
                LabeledContent("Pièces Hue", value: "\(summary.hueRooms)")
                LabeledContent("Pièces associées", value: "\(summary.mappedRooms)")
                LabeledContent("Déplacements", value: "\(summary.moves)")
                LabeledContent("Déjà corrects", value: "\(summary.alreadyCorrect)")
                LabeledContent(
                    "Accessoires non reconnus",
                    value: "\(summary.unmatchedAccessories)"
                )
                LabeledContent(
                    "Correspondances ambiguës",
                    value: "\(summary.ambiguousAccessories)"
                )
            }
        }
    }

    @ViewBuilder
    private var proposedMovesSection: some View {
        if !model.moves.isEmpty {
            Section("Déplacements proposés") {
                ForEach(model.moves) { move in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(move.accessoryName)
                            .font(.headline)
                        Text(
                            "\(move.fromRoomName ?? "Sans pièce") → \(move.toRoomName)"
                        )
                        .font(.subheadline)

                        Text(
                            "Appareil: \(move.matchMethod) · pièce: " +
                            "\(move.roomMatchMethod ?? "inconnue")" +
                            confidenceText(move.roomMatchConfidence)
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var statusView: some View {
        HStack(alignment: .top) {
            Image(systemName: model.hasError ? "exclamationmark.triangle" : "info.circle")
            Text(model.status)
                .textSelection(.enabled)
        }
        .foregroundStyle(model.hasError ? .red : .secondary)
    }

    private func confidenceText(_ value: Double?) -> String {
        guard let value else { return "" }
        return " (\(Int((value * 100).rounded())) %)"
    }
}
