import SwiftUI

@main
struct HueManagerHomeSyncApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = HomeSyncModel.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                model.start()
            }
        }
    }
}
