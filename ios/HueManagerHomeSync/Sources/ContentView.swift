import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: HomeSyncModel

    var body: some View {
        NavigationStack {
            Form {
                connectionSection
                serverActivitySection
                syncSection
                if !model.usesHomeAssistantSource {
                    reassociationSection
                }
                roomAssociationsSection
                proposedMovesSection
            }
            .navigationTitle("HueManager Home Sync")
            .disabled(model.webApplyRunning || model.planApplying || model.planLoading || model.automaticSyncRunning)
        }
    }

    private var bridgeSelection: Binding<String> {
        Binding(
            get: {
                if model.bridges.contains(where: { $0.name == model.bridgeProfile }) {
                    return model.bridgeProfile
                }
                return model.bridges.first?.name ?? ""
            },
            set: { model.bridgeProfile = $0 }
        )
    }

    private var homeSelection: Binding<String> {
        Binding(
            get: {
                if model.homes.contains(
                    where: { $0.uniqueIdentifier.uuidString == model.selectedHomeID }
                ) {
                    return model.selectedHomeID
                }
                return model.homes.first?.uniqueIdentifier.uuidString ?? ""
            },
            set: { model.selectedHomeID = $0 }
        )
    }

    private var connectionSection: some View {
        Section("Connexion") {
            TextField("URL HueManager", text: $model.serverURL)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .autocorrectionDisabled()

            Picker("Source de référence", selection: $model.syncSource) {
                Text("Philips Hue").tag("hue")
                Text("Home Assistant").tag("home_assistant")
            }

            if model.usesHomeAssistantSource {
                LabeledContent("Source", value: "Home Assistant via HueManager")
                Text(
                    "L’URL et le Long-Lived Access Token Home Assistant se configurent " +
                    "dans l’onglet Apple Maison de l’interface web HueManager."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            } else if model.bridges.isEmpty {
                LabeledContent("Bridge Hue") {
                    HStack(spacing: 8) {
                        ProgressView()
                        Text("Chargement…")
                            .foregroundStyle(.secondary)
                    }
                }

                Button("Charger les Bridges HueManager") {
                    Task { await model.loadBridges() }
                }
            } else {
                Picker("Pont utilisé pour la synchronisation", selection: bridgeSelection) {
                    ForEach(model.bridges) { bridge in
                        Text("\(bridge.name) · \(bridge.host)")
                            .tag(bridge.name)
                    }
                }
            }

            Text(NSLocalizedString(model.usesHomeAssistantSource
                 ? "La source Home Assistant utilise ses zones et appareils. Aucun pont Hue sélectionné n’intervient."
                 : "Le pont sélectionné est utilisé par Analyser, Appliquer, le mode automatique, les demandes web et la réassociation. Il ne filtre pas l’inventaire Apple publié et ne sert pas au test de connexion HueManager.", comment: "Selected source scope"))
                .font(.caption)
                .foregroundStyle(.secondary)

            if model.homes.isEmpty {
                LabeledContent("Maison Apple") {
                    HStack(spacing: 8) {
                        if !model.homeKitLoaded {
                            ProgressView()
                        }
                        Text(model.homeKitLoaded ? "Aucune maison disponible" : "Chargement…")
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Picker("Maison Apple", selection: homeSelection) {
                    ForEach(model.homes, id: \.uniqueIdentifier) { home in
                        Text(home.name).tag(home.uniqueIdentifier.uuidString)
                    }
                }
            }

            LabeledContent("Autorisation Maison", value: model.homeKitAuthorization)
            LabeledContent(
                "Chargement HomeKit",
                value: model.homeKitLoaded ? "Terminé" : "En cours"
            )
            LabeledContent("Maisons détectées", value: "\(model.homes.count)")

            Button {
                Task { await model.refreshAndPublishInventory() }
            } label: {
                HStack {
                    if model.inventoryPublishing {
                        ProgressView()
                    }
                    Text("Actualiser et publier l’inventaire")
                }
            }
            .disabled(!model.homeKitLoaded || model.inventoryPublishing)

            LabeledContent(
                "Dernier inventaire publié",
                value: model.lastPublishedInventoryDisplay
            )

            Text(model.homeKitDiagnostic)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            Button {
                Task { await model.testConnection() }
            } label: {
                HStack {
                    if model.connectionTesting {
                        ProgressView()
                    }
                    Text("Tester HueManager")
                }
            }
            .disabled(model.connectionTesting)
            Text("Actualiser et publier relit toute la maison Apple sélectionnée puis l’envoie au web, sans déplacement. Tester HueManager vérifie le serveur, pas le pont Hue.")
                .font(.caption)
                .foregroundStyle(.secondary)

            LabeledContent("Connexion HueManager", value: model.connectionStatus)
        }
    }

    private var serverActivitySection: some View {
        Section("Activité serveur") {
            LabeledContent("État") {
                HStack(spacing: 8) {
                    if model.serverActivityInProgress {
                        ProgressView()
                    } else {
                        Image(
                            systemName: model.serverActivityState == "Erreur"
                                ? "exclamationmark.triangle.fill"
                                : (
                                    model.serverActivityState == "Terminé"
                                        ? "checkmark.circle.fill"
                                        : "circle"
                                )
                        )
                        .foregroundStyle(serverActivityColor)
                    }
                    Text(model.serverActivityState)
                }
            }

            Text(model.serverActivityDetail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            DisclosureGroup(
                "Journal des échanges (\(model.serverActivityLog.count))"
            ) {
                if model.serverActivityLog.isEmpty {
                    Text("Aucune activité enregistrée.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(
                        Array(
                            model.serverActivityLog
                                .suffix(30)
                                .reversed()
                                .enumerated()
                        ),
                        id: \.offset
                    ) { _, entry in
                        Text(entry)
                            .font(.caption2.monospaced())
                            .textSelection(.enabled)
                    }

                    Button("Effacer le journal", role: .destructive) {
                        model.clearServerActivityLog()
                    }
                }
            }
        }
    }

    private var serverActivityColor: Color {
        switch model.serverActivityState {
        case "Erreur":
            return .red
        case "Terminé":
            return .green
        default:
            return .secondary
        }
    }

    private var syncSection: some View {
        Section("Synchronisation") {
            Button {
                Task { await model.publishInventory() }
            } label: {
                HStack {
                    if model.inventoryPublishing {
                        ProgressView()
                    }
                    Text("Publier l’inventaire Maison")
                }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                model.inventoryPublishing
            )

            Button("Analyser et afficher le détail") {
                Task { await model.loadPlan() }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                (!model.usesHomeAssistantSource && model.bridges.isEmpty)
            )
            Text("Analyser publie un inventaire frais puis compare la maison à la source sélectionnée (et au pont sélectionné pour Hue). Aucun accessoire n’est déplacé.")
                .font(.caption)
                .foregroundStyle(.secondary)

            Button("Appliquer les déplacements") {
                Task { await model.applyPlan() }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                model.pendingMoves == 0
            )
            Text("Appliquer déplace réellement les accessoires du plan dans Apple Maison, uniquement pour les pièces cochées. Publier l’inventaire ne déplace rien.")
                .font(.caption)
                .foregroundStyle(.secondary)

            Text("Depuis le web, Enregistrer conserve la configuration. Enregistrer et appliquer déclenche les déplacements ici : garde cette app ouverte avec la même maison, source et pont. Les demandes sont vérifiées toutes les 5 secondes ; le mode automatique n’a pas besoin d’être activé.")
                .font(.caption)
                .foregroundStyle(.secondary)

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
                LabeledContent(
                    "Pièces \(model.sourceDisplayName)",
                    value: "\(summary.hueRooms)"
                )
                LabeledContent("Pièces associées", value: "\(summary.mappedRooms)")
                LabeledContent(
                    "Pièces sélectionnées",
                    value: "\(model.selectedRoomCount)/\(model.roomPlans.count)"
                )
                LabeledContent(
                    "Déplacements sélectionnés",
                    value: "\(model.pendingMoves)/\(summary.moves)"
                )
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

    private var reassociationSection: some View {
        Section("Réassociation Apple Home") {
            Text("Ces trois boutons utilisent le pont Hue et la maison Apple sélectionnés. Sauvegarder mémorise les pièces actuelles, Analyser prépare la restauration sans déplacer, Restaurer effectue les déplacements HomeKit.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(
                "À utiliser avant de supprimer puis recréer la liaison Apple du Bridge. " +
                "HueManager sauvegarde les associations accessoire/pièce sans dépendre " +
                "uniquement des UUID Apple, qui peuvent être recréés."
            )
            .font(.caption)
            .foregroundStyle(.secondary)

            Button("1. Sauvegarder les pièces avant suppression") {
                Task { await model.createReassociationBackup() }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                model.bridges.isEmpty ||
                model.inventoryPublishing
            )

            Button("2. Après réassociation : analyser la restauration") {
                Task { await model.loadReassociationPlan() }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                model.bridges.isEmpty ||
                model.inventoryPublishing
            )

            Button("3. Restaurer les pièces Apple") {
                Task { await model.applyReassociationPlan() }
            }
            .disabled(
                !model.homeKitLoaded ||
                model.homes.isEmpty ||
                model.reassociationPendingMoves == 0
            )

            if model.reassociationBackupCount > 0 {
                LabeledContent(
                    "Sauvegarde",
                    value: "\(model.reassociationBackupCount) accessoire(s)"
                )
                if let date = model.reassociationBackupAt {
                    Text("Créée : \(date)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }

            if let summary = model.reassociationSummary {
                LabeledContent(
                    "Accessoires reconnus",
                    value: "\(summary.matchedAccessories)/\(summary.savedAccessories)"
                )
                LabeledContent(
                    "Déplacements à restaurer",
                    value: "\(summary.moves)"
                )
                LabeledContent(
                    "Déjà dans la bonne pièce",
                    value: "\(summary.alreadyCorrect)"
                )
                LabeledContent(
                    "Non reconnus",
                    value: "\(summary.unmatchedAccessories)"
                )
                if summary.missingRooms > 0 {
                    LabeledContent(
                        "Pièces cibles introuvables",
                        value: "\(summary.missingRooms)"
                    )
                }
            }

            Text(
                "La restauration est conservatrice : un accessoire ambigu n'est jamais déplacé. " +
                "Les correspondances fortes utilisent notamment le numéro de série, les identifiants " +
                "HomeKit/Matter disponibles et la position de l'accessoire derrière le pont."
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var roomAssociationsSection: some View {
        if !model.roomPlans.isEmpty {
            Section("Associations de pièces et impact") {
                HStack {
                    Button("Tout sélectionner") {
                        model.selectAllRooms()
                    }
                    Spacer()
                    Button("Aucune") {
                        model.deselectAllRooms()
                    }
                }

                Text(
                    "Seules les pièces cochées seront modifiées dans Apple Maison. " +
                    "La sélection est mémorisée pour cette source et cette Maison."
                )
                .font(.caption)
                .foregroundStyle(.secondary)

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
            Toggle(
                "Synchroniser cette pièce",
                isOn: Binding(
                    get: { model.isRoomSelected(room.hueRoomID) },
                    set: { model.setRoomSelected(room.hueRoomID, selected: $0) }
                )
            )

            HStack(alignment: .firstTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(model.sourceDisplayName) · \(room.hueRoomName)")
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
                        Text("Aucun appareil \(model.sourceDisplayName) dans cette pièce.")
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
                    "Présents côté \(model.sourceDisplayName)",
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
                                    Text("↔ \(model.sourceDisplayName) : \(hueName)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                } else {
                                    Text(
                                        "Non associé à un appareil " +
                                        "\(model.sourceDisplayName) de cette analyse"
                                    )
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
                                Text(
                                    "Correspond à \(model.sourceDisplayName) : " +
                                    "\(move.hueDeviceName)"
                                )
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
        .opacity(model.isRoomSelected(room.hueRoomID) ? 1 : 0.55)
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
                if device.status == "ambiguous_accessory" {
                    Text("Plusieurs correspondances possibles : choisis l’accessoire Apple à associer.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                } else {
                    Text("Aucune correspondance trouvée dans Apple Maison")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if device.matchMethod == "name_type" {
                Text("Correspondance par nom + type d’appareil")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            let candidates = model.manualCandidates(for: device)
            if !candidates.isEmpty {
                Picker("Association Apple manuelle", selection: Binding(
                    get: { model.accessoryMappings[device.id] ?? "" },
                    set: { accessoryID in
                        Task { await model.associateAccessory(accessoryID, with: device.id) }
                    }
                )) {
                    Text("Correspondance automatique").tag("")
                    ForEach(candidates) { candidate in
                        Text(candidate.choiceLabel).tag(candidate.id)
                    }
                }
                .disabled(
                    model.accessoryMappingSaving || model.inventoryPublishing || model.automaticSyncRunning
                )
            }
        }
    }

    @ViewBuilder
    private var proposedMovesSection: some View {
        if !model.selectedMoves.isEmpty {
            Section("Déplacements des pièces sélectionnées") {
                ForEach(model.selectedMoves) { move in
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
