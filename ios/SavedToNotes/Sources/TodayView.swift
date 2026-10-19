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

            if store.saves.isEmpty {
                EmptyState(symbol: "sparkles", title: "Nothing to do yet",
                           hint: "Send a reel about a place, an event, a recipe, a workout or something to buy to your bot. It lands here, sorted.")
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
                Text("No workouts saved yet").font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
                Text("Save a mobility or workout reel and it becomes a looping clip here.")
                    .font(.system(size: 13)).foregroundStyle(Theme.mute)
            } else {
                HStack(spacing: 6) {
                    ForEach(r.prefix(4)) { s in
                        LoopView(save: s).frame(height: 92).clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
                Text(r.count == 1 ? r[0].name : "\(r.count) workouts")
                    .font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
                Text("about \(store.routineMinutes) min · \(r.compactMap { $0.details.bodyArea }.uniqued().joined(separator: ", ").ifEmpty("from your saves"))")
                    .font(.system(size: 13)).foregroundStyle(Theme.mute)
                PrimaryButton(label: "Start") { playing = true }
            }
        }
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
