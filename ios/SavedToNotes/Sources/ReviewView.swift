import SwiftUI

struct ReviewView: View {
    @EnvironmentObject var store: Store
    @State private var answer = ""
    @State private var revealed = false
    @State private var script = Script()
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.ground.ignoresSafeArea()
                if let note = store.dueToday { card(note) } else { empty }
            }
            .navigationTitle("Review")
            .toolbarBackground(Theme.ground, for: .navigationBar)
            .task(id: store.dueToday?.id) {
                // --open review-revealed jumps past the answer step, so the
                // revealed state can be checked without tapping through.
                guard LaunchFlag.value == "review-revealed",
                      let note = store.dueToday, !revealed else { return }
                revealed = true
                if case .success(let s) = await store.script(for: note) { script = s }
            }
        }
    }

    private var empty: some View {
        VStack(spacing: 12) {
            Text("Nothing due").font(.system(size: 20, weight: .semibold)).foregroundStyle(Theme.ink)
            Text(store.reviewableCount == 0
                 ? "None of your notes carry a review question yet. The pipeline writes one at save time."
                 : "You're done for today. One card a day, and it never piles up.")
                .font(.system(size: 14)).foregroundStyle(Theme.mute)
                .multilineTextAlignment(.center)
        }
        .padding(36)
    }

    private func card(_ note: Note) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Eyebrow(text: savedAgo(note))

                Text(note.reviewQuestion)
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                if !revealed {
                    TextEditor(text: $answer)
                        .focused($typing)
                        .font(.system(size: 15))
                        .foregroundStyle(Theme.ink)
                        .scrollContentBackground(.hidden)
                        .frame(height: 120)
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.sunk))
                        .overlay(RoundedRectangle(cornerRadius: 9).stroke(Theme.line, lineWidth: 1))
                        .overlay(alignment: .topLeading) {
                            if answer.isEmpty {
                                Text("Type what you remember")
                                    .font(.system(size: 15)).foregroundStyle(Theme.mute)
                                    .padding(.horizontal, 15).padding(.vertical, 18)
                                    .allowsHitTesting(false)
                            }
                        }

                    Button {
                        typing = false
                        revealed = true
                        Task { if case .success(let s) = await store.script(for: note) { script = s } }
                    } label: {
                        Text("Show me the note")
                            .font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ground)
                            .frame(maxWidth: .infinity).padding(.vertical, 13)
                            .background(RoundedRectangle(cornerRadius: 9).fill(Theme.signal))
                    }
                    .buttonStyle(.plain)

                    Text("Answering first is the part that works. Reading it again isn't.")
                        .font(.system(size: 12)).foregroundStyle(Theme.mute)
                } else {
                    reveal(note)
                }
            }
            .padding(20)
        }
    }

    @ViewBuilder private func reveal(_ note: Note) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Divider().overlay(Theme.line)
            Text(note.title)
                .font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if !note.hook.isEmpty {
                Text(note.hook).font(.system(size: 15)).foregroundStyle(Theme.ink.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !script.isEmpty {
                Text(script.paragraphs.prefix(2).joined(separator: "\n\n"))
                    .font(Theme.mono(12))
                    .foregroundStyle(Theme.ink.opacity(0.8))
                    .lineSpacing(4)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 4).fill(Theme.sunk))
                    .overlay(alignment: .leading) { Rectangle().fill(Theme.ok).frame(width: 2) }
                    .clipShape(RoundedRectangle(cornerRadius: 4))
            }
            HStack(spacing: 10) {
                gradeButton("Missed it", filled: false) { finish(note, false) }
                gradeButton("Got it", filled: true) { finish(note, true) }
            }
        }
    }

    private func gradeButton(_ label: String, filled: Bool, tap: @escaping () -> Void) -> some View {
        Button(action: tap) {
            Text(label)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(filled ? Theme.ground : Theme.signal)
                .frame(maxWidth: .infinity).padding(.vertical, 13)
                .background(RoundedRectangle(cornerRadius: 9).fill(filled ? Theme.signal : .clear))
                .overlay(RoundedRectangle(cornerRadius: 9).stroke(filled ? .clear : Theme.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private func finish(_ note: Note, _ recalled: Bool) {
        store.grade(note, recalled: recalled)
        answer = ""; revealed = false; script = Script()
    }

    private func savedAgo(_ note: Note) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: String(note.date.prefix(10))) else { return "Saved earlier" }
        let days = Calendar.current.dateComponents([.day], from: d, to: Date()).day ?? 0
        return days <= 0 ? "Saved today" : "You saved this \(days) day\(days == 1 ? "" : "s") ago"
    }
}
