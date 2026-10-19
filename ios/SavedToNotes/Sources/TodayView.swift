import SwiftUI

/// What each save is for, right now: the morning routine, what's on this week,
/// and the newest places and things to get. Opened instead of Instagram.
struct TodayView: View {
    @EnvironmentObject var store: Store
    @State private var playing = false
    @State private var pasteResult: String?

    var body: some View {
        Screen(title: "Today") {
            Eyebrow(text: Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))

            if store.pending > 0 {
                HStack(spacing: 12) {
                    ProgressView().tint(Theme.signal)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(store.pending == 1 ? "Sorting 1 save…" : "Sorting \(store.pending) saves…")
                            .font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ink)
                        Text("Usually under a minute. It appears here on its own.")
                            .font(.system(size: 13)).foregroundStyle(Theme.mute)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 16).fill(Theme.raise))
            }

            if !store.recent.filter({ $0.status != "sorting" }).isEmpty { recentShares }

            routineCard

            if !upcoming.isEmpty {
                section("This week")
                ForEach(upcoming) { s in
                    NavigationLink(value: s) { EventRow(save: s) }.buttonStyle(.plain)
                }
            }

            if let place = store.of(.visit).first {
                section("A place you saved")
                NavigationLink(value: place) { PlaceRow(save: place) }.buttonStyle(.plain)
            }

            let toGet = store.of(.buy).filter { !store.isDone($0) }
            if !toGet.isEmpty {
                section("To get · \(toGet.count)")
                ForEach(toGet.prefix(3)) { s in
                    NavigationLink(value: s) { BuyRow(save: s) }.buttonStyle(.plain)
                }
            }

            if store.of(.visit).isEmpty && store.of(.attend).isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Places and events show up here").font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ink)
                    Text("In Instagram, tap Share, then Afterscroll on a café, trip or event reel.")
                        .font(.system(size: 14)).foregroundStyle(Theme.mute)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Theme.line, style: StrokeStyle(lineWidth: 1, dash: [4, 4])))
            }
        }
        .fullScreenCover(isPresented: $playing) { RoutinePlayer(saves: store.routine) }
        .overlay(alignment: .topTrailing) {
            // Fallback for apps whose share sheet doesn't pass a link: copy
            // the link there, tap this here.
            Button { Task { await pasteLink() } } label: {
                Label("Paste link", systemImage: "doc.on.clipboard")
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.signal)
                    .padding(.horizontal, 14).frame(minHeight: 44)
                    .background(Capsule().fill(Theme.raise))
            }
            .padding(.trailing, 16).padding(.top, 4)
        }
        .alert(pasteResult ?? "", isPresented: Binding(get: { pasteResult != nil }, set: { if !$0 { pasteResult = nil } })) {
            Button("OK", role: .cancel) {}
        }
    }

    private func pasteLink() async {
        guard let text = UIPasteboard.general.string,
              let r = text.range(of: #"https?://\S+"#, options: .regularExpression) else {
            pasteResult = "No link on the clipboard. In Instagram tap Share, then Copy link, and try again."
            return
        }
        do {
            try await APIClient.shared.share(String(text[r]))
            pasteResult = "Saved. It'll show up here in about a minute."
            store.pending += 1
            store.watch()
        } catch {
            pasteResult = "Couldn't save: \(error.localizedDescription)"
        }
    }

    private var upcoming: [Save] {
        let soon = Date().addingTimeInterval(8 * 86_400)
        let start = Calendar.current.startOfDay(for: Date())
        return store.of(.attend)
            .filter { ($0.details.eventDate ?? .distantPast) >= start && ($0.details.eventDate ?? .distantFuture) <= soon }
            .sorted { ($0.details.eventDate ?? .distantFuture) < ($1.details.eventDate ?? .distantFuture) }
    }

    @ViewBuilder private var routineCard: some View {
        let r = store.routine
        Card {
            Eyebrow(text: "Morning routine", color: Theme.signal)
            if r.isEmpty {
                Text("No workouts saved yet").font(.system(size: 18, weight: .bold)).foregroundStyle(Theme.ink)
                Text("Share a mobility or workout reel to Afterscroll and it becomes a looping clip here.")
                    .font(.system(size: 14)).foregroundStyle(Theme.mute)
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                    ForEach(r.prefix(3)) { s in ClipTile(save: s, radius: 12) }
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(title(r)).font(.system(size: 19, weight: .bold)).foregroundStyle(Theme.ink)
                    Text("\(r.count == 1 ? "1 workout" : "\(r.count) workouts") · about \(store.routineMinutes) min")
                        .font(.system(size: 14)).foregroundStyle(Theme.mute)
                }
                WideButton(label: "Start routine") { playing = true }
            }
        }
    }

    /// Where the last shares went. A tip or idea shared here is filed in Notion,
    /// not the app — without this line it just seemed to disappear.
    @ViewBuilder private var recentShares: some View {
        let done = store.recent.filter { $0.status != "sorting" }.prefix(3)
        VStack(alignment: .leading, spacing: 0) {
            Eyebrow(text: "Just saved").padding(.bottom, 6)
            ForEach(Array(done), id: \.self) { r in
                let save = store.saves.first { $0.sourceURL.hasPrefix(r.url) || r.url.hasPrefix($0.sourceURL) }
                let row = HStack(spacing: 10) {
                    Image(systemName: icon(r)).font(.system(size: 15)).foregroundStyle(r.status == "failed" ? .red : Theme.signal)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.title?.nilIfEmpty ?? r.url).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ink).lineLimit(1)
                        Text(where_(r)).font(.system(size: 13)).foregroundStyle(Theme.mute)
                    }
                    Spacer(minLength: 0)
                }
                .frame(minHeight: 52)
                .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
                if let save { NavigationLink(value: save) { row }.buttonStyle(.plain) } else { row }
            }
        }
    }

    private func icon(_ r: Share) -> String {
        switch r.status {
        case "app": "checkmark.circle.fill"
        case "notion": "doc.text"
        case "duplicate": "arrow.uturn.backward.circle"
        default: "exclamationmark.triangle.fill"
        }
    }

    private func where_(_ r: Share) -> String {
        switch r.status {
        case "app": "In the app · \(r.category ?? "")"
        case "notion": "Filed in Notion as \(r.category ?? "a note") — not a real-life thing"
        case "duplicate": "Already saved before"
        default: "Couldn't save — try sharing it again"
        }
    }

    private func title(_ r: [Save]) -> String {
        let areas = r.compactMap { $0.details.bodyArea?.capitalized }.uniqued()
        return areas.isEmpty ? (r.count == 1 ? r[0].name : "Your routine") : areas.prefix(2).joined(separator: " + ")
    }

    private func section(_ t: String) -> some View {
        Eyebrow(text: t).padding(.top, 10)
    }
}

extension Array where Element: Hashable {
    func uniqued() -> [Element] { var seen = Set<Element>(); return filter { seen.insert($0).inserted } }
}

extension String {
    func ifEmpty(_ fallback: String) -> String { isEmpty ? fallback : self }
}
