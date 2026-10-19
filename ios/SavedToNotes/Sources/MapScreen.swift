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
                // Frame the pins at street level. .automatic zoomed one pin to
                // building level: no streets, no context, it looked broken.
                .onAppear { frame() }
                .onChange(of: pinned.map(\.id)) { _, _ in frame() }

                HStack(spacing: 6) {
                    // On a solid ground: over the map's street labels the
                    // outlined chips were hard to read.
                    Group {
                        Chip(label: "All", on: filter == nil) { filter = nil }
                        Chip(label: "Places \(store.of(.visit).count)", on: filter == .visit) { filter = .visit }
                        Chip(label: "Events \(store.of(.attend).count)", on: filter == .attend) { filter = .attend }
                    }
                    .background(Capsule().fill(Theme.ground.opacity(0.9)))
                    Spacer()
                    Button {
                        locator.ask()
                        withAnimation { camera = .userLocation(fallback: camera) }
                    } label: {
                        Image(systemName: locator.allowed ? "location.fill" : "location")
                            .font(Theme.text(16, .semibold)).foregroundStyle(Theme.signal)
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
                        Text("No places yet").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                        Text("In Instagram, tap Share, then Afterscroll on a café, restaurant, trip or event reel. It shows up here as a pin.")
                            .font(Theme.text(14)).foregroundStyle(Theme.mute)
                    }
                    .padding(.horizontal, 14).padding(.bottom, 8)
                } else if let s = selected {
                    VStack(spacing: 8) {
                    NavigationLink(value: s) {
                        Card {
                            Eyebrow(text: s.kind == .attend ? (s.details.eventDate?.formatted(.dateTime.weekday().day().month().hour().minute()) ?? "Event")
                                                            : (s.details.kind ?? "Place"), color: Theme.signal)
                            Text(s.name).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                            if let why = s.details.why ?? s.summary.nilIfEmpty {
                                Text(why).font(Theme.text(13)).foregroundStyle(Theme.mute).lineLimit(2)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    HStack(spacing: 8) {
                        PrimaryButton(label: "Directions", symbol: "arrow.triangle.turn.up.right.diamond") { directions(s) }
                        if let src = s.source {
                            Link(destination: src) {
                                Text("See the reel").font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                                    .padding(.horizontal, 16).frame(minHeight: 44)
                                    .overlay(Capsule().stroke(Theme.line))
                            }
                        }
                        Spacer()
                    }
                    }
                    .padding(.horizontal, 14).padding(.bottom, 8)
                }
            }
            .navigationDestination(for: Save.self) { SaveView(save: $0) }
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private func frame() {
        let coords = pinned.compactMap { store.pins[$0.id] }
        guard !coords.isEmpty else { return }
        let lats = coords.map(\.latitude), lons = coords.map(\.longitude)
        let center = CLLocationCoordinate2D(latitude: (lats.min()! + lats.max()!) / 2,
                                            longitude: (lons.min()! + lons.max()!) / 2)
        let span = MKCoordinateSpan(latitudeDelta: max(0.025, (lats.max()! - lats.min()!) * 1.6),
                                    longitudeDelta: max(0.025, (lons.max()! - lons.min()!) * 1.6))
        camera = .region(MKCoordinateRegion(center: center, span: span))
    }

    private func directions(_ s: Save) {
        guard let c = store.pins[s.id] else { return }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: c))
        item.name = s.name
        item.openInMaps()
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
