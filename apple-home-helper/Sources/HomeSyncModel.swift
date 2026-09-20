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

private struct SyncPlan: Codable {
    let actions: [SyncMove]
    let summary: SyncSummary
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

final class HomeSyncModel: NSObject, ObservableObject, HMHomeManagerDelegate {
    static let shared = HomeSyncModel()

    @Published var serverURL = "http://127.0.0.1:8787"
    @Published var bridgeProfile = "pro"
    @Published var selectedHomeID = ""
    @Published private(set) var homes: [HMHome] = []
    @Published private(set) var moves: [SyncMove] = []
    @Published private(set) var planSummary: SyncSummary?
    @Published private(set) var status = "En attente de l’autorisation Apple Maison…"
    @Published private(set) var hasError = false
    @Published var automaticSyncEnabled: Bool {
        didSet {
            UserDefaults.standard.set(automaticSyncEnabled, forKey: "automaticSyncEnabled")
            configureAutomaticSync()
        }
    }

    private let homeManager = HMHomeManager()
    private var automaticTimer: Timer?
    private var automaticSyncRunning = false

    var pendingMoves: Int { moves.count }

    private override init() {
        automaticSyncEnabled = UserDefaults.standard.bool(forKey: "automaticSyncEnabled")
        super.init()
        homeManager.delegate = self
    }

    func start() {
        refreshHomes()
        configureAutomaticSync()
    }

    func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        refreshHomes()
        if automaticSyncEnabled {
            Task { @MainActor in
                await automaticSyncCycle()
            }
        }
    }

    private func configureAutomaticSync() {
        automaticTimer?.invalidate()
        automaticTimer = nil
        guard automaticSyncEnabled else { return }

        automaticTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.automaticSyncCycle()
            }
        }
        Task { @MainActor in
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

    @MainActor
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

    @MainActor
    private func automaticSyncCycle() async {
        guard automaticSyncEnabled, !automaticSyncRunning, !homes.isEmpty else { return }
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
                status = "Synchronisation automatique suspendue : correspondance ambiguë ou confiance insuffisante."
            }
            return
        }
        if !moves.isEmpty {
            await applyPlan()
        }
    }

    private func refreshHomes() {
        homes = homeManager.homes.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        if selectedHomeID.isEmpty || !homes.contains(where: { $0.uniqueIdentifier.uuidString == selectedHomeID }) {
            selectedHomeID = homes.first?.uniqueIdentifier.uuidString ?? ""
        }
        if homes.isEmpty {
            status = "Aucune maison HomeKit accessible. Vérifie l’autorisation Maison de l’application."
        } else {
            status = "\(homes.count) maison(s) Apple disponible(s)."
            hasError = false
        }
    }

    private var selectedHome: HMHome? {
        homes.first { $0.uniqueIdentifier.uuidString == selectedHomeID }
    }

    private func characteristicValue(_ accessory: HMAccessory, type: String) -> String? {
        for service in accessory.services {
            for characteristic in service.characteristics where characteristic.characteristicType == type {
                if let value = characteristic.value as? String, !value.isEmpty {
                    return value
                }
            }
        }
        return nil
    }

    private func inventory(for home: HMHome) -> HomeInventory {
        HomeInventory(
            home: HomeInfo(id: home.uniqueIdentifier.uuidString, name: home.name),
            rooms: home.rooms.map {
                RoomInfo(id: $0.uniqueIdentifier.uuidString, name: $0.name)
            },
            accessories: home.accessories.map { accessory in
                AccessoryInfo(
                    id: accessory.uniqueIdentifier.uuidString,
                    name: accessory.name,
                    roomID: accessory.room?.uniqueIdentifier.uuidString,
                    roomName: accessory.room?.name,
                    manufacturer: characteristicValue(accessory, type: HMCharacteristicTypeManufacturer),
                    model: characteristicValue(accessory, type: HMCharacteristicTypeModel),
                    serialNumber: characteristicValue(accessory, type: HMCharacteristicTypeSerialNumber)
                )
            }
        )
    }

    private func endpoint(_ path: String) throws -> URL {
        let base = serverURL.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        guard let url = URL(string: base + path) else {
            throw URLError(.badURL)
        }
        return url
    }

    private func send<T: Encodable>(
        path: String,
        method: String,
        body: T
    ) async throws -> Data {
        var request = URLRequest(url: try endpoint(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            let detail = String(data: data, encoding: .utf8) ?? "Erreur HueManager"
            throw NSError(domain: "HueManagerHomeSync", code: 1, userInfo: [NSLocalizedDescriptionKey: detail])
        }
        return data
    }

    private func get(path: String) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(from: endpoint(path))
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            let detail = String(data: data, encoding: .utf8) ?? "Erreur HueManager"
            throw NSError(domain: "HueManagerHomeSync", code: 2, userInfo: [NSLocalizedDescriptionKey: detail])
        }
        return data
    }

    @MainActor
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

    @MainActor
    func loadPlan() async {
        guard !bridgeProfile.isEmpty else {
            status = "Indique le nom du profil Bridge HueManager."
            hasError = true
            return
        }
        await publishInventory()
        guard !hasError else { return }
        do {
            status = "Analyse des correspondances Hue ↔ Maison…"
            let encodedBridge = bridgeProfile.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? bridgeProfile
            let data = try await get(path: "/api/bridges/\(encodedBridge)/apple-home/plan")
            let plan = try JSONDecoder().decode(SyncPlan.self, from: data)
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

    private func assign(_ accessory: HMAccessory, to room: HMRoom, in home: HMHome) async -> Error? {
        await withCheckedContinuation { continuation in
            home.assignAccessory(accessory, to: room) { error in
                continuation.resume(returning: error)
            }
        }
    }

    @MainActor
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
            uniqueKeysWithValues: home.accessories.map { ($0.uniqueIdentifier.uuidString, $0) }
        )
        let rooms = Dictionary(
            uniqueKeysWithValues: home.rooms.map { ($0.uniqueIdentifier.uuidString, $0) }
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
                    "error": "Accessoire ou pièce introuvable dans HomeKit"
                ])
                continue
            }
            if let error = await assign(accessory, to: room, in: home) {
                failures.append([
                    "accessory_id": move.accessoryID,
                    "name": move.accessoryName,
                    "error": error.localizedDescription
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
