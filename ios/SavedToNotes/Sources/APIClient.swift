import Foundation

/// Talks to the Afterscroll API on the server (api.py). The bot that writes
/// saves runs on the same machine, so this is the single source of truth —
/// no Notion in the app's path any more.
enum APIError: LocalizedError {
    case notConfigured
    case http(Int)

    var errorDescription: String? {
        switch self {
        case .notConfigured: "The app has no server token yet. Run ios/configure.sh and rebuild."
        case .http(401): "The server rejected the app's token. Copy APP_TOKEN from the server's .env and rebuild."
        case .http(let code): "The server returned \(code)."
        }
    }
}

struct APIClient {
    static let shared = APIClient()
    let base = URL(string: Secrets.apiBase)
    let token = Secrets.apiToken

    func request(_ path: String, method: String = "GET", json: [String: Any]? = nil) throws -> URLRequest {
        guard Secrets.configured, let base else { throw APIError.notConfigured }
        var r = URLRequest(url: base.appendingPathComponent(path))
        r.httpMethod = method
        r.timeoutInterval = 30
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let json {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        return r
    }

    /// Saves in the app, plus how many shared links are still being sorted.
    func saves() async throws -> (saves: [Save], pending: Int, recent: [Share]) {
        let (data, resp) = try await URLSession.shared.data(for: request("v1/saves"))
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200 else { throw APIError.http(code) }
        let reply = try JSONDecoder().decode(SavesReply.self, from: data)
        return (reply.saves.compactMap { $0.save(base: base!) }, reply.pending ?? 0, reply.recent ?? [])
    }

    /// Queue a link for the bot — used by the share button.
    func share(_ url: String, note: String = "") async throws {
        let (_, resp) = try await URLSession.shared.data(for: request("v1/save", method: "POST",
                                                                      json: ["url": url, "note": note]))
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 202 else { throw APIError.http(code) }
    }

    /// A clip request carries the token, so it goes through URLSession (the
    /// cache downloads it once) rather than straight into AVPlayer.
    func clipRequest(_ url: URL) -> URLRequest {
        var r = URLRequest(url: url)
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return r
    }
}

// MARK: - Wire format (api.py / appdb.all_saves)

private struct SavesReply: Decodable { let saves: [WireSave]; let pending: Int?; let recent: [Share]? }

/// Where a link shared from the phone ended up (api.py /v1/saves "recent").
struct Share: Decodable, Hashable {
    let url: String
    let ts: Double
    let status: String        // sorting | app | notion | duplicate | failed
    let category: String?
    let title: String?
}

private struct WireSave: Decodable {
    let id: String
    let url: String
    let category: String
    let title: String?
    let author: String?
    let summary: String?
    let details: Details
    let created: String?
    let loop: String?
    let poster: String?
    let moves: [WireClip]

    func save(base: URL) -> Save? {
        guard let kind = Kind(rawValue: category) else { return nil }
        let abs = { (p: String) in URL(string: p, relativeTo: base)?.absoluteURL }
        return Save(
            id: id, title: title ?? "", kind: kind, summary: summary ?? "", author: author ?? "",
            sourceURL: url, date: created ?? "", details: details,
            loop: loop.flatMap(abs).map { Clip(saveID: id, url: $0, poster: poster.flatMap(abs)) },
            moves: moves.enumerated().compactMap { i, m in
                abs(m.url).map { MoveClip(name: m.name ?? "Move \(i + 1)",
                                          clip: Clip(saveID: id, url: $0, poster: m.poster.flatMap(abs))) }
            })
    }
}

private struct WireClip: Decodable {
    let name: String?
    let url: String
    let poster: String?
}
