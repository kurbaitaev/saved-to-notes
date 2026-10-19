import EventKit
import EventKitUI
import MapKit
import SwiftUI

/// One save, laid out for how it gets used: a workout's moves, a recipe in
/// cook mode, an event with Add to Calendar, a place with Directions.
struct SaveView: View {
    let save: Save
    @EnvironmentObject var store: Store
    @Environment(\.openURL) private var openURL
    @State private var steps: [String] = []
    @State private var addingEvent = false
    @State private var playing = false

    var body: some View {
        ZStack {
            Theme.ground.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 14) {
                        if save.kind == .move || save.cover != nil {
                            ClipTile(save: save, radius: 18).frame(width: 150)
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            Eyebrow(text: meta, color: Theme.signal)
                            Text(save.name).font(.system(size: 26, weight: .heavy)).foregroundStyle(Theme.ink)
                                .fixedSize(horizontal: false, vertical: true)
                            if let why = save.details.why ?? save.summary.nilIfEmpty {
                                Text(why).font(.system(size: 14)).foregroundStyle(Theme.soft).lineLimit(5)
                            }
                            if !save.author.isEmpty {
                                Text("From \(save.author)").font(.system(size: 13)).foregroundStyle(Theme.mute)
                            }
                        }
                        .padding(.top, 4)
                    }
                    actions
                    kindBody
                }
                .padding(18)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Theme.ground, for: .navigationBar)
        .task { steps = save.details.steps ?? [] }
        .sheet(isPresented: $addingEvent) { EventEditor(save: save).ignoresSafeArea() }
        .fullScreenCover(isPresented: $playing) { RoutinePlayer(saves: [save]) }
        .onAppear { if save.kind == .cook { UIApplication.shared.isIdleTimerDisabled = true } }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }

    private var meta: String {
        let d = save.details
        switch save.kind {
        case .move: return [d.bodyArea, d.purpose, d.minutes.map { "\($0) min" }].compactMap { $0 }.joined(separator: " · ").ifEmpty("Workout")
        case .visit: return [d.kind, d.city].compactMap { $0 }.joined(separator: " · ").ifEmpty("Place")
        case .attend: return d.eventDate?.formatted(.dateTime.weekday(.wide).day().month(.wide).hour().minute()) ?? "Event · date not given"
        case .cook: return [d.minutes.map { "\($0) min" }, d.servings.map { "serves \($0)" }].compactMap { $0 }.joined(separator: " · ").ifEmpty("Recipe")
        case .buy: return [d.brand, d.price].compactMap { $0 }.joined(separator: " · ").ifEmpty("To get")
        }
    }

    @ViewBuilder private var actions: some View {
        HStack(spacing: 8) {
            switch save.kind {
            case .attend:
                PrimaryButton(label: "Add to Calendar", symbol: "calendar.badge.plus") { addingEvent = true }
            case .visit:
                PrimaryButton(label: "Directions", symbol: "arrow.triangle.turn.up.right.diamond") { directions() }
            case .buy:
                if let u = save.details.url.flatMap(URL.init(string:)) {
                    PrimaryButton(label: "Open product", symbol: "bag") { openURL(u) }
                }
                OutlineButton(label: store.isDone(save) ? "Bought ✓" : "Mark bought") { store.toggleDone(save) }
            case .move:
                WideButton(label: "Start") { playing = true }
                OutlineButton(label: store.inRoutine(save) ? "In routine ✓" : "Add to routine") { store.toggleRoutine(save) }
            case .cook:
                EmptyView()
            }
            if let src = save.source {
                Button { openURL(src) } label: {
                    Image(systemName: "arrow.up.right").font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.soft)
                        .frame(width: 48, height: 48).overlay(Circle().stroke(Theme.line))
                }
                .accessibilityLabel("Open the original post")
            }
        }
    }

    @ViewBuilder private var kindBody: some View {
        let d = save.details
        switch save.kind {
        case .move:
            if !save.steps.isEmpty { section("Moves · \(save.steps.count)"); MovesList(steps: save.steps) }
        case .cook:
            if let ing = d.ingredients, !ing.isEmpty {
                section("Ingredients")
                ForEach(ing, id: \.self) { i in
                    Label(i, systemImage: "circle.fill").labelStyle(Dot()).padding(.vertical, 2)
                }
            }
            if !steps.isEmpty {
                section("Method")
                ForEach(Array(steps.enumerated()), id: \.offset) { n, s in
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("\(n + 1)").font(Theme.mono(14, .medium)).foregroundStyle(Theme.signal)
                        Text(s).font(.system(size: 18)).foregroundStyle(Theme.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.vertical, 6)
                }
            }
        case .visit, .attend:
            if !d.whereLine.isEmpty { section("Where"); Text(d.whereLine).foregroundStyle(Theme.ink) }
            if let u = d.url.flatMap(URL.init(string:)) {
                Button("Tickets / event page") { openURL(u) }.foregroundStyle(Theme.signal)
            }
        case .buy:
            EmptyView()
        }
    }

    private func section(_ t: String) -> some View { Eyebrow(text: t).padding(.top, 8) }

    private func directions() {
        if let c = store.pins[save.id] {
            let item = MKMapItem(placemark: MKPlacemark(coordinate: c))
            item.name = save.name
            item.openInMaps()
        } else if let q = [save.name, save.details.city].compactMap({ $0 }).joined(separator: " ")
                    .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
                  let u = URL(string: "maps://?q=\(q)") {
            openURL(u)
        }
    }
}

private struct Dot: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Circle().fill(Theme.signal).frame(width: 5, height: 5).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
            configuration.title.font(.system(size: 16)).foregroundStyle(Theme.ink)
        }
    }
}

/// The system's own event editor, pre-filled. Since iOS 17 presenting it needs
/// no calendar permission: the person adds the event themselves.
struct EventEditor: UIViewControllerRepresentable {
    let save: Save
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIViewController(context: Context) -> EKEventEditViewController {
        let store = EKEventStore()
        let vc = EKEventEditViewController()
        vc.eventStore = store
        let e = EKEvent(eventStore: store)
        e.title = save.name
        e.location = save.details.whereLine
        if let start = save.details.eventDate {
            e.startDate = start
            e.endDate = start.addingTimeInterval(2 * 3600)
            e.isAllDay = save.details.time == nil
        }
        e.url = save.details.url.flatMap(URL.init(string:)) ?? save.source
        e.notes = save.details.why
        vc.event = e
        vc.editViewDelegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: EKEventEditViewController, context: Context) {}

    final class Coordinator: NSObject, EKEventEditViewDelegate {
        func eventEditViewController(_ c: EKEventEditViewController, didCompleteWith action: EKEventEditViewAction) {
            c.dismiss(animated: true)
        }
    }
}
