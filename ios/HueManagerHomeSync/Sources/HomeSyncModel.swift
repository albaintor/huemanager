import Combine
import Foundation
import HomeKit
import UIKit

struct SyncMove: Codable, Identifiable {
    let accessoryID: String
    let accessoryName: String
    let fromRoomID: String?
    let fromRoomName: String?
    let toRoomID: String
    let toRoomName: String
    let hueDeviceID: String
    let hueDeviceName: String
    let hueRoomID: String?
    let hueRoomName: String?
    let matchMethod: String
    let roomMatchMethod: String?
    let roomMatchConfidence: Double?

    var id: String { accessoryID + ":" + toRoomID }

    enum CodingKeys: String, CodingKey {
        case accessoryID = "accessory_id"
        case accessoryName = "accessory_name"
        case fromRoomID = "from_room_id"
        case fromRoomName = "from_room_name"
        case toRoomID = "to_room_id"
        case toRoomName = "to_room_name"
        case hueDeviceID = "hue_device_id"
        case hueDeviceName = "hue_device_name"
        case hueRoomID = "hue_room_id"
        case hueRoomName = "hue_room_name"
        case matchMethod = "match_method"
        case roomMatchMethod = "room_match_method"
        case roomMatchConfidence = "room_match_confidence"
    }
}

struct SyncSummary: Codable {
    let hueRooms: Int
    let mappedRooms: Int
    let moves: Int
    let alreadyCorrect: Int
    let unmatchedAccessories: Int
    let ambiguousAccessories: Int
    let missingHomeRooms: Int

    enum CodingKeys: String, CodingKey {
        case hueRooms = "hue_rooms"
        case mappedRooms = "mapped_rooms"
        case moves
        case alreadyCorrect = "already_correct"
        case unmatchedAccessories = "unmatched_accessories"
        case ambiguousAccessories = "ambiguous_accessories"
        case missingHomeRooms = "missing_home_rooms"
    }
}

struct SyncRoomHueDevice: Codable, Identifiable {
    let id: String
    let name: String
    let status: String
    let matchMethod: String?
    let appleAccessoryID: String?
    let appleAccessoryName: String?
    let appleCurrentRoomID: String?
    let appleCurrentRoomName: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case status
        case matchMethod = "match_method"
        case appleAccessoryID = "apple_accessory_id"
        case appleAccessoryName = "apple_accessory_name"
        case appleCurrentRoomID = "apple_current_room_id"
        case appleCurrentRoomName = "apple_current_room_name"
    }
}

struct SyncRoomAppleAccessory: Codable, Identifiable {
    let id: String
    let name: String
    let manufacturer: String?
    let model: String?
    let origin: String?
    let bridgeName: String?
    let bridgeManufacturer: String?
    let matchedHueDeviceID: String?
    let matchedHueDeviceName: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case manufacturer
        case model
        case origin
        case bridgeName = "bridge_name"
        case bridgeManufacturer = "bridge_manufacturer"
        case matchedHueDeviceID = "matched_hue_device_id"
        case matchedHueDeviceName = "matched_hue_device_name"
    }
}

struct SyncRoomImpact: Codable {
    let hueDeviceCount: Int
    let appleAccessoryCount: Int
    let moveCount: Int
    let alreadyCorrectCount: Int

    enum CodingKeys: String, CodingKey {
        case hueDeviceCount = "hue_device_count"
        case appleAccessoryCount = "apple_accessory_count"
        case moveCount = "move_count"
        case alreadyCorrectCount = "already_correct_count"
    }
}

struct SyncRoomPlan: Codable, Identifiable {
    let hueRoomID: String
    let hueRoomName: String
    let appleRoomID: String?
    let appleRoomName: String?
    let method: String?
    let confidence: Double?
    let status: String
    let hueDevices: [SyncRoomHueDevice]?
    let appleAccessories: [SyncRoomAppleAccessory]?
    let plannedMoves: [SyncMove]?
    let impact: SyncRoomImpact?

    var id: String { hueRoomID }

    enum CodingKeys: String, CodingKey {
        case hueRoomID = "hue_room_id"
        case hueRoomName = "hue_room_name"
        case appleRoomID = "apple_room_id"
        case appleRoomName = "apple_room_name"
        case method
        case confidence
        case status
        case hueDevices = "hue_devices"
        case appleAccessories = "apple_accessories"
        case plannedMoves = "planned_moves"
        case impact
    }
}

private struct SyncPlan: Codable {
    let rooms: [SyncRoomPlan]?
    let devices: [SyncDeviceRow]?
    let actions: [SyncMove]
    let summary: SyncSummary
    let selectedHueRoomIDs: [String]?

    enum CodingKeys: String, CodingKey {
        case rooms
        case devices
        case actions
        case summary
        case selectedHueRoomIDs = "selected_hue_room_ids"
    }
}

struct BridgeInfo: Codable, Identifiable, Hashable {
    let name: String
    let host: String
    let verifyTLS: Bool?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name
        case host
        case verifyTLS = "verify_tls"
    }
}

private struct BridgesResponse: Codable {
    let bridges: [BridgeInfo]
}

struct SyncDeviceRow: Codable, Identifiable {
    let hueDeviceID: String
    let hueDeviceName: String
    let hueRoomID: String
    let hueRoomName: String?
    let appleAccessoryID: String?
    let appleAccessoryName: String?
    let appleRoomID: String?
    let appleRoomName: String?
    let desiredAppleRoomID: String?
    let desiredAppleRoomName: String?
    let status: String
    let matchMethod: String?

    var id: String { hueDeviceID }

    enum CodingKeys: String, CodingKey {
        case hueDeviceID = "hue_device_id"
        case hueDeviceName = "hue_device_name"
        case hueRoomID = "hue_room_id"
        case hueRoomName = "hue_room_name"
        case appleAccessoryID = "apple_accessory_id"
        case appleAccessoryName = "apple_accessory_name"
        case appleRoomID = "apple_room_id"
        case appleRoomName = "apple_room_name"
        case desiredAppleRoomID = "desired_apple_room_id"
        case desiredAppleRoomName = "desired_apple_room_name"
        case status
        case matchMethod = "match_method"
    }
}

private struct HealthResponse: Codable {
    let status: String
    let version: String
}

private struct RoomSelectionRequest: Codable {
    let homeID: String
    let hueRoomIDs: [String]

    enum CodingKeys: String, CodingKey {
        case homeID = "home_id"
        case hueRoomIDs = "hue_room_ids"
    }
}

private struct HomeInfo: Codable {
    let id: String
    let name: String
}

private struct RoomInfo: Codable {
    let id: String
    let name: String
}

private struct AccessoryInfo: Codable {
    let id: String
    let name: String
    let roomID: String?
    let roomName: String?
    let manufacturer: String?
    let model: String?
    let serialNumber: String?
    let legacyIdentifier: String?
    let isBridged: Bool
    let bridgeID: String?
    let bridgeName: String?
    let bridgeManufacturer: String?
    let bridgeModel: String?
    let hapInstanceID: UInt64?
    let vendorAccessory: Bool?
    let bridgeChildIndex: Int?
    let bridgeReportedIdentifierIndex: Int?
    let bridgeLegacyIdentifierIndex: Int?
    let serviceTypes: [String]
    let reachable: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case roomID = "room_id"
        case roomName = "room_name"
        case manufacturer
        case model
        case serialNumber = "serial_number"
        case legacyIdentifier = "legacy_identifier"
        case isBridged = "is_bridged"
        case bridgeID = "bridge_id"
        case bridgeName = "bridge_name"
        case bridgeManufacturer = "bridge_manufacturer"
        case bridgeModel = "bridge_model"
        case hapInstanceID = "hap_instance_id"
        case vendorAccessory = "vendor_accessory"
        case bridgeChildIndex = "bridge_child_index"
        case bridgeReportedIdentifierIndex = "bridge_reported_identifier_index"
        case bridgeLegacyIdentifierIndex = "bridge_legacy_identifier_index"
        case serviceTypes = "service_types"
        case reachable
    }
}

private struct BridgeIdentityInfo: Codable {
    let id: String
    let name: String
    let manufacturer: String?
    let model: String?
    let hapInstanceID: UInt64?
    let vendorAccessory: Bool?
    let bridgedAccessoryIDs: [String]
    let bridgedAccessoryLegacyIDs: [String]
    let uniqueIdentifiersForBridgedAccessories: [String]
    let identifiersForBridgedAccessories: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case manufacturer
        case model
        case hapInstanceID = "hap_instance_id"
        case vendorAccessory = "vendor_accessory"
        case bridgedAccessoryIDs = "bridged_accessory_ids"
        case bridgedAccessoryLegacyIDs = "bridged_accessory_legacy_ids"
        case uniqueIdentifiersForBridgedAccessories =
            "unique_identifiers_for_bridged_accessories"
        case identifiersForBridgedAccessories =
            "identifiers_for_bridged_accessories"
    }
}

private struct HomeInventory: Codable {
    let home: HomeInfo
    let rooms: [RoomInfo]
    let accessories: [AccessoryInfo]
    let bridges: [BridgeIdentityInfo]
}

private struct SyncResult: Codable {
    let homeID: String
    let bridgeProfile: String
    let moved: Int
    let failed: [[String: String]]

    enum CodingKeys: String, CodingKey {
        case homeID = "home_id"
        case bridgeProfile = "bridge_profile"
        case moved
        case failed
    }
}

private struct InventoryPublishResponse: Codable {
    let ok: Bool
    let receivedAt: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case receivedAt = "received_at"
    }
}

private struct EmptyRequest: Codable {}

private struct ReassociationBackupResponse: Codable {
    let ok: Bool
    let createdAt: String?
    let accessories: Int

    enum CodingKeys: String, CodingKey {
        case ok
        case createdAt = "created_at"
        case accessories
    }
}

struct ReassociationSummary: Codable {
    let savedAccessories: Int
    let currentAccessories: Int
    let matchedAccessories: Int
    let moves: Int
    let alreadyCorrect: Int
    let unmatchedAccessories: Int
    let missingRooms: Int

    enum CodingKeys: String, CodingKey {
        case savedAccessories = "saved_accessories"
        case currentAccessories = "current_accessories"
        case matchedAccessories = "matched_accessories"
        case moves
        case alreadyCorrect = "already_correct"
        case unmatchedAccessories = "unmatched_accessories"
        case missingRooms = "missing_rooms"
    }
}

private struct ReassociationPlan: Codable {
    let backupCreatedAt: String?
    let actions: [SyncMove]
    let summary: ReassociationSummary

    enum CodingKeys: String, CodingKey {
        case backupCreatedAt = "backup_created_at"
        case actions
        case summary
    }
}

@MainActor
final class HomeSyncModel: NSObject, ObservableObject, HMHomeManagerDelegate {
    static let shared = HomeSyncModel()

    private enum DefaultsKey {
        static let serverURL = "serverURL"
        static let bridgeProfile = "bridgeProfile"
        static let selectedHomeID = "selectedHomeID"
        static let automaticSyncEnabled = "automaticSyncEnabled"
        static let selectedHueRoomIDsPrefix = "selectedHueRoomIDs"
    }

    @Published var serverURL: String {
        didSet {
            UserDefaults.standard.set(serverURL, forKey: DefaultsKey.serverURL)
        }
    }

    @Published var bridgeProfile: String {
        didSet {
            UserDefaults.standard.set(bridgeProfile, forKey: DefaultsKey.bridgeProfile)
            if bridgeProfile != oldValue {
                clearPlanForContextChange()
            }
        }
    }

    @Published var selectedHomeID: String {
        didSet {
            UserDefaults.standard.set(selectedHomeID, forKey: DefaultsKey.selectedHomeID)
            if selectedHomeID != oldValue {
                clearPlanForContextChange()
            }
        }
    }

    @Published private(set) var homes: [HMHome] = []
    @Published private(set) var bridges: [BridgeInfo] = []
    @Published private(set) var moves: [SyncMove] = []
    @Published private(set) var roomPlans: [SyncRoomPlan] = []
    @Published private(set) var selectedHueRoomIDs: Set<String> = []
    @Published private(set) var planSummary: SyncSummary?
    @Published private(set) var status = "En attente de l’autorisation Apple Maison…"
    @Published private(set) var hasError = false
    @Published private(set) var homeKitAuthorization = "Indéterminée"
    @Published private(set) var homeKitLoaded = false
    @Published private(set) var backgroundRefreshStatus = "Indéterminée"
    @Published private(set) var connectionStatus = "Non testé"
    @Published private(set) var connectionTesting = false
    @Published private(set) var inventoryPublishing = false
    @Published private(set) var serverActivityState = "Au repos"
    @Published private(set) var serverActivityDetail = "Aucun échange serveur."
    @Published private(set) var serverActivityLog: [String] = []
    @Published private(set) var serverActivityInProgress = false
    @Published private(set) var lastPublishedInventoryAt: String?

    @Published private(set) var reassociationMoves: [SyncMove] = []
    @Published private(set) var reassociationSummary: ReassociationSummary?
    @Published private(set) var reassociationBackupCount = 0
    @Published private(set) var reassociationBackupAt: String?

    @Published var automaticSyncEnabled: Bool {
        didSet {
            UserDefaults.standard.set(
                automaticSyncEnabled,
                forKey: DefaultsKey.automaticSyncEnabled
            )
            configureAutomaticSync()
        }
    }

    private var homeManager: HMHomeManager?
    private var automaticTimer: Timer?
    private var automaticSyncRunning = false
    private var activeServerRequests = 0
    private var started = false

    var selectedMoves: [SyncMove] {
        moves.filter { move in
            guard let roomID = move.hueRoomID else { return false }
            return selectedHueRoomIDs.contains(roomID)
        }
    }

    var pendingMoves: Int { selectedMoves.count }

    var reassociationPendingMoves: Int { reassociationMoves.count }

    var selectedRoomCount: Int {
        roomPlans.reduce(into: 0) { count, room in
            if selectedHueRoomIDs.contains(room.hueRoomID) {
                count += 1
            }
        }
    }

    var homeKitDiagnostic: String {
        let raw = homeManager?.authorizationStatus.rawValue.description ?? "n/a"
        return "auth=\(homeKitAuthorization) raw=\(raw) " +
            "loaded=\(homeKitLoaded) homes=\(homes.count)"
    }

    var lastPublishedInventoryDisplay: String {
        guard let value = lastPublishedInventoryAt else {
            return "Non publié dans cette session"
        }
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: value) else { return value }

        let display = DateFormatter()
        display.locale = Locale(identifier: "fr_FR")
        display.dateStyle = .medium
        display.timeStyle = .medium
        return display.string(from: date)
    }

    private override init() {
        let defaults = UserDefaults.standard
        serverURL = defaults.string(forKey: DefaultsKey.serverURL) ?? ""
        bridgeProfile = defaults.string(forKey: DefaultsKey.bridgeProfile) ?? ""
        selectedHomeID = defaults.string(forKey: DefaultsKey.selectedHomeID) ?? ""
        automaticSyncEnabled = defaults.bool(forKey: DefaultsKey.automaticSyncEnabled)
        super.init()
    }

    private func roomSelectionDefaultsKey() -> String {
        let bridge = bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines)
        let homeID = selectedHomeID.trimmingCharacters(in: .whitespacesAndNewlines)
        return DefaultsKey.selectedHueRoomIDsPrefix + "." + bridge + "." + homeID
    }

    private func clearPlanForContextChange() {
        moves = []
        roomPlans = []
        selectedHueRoomIDs = []
        planSummary = nil
    }

    private func restoreRoomSelection(for rooms: [SyncRoomPlan]) {
        let available = Set(rooms.map(\.hueRoomID))
        let defaults = UserDefaults.standard
        let key = roomSelectionDefaultsKey()

        if defaults.object(forKey: key) != nil {
            let stored = Set(defaults.stringArray(forKey: key) ?? [])
            selectedHueRoomIDs = stored.intersection(available)
        } else {
            // Backward-compatible first use: keep the previous "all rooms" behavior,
            // while exposing an explicit selection before anything is applied.
            selectedHueRoomIDs = available
        }
    }

    private func persistRoomSelection() {
        UserDefaults.standard.set(
            selectedHueRoomIDs.sorted(),
            forKey: roomSelectionDefaultsKey()
        )
    }

    func isRoomSelected(_ roomID: String) -> Bool {
        selectedHueRoomIDs.contains(roomID)
    }

    func setRoomSelected(_ roomID: String, selected: Bool) {
        var updated = selectedHueRoomIDs
        if selected {
            updated.insert(roomID)
        } else {
            updated.remove(roomID)
        }
        selectedHueRoomIDs = updated
        persistRoomSelection()
        Task { await publishRoomSelection() }
    }

    func selectAllRooms() {
        selectedHueRoomIDs = Set(roomPlans.map(\.hueRoomID))
        persistRoomSelection()
        Task { await publishRoomSelection() }
    }

    func deselectAllRooms() {
        selectedHueRoomIDs = []
        persistRoomSelection()
        Task { await publishRoomSelection() }
    }

    private func publishRoomSelection() async {
        guard let home = selectedHome else { return }
        let bridge = bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !bridge.isEmpty else { return }

        let encodedBridge =
            bridge.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
            ?? bridge
        do {
            _ = try await send(
                path: "/api/bridges/\(encodedBridge)/apple-home/selection",
                method: "PUT",
                body: RoomSelectionRequest(
                    homeID: home.uniqueIdentifier.uuidString,
                    hueRoomIDs: selectedHueRoomIDs.sorted()
                )
            )
        } catch {
            status = "Sélection des pièces non enregistrée : \(error.localizedDescription)"
            hasError = true
        }
    }

    func start() {
        guard !started else {
            updateBackgroundRefreshStatus()
            if homeKitLoaded {
                refreshHomes()
            }
            return
        }
        started = true

        updateBackgroundRefreshStatus()
        startHomeKitIfNeeded()
        configureAutomaticSync()

        if !serverURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Task {
                await loadBridges()
            }
        }
    }

    private func startHomeKitIfNeeded() {
        guard homeManager == nil else { return }

        // Create HomeKit only after the SwiftUI scene is active. Initializing
        // HMHomeManager from singleton/bootstrap or background-launch paths can
        // race the homed XPC service.
        let manager = HMHomeManager()
        homeManager = manager
        manager.delegate = self
        updateAuthorizationStatus(manager.authorizationStatus)
        status = "Chargement de la base Apple Maison…"
        hasError = false
    }

    nonisolated func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        let managerID = ObjectIdentifier(manager)
        DispatchQueue.main.async { [weak self] in
            guard let self,
                  let current = self.homeManager,
                  ObjectIdentifier(current) == managerID
            else {
                return
            }

            self.homeKitLoaded = true
            self.updateAuthorizationStatus(current.authorizationStatus)
            self.refreshHomes()

            if self.automaticSyncEnabled {
                Task { @MainActor [weak self] in
                    await self?.automaticSyncCycle()
                }
            }
        }
    }

    nonisolated func homeManager(
        _ manager: HMHomeManager,
        didUpdate authorizationStatus: HMHomeManagerAuthorizationStatus
    ) {
        let managerID = ObjectIdentifier(manager)
        DispatchQueue.main.async { [weak self] in
            guard let self,
                  let current = self.homeManager,
                  ObjectIdentifier(current) == managerID
            else {
                return
            }

            // Read the manager again on the main actor instead of carrying a
            // HomeKit object across a Swift-concurrency boundary.
            self.updateAuthorizationStatus(current.authorizationStatus)

            if current.authorizationStatus.contains(.authorized) {
                if self.homeKitLoaded || !current.homes.isEmpty {
                    self.refreshHomes()
                } else {
                    self.status = "Autorisation accordée, chargement de la base Apple Maison…"
                    self.hasError = false
                }
            } else if current.authorizationStatus.contains(.restricted) {
                self.homes = []
                self.homeKitLoaded = false
                self.selectedHomeID = ""
                self.status =
                    "Accès Apple Maison refusé ou restreint. Autorise HueManager Home Sync " +
                    "dans Réglages."
                self.hasError = true
            }
        }
    }

    func reloadHomeKit() {
        guard let manager = homeManager else {
            startHomeKitIfNeeded()
            return
        }

        updateAuthorizationStatus(manager.authorizationStatus)

        // HMHomeManager is live-updated by homed. Never recreate it and never
        // poll homes repeatedly while its initial database sync is in progress.
        if homeKitLoaded {
            refreshHomes()
            if !homes.isEmpty {
                status = "\(homes.count) maison(s) Apple actualisée(s)."
                hasError = false
            }
        } else {
            status = "Chargement de la base Apple Maison en cours…"
            hasError = false
        }
    }

    func updateBackgroundRefreshStatus() {
        switch UIApplication.shared.backgroundRefreshStatus {
        case .available:
            backgroundRefreshStatus = "Disponible"
        case .denied:
            backgroundRefreshStatus = "Désactivée"
        case .restricted:
            backgroundRefreshStatus = "Restreinte"
        @unknown default:
            backgroundRefreshStatus = "Inconnue"
        }
    }

    private func updateAuthorizationStatus(_ authorizationStatus: HMHomeManagerAuthorizationStatus) {
        if authorizationStatus.contains(.authorized) {
            homeKitAuthorization = "Autorisée"
        } else if authorizationStatus.contains(.restricted) {
            homeKitAuthorization = "Refusée / restreinte"
        } else if authorizationStatus.contains(.determined) {
            homeKitAuthorization = "Déterminée, sans accès"
        } else {
            homeKitAuthorization = "En attente"
        }
    }

    private func configureAutomaticSync() {
        automaticTimer?.invalidate()
        automaticTimer = nil
        guard automaticSyncEnabled else { return }

        automaticTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) {
            [weak self] _ in
            Task { @MainActor in
                await self?.automaticSyncCycle()
            }
        }

        Task {
            await automaticSyncCycle()
        }
    }

    private func accessoryMatchIsSafe(_ move: SyncMove) -> Bool {
        if move.matchMethod == "serial" || move.matchMethod == "name" {
            return true
        }
        if move.matchMethod.hasPrefix("heuristic:"),
           let score = Double(move.matchMethod.split(separator: ":").last ?? "") {
            return score >= 0.90
        }
        return false
    }

    private func roomMatchIsSafe(_ move: SyncMove) -> Bool {
        switch move.roomMatchMethod {
        case "manual", "name":
            return true
        case "heuristic":
            return (move.roomMatchConfidence ?? 0) >= 0.85
        default:
            return false
        }
    }

    func runBackgroundSync() async -> Bool {
        guard automaticSyncEnabled else { return true }

        // A BGAppRefresh launch must not bootstrap/poll HomeKit. Only reuse an
        // already loaded manager from the foreground process.
        guard homeKitLoaded, homeManager != nil, !homes.isEmpty else {
            return false
        }

        await automaticSyncCycle()
        return !hasError
    }

    private func automaticSyncCycle() async {
        guard automaticSyncEnabled,
              !automaticSyncRunning,
              !homes.isEmpty,
              !serverURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            return
        }

        automaticSyncRunning = true
        defer { automaticSyncRunning = false }

        await loadPlan()
        guard !hasError else { return }

        let selectedPlans = roomPlans.filter {
            selectedHueRoomIDs.contains($0.hueRoomID)
        }
        let blockingStatuses: Set<String> = [
            "unmatched_accessory",
            "ambiguous_accessory",
            "missing_home_room",
        ]
        let selectedPlanHasBlockingIssue = selectedPlans.contains { room in
            room.status != "mapped" ||
                (room.hueDevices ?? []).contains { blockingStatuses.contains($0.status) }
        }
        let movesToApply = selectedMoves
        let safePlan =
            !selectedPlanHasBlockingIssue &&
            movesToApply.allSatisfy {
                accessoryMatchIsSafe($0) && roomMatchIsSafe($0)
            }

        guard safePlan else {
            if !movesToApply.isEmpty || selectedPlanHasBlockingIssue {
                status =
                    "Synchronisation automatique suspendue pour les pièces sélectionnées : " +
                    "correspondance ambiguë ou confiance insuffisante."
            }
            return
        }

        if !movesToApply.isEmpty {
            await applyPlan()
        }
    }

    private func refreshHomes() {
        guard let manager = homeManager else {
            homes = []
            selectedHomeID = ""
            homeKitLoaded = false
            return
        }

        updateAuthorizationStatus(manager.authorizationStatus)
        homes = manager.homes.sorted {
            $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }

        if selectedHomeID.isEmpty ||
            !homes.contains(where: { $0.uniqueIdentifier.uuidString == selectedHomeID }) {
            selectedHomeID = homes.first?.uniqueIdentifier.uuidString ?? ""
        }

        if homes.isEmpty {
            if manager.authorizationStatus.contains(.restricted) {
                status =
                    "Accès Apple Maison refusé ou restreint. Vérifie Réglages > " +
                    "Confidentialité et sécurité > HomeKit."
                hasError = true
            } else if !homeKitLoaded {
                status = "Chargement de la base Apple Maison…"
                hasError = false
            } else if manager.authorizationStatus.contains(.authorized) {
                status =
                    "HomeKit est autorisé mais n’a retourné aucune Maison après le chargement."
                hasError = true
            } else {
                status = "En attente de l’autorisation Apple Maison…"
                hasError = false
            }
        } else {
            status = "\(homes.count) maison(s) Apple disponible(s)."
            hasError = false
        }
    }

    private var selectedHome: HMHome? {
        homes.first { $0.uniqueIdentifier.uuidString == selectedHomeID }
    }

    private func serialString(from characteristic: HMCharacteristic) -> String? {
        guard let value = characteristic.value as? String else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let normalized = trimmed.lowercased()
        let unusable = ["unknown", "n/a", "na", "none", "null", "-"]
        return unusable.contains(normalized) ? nil : trimmed
    }

    private func homeKitSerialNumber(for accessory: HMAccessory) async -> String? {
        for service in accessory.services {
            for characteristic in service.characteristics
            where characteristic.characteristicType == HMCharacteristicTypeSerialNumber {
                let cachedValue = serialString(from: characteristic)
                return await withCheckedContinuation { continuation in
                    characteristic.readValue { [weak self] error in
                        guard let self else {
                            continuation.resume(returning: cachedValue)
                            return
                        }
                        if error == nil, let refreshed = self.serialString(from: characteristic) {
                            continuation.resume(returning: refreshed)
                        } else {
                            continuation.resume(returning: cachedValue)
                        }
                    }
                }
            }
        }
        return nil
    }

    private func vendorHAPIdentity(
        for accessory: HMAccessory
    ) -> (hapInstanceID: UInt64?, vendorAccess: Bool?) {
        if #available(iOS 26.1, *) {
            return (
                hapInstanceID: accessory.hapInstanceID,
                vendorAccess: accessory.isVendorAccessory
            )
        }
        return (hapInstanceID: nil, vendorAccess: nil)
    }

    private func inventory(for home: HMHome) async -> HomeInventory {
        var parentBridgeByAccessoryID: [String: HMAccessory] = [:]
        for possibleBridge in home.accessories {
            for bridgedAccessory in possibleBridge.bridgedAccessories {
                parentBridgeByAccessoryID[
                    bridgedAccessory.uniqueIdentifier.uuidString
                ] = possibleBridge
            }
        }

        let bridgeRows: [BridgeIdentityInfo] = home.accessories.compactMap { bridge in
            let bridged = bridge.bridgedAccessories
            let reported = bridge.uniqueIdentifiersForBridgedAccessories ?? []
            let legacyReported = bridge.identifiersForBridgedAccessories ?? []
            guard !bridged.isEmpty || !reported.isEmpty || !legacyReported.isEmpty
            else { return nil }
            let identity = vendorHAPIdentity(for: bridge)
            return BridgeIdentityInfo(
                id: bridge.uniqueIdentifier.uuidString,
                name: bridge.name,
                manufacturer: bridge.manufacturer,
                model: bridge.model,
                hapInstanceID: identity.hapInstanceID,
                vendorAccessory: identity.vendorAccess,
                bridgedAccessoryIDs: bridged.map {
                    $0.uniqueIdentifier.uuidString
                },
                bridgedAccessoryLegacyIDs: bridged.map {
                    $0.identifier.uuidString
                },
                uniqueIdentifiersForBridgedAccessories: reported.map {
                    $0.uuidString
                },
                identifiersForBridgedAccessories: legacyReported.map {
                    $0.uuidString
                }
            )
        }

        var accessoryRows: [AccessoryInfo] = []
        accessoryRows.reserveCapacity(home.accessories.count)
        for accessory in home.accessories {
            let accessoryID = accessory.uniqueIdentifier.uuidString
            let bridge = parentBridgeByAccessoryID[accessoryID]
            let serialNumber = await homeKitSerialNumber(for: accessory)
            let legacyIdentifier = accessory.identifier.uuidString
            let identity = vendorHAPIdentity(for: accessory)
            let bridgeChildIndex = bridge?.bridgedAccessories.firstIndex {
                $0.uniqueIdentifier == accessory.uniqueIdentifier
            }
            let bridgeReportedIdentifierIndex =
                bridge?.uniqueIdentifiersForBridgedAccessories?.firstIndex {
                    $0 == accessory.uniqueIdentifier
                }
            let bridgeLegacyIdentifierIndex =
                bridge?.identifiersForBridgedAccessories?.firstIndex {
                    $0 == accessory.identifier
                }

            accessoryRows.append(
                AccessoryInfo(
                    id: accessoryID,
                    name: accessory.name,
                    roomID: accessory.room?.uniqueIdentifier.uuidString,
                    roomName: accessory.room?.name,
                    manufacturer: accessory.manufacturer,
                    model: accessory.model,
                    serialNumber: serialNumber,
                    legacyIdentifier: legacyIdentifier,
                    isBridged: accessory.isBridged,
                    bridgeID: bridge?.uniqueIdentifier.uuidString,
                    bridgeName: bridge?.name,
                    bridgeManufacturer: bridge?.manufacturer,
                    bridgeModel: bridge?.model,
                    hapInstanceID: identity.hapInstanceID,
                    vendorAccessory: identity.vendorAccess,
                    bridgeChildIndex: bridgeChildIndex,
                    bridgeReportedIdentifierIndex: bridgeReportedIdentifierIndex,
                    bridgeLegacyIdentifierIndex: bridgeLegacyIdentifierIndex,
                    serviceTypes: accessory.services.map { $0.serviceType },
                    reachable: accessory.isReachable
                )
            )
        }

        return HomeInventory(
            home: HomeInfo(
                id: home.uniqueIdentifier.uuidString,
                name: home.name
            ),
            rooms: home.rooms.map {
                RoomInfo(id: $0.uniqueIdentifier.uuidString, name: $0.name)
            },
            accessories: accessoryRows,
            bridges: bridgeRows
        )
    }

    private func endpoint(_ path: String) throws -> URL {
        let base = serverURL.trimmingCharacters(
            in: CharacterSet(charactersIn: "/ \n\t")
        )
        guard !base.isEmpty, let url = URL(string: base + path) else {
            throw NSError(
                domain: "HueManagerHomeSync",
                code: 10,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "Renseigne l’URL de HueManager, par exemple http://192.168.1.10:8787."
                ]
            )
        }
        return url
    }

    private func serverActivityTimestamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: Date())
    }

    private func appendServerActivity(_ message: String) {
        serverActivityLog.append("[\(serverActivityTimestamp())] \(message)")
        if serverActivityLog.count > 80 {
            serverActivityLog.removeFirst(serverActivityLog.count - 80)
        }
    }

    private func beginServerActivity(_ request: URLRequest) {
        activeServerRequests += 1
        serverActivityInProgress = true
        serverActivityState = "En cours"
        let method = request.httpMethod ?? "GET"
        let path = request.url?.path ?? request.url?.absoluteString ?? "?"
        serverActivityDetail = "\(method) \(path)"
        appendServerActivity("→ \(method) \(path)")
    }

    private func finishServerActivity(
        _ request: URLRequest,
        success: Bool,
        detail: String
    ) {
        activeServerRequests = max(0, activeServerRequests - 1)
        let method = request.httpMethod ?? "GET"
        let path = request.url?.path ?? request.url?.absoluteString ?? "?"
        appendServerActivity(
            "\(success ? "✓" : "✕") \(method) \(path) · \(detail)"
        )
        if activeServerRequests > 0 {
            serverActivityInProgress = true
            serverActivityState = "En cours"
            serverActivityDetail = "\(activeServerRequests) échange(s) en cours"
        } else {
            serverActivityInProgress = false
            serverActivityState = success ? "Terminé" : "Erreur"
            serverActivityDetail = detail
        }
    }

    func clearServerActivityLog() {
        serverActivityLog.removeAll()
        if !serverActivityInProgress {
            serverActivityState = "Au repos"
            serverActivityDetail = "Aucun échange serveur."
        }
    }

    private func responseData(for request: URLRequest) async throws -> Data {
        beginServerActivity(request)
        var activityFinished = false
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse,
                  200..<300 ~= http.statusCode
            else {
                let detail = String(data: data, encoding: .utf8)
                    ?? "Erreur HueManager"
                let code = (response as? HTTPURLResponse)?.statusCode
                let activityDetail = code.map { "HTTP \($0) · \(detail)" }
                    ?? detail
                finishServerActivity(
                    request,
                    success: false,
                    detail: activityDetail
                )
                activityFinished = true
                throw NSError(
                    domain: "HueManagerHomeSync",
                    code: 11,
                    userInfo: [NSLocalizedDescriptionKey: detail]
                )
            }
            finishServerActivity(
                request,
                success: true,
                detail: "HTTP \(http.statusCode) · \(data.count) octets"
            )
            activityFinished = true
            return data
        } catch {
            if !activityFinished {
                finishServerActivity(
                    request,
                    success: false,
                    detail: error.localizedDescription
                )
            }
            throw error
        }
    }

    private func send<T: Encodable>(
        path: String,
        method: String,
        body: T
    ) async throws -> Data {
        var request = URLRequest(url: try endpoint(path))
        request.httpMethod = method
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await responseData(for: request)
    }

    private func get(path: String) async throws -> Data {
        var request = URLRequest(url: try endpoint(path))
        request.timeoutInterval = 20
        return try await responseData(for: request)
    }

    func loadBridges() async {
        do {
            let data = try await get(path: "/api/bridges")
            let response = try JSONDecoder().decode(BridgesResponse.self, from: data)
            bridges = response.bridges.sorted {
                $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
            }

            if bridgeProfile.isEmpty || !bridges.contains(where: { $0.name == bridgeProfile }) {
                bridgeProfile = bridges.first?.name ?? ""
            }
        } catch {
            bridges = []
        }
    }

    func testConnection() async {
        guard !connectionTesting else { return }

        connectionTesting = true
        connectionStatus = "Test en cours…"
        status = "Connexion à HueManager…"
        defer { connectionTesting = false }

        do {
            let data = try await get(path: "/api/health")
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            connectionStatus = "HueManager \(health.version) accessible"
            status = "HueManager \(health.version) accessible."
            hasError = false
            await loadBridges()
        } catch {
            connectionStatus = "Échec : \(error.localizedDescription)"
            status = error.localizedDescription
            hasError = true
        }
    }

    func refreshAndPublishInventory() async {
        reloadHomeKit()
        guard homeKitLoaded, !homes.isEmpty else {
            status = "Apple Maison n’est pas encore chargée : inventaire non publié."
            hasError = true
            return
        }
        await publishInventory()
    }

    func publishInventory() async {
        guard let home = selectedHome else {
            status = "Sélectionne une maison Apple."
            hasError = true
            return
        }
        guard !inventoryPublishing else { return }

        inventoryPublishing = true
        defer { inventoryPublishing = false }

        do {
            status = "Lecture des identifiants Apple Maison…"
            let snapshot = await inventory(for: home)
            let serialCount = snapshot.accessories.reduce(into: 0) { count, accessory in
                if accessory.serialNumber != nil {
                    count += 1
                }
            }

            status = "Publication de l’inventaire Apple Maison…"
            let data = try await send(
                path: "/api/apple-home/inventory",
                method: "POST",
                body: snapshot
            )
            let response = try JSONDecoder().decode(
                InventoryPublishResponse.self,
                from: data
            )
            lastPublishedInventoryAt = response.receivedAt
            let identifierInfo =
                "\(serialCount)/\(snapshot.accessories.count) numéro(s) de série HomeKit lu(s)"
            status = response.receivedAt == nil
                ? "Inventaire Apple Maison publié · \(identifierInfo)."
                : "Inventaire Apple Maison publié à \(lastPublishedInventoryDisplay) · " +
                    identifierInfo + "."
            hasError = false
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    private func enrichedRoomPlans(
        _ rooms: [SyncRoomPlan],
        devices: [SyncDeviceRow],
        moves: [SyncMove]
    ) -> [SyncRoomPlan] {
        guard let home = selectedHome else { return rooms }

        let homeAccessoriesByRoom = Dictionary(
            grouping: home.accessories,
            by: { $0.room?.uniqueIdentifier.uuidString ?? "" }
        )
        let devicesByRoom = Dictionary(grouping: devices, by: { $0.hueRoomID })
        let movesByRoom = Dictionary(grouping: moves, by: { $0.hueRoomID ?? "" })

        return rooms.map { room in
            let deviceRows = devicesByRoom[room.hueRoomID] ?? []
            let hueDevices = room.hueDevices ?? deviceRows.map { row in
                SyncRoomHueDevice(
                    id: row.hueDeviceID,
                    name: row.hueDeviceName,
                    status: row.status,
                    matchMethod: row.matchMethod,
                    appleAccessoryID: row.appleAccessoryID,
                    appleAccessoryName: row.appleAccessoryName,
                    appleCurrentRoomID: row.appleRoomID,
                    appleCurrentRoomName: row.appleRoomName
                )
            }

            let appleAccessories: [SyncRoomAppleAccessory]
            if let serverAccessories = room.appleAccessories {
                appleAccessories = serverAccessories
            } else if let appleRoomID = room.appleRoomID {
                var matchedByAccessoryID: [String: SyncDeviceRow] = [:]
                for row in deviceRows {
                    if let id = row.appleAccessoryID {
                        matchedByAccessoryID[id] = row
                    }
                }
                appleAccessories = (homeAccessoriesByRoom[appleRoomID] ?? []).map { accessory in
                    let id = accessory.uniqueIdentifier.uuidString
                    let match = matchedByAccessoryID[id]
                    return SyncRoomAppleAccessory(
                        id: id,
                        name: accessory.name,
                        manufacturer: accessory.manufacturer,
                        model: accessory.model,
                        origin: match == nil ? nil : "hue",
                        bridgeName: nil,
                        bridgeManufacturer: nil,
                        matchedHueDeviceID: match?.hueDeviceID,
                        matchedHueDeviceName: match?.hueDeviceName
                    )
                }
            } else {
                appleAccessories = []
            }

            let plannedMoves = room.plannedMoves ?? movesByRoom[room.hueRoomID] ?? []
            let impact = room.impact ?? SyncRoomImpact(
                hueDeviceCount: hueDevices.count,
                appleAccessoryCount: appleAccessories.count,
                moveCount: plannedMoves.count,
                alreadyCorrectCount: deviceRows.filter { $0.status == "already_correct" }.count
            )

            return SyncRoomPlan(
                hueRoomID: room.hueRoomID,
                hueRoomName: room.hueRoomName,
                appleRoomID: room.appleRoomID,
                appleRoomName: room.appleRoomName,
                method: room.method,
                confidence: room.confidence,
                status: room.status,
                hueDevices: hueDevices,
                appleAccessories: appleAccessories,
                plannedMoves: plannedMoves,
                impact: impact
            )
        }
    }

    func createReassociationBackup() async {
        guard !bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            status = "Indique le nom du profil Bridge HueManager."
            hasError = true
            return
        }

        await publishInventory()
        guard !hasError else { return }

        do {
            status = "Sauvegarde des associations appareil/pièce Apple Maison…"
            let encodedBridge =
                bridgeProfile.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
                ?? bridgeProfile
            let data = try await send(
                path: "/api/bridges/\(encodedBridge)/apple-home/reassociation-backup",
                method: "POST",
                body: EmptyRequest()
            )
            let response = try JSONDecoder().decode(
                ReassociationBackupResponse.self,
                from: data
            )
            reassociationBackupCount = response.accessories
            reassociationBackupAt = response.createdAt
            reassociationMoves = []
            reassociationSummary = nil
            status =
                "Sauvegarde de réassociation créée : " +
                "\(response.accessories) accessoire(s). Tu peux maintenant supprimer puis recréer le lien Apple Home."
            hasError = false
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    func loadReassociationPlan() async {
        guard !bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            status = "Indique le nom du profil Bridge HueManager."
            hasError = true
            return
        }

        await publishInventory()
        guard !hasError else { return }

        do {
            status = "Comparaison de la nouvelle association Apple avec la sauvegarde…"
            let encodedBridge =
                bridgeProfile.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
                ?? bridgeProfile
            let data = try await get(
                path: "/api/bridges/\(encodedBridge)/apple-home/reassociation-plan"
            )
            let plan = try JSONDecoder().decode(ReassociationPlan.self, from: data)
            reassociationMoves = plan.actions
            reassociationSummary = plan.summary
            reassociationBackupAt = plan.backupCreatedAt
            reassociationBackupCount = plan.summary.savedAccessories

            if plan.summary.unmatchedAccessories > 0 || plan.summary.missingRooms > 0 {
                status =
                    "Réassociation analysée : \(plan.summary.matchedAccessories)/" +
                    "\(plan.summary.savedAccessories) reconnu(s), " +
                    "\(plan.actions.count) déplacement(s), " +
                    "\(plan.summary.unmatchedAccessories) non reconnu(s)."
                hasError = false
            } else if plan.actions.isEmpty {
                status =
                    "Réassociation analysée : tous les accessoires reconnus et déjà dans leurs pièces."
                hasError = false
            } else {
                status =
                    "Réassociation analysée : \(plan.actions.count) déplacement(s) prêts à être restaurés."
                hasError = false
            }
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    func applyReassociationPlan() async {
        guard let home = selectedHome else {
            status = "Sélectionne une maison Apple."
            hasError = true
            return
        }
        guard !reassociationMoves.isEmpty else {
            status = "Aucun déplacement de réassociation à appliquer."
            return
        }

        let accessories = Dictionary(
            uniqueKeysWithValues: home.accessories.map {
                ($0.uniqueIdentifier.uuidString, $0)
            }
        )
        let rooms = Dictionary(
            uniqueKeysWithValues: home.rooms.map {
                ($0.uniqueIdentifier.uuidString, $0)
            }
        )

        var moved = 0
        var failures: [[String: String]] = []
        status = "Restauration des pièces Apple Maison après réassociation…"

        for move in reassociationMoves {
            guard let accessory = accessories[move.accessoryID],
                  let room = rooms[move.toRoomID] else {
                failures.append([
                    "accessory_id": move.accessoryID,
                    "name": move.accessoryName,
                    "error": "Accessoire ou pièce introuvable dans HomeKit",
                ])
                continue
            }

            if let error = await assign(accessory, to: room, in: home) {
                failures.append([
                    "accessory_id": move.accessoryID,
                    "name": move.accessoryName,
                    "error": error.localizedDescription,
                ])
            } else {
                moved += 1
            }
        }

        do {
            _ = try await send(
                path: "/api/apple-home/sync-result",
                method: "POST",
                body: SyncResult(
                    homeID: home.uniqueIdentifier.uuidString,
                    bridgeProfile: bridgeProfile,
                    moved: moved,
                    failed: failures
                )
            )
            await loadReassociationPlan()
            if failures.isEmpty {
                status =
                    "\(moved) accessoire(s) remis dans leur pièce Apple Maison sauvegardée."
                hasError = false
            } else {
                status =
                    "\(moved) restauré(s), \(failures.count) échec(s)."
                hasError = true
            }
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    func loadPlan() async {
        guard !bridgeProfile.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            status = "Indique le nom du profil Bridge HueManager."
            hasError = true
            return
        }

        await publishInventory()
        guard !hasError else { return }

        do {
            status = "Analyse des correspondances Hue ↔ Maison…"
            let encodedBridge =
                bridgeProfile.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
                ?? bridgeProfile
            let data = try await get(
                path: "/api/bridges/\(encodedBridge)/apple-home/plan"
            )
            let plan = try JSONDecoder().decode(SyncPlan.self, from: data)
            moves = plan.actions
            roomPlans = enrichedRoomPlans(
                plan.rooms ?? [],
                devices: plan.devices ?? [],
                moves: plan.actions
            )
            if let selected = plan.selectedHueRoomIDs {
                let available = Set(roomPlans.map(\.hueRoomID))
                selectedHueRoomIDs = Set(selected).intersection(available)
                persistRoomSelection()
            } else {
                restoreRoomSelection(for: roomPlans)
            }
            planSummary = plan.summary
            if plan.actions.isEmpty {
                status = "Aucun déplacement nécessaire."
            } else {
                status =
                    "\(plan.actions.count) déplacement(s) proposé(s), " +
                    "\(pendingMoves) dans les pièces sélectionnées."
            }
            hasError = false
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    private func assign(
        _ accessory: HMAccessory,
        to room: HMRoom,
        in home: HMHome
    ) async -> Error? {
        await withCheckedContinuation { continuation in
            home.assignAccessory(accessory, to: room) { error in
                continuation.resume(returning: error)
            }
        }
    }

    func applyPlan() async {
        guard let home = selectedHome else {
            status = "Sélectionne une maison Apple."
            hasError = true
            return
        }
        let movesToApply = selectedMoves
        guard !movesToApply.isEmpty else {
            status = selectedHueRoomIDs.isEmpty
                ? "Aucune pièce sélectionnée."
                : "Aucun déplacement à appliquer dans les pièces sélectionnées."
            return
        }

        let accessories = Dictionary(
            uniqueKeysWithValues: home.accessories.map {
                ($0.uniqueIdentifier.uuidString, $0)
            }
        )
        let rooms = Dictionary(
            uniqueKeysWithValues: home.rooms.map {
                ($0.uniqueIdentifier.uuidString, $0)
            }
        )

        var moved = 0
        var failures: [[String: String]] = []
        status = "Application des affectations dans Apple Maison…"

        for move in movesToApply {
            guard let accessory = accessories[move.accessoryID],
                  let room = rooms[move.toRoomID] else {
                failures.append([
                    "accessory_id": move.accessoryID,
                    "name": move.accessoryName,
                    "error": "Accessoire ou pièce introuvable dans HomeKit",
                ])
                continue
            }

            if let error = await assign(accessory, to: room, in: home) {
                failures.append([
                    "accessory_id": move.accessoryID,
                    "name": move.accessoryName,
                    "error": error.localizedDescription,
                ])
            } else {
                moved += 1
            }
        }

        do {
            _ = try await send(
                path: "/api/apple-home/sync-result",
                method: "POST",
                body: SyncResult(
                    homeID: home.uniqueIdentifier.uuidString,
                    bridgeProfile: bridgeProfile,
                    moved: moved,
                    failed: failures
                )
            )

            await loadPlan()
            if failures.isEmpty {
                status = "\(moved) accessoire(s) déplacé(s) dans Apple Maison."
                hasError = false
            } else {
                status = "\(moved) déplacé(s), \(failures.count) échec(s)."
                hasError = true
            }
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }
}
