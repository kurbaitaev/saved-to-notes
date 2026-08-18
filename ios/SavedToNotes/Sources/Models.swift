import Foundation

struct Note: Identifiable, Hashable {
    let id: String
    let title: String
    let folder: String
    let topics: [String]
    let summary: String
    let hook: String
    let author: String
    let platform: String
    let sourceURL: String
    let date: String
    let worthRemaking: Bool
    /// Written by the pipeline at save time. The app never invents a question:
    /// self-written prompts measurably fail (Myers, Hausman & Rhodes 2024), so a
    /// note without one is simply skipped in review rather than faked.
    let reviewQuestion: String

    var canReview: Bool { !reviewQuestion.isEmpty }

    static func == (a: Note, b: Note) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

/// Verbatim source text, fetched lazily because it lives in the page's blocks
/// rather than its properties.
struct Script {
    var paragraphs: [String] = []
    var isEmpty: Bool { paragraphs.isEmpty }
    var joined: String { paragraphs.joined(separator: "\n\n") }
}
