import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: HomeSyncModel

    var body: some View {
        Form {
            Section("Connexion") {
                TextField("HueManager URL", text: $model.serverURL)
                    .textFieldStyle(.roundedBorder)
                TextField("Profil Bridge Hue", text: $model.bridgeProfile)
                    .textFieldStyle(.roundedBorder)
                Picker("Maison Apple", selection: $model.selectedHomeID) {
                    ForEach(model.homes, id: \.uniqueIdentifier) { home in
                        Text(home.name).tag(home.uniqueIdentifier.uuidString)
                    }
                }
            }

            Section("Synchronisation") {
                HStack {
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
                }

                Text(model.status)
                    .foregroundStyle(model.hasError ? .red : .secondary)

                if let summary = model.planSummary {
                    Grid(alignment: .leading) {
                        GridRow {
                            Text("Pièces Hue")
                            Text("\(summary.hueRooms)")
                        }
                        GridRow {
                            Text("Pièces associées")
                            Text("\(summary.mappedRooms)")
                        }
                        GridRow {
                            Text("Déplacements")
                            Text("\(summary.moves)")
                        }
                        GridRow {
                            Text("Déjà corrects")
                            Text("\(summary.alreadyCorrect)")
                        }
                        GridRow {
                            Text("Accessoires non reconnus")
                            Text("\(summary.unmatchedAccessories)")
                        }
                    }
                }
            }

            if !model.moves.isEmpty {
                Section("Déplacements proposés") {
                    ForEach(model.moves) { move in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(move.accessoryName)
                                Text("\(move.fromRoomName ?? "Sans pièce") → \(move.toRoomName)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(move.matchMethod)
                                .font(.caption2)
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(minWidth: 720, minHeight: 520)
        .padding()
        .task {
            model.start()
        }
    }
}
