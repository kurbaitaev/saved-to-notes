import SwiftUI

@main
struct SavedToNotesApp: App {
    @StateObject private var store = Store()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store).preferredColorScheme(.dark)
        }
    }
}

/// `--open review` or `--open note:<text>` jumps straight to a screen on launch.
/// Screenshotting and checking a single view shouldn't require tapping through
/// the whole app.
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
            LibraryView().tabItem { Label("Library", systemImage: "square.stack") }.tag(0)
            ReviewView().tabItem { Label("Review", systemImage: "questionmark.bubble") }.tag(1)
        }
        .tint(Theme.signal)
        .task {
            if store.notes.isEmpty { await store.load() }
            if LaunchFlag.value?.hasPrefix("review") == true { tab = 1 }
        }
    }
}
