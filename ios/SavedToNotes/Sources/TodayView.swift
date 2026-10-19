import SwiftUI

/// What each save is for, right now: the morning routine, what's on this week,
/// and the newest places and things to get. Opened instead of Instagram.
struct TodayView: View {
    @EnvironmentObject var store: Store
    @State private var playing = false

    var body: some View {
        Screen(title: "Today") {
            Eyebrow(text: Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))

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
