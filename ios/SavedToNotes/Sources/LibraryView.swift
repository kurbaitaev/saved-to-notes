import SwiftUI

struct LibraryView: View {
    @EnvironmentObject var store: Store

    @State private var path: [Note] = []

    var body: some View {
        NavigationStack(path: $path) {
            ZStack {
                Theme.ground.ignoresSafeArea()
                content
            }
            .navigationTitle("Library")
            .toolbarBackground(Theme.ground, for: .navigationBar)
            .navigationDestination(for: Note.self) { NoteView(note: $0) }
        }
        .onChange(of: store.notes) { _, notes in
            guard path.isEmpty, let flag = LaunchFlag.value, flag.hasPrefix("note:") else { return }
            let needle = String(flag.dropFirst(5)).lowercased()
            if let match = notes.first(where: { $0.title.lowercased().contains(needle) }) {
                path = [match]
            }
        }
    }

    @ViewBuilder private var content: some View {
        if store.loading && store.notes.isEmpty {
            ProgressView().tint(Theme.signal)
        } else if let err = store.error, store.notes.isEmpty {
            FailureView(message: err) { Task { await store.load() } }
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    filters
                    ForEach(store.visible) { note in
                        NavigationLink(value: note) { Row(note: note) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 20)
            }
            .refreshable { await store.load() }
        }
    }

    private var filters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                Chip(label: "All \(store.notes.count)", on: store.folder == nil) { store.folder = nil }
                ForEach(store.folders, id: \.name) { f in
                    Chip(label: "\(f.name) \(f.count)", on: store.folder == f.name) {
                        store.folder = (store.folder == f.name) ? nil : f.name
                    }
                }
            }
            .padding(.vertical, 10)
        }
    }
}

private struct Row: View {
    let note: Note
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(note.title)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Eyebrow(text: note.folder.isEmpty ? "Unfiled" : note.folder)
                if note.worthRemaking {
                    Eyebrow(text: "· worth remaking", color: Theme.signal)
                }
                if note.canReview {
                    Eyebrow(text: "· ?", color: Theme.ok)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 13)
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
    }
}

struct Chip: View {
    let label: String
    let on: Bool
    let tap: () -> Void
    var body: some View {
        Button(action: tap) {
            Text(label)
                .font(Theme.mono(10))
                .tracking(0.8)
                .foregroundStyle(on ? Theme.ground : Theme.mute)
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Capsule().fill(on ? Theme.signal : .clear))
                .overlay(Capsule().stroke(on ? .clear : Theme.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct FailureView: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Text("Couldn't load your notes")
                .font(.system(size: 18, weight: .semibold)).foregroundStyle(Theme.ink)
            Text(message)
                .font(.system(size: 14)).foregroundStyle(Theme.mute)
                .multilineTextAlignment(.center)
            Button("Try again", action: retry)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Theme.ground)
                .padding(.horizontal, 18).padding(.vertical, 10)
                .background(RoundedRectangle(cornerRadius: 9).fill(Theme.signal))
        }
        .padding(32)
    }
}
