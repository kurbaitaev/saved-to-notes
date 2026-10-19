import SwiftUI

/// Every saved workout as an uncropped looping clip, or grouped by the creator
/// who made it so one creator's moves play together as a follow-along set.
struct MoveView: View {
    @EnvironmentObject var store: Store
    @State private var byCreator = false
    @State private var area: String?
    @State private var playing: [Save]?

    private let cols = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        Screen(title: "Move") {
            let all = store.of(.move)
            if all.isEmpty {
                EmptyState(symbol: "figure.flexibility", title: "No workouts yet",
                           hint: "In Instagram, tap Share, then Afterscroll on a mobility or workout reel. It becomes a looping clip you can follow.")
            } else {
                Picker("View", selection: $byCreator) {
                    Text("Workouts").tag(false)
                    Text("By creator").tag(true)
                }
                .pickerStyle(.segmented)

                if byCreator { creators(all) } else { workouts(all) }
            }
        }
        .fullScreenCover(item: Binding(get: { playing.map(PlayList.init) }, set: { playing = $0?.saves })) {
            RoutinePlayer(saves: $0.saves)
        }
    }

    @ViewBuilder private func workouts(_ all: [Save]) -> some View {
        let areas = all.compactMap { $0.details.bodyArea }.uniqued().sorted()
        if areas.count > 1 {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    Chip(label: "All \(all.count)", on: area == nil) { area = nil }
                    ForEach(areas, id: \.self) { a in
                        Chip(label: a.capitalized, on: area == a) { area = (area == a) ? nil : a }
                    }
                }
            }
        }
        LazyVGrid(columns: cols, alignment: .leading, spacing: 18) {
            ForEach(all.filter { area == nil || $0.details.bodyArea == area }) { s in
                NavigationLink(value: s) { Tile(save: s, inRoutine: store.inRoutine(s)) }
                    .buttonStyle(.plain)
                    .contextMenu {
                        Button(store.inRoutine(s) ? "Remove from routine" : "Add to routine") { store.toggleRoutine(s) }
                    }
            }
        }
    }

    @ViewBuilder private func creators(_ all: [Save]) -> some View {
        let groups = Dictionary(grouping: all) { $0.author.isEmpty ? "Unknown creator" : $0.author }
            .sorted { $0.value.count == $1.value.count ? $0.key < $1.key : $0.value.count > $1.value.count }
        ForEach(groups.filter { isSet($0.value) }, id: \.key) { creator, saves in
            Card {
                HStack(spacing: 10) {
                    Text(initials(creator))
                        .font(.system(size: 14, weight: .bold)).foregroundStyle(Theme.signal)
                        .frame(width: 36, height: 36).background(Circle().fill(Theme.line))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(creator).font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.ink)
                        Text(summary(saves)).font(.system(size: 13)).foregroundStyle(Theme.mute)
                    }
                }
                // A collage per workout: its moves, each looping on its own, under
                // the workout's name — one wall of 17 mixed tiles was unreadable.
                ForEach(saves) { s in
                    let steps = s.steps
                    VStack(alignment: .leading, spacing: 8) {
                        if saves.count > 1 {
                            NavigationLink(value: s) {
                                HStack {
                                    Text(s.name).font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.ink)
                                    Text("· \(steps.count) moves").font(.system(size: 13)).foregroundStyle(Theme.mute)
                                    Spacer()
                                    Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.line)
                                }
                                .frame(minHeight: 32)
                            }
                            .buttonStyle(.plain)
                        }
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 8) {
                            ForEach(Array(steps.enumerated()), id: \.offset) { i, st in
                                NavigationLink(value: s) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        ClipTile(clip: st.clip ?? s.cover, radius: 10)
                                            .overlay(alignment: .topLeading) {
                                                Text("\(i + 1)").font(.system(size: 11, weight: .bold))
                                                    .foregroundStyle(i == 0 ? Theme.ground : Theme.ink)
                                                    .frame(width: 18, height: 18)
                                                    .background(Circle().fill(i == 0 ? Theme.signal : Theme.line))
                                                    .padding(5)
                                            }
                                        Text(st.name).font(.system(size: 11)).foregroundStyle(Theme.soft).lineLimit(2)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
                WideButton(label: "Follow along") { playing = saves }
            }
        }
        // One workout from a creator: a compact row, not a mostly-empty collage.
        let singles = groups.filter { !isSet($0.value) }
        if !singles.isEmpty {
            VStack(spacing: 0) {
                ForEach(singles, id: \.key) { creator, saves in
                    HStack(spacing: 12) {
                        NavigationLink(value: saves[0]) {
                            HStack(spacing: 12) {
                                ClipTile(save: saves[0], radius: 9).frame(width: 54)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(creator).font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.ink)
                                    Text(saves[0].name).font(.system(size: 14)).foregroundStyle(Theme.mute).lineLimit(2)
                                }
                                Spacer(minLength: 0)
                            }
                        }
                        .buttonStyle(.plain)
                        Button { playing = saves } label: {
                            Image(systemName: "play.fill").font(.system(size: 15)).foregroundStyle(Theme.ink)
                                .frame(width: 44, height: 44).overlay(Circle().stroke(Theme.line))
                        }
                        .accessibilityLabel("Follow along with \(creator)")
                    }
                    .padding(.vertical, 10)
                    .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
                }
            }
            Text("Save more reels from the same creator and they group into one follow-along set.")
                .font(.system(size: 13)).foregroundStyle(Theme.mute)
        }
    }

    /// Worth a collage: several workouts, or one reel split into several moves.
    private func isSet(_ saves: [Save]) -> Bool {
        saves.count > 1 || saves.reduce(0) { $0 + $1.steps.count } > 1
    }

    private func initials(_ name: String) -> String {
        String(name.split(separator: " ").prefix(2).compactMap(\.first)).uppercased().ifEmpty("?")
    }

    private func summary(_ saves: [Save]) -> String {
        let minutes = saves.compactMap(\.details.minutes).reduce(0, +)
        let moves = saves.reduce(0) { $0 + $1.steps.count }
        return [saves.count == 1 ? "1 workout" : "\(saves.count) workouts",
                moves > 0 ? "\(moves) moves" : nil,
                minutes > 0 ? "\(minutes) min" : nil].compactMap { $0 }.joined(separator: " · ")
    }
}

private struct PlayList: Identifiable {
    let saves: [Save]
    var id: String { saves.map(\.id).joined() }
}

private struct Tile: View {
    let save: Save
    let inRoutine: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ClipTile(save: save)
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(inRoutine ? Theme.signal : Theme.line, lineWidth: inRoutine ? 1.5 : 1))
                .overlay(alignment: .bottomLeading) {
                    if inRoutine {
                        Label("In routine", systemImage: "repeat")
                            .font(Theme.mono(10, .medium)).foregroundStyle(Theme.ink)
                            .padding(.horizontal, 6).padding(.vertical, 3)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Theme.ground.opacity(0.75)))
                            .padding(8)
                    }
                }
            VStack(alignment: .leading, spacing: 2) {
                Text(save.name).font(.system(size: 15, weight: .bold)).foregroundStyle(Theme.ink)
                    .lineLimit(2).multilineTextAlignment(.leading)
                Text(meta).font(.system(size: 13)).foregroundStyle(Theme.mute).lineLimit(1)
            }
        }
    }

    private var meta: String {
        let d = save.details
        return [d.bodyArea?.capitalized, save.steps.isEmpty ? nil : "\(save.steps.count) moves", d.minutes.map { "\($0) min" }]
            .compactMap { $0 }.joined(separator: " · ")
    }
}

/// Full-screen follow-along, one MOVE at a time: the clip it comes from fills
/// the frame uncropped, the move and its dose are readable from the floor, and
/// Next is a thumb-sized target. The screen stays awake throughout.
struct RoutinePlayer: View {
    let saves: [Save]
    @Environment(\.dismiss) private var dismiss
    @State private var step = 0
    @State private var started = Date()

    private struct Item { let save: Save; let step: Step?; let index: Int; let total: Int; let workout: Int }

    private var steps: [Item] {
        saves.enumerated().flatMap { w, s -> [Item] in
            let st = s.steps
            if st.isEmpty { return [Item(save: s, step: nil, index: 0, total: 1, workout: w)] }
            return st.enumerated().map { Item(save: s, step: $1, index: $0, total: st.count, workout: w) }
        }
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if steps.isEmpty {
                EmptyState(symbol: "figure.flexibility", title: "Routine is empty", hint: "Add workouts from the Move tab.")
            } else {
                let s = steps[min(step, steps.count - 1)]
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 10) {
                        HStack(spacing: 4) {
                            ForEach(0..<steps.count, id: \.self) { i in
                                Capsule().fill(i <= step ? Theme.signal : Theme.line).frame(height: 4)
                            }
                        }
                        TimelineView(.periodic(from: started, by: 1)) { ctx in
                            Text(Duration.seconds(ctx.date.timeIntervalSince(started)).formatted(.time(pattern: .minuteSecond)))
                                .font(Theme.mono(15, .medium)).foregroundStyle(Theme.ink).monospacedDigit()
                        }
                        Button { dismiss() } label: {
                            Image(systemName: "xmark").font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.soft)
                                .frame(width: 44, height: 44)
                        }
                        .accessibilityLabel("Close routine")
                    }
                    // The move's own clip when the reel was split, else the whole reel.
                    LoopView(clip: s.step?.clip ?? s.save.cover)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: 22))
                        .id(s.step?.clip?.key ?? s.save.id)
                    VStack(alignment: .leading, spacing: 4) {
                        Eyebrow(text: "Workout \(s.workout + 1) of \(saves.count)" + (s.step == nil ? "" : " · move \(s.index + 1) of \(s.total)"),
                                color: Theme.signal)
                        HStack(alignment: .firstTextBaseline) {
                            Text(s.step?.name ?? s.save.name).font(.system(size: 26, weight: .heavy)).foregroundStyle(Theme.ink)
                            Spacer(minLength: 8)
                            if let dose = s.step?.dose {
                                Text(dose).font(Theme.mono(15, .medium)).foregroundStyle(Theme.ink).multilineTextAlignment(.trailing)
                            }
                        }
                        if let cue = s.step?.cues ?? (s.step == nil ? s.save.details.why : nil) {
                            Text(cue).font(.system(size: 15)).foregroundStyle(Theme.soft).lineLimit(3)
                        }
                    }
                    HStack(spacing: 10) {
                        if step > 0 {
                            Button("Back") { step -= 1 }
                                .font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                                .frame(width: 112, height: 56).overlay(Capsule().stroke(Theme.line))
                        }
                        Button { if step + 1 < steps.count { step += 1 } else { dismiss() } } label: {
                            Text(step + 1 < steps.count ? (steps[step + 1].workout == s.workout ? "Next move" : "Next workout") : "Done")
                                .font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.ground)
                                .frame(maxWidth: .infinity, minHeight: 56).background(Capsule().fill(Theme.signal))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 20).padding(.vertical, 8)
            }
        }
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }
}

struct MovesList: View {
    let steps: [Step]
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { i, m in
                HStack(alignment: .top, spacing: 12) {
                    if let clip = m.clip {
                        // Each exercise loops on its own — the "gif per move".
                        ClipTile(clip: clip, radius: 8).frame(width: 54)
                    } else {
                        Text("\(i + 1)").font(Theme.mono(13, .medium)).foregroundStyle(Theme.signal).frame(width: 16)
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(m.name).font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.ink)
                        if let c = m.cues { Text(c).font(.system(size: 14)).foregroundStyle(Theme.mute) }
                        if let d = m.dose { Text(d).font(Theme.mono(12, .medium)).foregroundStyle(Theme.signal) }
                    }
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 10)
                .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
            }
        }
    }
}
