import MapKit
import SwiftUI

/// Saved places and events as pins. Places are amber, events are green.
struct MapScreen: View {
    @EnvironmentObject var store: Store
    @State private var filter: Kind?
    @State private var selected: Save?
    @State private var camera: MapCameraPosition = .automatic
    @State private var location = CLLocationManager()

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Map(position: $camera, selection: Binding(
                    get: { selected?.id },
                    set: { id in selected = store.saves.first { $0.id == id } })) {
                    UserAnnotation()
                    ForEach(pinned) { s in
                        if let c = store.pins[s.id] {
                            Marker(s.name, systemImage: s.kind.symbol, coordinate: c)
                                .tint(s.kind == .attend ? Theme.ok : Theme.signal)
                                .tag(s.id)
                        }
                    }
                }
                .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
                .mapControls { MapUserLocationButton() }
                .preferredColorScheme(.dark)

                HStack(spacing: 6) {
                    Chip(label: "All", on: filter == nil) { filter = nil }
                    Chip(label: "Places \(store.of(.visit).count)", on: filter == .visit) { filter = .visit }
                    Chip(label: "Events \(store.of(.attend).count)", on: filter == .attend) { filter = .attend }
                    Spacer()
                }
                .padding(.horizontal, 14).padding(.top, 8)

                if pinned.isEmpty && !store.loading {
                    Card {
                        Text("No places yet").font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                        Text("Save a reel about a café, restaurant, spot, trip or event. It shows up here as a pin.")
                            .font(.system(size: 13)).foregroundStyle(Theme.mute)
                    }
                    .padding(.horizontal, 14).padding(.top, 52)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if let s = selected {
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
        .task { location.requestWhenInUseAuthorization() }
    }

    private var pinned: [Save] {
        store.mappable.filter { filter == nil || $0.kind == filter }.filter { store.pins[$0.id] != nil }
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
