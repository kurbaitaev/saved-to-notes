import SwiftUI

/// Every saved workout as a looping clip. Tap a clip for its moves; Play runs
/// the routine full-screen.
struct MoveView: View {
    @EnvironmentObject var store: Store
    @State private var area: String?
    @State private var playing = false

    private let cols = [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8),
                        GridItem(.flexible(), spacing: 8)]

    var body: some View {
        Screen(title: "Move") {
            let all = store.of(.move)
            if all.isEmpty {
                EmptyState(symbol: "figure.flexibility", title: "No workouts yet",
                           hint: "Save a mobility, stretching or workout reel. It turns into a silent looping clip you can follow in the morning.")
            } else {
                filters(all)
                LazyVGrid(columns: cols, spacing: 8) {
                    ForEach(visible(all)) { s in
                        NavigationLink(value: s) { Tile(save: s, inRoutine: store.inRoutine(s)) }
                            .buttonStyle(.plain)
                            .contextMenu {
                                Button(store.inRoutine(s) ? "Remove from routine" : "Add to routine") {
                                    store.toggleRoutine(s)
                                }
                            }
                    }
                }
                Card {
                    Eyebrow(text: "Routine", color: Theme.signal)
                    Text("\(store.routine.count) workouts · about \(store.routineMinutes) min")
                        .font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                    Text("Long-press a clip to add or remove it.")
                        .font(.system(size: 13)).foregroundStyle(Theme.mute)
                    if !store.routine.isEmpty { PrimaryButton(label: "Play routine") { playing = true } }
                }
                .padding(.top, 6)
            }
        }
        .fullScreenCover(isPresented: $playing) { RoutinePlayer(saves: store.routine) }
    }

    private func filters(_ all: [Save]) -> some View {
        let areas = all.compactMap { $0.details.bodyArea }.uniqued().sorted()
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                Chip(label: "All \(all.count)", on: area == nil) { area = nil }
                ForEach(areas, id: \.self) { a in
                    Chip(label: a.capitalized, on: area == a) { area = (area == a) ? nil : a }
                }
            }
        }
    }

    private func visible(_ all: [Save]) -> [Save] {
        guard let area else { return all }
        return all.filter { $0.details.bodyArea == area }
    }
}

private struct Tile: View {
    let save: Save
    let inRoutine: Bool
    var body: some View {
        LoopView(save: save)
            .aspectRatio(3 / 4, contentMode: .fit)
            .overlay(alignment: .bottomLeading) {
                Text(save.name)
                    .font(Theme.mono(9, .medium)).foregroundStyle(.white)
                    .lineLimit(2).padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(LinearGradient(colors: [.clear, .black.opacity(0.7)], startPoint: .top, endPoint: .bottom))
            }
            .overlay(alignment: .topTrailing) {
                if let m = save.details.minutes {
                    Text("\(m) min").font(Theme.mono(8.5, .medium)).foregroundStyle(Theme.signal)
                        .padding(5)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(inRoutine ? Theme.signal.opacity(0.7) : Theme.line, lineWidth: 1))
    }
}

/// Full-screen follow-along: one workout at a time, its loop large, its moves
/// underneath, a running clock, and a big Next.
struct RoutinePlayer: View {
    let saves: [Save]
    @Environment(\.dismiss) private var dismiss
    @State private var index = 0
    @State private var started = Date()

    var body: some View {
        ZStack {
            Theme.ground.ignoresSafeArea()
            if saves.isEmpty {
                EmptyState(symbol: "figure.flexibility", title: "Routine is empty", hint: "Add workouts from the Move tab.")
            } else {
                let s = saves[index]
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Eyebrow(text: "\(index + 1) of \(saves.count)", color: Theme.signal)
                        Spacer()
                        TimelineView(.periodic(from: started, by: 1)) { ctx in
                            Text(Duration.seconds(ctx.date.timeIntervalSince(started)).formatted(.time(pattern: .minuteSecond)))
                                .font(Theme.mono(13, .medium)).foregroundStyle(Theme.ink)
                        }
                        Button { dismiss() } label: {
                            Image(systemName: "xmark").font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.mute)
                                .padding(8)
                        }
                        .accessibilityLabel("Close")
                    }
                    LoopView(save: s, gravity: .resizeAspect)
                        .frame(maxWidth: .infinity).frame(height: 380)
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                    Text(s.name).font(.system(size: 22, weight: .bold)).foregroundStyle(Theme.ink)
                    ScrollView { MovesList(moves: s.details.moves ?? []) }
                    HStack(spacing: 10) {
                        if index > 0 {
                            Button("Back") { index -= 1 }
                                .font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.mute)
                                .padding(.horizontal, 18).padding(.vertical, 12)
                                .overlay(Capsule().stroke(Theme.line))
                        }
                        Spacer()
                        PrimaryButton(label: index + 1 < saves.count ? "Next" : "Done",
                                      symbol: index + 1 < saves.count ? "forward.fill" : "checkmark") {
                            if index + 1 < saves.count { index += 1 } else { dismiss() }
                        }
                    }
                }
                .padding(20)
            }
        }
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }
}

struct MovesList: View {
    let moves: [Exercise]
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(moves.enumerated()), id: \.offset) { i, m in
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("\(i + 1)").font(Theme.mono(12, .medium)).foregroundStyle(Theme.signal).frame(width: 18)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(m.name).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ink)
                        if let c = m.cues { Text(c).font(.system(size: 13)).foregroundStyle(Theme.mute) }
                    }
                    Spacer()
                    if let d = m.dose { Text(d).font(Theme.mono(11, .medium)).foregroundStyle(Theme.ink) }
                }
                .padding(.vertical, 10)
                .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
            }
        }
    }
}
