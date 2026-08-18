import SwiftUI

struct NoteView: View {
    let note: Note
    @EnvironmentObject var store: Store
    @State private var script = Script()
    @State private var loading = true
    @State private var failure: String?
    @State private var copied = false

    var body: some View {
        ZStack {
            Theme.ground.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(note.title)
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)

                    HStack(spacing: 6) {
                        Eyebrow(text: [note.platform, note.folder].filter { !$0.isEmpty }.joined(separator: " · "))
                        if !script.isEmpty { Eyebrow(text: "· verbatim kept", color: Theme.ok) }
                    }

                    if !note.hook.isEmpty {
                        Text(note.hook)
                            .font(.system(size: 16))
                            .foregroundStyle(Theme.ink.opacity(0.9))
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if !note.topics.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                ForEach(note.topics, id: \.self) { Chip(label: $0, on: false) {} }
                            }
                        }
                    }

                    scriptBlock
                    actions
                }
                .padding(20)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await fetch() }
    }

    @ViewBuilder private var scriptBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Exact wording")
            if loading {
                ProgressView().tint(Theme.signal).frame(maxWidth: .infinity).padding(.vertical, 24)
            } else if let failure {
                Text(failure).font(.system(size: 13)).foregroundStyle(Theme.mute)
            } else if script.isEmpty {
                Text("No verbatim text was captured for this one.")
                    .font(.system(size: 13)).foregroundStyle(Theme.mute)
            } else {
                // Monospaced on purpose: this is the text you'd lift for a remake,
                // so it should read as a transcript rather than as prose.
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(Array(script.paragraphs.enumerated()), id: \.offset) { _, p in
                        Text(p)
                            .font(Theme.mono(12.5))
                            .foregroundStyle(Theme.ink.opacity(0.86))
                            .lineSpacing(4)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 4).fill(Theme.sunk))
                .overlay(alignment: .leading) { Rectangle().fill(Theme.signal).frame(width: 2) }
                .clipShape(RoundedRectangle(cornerRadius: 4))
            }
        }
    }

    @ViewBuilder private var actions: some View {
        VStack(spacing: 10) {
            if !script.isEmpty {
                Button {
                    UIPasteboard.general.string = script.joined
                    copied = true
                    Task { try? await Task.sleep(nanoseconds: 1_600_000_000); copied = false }
                } label: {
                    Label(copied ? "Copied" : "Copy full script", systemImage: copied ? "checkmark" : "doc.on.doc")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Theme.ground)
                        .frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.signal))
                }
                .buttonStyle(.plain)
            }
            if let url = URL(string: note.sourceURL), !note.sourceURL.isEmpty {
                Link(destination: url) {
                    Text("Open original")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Theme.signal)
                        .frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(RoundedRectangle(cornerRadius: 9).stroke(Theme.line, lineWidth: 1))
                }
            }
        }
    }

    private func fetch() async {
        loading = true
        switch await store.script(for: note) {
        case .success(let s): script = s
        case .failure(let e): failure = e.message
        }
        loading = false
    }
}
