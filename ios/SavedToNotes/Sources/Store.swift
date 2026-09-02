import Foundation
import SwiftUI

/// Carries a message a person can read. Swift needs a real Error type here;
/// a bare String will not do.
struct Failure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

@MainActor
final class Store: ObservableObject {
    @Published var notes: [Note] = []
    @Published var loading = false
    @Published var error: String?
    @Published var folder: String? = nil

    private let client = NotionClient(token: Secrets.notionToken, databaseID: Secrets.notionDatabaseID)
    private let schedule = ReviewSchedule()

    var folders: [(name: String, count: Int)] {
        Dictionary(grouping: notes, by: \.folder)
            .filter { !$0.key.isEmpty }
            .map { ($0.key, $0.value.count) }
            .sorted { $0.count > $1.count }
    }

    var visible: [Note] {
        guard let folder else { return notes }
        return notes.filter { $0.folder == folder }
    }

    /// Exactly one card, and only if it is actually due. A queue that can grow is
    /// the documented failure mode for every review product: backlog, then dread,
    /// then deletion. There is nothing to catch up on here by construction.
    var dueToday: Note? {
        notes.filter { $0.canReview && schedule.isDue($0) }
            // Oldest due first, with the id as a tie-break. The tie-break is not
            // cosmetic: without a total order the chosen card could change
            // between rendering the question and fetching its note, which showed
            // one note's question above another note's script.
            .min { a, b in
                let (x, y) = (schedule.due(for: a), schedule.due(for: b))
                return x == y ? a.id < b.id : x < y
            }
    }

    var reviewableCount: Int { notes.filter(\.canReview).count }

    func load() async {
        loading = true; error = nil
        do { notes = try await client.notes() }
        catch { self.error = error.localizedDescription }
        loading = false
    }

    func script(for note: Note) async -> Result<Script, Failure> {
        do { return .success(try await client.script(pageID: note.id)) }
        catch { return .failure(Failure(message: error.localizedDescription)) }
    }

    func grade(_ note: Note, recalled: Bool) {
        schedule.record(note.id, recalled: recalled)
        objectWillChange.send()
        // Local schedule first so the card advances even offline; Notion is
        // the shared ledger and a failure here must not block the next card.
        Task { try? await client.recordReview(pageID: note.id, recalled: recalled) }
    }
}

/// Fixed ladder, stored on the device. Deliberately not FSRS: the evidence says
/// the penalty for a gap that is too *short* is far larger than for one that is
/// too long, so precision buys almost nothing next to whether you show up.
struct ReviewSchedule {
    private let key = "review.due.v1"
    private let ladder = [10, 30, 90]      // days after each successful recall
    private let missed = 3
    private let firstReviewAfterDays = 7

    private var table: [String: [String: Any]] {
        get { UserDefaults.standard.dictionary(forKey: key) as? [String: [String: Any]] ?? [:] }
        nonmutating set { UserDefaults.standard.set(newValue, forKey: key) }
    }

    /// A note becomes reviewable 7 days after it was saved — long enough that
    /// answering is real recall rather than short-term memory.
    ///
    /// Never-reviewed notes derive their date from when they were saved rather
    /// than from `Date()`. A "now minus one second" default is not a fixed point:
    /// every read returned a different value, so sorting by it had no stable
    /// order at all.
    func due(for note: Note) -> Date {
        if let row = table[note.id], let ts = row["due"] as? Double {
            return Date(timeIntervalSince1970: ts)
        }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(secondsFromGMT: 0)
        guard let saved = f.date(from: String(note.date.prefix(10))) else { return .distantPast }
        return saved.addingTimeInterval(Double(firstReviewAfterDays) * 86_400)
    }

    func isDue(_ note: Note) -> Bool { due(for: note) <= Date() }

    func step(_ id: String) -> Int { (table[id]?["step"] as? Int) ?? 0 }

    func record(_ id: String, recalled: Bool) {
        var t = table
        let current = step(id)
        let next = recalled ? min(current + 1, ladder.count) : 0
        let days = recalled ? ladder[min(current, ladder.count - 1)] : missed
        t[id] = ["due": Date().addingTimeInterval(Double(days) * 86_400).timeIntervalSince1970,
                 "step": next]
        table = t
    }
}
