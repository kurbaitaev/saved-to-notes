import AVFoundation
import SwiftUI
import UIKit

// MARK: - Looping clip

/// A silent clip that plays on repeat — the whole point of the Move screen is
/// following along without touching anything. Muted so a grid of them, or a
/// routine at 7am, never makes a sound.
struct LoopView: View {
    let clip: Clip?
    var symbol: String = Kind.move.symbol
    /// Aspect-fit by default: a preview must show the whole frame, never a crop.
    var gravity: AVLayerVideoGravity = .resizeAspect
    @State private var file: URL?
    @State private var still: UIImage?

    init(clip: Clip?, symbol: String = Kind.move.symbol, gravity: AVLayerVideoGravity = .resizeAspect) {
        self.clip = clip; self.symbol = symbol; self.gravity = gravity
    }

    /// A save's tile: its whole loop, else its first move.
    init(save: Save, gravity: AVLayerVideoGravity = .resizeAspect) {
        self.init(clip: save.cover, symbol: save.kind.symbol, gravity: gravity)
    }

    var body: some View {
        ZStack {
            Theme.raise
            if let file {
                LoopLayer(url: file, gravity: gravity)
            } else if let still {
                Image(uiImage: still).resizable().aspectRatio(contentMode: .fit)
            } else {
                Image(systemName: symbol)
                    .font(.system(size: 22, weight: .light))
                    .foregroundStyle(Theme.mute)
            }
        }
        .task(id: clip?.key) {
            file = nil
            guard let clip else { return }
            if let f = await ClipCache.shared.cached(clip.key) { file = f; return }
            // The still first (a few KB), so the tile is a picture at once.
            if let p = try? await ClipCache.shared.poster(for: clip),
               let img = UIImage(contentsOfFile: p.path) { still = img }
            file = try? await ClipCache.shared.file(for: clip)
        }
    }
}

private struct LoopLayer: UIViewRepresentable {
    let url: URL
    let gravity: AVLayerVideoGravity

    final class PlayerView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
        var looper: AVPlayerLooper?
    }

    func makeUIView(context: Context) -> PlayerView {
        let v = PlayerView()
        let player = AVQueuePlayer()
        player.isMuted = true
        // Don't stop someone's music or podcast to show a silent loop.
        try? AVAudioSession.sharedInstance().setCategory(.ambient, options: .mixWithOthers)
        v.looper = AVPlayerLooper(player: player, templateItem: AVPlayerItem(url: url))
        v.playerLayer.player = player
        v.playerLayer.videoGravity = gravity
        player.play()
        return v
    }

    func updateUIView(_ v: PlayerView, context: Context) {
        v.playerLayer.videoGravity = gravity
    }

    static func dismantleUIView(_ v: PlayerView, coordinator: ()) {
        v.playerLayer.player?.pause()
        v.looper = nil
    }
}

// MARK: - Small pieces

struct Chip: View {
    let label: String
    let on: Bool
    let tap: () -> Void
    var body: some View {
        Button(action: tap) {
            Text(label)
                .font(.system(size: 13, weight: on ? .semibold : .medium))
                .foregroundStyle(on ? Theme.ground : Theme.soft)
                .padding(.horizontal, 14).frame(minHeight: 32)
                .background(Capsule().fill(on ? Theme.signal : .clear))
                .overlay(Capsule().stroke(on ? .clear : Theme.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct Card<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.raise))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.line, lineWidth: 1))
    }
}

struct PrimaryButton: View {
    let label: String
    var symbol: String = "play.fill"
    let tap: () -> Void
    var body: some View {
        Button(action: tap) {
            Label(label, systemImage: symbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.ground)
                .padding(.horizontal, 18).frame(minHeight: 44)
                .background(Capsule().fill(Theme.signal))
        }
        .buttonStyle(.plain)
    }
}

/// A clip at its true 9:16 shape, so nothing is cropped at any size.
struct ClipTile: View {
    let clip: Clip?
    var radius: CGFloat = 16
    init(save: Save, radius: CGFloat = 16) { clip = save.cover; self.radius = radius }
    init(clip: Clip?, radius: CGFloat = 16) { self.clip = clip; self.radius = radius }
    var body: some View {
        LoopView(clip: clip)
            .aspectRatio(9 / 16, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: radius))
    }
}

/// Wide primary action: full-width, 48 pt tall.
struct WideButton: View {
    let label: String
    var symbol: String = "play.fill"
    let tap: () -> Void
    var body: some View {
        Button(action: tap) {
            Label(label, systemImage: symbol)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Theme.ground)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(Capsule().fill(Theme.signal))
        }
        .buttonStyle(.plain)
    }
}

struct OutlineButton: View {
    let label: String
    let tap: () -> Void
    var body: some View {
        Button(action: tap) {
            Text(label)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .frame(maxWidth: .infinity, minHeight: 48)
                .overlay(Capsule().stroke(Theme.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// What an empty screen says: what will appear here and how to get it there.
struct EmptyState: View {
    let symbol: String
    let title: String
    let hint: String
    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: symbol).font(.system(size: 30, weight: .light)).foregroundStyle(Theme.mute)
            Text(title).font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
            Text(hint).font(.system(size: 14)).foregroundStyle(Theme.mute).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40).padding(.horizontal, 24)
    }
}

struct FailureView: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Text("Couldn't load your saves")
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

/// Screen scaffold: dark ground, large title, pull to refresh, load/failure states.
struct Screen<Content: View>: View {
    let title: String
    @EnvironmentObject var store: Store
    @ViewBuilder let content: Content

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.ground.ignoresSafeArea()
                if store.loading && store.saves.isEmpty {
                    ProgressView().tint(Theme.signal)
                } else if let err = store.error, store.saves.isEmpty {
                    FailureView(message: err) { Task { await store.load() } }
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) { content }
                            .padding(.horizontal, 18).padding(.bottom, 30)
                    }
                    .refreshable { await store.load() }
                }
            }
            .navigationTitle(title)
            .toolbarBackground(Theme.ground, for: .navigationBar)
            .navigationDestination(for: Save.self) { SaveView(save: $0) }
        }
    }
}

extension Save {
    /// Opens the original reel or post.
    var source: URL? { URL(string: sourceURL) }
}
