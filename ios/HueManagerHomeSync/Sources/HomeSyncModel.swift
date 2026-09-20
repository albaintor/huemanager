import Combine
import Foundation
import HomeKit

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
    let matchedHueDeviceID: String?
    let matchedHueDeviceName: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case manufacturer
        case model
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
    let actions: [SyncMove]
    let summary: SyncSummary
}

private struct HealthResponse: Codable {
    let status: String
    let version: String
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

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case roomID = "room_id"
        case roomName = "room_name"
        case manufacturer
        case model
        case serialNumber = "serial_number"
    }
}

private struct HomeInventory: Codable {
    let home: HomeInfo
    let rooms: [RoomInfo]
    let accessories: [AccessoryInfo]
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

@MainActor
final class HomeSyncModel: NSObject, ObservableObject, HMHomeManagerDelegate {
    static let shared = HomeSyncModel()

    private enum DefaultsKey {
        static let serverURL = "serverURL"
        static let bridgeProfile = "bridgeProfile"
        static let selectedHomeID = "selectedHomeID"
        static let automaticSyncEnabled = "automaticSyncEnabled"
    }

    @Published var serverURL: String {
        didSet {
            UserDefaults.standard.set(serverURL, forKey: DefaultsKey.serverURL)
        }
    }

    @Published var bridgeProfile: String {
        didSet {
            UserDefaults.standard.set(bridgeProfile, forKey: DefaultsKey.bridgeProfile)
        }
    }

    @Published var selectedHomeID: String {
        didSet {
            UserDefaults.standard.set(selectedHomeID, forKey: DefaultsKey.selectedHomeID)
        }
    }

    @Published private(set) var homes: [HMHome] = []
    @Published private(set) var moves: [SyncMove] = []
    @Published private(set) var roomPlans: [SyncRoomPlan] = []
    @Published private(set) var planSummary: SyncSummary?
    @Published private(set) var status = "En attente de l’autorisation Apple Maison…"
    @Published private(set) var hasError = false
    @Published private(set) var homeKitAuthorization = "Indéterminée"
    @Published private(set) var homeKitLoaded = false

    @Published var automaticSyncEnabled: Bool {
        didSet {
            UserDefaults.standard.set(
                automaticSyncEnabled,
                forKey: DefaultsKey.automaticSyncEnabled
            )
            configureAutomaticSync()
        }
    }

    private let homeManager = HMHomeManager()
    private var automaticTimer: Timer?
    private var automaticSyncRunning = false

    var pendingMoves: Int { moves.count }

    var homeKitDiagnostic: String {
        return "auth=\(homeKitAuthorization) raw=\(homeManager.authorizationStatus.rawValue) " +
            "loaded=\(homeKitLoaded) homes=\(homes.count)"
    }

    private override init() {
        let defaults = UserDefaults.standard
        serverURL = defaults.string(forKey: DefaultsKey.serverURL) ?? ""
        bridgeProfile = defaults.string(forKey: DefaultsKey.bridgeProfile) ?? ""
        selectedHomeID = defaults.string(forKey: DefaultsKey.selectedHomeID) ?? ""
        automaticSyncEnabled = defaults.bool(forKey: DefaultsKey.automaticSyncEnabled)
        super.init()
        homeManager.delegate = self
        updateAuthorizationStatus(homeManager.authorizationStatus)
    }

    func start() {
        updateAuthorizationStatus(homeManager.authorizationStatus)
        if homeKitLoaded {
            refreshHomes()
        } else {
            status = "Chargement de la base Apple Maison…"
            hasError = false
        }
        configureAutomaticSync()
    }

    nonisolated func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        Task { @MainActor [weak self] in
            guard let self, manager === self.homeManager else { return }
            self.homeKitLoaded = true
            self.updateAuthorizationStatus(manager.authorizationStatus)
            self.refreshHomes()

            if self.automaticSyncEnabled {
                await self.automaticSyncCycle()
            }
        }
    }

    nonisolated func homeManager(
        _ manager: HMHomeManager,
        didUpdate authorizationStatus: HMHomeManagerAuthorizationStatus
    ) {
        Task { @MainActor [weak self] in
            guard let self, manager === self.homeManager else { return }

            self.updateAuthorizationStatus(authorizationStatus)

            if authorizationStatus.contains(.authorized) {
                if self.homeKitLoaded || !manager.homes.isEmpty {
                    self.refreshHomes()
                } else {
                    self.status = "Autorisation accordée, chargement de la base Apple Maison…"
                    self.hasError = false
                }
            } else if authorizationStatus.contains(.restricted) {
                self.homes = []
                self.homeKitLoaded = false
                self.status =
                    "Accès Apple Maison refusé ou restreint. Autorise HueManager Home Sync " +
                    "dans Réglages, puis recharge les données Maison."
                self.hasError = true
            }
        }
    }

    func reloadHomeKit() {
        // HMHomeManager maintains a live connection to the shared HomeKit database.
        // Do not replace it: Apple documents one manager instance per app, and
        // recreating it while homed is synchronizing can invalidate the XPC session.
        updateAuthorizationStatus(homeManager.authorizationStatus)
        refreshHomes()

        if !homes.isEmpty {
            status = "\(homes.count) maison(s) Apple actualisée(s)."
            hasError = false
        } else if !homeKitLoaded {
            status = "Chargement de la base Apple Maison en cours…"
            hasError = false
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

        for _ in 0..<10 where homes.isEmpty {
            refreshHomes()
            if !homes.isEmpty { break }
            try? await Task.sleep(for: .milliseconds(500))
        }
        guard !homes.isEmpty else { return false }

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
        guard !hasError, let summary = planSummary else { return }

        let safePlan =
            summary.unmatchedAccessories == 0 &&
            summary.ambiguousAccessories == 0 &&
            summary.missingHomeRooms == 0 &&
            moves.allSatisfy { accessoryMatchIsSafe($0) && roomMatchIsSafe($0) }

        guard safePlan else {
            if !moves.isEmpty {
                status =
                    "Synchronisation automatique suspendue : correspondance ambiguë " +
                    "ou confiance insuffisante."
            }
            return
        }

        if !moves.isEmpty {
            await applyPlan()
        }
    }

    private func refreshHomes() {
        updateAuthorizationStatus(homeManager.authorizationStatus)
        homes = homeManager.homes.sorted {
            $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }

        if selectedHomeID.isEmpty ||
            !homes.contains(where: { $0.uniqueIdentifier.uuidString == selectedHomeID }) {
            selectedHomeID = homes.first?.uniqueIdentifier.uuidString ?? ""
        }

        if homes.isEmpty {
            if homeManager.authorizationStatus.contains(.restricted) {
                status =
                    "Accès Apple Maison refusé ou restreint. Vérifie Réglages > " +
                    "Confidentialité et sécurité > HomeKit."
                hasError = true
            } else if !homeKitLoaded {
                status = "Chargement de la base Apple Maison…"
                hasError = false
            } else if homeManager.authorizationStatus.contains(.authorized) {
                status =
                    "HomeKit est autorisé mais n’a retourné aucune Maison après le chargement. " +
                    "Relève le diagnostic affiché."
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

    private func inventory(for home: HMHome) -> HomeInventory {
        HomeInventory(
            home: HomeInfo(
                id: home.uniqueIdentifier.uuidString,
                name: home.name
            ),
            rooms: home.rooms.map {
                RoomInfo(id: $0.uniqueIdentifier.uuidString, name: $0.name)
            },
            accessories: home.accessories.map { accessory in
                AccessoryInfo(
                    id: accessory.uniqueIdentifier.uuidString,
                    name: accessory.name,
                    roomID: accessory.room?.uniqueIdentifier.uuidString,
                    roomName: accessory.room?.name,
                    manufacturer: accessory.manufacturer,
                    model: accessory.model,
                    serialNumber: nil
                )
            }
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

    private func responseData(for request: URLRequest) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            let detail = String(data: data, encoding: .utf8) ?? "Erreur HueManager"
            throw NSError(
                domain: "HueManagerHomeSync",
                code: 11,
                userInfo: [NSLocalizedDescriptionKey: detail]
            )
        }
        return data
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

    func testConnection() async {
        do {
            status = "Connexion à HueManager…"
            let data = try await get(path: "/api/health")
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            status = "HueManager \(health.version) accessible."
            hasError = false
        } catch {
            status = error.localizedDescription
            hasError = true
        }
    }

    func publishInventory() async {
        guard let home = selectedHome else {
            status = "Sélectionne une maison Apple."
            hasError = true
            return
        }

        do {
            status = "Publication de l’inventaire Apple Maison…"
            _ = try await send(
                path: "/api/apple-home/inventory",
                method: "POST",
                body: inventory(for: home)
            )
            status = "Inventaire Apple Maison publié dans HueManager."
            hasError = false
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
            roomPlans = plan.rooms ?? []
            moves = plan.actions
            planSummary = plan.summary
            status = plan.actions.isEmpty
                ? "Aucun déplacement nécessaire."
                : "\(plan.actions.count) déplacement(s) proposé(s)."
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
        guard !moves.isEmpty else {
            status = "Aucun déplacement à appliquer."
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

        for move in moves {
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
