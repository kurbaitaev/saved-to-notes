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
    @Published var error: String?
    /// Place pins, found on the phone with Apple Maps search — free, no key,
    /// and cached so each place is looked up once.
    @Published var pins: [String: CLLocationCoordinate2D] = [:]

    private let client = NotionClient(token: Secrets.notionToken, databaseID: Secrets.notionDatabaseID)
    private let local = LocalState()

    func of(_ kind: Kind) -> [Save] { saves.filter { $0.kind == kind } }

    func load() async {
        loading = true; error = nil
        do { saves = try await client.saves() }
        catch { self.error = error.localizedDescription }
        loading = false
        pins = local.pins
        await locatePlaces()
        // Pre-fetch loops so the morning routine plays offline and instantly.
        for s in of(.move) { if let u = s.clipURL { _ = try? await ClipCache.shared.file(for: s.id, remote: u) } }
    }

    func steps(for save: Save) async -> [String] {
        (try? await client.steps(pageID: save.id)) ?? []
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

    /// Defaults to every saved workout, newest first, until reordered.
    var routine: [Save] {
        let moves = of(.move)
        let order = local.routine.filter { id in moves.contains { $0.id == id } }
        guard !order.isEmpty else { return moves }
        return order.compactMap { id in moves.first { $0.id == id } }
    }
    func inRoutine(_ s: Save) -> Bool { routine.contains(s) }
    func toggleRoutine(_ s: Save) {
        var r = routine.map(\.id)
        if let i = r.firstIndex(of: s.id) { r.remove(at: i) } else { r.append(s.id) }
        local.routine = r.isEmpty ? ["-"] : r   // "-" marks "deliberately empty"
        objectWillChange.send()
    }
    var routineMinutes: Int {
        routine.reduce(0) { $0 + ($1.details.minutes ?? max(1, ($1.details.moves?.count ?? 1))) }
    }

    // MARK: - Map

    /// Places and events that have a findable location.
    var mappable: [Save] { saves.filter { ($0.kind == .visit || $0.kind == .attend) && !query(for: $0).isEmpty } }

    private func query(for s: Save) -> String {
        let d = s.details
        let parts = [d.name ?? (s.kind == .visit ? s.title : nil), d.venue, d.address, d.city, d.country]
        return parts.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
    }

    private func locatePlaces() async {
        for s in mappable where pins[s.id] == nil {
            let req = MKLocalSearch.Request()
            req.naturalLanguageQuery = query(for: s)
            guard let item = try? await MKLocalSearch(request: req).start().mapItems.first else { continue }
            pins[s.id] = item.placemark.coordinate
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

    func cached(_ id: String) -> URL? {
        let f = dir.appendingPathComponent("\(id).mp4")
        return FileManager.default.fileExists(atPath: f.path) ? f : nil
    }

    func file(for id: String, remote: URL) async throws -> URL {
        if let f = cached(id) { return f }
        let (tmp, _) = try await URLSession.shared.download(from: remote)
        let f = dir.appendingPathComponent("\(id).mp4")
        try? FileManager.default.removeItem(at: f)
        try FileManager.default.moveItem(at: tmp, to: f)
        return f
    }
}
