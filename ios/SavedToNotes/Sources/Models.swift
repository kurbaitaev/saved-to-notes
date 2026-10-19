import Foundation

/// The five real-life categories. Must match REAL_LIFE in folders.py exactly —
/// they are the Notion select values the app filters on.
enum Kind: String, CaseIterable, Identifiable {
    case move = "Move", visit = "Visit", attend = "Attend", cook = "Cook", buy = "Buy"
    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .move: "figure.flexibility"
        case .visit: "mappin.and.ellipse"
        case .attend: "calendar"
        case .cook: "fork.knife"
        case .buy: "bag"
        }
    }
}

/// One real-life save, read from the Afterscroll API on the server.
struct Save: Identifiable, Hashable {
    let id: String
    let title: String
    let kind: Kind
    let summary: String
    let author: String
    let sourceURL: String
    let date: String
    let details: Details
    /// The whole reel as a silent loop (workouts only).
    let loop: Clip?
    /// One loop per exercise, cut where Gemini saw each move — empty when the
    /// reel couldn't be split, in which case the whole loop stands in.
    let moves: [MoveClip]

    /// Something to show in a tile: the whole loop, else the first move.
    var cover: Clip? { loop ?? moves.first?.clip }

    /// The name a person would say: the place, the dish, the routine.
    var name: String { details.name?.isEmpty == false ? details.name! : title }

    static func == (a: Save, b: Save) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

/// Mirrors details.py. Every field is optional because each category fills
/// only its own subset, and an unknown value is left out rather than guessed.
struct Details: Decodable, Hashable {
    var name: String?
    var kind: String?
    var address: String?
    var city: String?
    var country: String?
    var why: String?
    var date: String?
    var time: String?
    var venue: String?
    var url: String?
    var brand: String?
    var price: String?
    var minutes: Int?
    var servings: Int?
    var ingredients: [String]?
    var bodyArea: String?
    var purpose: String?
    var moves: [Exercise]?
    var steps: [String]?

    enum CodingKeys: String, CodingKey {
        case name, kind, address, city, country, why, date, time, venue, url, brand, price,
             minutes, servings, ingredients, moves, steps
        case bodyArea = "body_area", purpose
    }

    static let empty = Details()

    static func parse(_ json: String) -> Details {
        guard let data = json.data(using: .utf8), !json.isEmpty,
              let d = try? JSONDecoder().decode(Details.self, from: data) else { return .empty }
        return d
    }

    /// "Thu 19 Nov · 19:00" for an event, nil when there is no usable date.
    var eventDate: Date? {
        guard let date else { return nil }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = time == nil ? "yyyy-MM-dd" : "yyyy-MM-dd HH:mm"
        return f.date(from: time == nil ? date : "\(date) \(time!)")
    }

    /// One line for where a place or event is.
    var whereLine: String {
        [venue, address, city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// A video on the server, cached on the phone under `key`.
struct Clip: Hashable {
    let key: String
    let url: URL
}

struct MoveClip: Hashable {
    let name: String
    let clip: Clip
}

struct Exercise: Decodable, Hashable {
    var name: String
    var dose: String?
    var cues: String?
}

/// One exercise as the app shows it: its own clip when the reel was split,
/// plus the dose and cue from the note when they can be matched to it.
struct Step: Hashable {
    let name: String
    let clip: Clip?
    let dose: String?
    let cues: String?
}

extension Save {
    /// The video cuts are the truth for WHICH moves exist (Gemini watched the
    /// reel; the text-only notes missed two of six on the hip reel). The note
    /// adds dose and cues: by position when both lists are the same length,
    /// otherwise by a shared word in the name.
    var steps: [Step] {
        let noted = details.moves ?? []
        guard !moves.isEmpty else {
            return noted.map { Step(name: $0.name, clip: loop, dose: $0.dose, cues: $0.cues) }
        }
        return moves.enumerated().map { i, m in
            let match = noted.count == moves.count ? noted[i] : noted.first { Self.related($0.name, m.name) }
            return Step(name: m.name, clip: m.clip, dose: match?.dose, cues: match?.cues)
        }
    }

    private static func related(_ a: String, _ b: String) -> Bool {
        let stop: Set = ["stretch", "pose", "with", "the", "and", "on", "of", "a"]
        let words = { (s: String) in Set(s.lowercased().split { !$0.isLetter }.map(String.init).filter { $0.count > 2 && !stop.contains($0) }) }
        return !words(a).isDisjoint(with: words(b))
    }
}
