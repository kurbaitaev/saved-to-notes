import MapKit
import SwiftUI

/// Saved places and events as pins. Places are amber, events are green.
struct MapScreen: View {
    @EnvironmentObject var store: Store
    @State private var filter: Kind?
    @State private var selected: Save?
    @State private var camera: MapCameraPosition = .automatic
    @StateObject private var locator = Locator()

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Map(position: $camera, selection: Binding(
                    get: { selected?.id },
                    set: { id in selected = store.saves.first { $0.id == id } })) {
                    // Only once allowed: the tab is built at launch, and showing the
                    // dot asks for permission before the person has seen the map.
                    // The locate button asks, when they tap it.
                    if locator.allowed { UserAnnotation() }
                    ForEach(pinned) { s in
                        if let c = store.pins[s.id] {
                            Marker(s.name, systemImage: s.kind.symbol, coordinate: c)
                                .tint(s.kind == .attend ? Theme.ok : Theme.signal)
                                .tag(s.id)
                        }
                    }
                }
                .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
                .preferredColorScheme(.dark)

                HStack(spacing: 6) {
                    Chip(label: "All", on: filter == nil) { filter = nil }
                    Chip(label: "Places \(store.of(.visit).count)", on: filter == .visit) { filter = .visit }
                    Chip(label: "Events \(store.of(.attend).count)", on: filter == .attend) { filter = .attend }
                    Spacer()
                    Button {
                        locator.ask()
                        withAnimation { camera = .userLocation(fallback: camera) }
                    } label: {
                        Image(systemName: locator.allowed ? "location.fill" : "location")
                            .font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.signal)
                            .frame(width: 44, height: 44)
                            .background(Circle().fill(Theme.raise))
                    }
                    .accessibilityLabel("Show my location")
                }
                .padding(.horizontal, 14).padding(.top, 8)

            }
            .safeAreaInset(edge: .bottom) {
                if pinned.isEmpty && !store.loading {
                    // Bottom, not top: up there it covered the locate-me button.
                    Card {
                        Text("No places yet").font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                        Text("In Instagram, tap Share, then Afterscroll on a café, restaurant, trip or event reel. It shows up here as a pin.")
                            .font(.system(size: 14)).foregroundStyle(Theme.mute)
                    }
                    .padding(.horizontal, 14).padding(.bottom, 8)
                } else if let s = selected {
                    NavigationLink(value: s) {
                        Card {
                            Eyebrow(text: s.kind == .attend ? (s.details.eventDate?.formatted(.dateTime.weekday().day().month().hour().minute()) ?? "Event")
                                                            : (s.details.kind ?? "Place"), color: Theme.signal)
                            Text(s.name).font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
                            if let why = s.details.why ?? s.summary.nilIfEmpty {
                                Text(why).font(.system(size: 13)).foregroundStyle(Theme.mute).lineLimit(2)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 14).padding(.bottom, 8)
                }
            }
            .navigationDestination(for: Save.self) { SaveView(save: $0) }
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private var pinned: [Save] {
        store.mappable.filter { filter == nil || $0.kind == filter }.filter { store.pins[$0.id] != nil }
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

/// Asks for location only when the person taps "Show my location" — never on
/// launch. MapKit's own locate button asked as soon as the Map tab was built,
/// which is at app start, before anyone had looked at a map.
@MainActor
final class Locator: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var allowed = false

    override init() {
        super.init()
        manager.delegate = self
        allowed = Self.ok(manager.authorizationStatus)
    }

    func ask() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        let ok = Self.ok(m.authorizationStatus)
        Task { @MainActor in self.allowed = ok }
    }

    nonisolated private static func ok(_ s: CLAuthorizationStatus) -> Bool {
        s == .authorizedWhenInUse || s == .authorizedAlways
    }
}
