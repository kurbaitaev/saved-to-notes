import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// "Afterscroll" in the share sheet. Takes the shared link (Instagram, TikTok,
/// Safari, Maps…), offers one optional line for why it's being saved, sends
/// both to the server's /v1/save, shows a short confirmation and closes. The
/// server's bot does all the work within a minute; nothing is decided on the
/// phone.
final class ShareViewController: UIViewController {
    /// How long the card waits for a note before saving on its own, so a save
    /// without one stays a single tap in the share sheet.
    static let autoSaveSeconds = 3.0

    private let model = ShareModel()
    private var link: String?
    private var appeared = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        let card = ShareCard(model: model,
                             save: { [weak self] in Task { await self?.save() } },
                             close: { [weak self] in self?.finish() })
        let host = UIHostingController(rootView: card)
        host.view.backgroundColor = .clear
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await start() }
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        appeared = true
        beginCountdown()
    }

    private func finish() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    private func start() async {
        guard let link = await sharedLink() else {
            await report()
            model.state = .failed("No link found in what was shared. Copy the link instead and tap Paste link in the app.")
            return
        }
        self.link = link
        let host = URL(string: link)?.host() ?? link
        model.state = .ready(host.hasPrefix("www.") ? String(host.dropFirst(4)) : host)
        beginCountdown()
    }

    /// Starts once the link is known and the sheet has stopped sliding up: a
    /// clock that ran during the slide left too little time to reach the field,
    /// and a save that fires early loses the note for good.
    private func beginCountdown() {
        guard appeared, link != nil, !model.counting else { return }
        model.counting = true
        Task {
            try? await Task.sleep(for: .seconds(Self.autoSaveSeconds))
            // Touching the note field holds the save until they send it themselves.
            if !model.holding { await save() }
        }
    }

    private func save() async {
        guard case .ready = model.state, let link else { return }
        model.state = .sending
        do {
            try await post(link, note: model.cleanNote)
            model.state = .saved
            try? await Task.sleep(for: .seconds(1.2))
            finish()
        } catch {
            await report(error.localizedDescription)
            model.state = .failed(error.localizedDescription)
        }
    }

    /// The first web link among the shared items. Apps hand it over in
    /// different shapes — a URL object, a string, raw data, or only inside the
    /// shared text ("caption + link") — so every shape is tried.
    private func sharedLink() async -> String? {
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        let providers = items.flatMap { $0.attachments ?? [] }
        let types = [UTType.url, .plainText, .text, .data].map(\.identifier)
        for type in types {
            for p in providers where p.hasItemConformingToTypeIdentifier(type) {
                guard let item = try? await p.loadItem(forTypeIdentifier: type) else { continue }
                if let link = Self.link(in: item) { return link }
            }
        }
        // Last resort: the text the app attached to the share itself.
        for i in items {
            if let t = i.attributedContentText?.string, let link = Self.link(in: t) { return link }
        }
        return nil
    }

    /// Tell the server what the other app handed over (types and a short
    /// sample), so a share that finds no link can be diagnosed.
    private func report(_ error: String = "no link") async {
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        var parts: [String] = ["error: \(error)"]
        for (i, item) in items.enumerated() {
            if let t = item.attributedContentText?.string { parts.append("item\(i) text: \(t.prefix(200))") }
            for p in item.attachments ?? [] {
                var line = "item\(i) types: \(p.registeredTypeIdentifiers.joined(separator: ","))"
                if let id = p.registeredTypeIdentifiers.first,
                   let v = try? await p.loadItem(forTypeIdentifier: id) {
                    line += " sample: \(String(describing: v).prefix(200))"
                }
                parts.append(line)
            }
        }
        guard let base = URL(string: Secrets.apiBase) else { return }
        var r = URLRequest(url: base.appendingPathComponent("v1/report"))
        r.httpMethod = "POST"
        r.timeoutInterval = 10
        r.setValue("Bearer \(Secrets.apiToken)", forHTTPHeaderField: "Authorization")
        r.httpBody = parts.joined(separator: " | ").data(using: .utf8)
        _ = try? await URLSession.shared.data(for: r)
    }

    static func link(in item: Any) -> String? {
        let text: String?
        switch item {
        case let u as URL: text = u.absoluteString
        case let s as String: text = s
        case let a as NSAttributedString: text = a.string
        case let d as Data: text = String(data: d, encoding: .utf8)
        default: text = nil
        }
        guard let text, let r = text.range(of: #"https?://[^\s"'<>]+"#, options: .regularExpression) else { return nil }
        return String(text[r])
    }

    private func post(_ link: String, note: String) async throws {
        guard let base = URL(string: Secrets.apiBase), Secrets.configured else {
            throw ShareError("This build has no server address.")
        }
        var r = URLRequest(url: base.appendingPathComponent("v1/save"))
        r.httpMethod = "POST"
        r.timeoutInterval = 20
        r.setValue("Bearer \(Secrets.apiToken)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Their own words ride along as "note"; the bot keeps them as my_note.
        var body = ["url": link]
        if !note.isEmpty { body["note"] = note }
        r.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (_, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 202 else {
            throw ShareError(code == 401 ? "The server didn't accept this app's key." : "The server answered \(code). Try again.")
        }
    }
}

struct ShareError: LocalizedError {
    let message: String
    init(_ m: String) { message = m }
    var errorDescription: String? { message }
}

@MainActor
final class ShareModel: ObservableObject {
    enum State { case finding, ready(String), sending, saved, failed(String) }
    @Published var state: State = .finding
    @Published var note = ""
    @Published var counting = false
    /// Set once they touch the note field: from then on only they send it.
    @Published var holding = false

    /// One line, at most what the server keeps (500 characters).
    var cleanNote: String {
        let line = note.split(whereSeparator: \.isNewline).joined(separator: " ")
        return String(line.trimmingCharacters(in: .whitespaces).prefix(500))
    }
}

private struct ShareCard: View {
    @ObservedObject var model: ShareModel
    let save: () -> Void
    let close: () -> Void
    @FocusState private var typing: Bool
    @State private var countdown: CGFloat = 0

    private let ground = Color(red: 0.090, green: 0.106, blue: 0.118)
    private let ink = Color(red: 0.914, green: 0.902, blue: 0.875)
    private let signal = Color(red: 0.949, green: 0.757, blue: 0.306)
    private let mute = Color(red: 0.604, green: 0.631, blue: 0.651)
    private let field = Color(red: 0.149, green: 0.173, blue: 0.192)

    var body: some View {
        VStack {
            Spacer()
            VStack(spacing: 12) {
                switch model.state {
                case .finding, .sending:
                    ProgressView().tint(signal)
                    Text("Saving to Afterscroll…").font(.system(size: 17, weight: .semibold)).foregroundStyle(ink)
                case .ready(let host):
                    Text("Save to Afterscroll").font(.system(size: 17, weight: .semibold)).foregroundStyle(ink)
                    Text(host).font(.system(size: 13)).foregroundStyle(mute).lineLimit(1)
                    TextField("", text: $model.note, prompt: Text("Why? (optional)").foregroundStyle(mute))
                        .focused($typing)
                        .submitLabel(.send)
                        .onSubmit(save)
                        .font(.system(size: 16)).foregroundStyle(ink).tint(signal)
                        .padding(.horizontal, 14)
                        .frame(minHeight: 48)
                        .background(RoundedRectangle(cornerRadius: 12).fill(field))
                        .onChange(of: typing) { _, now in if now { model.holding = true } }
                    Button(action: save) {
                        Text("Save").font(.system(size: 16, weight: .semibold)).foregroundStyle(Color.black)
                            .frame(maxWidth: .infinity, minHeight: 48)
                            .background(countdownFill)
                    }
                    .onChange(of: model.counting, initial: true) { _, now in
                        guard now else { return }
                        withAnimation(.linear(duration: ShareViewController.autoSaveSeconds)) { countdown = 1 }
                    }
                    Text(model.holding ? "Tap Save when you're done." : "Saves on its own in a moment.")
                        .font(.system(size: 12)).foregroundStyle(mute)
                case .saved:
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 34)).foregroundStyle(signal)
                    Text("Saved").font(.system(size: 19, weight: .bold)).foregroundStyle(ink)
                    Text("It'll be sorted and in the app in about a minute.")
                        .font(.system(size: 14)).foregroundStyle(mute).multilineTextAlignment(.center)
                case .failed(let why):
                    Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 30)).foregroundStyle(signal)
                    Text("Couldn't save").font(.system(size: 19, weight: .bold)).foregroundStyle(ink)
                    Text(why).font(.system(size: 14)).foregroundStyle(mute).multilineTextAlignment(.center)
                    Button("Close", action: close)
                        .font(.system(size: 16, weight: .semibold)).foregroundStyle(Color.black)
                        .frame(maxWidth: .infinity, minHeight: 48).background(Capsule().fill(signal))
                }
            }
            .padding(24)
            .frame(maxWidth: 340)
            .background(RoundedRectangle(cornerRadius: 24).fill(ground))
            .padding(.bottom, 40)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black.opacity(0.35).ignoresSafeArea())
    }

    /// The Save button fills up while it waits to save on its own, and goes
    /// solid once they start a note.
    private var countdownFill: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(signal.opacity(model.holding ? 1 : 0.45))
                if !model.holding {
                    Capsule().fill(signal).frame(width: max(48, g.size.width * countdown))
                }
            }
        }
    }
}
