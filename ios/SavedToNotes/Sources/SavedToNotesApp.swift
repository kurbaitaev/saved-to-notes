import SwiftUI

@main
struct AfterscrollApp: App {
    @StateObject private var store = Store()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store).preferredColorScheme(.dark)
        }
    }
}

/// `--open today|move|map|lists` jumps straight to a tab on launch, so a single
/// screen can be screenshotted without tapping through the app.
enum LaunchFlag {
    static var value: String? {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "--open"), i + 1 < args.count else { return nil }
        return args[i + 1]
    }
}

struct RootView: View {
    @EnvironmentObject var store: Store
    @State private var tab = 0

    var body: some View {
        TabView(selection: $tab) {
            TodayView().tabItem { Label("Today", systemImage: "sun.max") }.tag(0)
            MoveView().tabItem { Label("Move", systemImage: "figure.flexibility") }.tag(1)
            MapScreen().tabItem { Label("Map", systemImage: "map") }.tag(2)
            ListsView().tabItem { Label("Lists", systemImage: "checklist") }.tag(3)
        }
        .tint(Theme.signal)
        .task {
            tab = ["today", "move", "map", "lists"].firstIndex(of: LaunchFlag.value ?? "") ?? 0
            if store.saves.isEmpty { await store.load() }
        }
    }
}
