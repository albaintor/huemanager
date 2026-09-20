import BackgroundTasks
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    static let refreshIdentifier = "com.albaintor.HueManagerHomeSync.refresh"

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: Self.refreshIdentifier,
            using: nil
        ) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            Self.scheduleRefresh()
            let operation = Task { @MainActor in
                let success = await HomeSyncModel.shared.runBackgroundSync()
                refreshTask.setTaskCompleted(success: success)
            }
            refreshTask.expirationHandler = {
                operation.cancel()
            }
        }
        Self.scheduleRefresh()
        return true
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        Self.scheduleRefresh()
    }

    static func scheduleRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: refreshIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // The system can reject scheduling temporarily; the next foreground/background
            // transition will try again.
        }
    }
}
