import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// "Afterscroll" in the share sheet. Takes the shared link (Instagram, TikTok,
/// Safari, Maps…), sends it to the server's /v1/save, shows a short
/// confirmation and closes. The server's bot does all the work within a minute;
/// nothing is decided on the phone.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        let host = UIHostingController(rootView: ShareCard(model: model) { [weak self] in self?.finish() })
        host.view.backgroundColor = .clear
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await send() }
    }

    private func finish() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    private func send() async {
        guard let link = await sharedLink() else {
            model.state = .failed("No link in what you shared.")
            return
        }
        do {
            try await post(link)
            model.state = .saved
            try? await Task.sleep(for: .seconds(1.2))
            finish()
        } catch {
            model.state = .failed(error.localizedDescription)
        }
    }

    /// The first URL among the shared items — as a URL, or inside shared text
    /// (Instagram shares "caption + link" as text in some versions).
    private func sharedLink() async -> String? {
        let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? []).flatMap { $0.attachments ?? [] }
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let url = try? await p.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL,
               url.scheme?.hasPrefix("http") == true { return url.absoluteString }
        }
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            if let text = try? await p.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String,
               let r = text.range(of: #"https?://\S+"#, options: .regularExpression) {
                return String(text[r])
            }
        }
        return nil
    }

    private func post(_ link: String) async throws {
        guard let base = URL(string: Secrets.apiBase), Secrets.configured else {
            throw ShareError("This build has no server address.")
        }
        var r = URLRequest(url: base.appendingPathComponent("v1/save"))
        r.httpMethod = "POST"
        r.timeoutInterval = 20
        r.setValue("Bearer \(Secrets.apiToken)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["url": link])
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
    enum State { case sending, saved, failed(String) }
    @Published var state: State = .sending
}

private struct ShareCard: View {
    @ObservedObject var model: ShareModel
    let close: () -> Void

    private let ground = Color(red: 0.090, green: 0.106, blue: 0.118)
    private let ink = Color(red: 0.914, green: 0.902, blue: 0.875)
    private let signal = Color(red: 0.949, green: 0.757, blue: 0.306)
    private let mute = Color(red: 0.604, green: 0.631, blue: 0.651)

    var body: some View {
        VStack {
            Spacer()
            VStack(spacing: 12) {
                switch model.state {
                case .sending:
                    ProgressView().tint(signal)
                    Text("Saving to Afterscroll…").font(.system(size: 17, weight: .semibold)).foregroundStyle(ink)
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
}
