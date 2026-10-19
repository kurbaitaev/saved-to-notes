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

    func saves() async throws -> [Save] {
        let (data, resp) = try await URLSession.shared.data(for: request("v1/saves"))
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200 else { throw APIError.http(code) }
        return try JSONDecoder().decode(SavesReply.self, from: data).saves.compactMap { $0.save(base: base!) }
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

private struct SavesReply: Decodable { let saves: [WireSave] }

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
    let moves: [WireClip]

    func save(base: URL) -> Save? {
        guard let kind = Kind(rawValue: category) else { return nil }
        let abs = { (p: String) in URL(string: p, relativeTo: base)?.absoluteURL }
        return Save(
            id: id, title: title ?? "", kind: kind, summary: summary ?? "", author: author ?? "",
            sourceURL: url, date: created ?? "", details: details,
            loop: loop.flatMap(abs).map { Clip(key: "\(id)-loop", url: $0) },
            moves: moves.enumerated().compactMap { i, m in
                abs(m.url).map { MoveClip(name: m.name ?? "Move \(i + 1)", clip: Clip(key: "\(id)-m\(i + 1)", url: $0)) }
            })
    }
}

private struct WireClip: Decodable {
    let name: String?
    let url: String
}
