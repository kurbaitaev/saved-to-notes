import CoreLocation
import Foundation
import MapKit
import SwiftUI

/// Carries a message a person can read. Swift needs a real Error type here;
/// a bare String will not do.
struct Failure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

@MainActor
final class Store: ObservableObject {
    @Published var saves: [Save] = []
    @Published var loading = false
    /// True when the server couldn't be reached and the last copy is shown.
    @Published var offline = false
    /// Links sent from the phone that the server is still sorting.
    @Published var pending = 0
    /// Links shared from the phone in the last day, and where each went.
    @Published var recent: [Share] = []
    private var watching = false
    @Published var error: String?
    /// Place pins, found on the phone with Apple Maps search — free, no key,
    /// and cached so each place is looked up once.
    @Published var pins: [String: CLLocationCoordinate2D] = [:]

    private let client = APIClient.shared
    private let local = LocalState()

    func of(_ kind: Kind) -> [Save] { saves.filter { $0.kind == kind } }

    /// While something is being sorted, check every few seconds so it appears
    /// on its own — nobody should have to pull to refresh to see a save land.
    func watch() {
        guard !watching else { return }
        watching = true
        Task {
            var tries = 0
            while pending > 0 && tries < 60 {
                try? await Task.sleep(for: .seconds(4))
                tries += 1
                if let (s, p, r) = try? await client.saves() { saves = s; pending = p; recent = r }
            }
            watching = false
            await load()   // clips, pins and cache for whatever just arrived
        }
    }

    func load() async {
        loading = true; error = nil
        if saves.isEmpty, let kept = client.lastCopy() { saves = kept }   // instant start
        do {
            (saves, pending, recent) = try await client.saves()
            offline = false
        } catch {
            // Keep showing what we have. Only an empty app shows the error.
            if saves.isEmpty, let kept = client.lastCopy() { saves = kept }
            offline = !saves.isEmpty
            if saves.isEmpty { self.error = error.localizedDescription }
        }
        if pending > 0 { watch() }
        loading = false
        pins = local.pins
        await locatePlaces()
        // Pre-fetch every loop so the morning routine plays offline and
        // instantly — six at a time: one by one, ~40 clips left the tiles grey
        // for ten seconds on first open.
        let all = of(.move).flatMap { s in [s.loop].compactMap { $0 } + s.moves.map(\.clip) }
        await withTaskGroup(of: Void.self) { g in
            for (i, c) in all.enumerated() {
                if i >= 6 { await g.next() }
                g.addTask { _ = try? await ClipCache.shared.file(for: c) }
            }
        }
    }

    // MARK: - Things to buy: ticked off on this phone

    func isDone(_ s: Save) -> Bool { local.done.contains(s.id) }
    func toggleDone(_ s: Save) {
        var d = local.done
        if d.contains(s.id) { d.remove(s.id) } else { d.insert(s.id) }
        local.done = d
        objectWillChange.send()
    }

    // MARK: - Morning routine: an ordered pick of Move saves

    /// Until edited: newest workouts first, filled to at least ~10 minutes and
    /// never past ~20 (it was every workout, 34 min; then a cap that stopped at
    /// a single 3-minute one). Once edited, exactly the person's pick.
    var routine: [Save] {
        let moves = of(.move)
        let stored = local.routine
        guard !stored.isEmpty else {
            var pick: [Save] = [], total = 0
            for s in moves where total < 10 && pick.count < 4 {
                let m = Self.minutes(s)
                if !pick.isEmpty && total + m > 20 { continue }   // too long: try a shorter one
                pick.append(s); total += m
            }
            return pick
        }
        return stored.compactMap { id in moves.first { $0.id == id } }  // "-" = deliberately empty
    }

    static func minutes(_ s: Save) -> Int {
        s.details.minutes ?? max(2, s.steps.count)
    }
    func inRoutine(_ s: Save) -> Bool { routine.contains(s) }
    func toggleRoutine(_ s: Save) {
        var r = routine.map(\.id)
        if let i = r.firstIndex(of: s.id) { r.remove(at: i) } else { r.append(s.id) }
        local.routine = r.isEmpty ? ["-"] : r   // "-" marks "deliberately empty"
        objectWillChange.send()
    }
    var routineMinutes: Int { routine.reduce(0) { $0 + Self.minutes($1) } }

    // MARK: - Map

    /// Places and events that have a findable location.
    var mappable: [Save] { saves.filter { ($0.kind == .visit || $0.kind == .attend) && !queries(for: $0).isEmpty } }

    /// What to search for, most specific first. An event is found by its VENUE
    /// — searching "Founders Meetup, Frontier Tower…" found nothing, so the
    /// event never got a pin.
    private func queries(for s: Save) -> [String] {
        let d = s.details
        let join = { (parts: [String?]) in parts.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ") }
        let name = (d.name ?? s.title).replacingOccurrences(of: "[TEST] ", with: "")
        let tries = s.kind == .attend
            ? [join([d.venue, d.address, d.city]), join([d.venue, d.city]), join([d.address, d.city])]
            : [join([name, d.address, d.city]), join([name, d.city]), join([d.address, d.city])]
        return tries.filter { $0.contains(",") }.uniqued()
    }

    private func locatePlaces() async {
        for s in mappable where pins[s.id] == nil {
            for q in queries(for: s) {
                let req = MKLocalSearch.Request()
                req.naturalLanguageQuery = q
                if let item = try? await MKLocalSearch(request: req).start().mapItems.first {
                    pins[s.id] = item.placemark.coordinate
                    break
                }
            }
        }
        local.pins = pins
    }
}

/// Small per-phone state in UserDefaults: what's ticked off, the routine order
/// and the place coordinates. Nothing here is precious — it can all be rebuilt.
private struct LocalState {
    private let d = UserDefaults.standard

    var done: Set<String> {
        get { Set(d.stringArray(forKey: "done.v1") ?? []) }
        nonmutating set { d.set(Array(newValue), forKey: "done.v1") }
    }
    var routine: [String] {
        get { d.stringArray(forKey: "routine.v1") ?? [] }
        nonmutating set { d.set(newValue, forKey: "routine.v1") }
    }
    var pins: [String: CLLocationCoordinate2D] {
        get {
            (d.dictionary(forKey: "pins.v1") as? [String: [Double]] ?? [:]).compactMapValues {
                $0.count == 2 ? CLLocationCoordinate2D(latitude: $0[0], longitude: $0[1]) : nil
            }
        }
        nonmutating set { d.set(newValue.mapValues { [$0.latitude, $0.longitude] }, forKey: "pins.v1") }
    }
}

/// Downloads each loop once into Caches. Notion's file links expire after an
/// hour, and a morning routine should not depend on the network.
actor ClipCache {
    static let shared = ClipCache()
    private let dir: URL = {
        let u = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("clips", isDirectory: true)
        try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        return u
    }()

    func cached(_ id: String, ext: String = "mp4") -> URL? {
        let f = dir.appendingPathComponent("\(id).\(ext)")
        return FileManager.default.fileExists(atPath: f.path) ? f : nil
    }

    func file(for clip: Clip) async throws -> URL {
        try await fetch(clip.url, key: clip.key, ext: "mp4")
    }

    func poster(for clip: Clip) async throws -> URL? {
        guard let p = clip.poster else { return nil }
        return try await fetch(p, key: clip.key, ext: "jpg")
    }

    private func fetch(_ remote: URL, key: String, ext: String) async throws -> URL {
        if let f = cached(key, ext: ext) { return f }
        let (tmp, resp) = try await URLSession.shared.download(for: APIClient.shared.clipRequest(remote))
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? 0) }
        let f = dir.appendingPathComponent("\(key).\(ext)")
        try? FileManager.default.removeItem(at: f)
        try FileManager.default.moveItem(at: tmp, to: f)
        return f
    }
}
