import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: HomeSyncModel

    var body: some View {
        NavigationStack {
            Form {
                connectionSection
                syncSection
                roomAssociationsSection
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

            LabeledContent(
                "Actualisation en arrière-plan",
                value: model.backgroundRefreshStatus
            )

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
    private var roomAssociationsSection: some View {
        if !model.roomPlans.isEmpty {
            Section("Associations de pièces et impact") {
                ForEach(model.roomPlans) { room in
                    roomAssociationView(room)
                }
            }
        }
    }

    private func roomAssociationView(_ room: SyncRoomPlan) -> some View {
        let hueDevices = room.hueDevices ?? []
        let appleAccessories = room.appleAccessories ?? []
        let plannedMoves = room.plannedMoves ?? []

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Hue · \(room.hueRoomName)")
                        .font(.headline)
                    Text("\(hueDevices.count) accessoire(s)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()
                Image(systemName: "arrow.left.arrow.right")
                    .foregroundStyle(.secondary)
                Spacer()

                VStack(alignment: .trailing, spacing: 2) {
                    Text("Maison · \(room.appleRoomName ?? "Non associée")")
                        .font(.headline)
                    Text("\(appleAccessories.count) actuellement")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let method = room.method {
                Text(
                    "Association \(method)" +
                    confidenceText(room.confidence) +
                    " · \(plannedMoves.count) déplacement(s)"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    if hueDevices.isEmpty {
                        Text("Aucun accessoire Hue dans cette pièce.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(hueDevices) { device in
                            hueDeviceRow(device, targetRoomName: room.appleRoomName)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Label(
                    "Présents côté Philips Hue",
                    systemImage: "lightbulb.2"
                )
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    if room.appleRoomName == nil {
                        Text("Aucune pièce Apple associée.")
                            .foregroundStyle(.secondary)
                    } else if appleAccessories.isEmpty {
                        Text("Aucun accessoire actuellement dans cette pièce Apple.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(appleAccessories) { accessory in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(accessory.name)
                                if let hueName = accessory.matchedHueDeviceName {
                                    Text("↔ Hue : \(hueName)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                } else {
                                    Text("Non associé à un appareil Hue de cette analyse")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Label(
                    "Présents côté Apple Maison avant synchro",
                    systemImage: "house"
                )
            }

            if !plannedMoves.isEmpty {
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(plannedMoves) { move in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(move.accessoryName)
                                    .fontWeight(.medium)
                                Text(
                                    "\(move.fromRoomName ?? "Sans pièce") → " +
                                    "\(move.toRoomName)"
                                )
                                .font(.subheadline)
                                Text("Correspond à Hue : \(move.hueDeviceName)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } label: {
                    Label(
                        "Impact après synchronisation",
                        systemImage: "arrow.right.circle"
                    )
                }
            }
        }
        .padding(.vertical, 6)
    }

    @ViewBuilder
    private func hueDeviceRow(
        _ device: SyncRoomHueDevice,
        targetRoomName: String?
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(device.name)

            if let appleName = device.appleAccessoryName {
                HStack(spacing: 4) {
                    Text("Apple : \(appleName)")
                    Text("·")
                    if device.status == "move" {
                        Text(
                            "\(device.appleCurrentRoomName ?? "Sans pièce") → " +
                            "\(targetRoomName ?? "Pièce cible inconnue")"
                        )
                    } else if device.status == "already_correct" {
                        Text(device.appleCurrentRoomName ?? targetRoomName ?? "Pièce inconnue")
                        Image(systemName: "checkmark.circle.fill")
                    } else {
                        Text(device.appleCurrentRoomName ?? "Sans pièce")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            } else {
                Text("Aucune correspondance trouvée dans Apple Maison")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
