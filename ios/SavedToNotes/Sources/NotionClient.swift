import Foundation

/// Talks to Notion directly from the phone. The server writes every save into
/// one database; the app reads only the real-life categories from it.
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

    // MARK: - Saves

    func saves() async throws -> [Save] {
        var out: [Save] = []
        var cursor: String?
        let filter: [String: Any] = ["or": Kind.allCases.map {
            ["property": "Category", "select": ["equals": $0.rawValue]]
        }]
        repeat {
            var body: [String: Any] = [
                "page_size": 100,
                "filter": filter,
                "sorts": [["property": "Date", "direction": "descending"]],
            ]
            if let cursor { body["start_cursor"] = cursor }
            let json = try await request(
                URL(string: "https://api.notion.com/v1/databases/\(databaseID)/query")!,
                method: "POST", body: body)
            for row in json["results"] as? [[String: Any]] ?? [] {
                if let s = Self.parse(row) { out.append(s) }
            }
            cursor = (json["has_more"] as? Bool == true) ? json["next_cursor"] as? String : nil
        } while cursor != nil
        return out
    }

    private static func parse(_ row: [String: Any]) -> Save? {
        guard let id = row["id"] as? String,
              let props = row["properties"] as? [String: Any],
              let kind = Kind(rawValue: select(props["Category"])) else { return nil }
        let title = plain(props["Name"], key: "title")
        guard !title.isEmpty else { return nil }
        return Save(
            id: id,
            title: title,
            kind: kind,
            summary: plain(props["Hook / key idea"]).isEmpty ? plain(props["Summary"]) : plain(props["Hook / key idea"]),
            author: plain(props["Author"]),
            sourceURL: (props["Source"] as? [String: Any])?["url"] as? String ?? "",
            date: ((props["Date"] as? [String: Any])?["date"] as? [String: Any])?["start"] as? String ?? "",
            details: Details.parse(plain(props["Details"])),
            clipURL: fileURL(props["Clip"])
        )
    }

    // MARK: - Steps (a recipe's method lives in the page body as a numbered list)

    func steps(pageID: String) async throws -> [String] {
        var out: [String] = []
        var cursor: String?
        repeat {
            var comps = URLComponents(string: "https://api.notion.com/v1/blocks/\(pageID)/children")!
            comps.queryItems = [URLQueryItem(name: "page_size", value: "100")]
            if let cursor { comps.queryItems?.append(URLQueryItem(name: "start_cursor", value: cursor)) }
            let json = try await request(comps.url!, method: "GET")
            for block in json["results"] as? [[String: Any]] ?? [] where block["type"] as? String == "numbered_list_item" {
                let text = Self.richText((block["numbered_list_item"] as? [String: Any])?["rich_text"])
                if !text.isEmpty { out.append(text) }
            }
            cursor = (json["has_more"] as? Bool == true) ? json["next_cursor"] as? String : nil
        } while cursor != nil
        return out
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
    private static func fileURL(_ any: Any?) -> URL? {
        guard let first = ((any as? [String: Any])?["files"] as? [[String: Any]])?.first else { return nil }
        let type = first["type"] as? String ?? "file"
        return ((first[type] as? [String: Any])?["url"] as? String).flatMap(URL.init(string:))
    }
}
