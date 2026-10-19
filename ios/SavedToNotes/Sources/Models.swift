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

/// One real-life save, read from the shared Notion database.
struct Save: Identifiable, Hashable {
    let id: String
    let title: String
    let kind: Kind
    let summary: String
    let author: String
    let sourceURL: String
    let date: String
    let details: Details
    /// Notion's signed file URL. It expires after about an hour, so it is
    /// refreshed on every load and the video itself is cached on the phone.
    let clipURL: URL?

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

    enum CodingKeys: String, CodingKey {
        case name, kind, address, city, country, why, date, time, venue, url, brand, price,
             minutes, servings, ingredients, moves
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

struct Exercise: Decodable, Hashable {
    var name: String
    var dose: String?
    var cues: String?
}
