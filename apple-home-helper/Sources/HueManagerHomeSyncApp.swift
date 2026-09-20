import SwiftUI

@main
struct HueManagerHomeSyncApp: App {
    @StateObject private var model = HomeSyncModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}
