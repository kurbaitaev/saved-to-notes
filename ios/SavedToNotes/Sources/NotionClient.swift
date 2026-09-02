import Foundation

/// Talks to Notion directly from the phone. There is deliberately no server in
/// this app: the pipeline that *writes* notes needs yt-dlp, ffmpeg and a headless
/// agent and stays on the Mac, but reading them needs none of that.
enum NotionError: LocalizedError {
    case notConfigured
    case http(Int, String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "No Notion token yet. Add it in Secrets.swift and rebuild."
        case .http(let code, let msg):
            return code == 401 ? "Notion rejected the token (401). Check it's the integration's secret and that the database is shared with the integration."
                               : "Notion returned \(code). \(msg)"
        }
    }
}

struct NotionClient {
    let token: String
    let databaseID: String

    private func request(_ url: URL, method: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        guard !token.isEmpty, !databaseID.isEmpty else { throw NotionError.notConfigured }
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue("2022-06-28", forHTTPHeaderField: "Notion-Version")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body { r.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])??["message"] as? String
            throw NotionError.http(code, msg ?? "")
        }
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    // MARK: - Notes

    func notes() async throws -> [Note] {
        var out: [Note] = []
        var cursor: String?
        // Notion pages at 100; the vault is past 200 notes, so paging is not optional.
        repeat {
            var body: [String: Any] = [
                "page_size": 100,
                "sorts": [["property": "Date", "direction": "descending"]],
            ]
            if let cursor { body["start_cursor"] = cursor }
            let json = try await request(
                URL(string: "https://api.notion.com/v1/databases/\(databaseID)/query")!,
                method: "POST", body: body)
            for row in json["results"] as? [[String: Any]] ?? [] {
                if let n = Self.parse(row) { out.append(n) }
            }
            cursor = (json["has_more"] as? Bool == true) ? json["next_cursor"] as? String : nil
        } while cursor != nil
        return out
    }

    private static func parse(_ row: [String: Any]) -> Note? {
        guard let id = row["id"] as? String,
              let props = row["properties"] as? [String: Any] else { return nil }
        let title = plain(props["Name"], key: "title")
        guard !title.isEmpty else { return nil }
        return Note(
            id: id,
            title: title,
            folder: select(props["Folder"]),
            topics: multiSelect(props["Topics"]),
            summary: plain(props["Summary"]),
            hook: plain(props["Hook / key idea"]),
            author: plain(props["Author"]),
            platform: select(props["Platform"]),
            sourceURL: (props["Source"] as? [String: Any])?["url"] as? String ?? "",
            date: ((props["Date"] as? [String: Any])?["date"] as? [String: Any])?["start"] as? String ?? "",
            worthRemaking: (props["Worth remaking"] as? [String: Any])?["checkbox"] as? Bool ?? false,
            reviewQuestion: plain(props["Review question"])
        )
    }

    // MARK: - Script (the verbatim body, stored as page blocks)

    func script(pageID: String) async throws -> Script {
        var paras: [String] = []
        var cursor: String?
        repeat {
            var comps = URLComponents(string: "https://api.notion.com/v1/blocks/\(pageID)/children")!
            comps.queryItems = [URLQueryItem(name: "page_size", value: "100")]
            if let cursor { comps.queryItems?.append(URLQueryItem(name: "start_cursor", value: cursor)) }
            let json = try await request(comps.url!, method: "GET")
            for block in json["results"] as? [[String: Any]] ?? [] {
                guard let type = block["type"] as? String,
                      let inner = block[type] as? [String: Any] else { continue }
                let text = Self.richText(inner["rich_text"])
                if !text.isEmpty { paras.append(text) }
            }
            cursor = (json["has_more"] as? Bool == true) ? json["next_cursor"] as? String : nil
        } while cursor != nil
        return Script(paragraphs: paras)
    }

    // MARK: - Review answers

    /// Record one answer on the note's Notion page. The counts live in Notion
    /// rather than only on this phone so the weekly digest can read them —
    /// and so the number nobody in this category has ever published (do people
    /// actually remember what they saved?) accumulates somewhere durable.
    func recordReview(pageID: String, recalled: Bool) async throws {
        let page = try await request(URL(string: "https://api.notion.com/v1/pages/\(pageID)")!, method: "GET")
        let props = page["properties"] as? [String: Any] ?? [:]
        let reviews = ((props["Reviews"] as? [String: Any])?["number"] as? Int ?? 0) + 1
        let hits = ((props["Recalled"] as? [String: Any])?["number"] as? Int ?? 0) + (recalled ? 1 : 0)
        let today = ISO8601DateFormatter().string(from: Date()).prefix(10)
        _ = try await request(
            URL(string: "https://api.notion.com/v1/pages/\(pageID)")!, method: "PATCH",
            body: ["properties": [
                "Reviews": ["number": reviews],
                "Recalled": ["number": hits],
                "Last reviewed": ["date": ["start": String(today)]],
                "Last result": ["select": ["name": recalled ? "recalled" : "missed"]],
            ]])
    }

    // MARK: - Field helpers
    // Notion wraps every value in its own shape; these keep that noise in one place.

    private static func richText(_ any: Any?) -> String {
        (any as? [[String: Any]] ?? []).compactMap { $0["plain_text"] as? String }.joined()
    }
    private static func plain(_ any: Any?, key: String = "rich_text") -> String {
        richText((any as? [String: Any])?[key]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private static func select(_ any: Any?) -> String {
        ((any as? [String: Any])?["select"] as? [String: Any])?["name"] as? String ?? ""
    }
    private static func multiSelect(_ any: Any?) -> [String] {
        ((any as? [String: Any])?["multi_select"] as? [[String: Any]] ?? [])
            .compactMap { $0["name"] as? String }
    }
}
