import SwiftUI

/// Everything that isn't a workout or a pin: things to get, recipes, events
/// (by date) and places (by city).
struct ListsView: View {
    @EnvironmentObject var store: Store
    @State private var tab: Kind = .buy

    var body: some View {
        Screen(title: "Lists") {
            Picker("List", selection: $tab) {
                Text("To get").tag(Kind.buy)
                Text("Recipes").tag(Kind.cook)
                Text("Events").tag(Kind.attend)
                Text("Places").tag(Kind.visit)
            }
            .pickerStyle(.segmented)

            let items = store.of(tab)
            if items.isEmpty {
                EmptyState(symbol: tab.symbol, title: emptyTitle, hint: emptyHint)
            } else {
                switch tab {
                case .buy:
                    ForEach(items.sorted { !store.isDone($0) && store.isDone($1) }) { s in
                        HStack(spacing: 12) {
                            Button { store.toggleDone(s) } label: {
                                Image(systemName: store.isDone(s) ? "checkmark.circle.fill" : "circle")
                                    .font(.system(size: 20)).foregroundStyle(store.isDone(s) ? Theme.ok : Theme.mute)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(store.isDone(s) ? "Mark as not bought" : "Mark as bought")
                            NavigationLink(value: s) { BuyRow(save: s) }.buttonStyle(.plain)
                        }
                        .opacity(store.isDone(s) ? 0.5 : 1)
                    }
                case .attend:
                    ForEach(items.sorted { ($0.details.eventDate ?? .distantFuture) < ($1.details.eventDate ?? .distantFuture) }) { s in
                        NavigationLink(value: s) { EventRow(save: s) }.buttonStyle(.plain)
                    }
                case .visit:
                    let byCity = Dictionary(grouping: items) { $0.details.city ?? "Somewhere" }
                    ForEach(byCity.keys.sorted(), id: \.self) { city in
                        Eyebrow(text: city).padding(.top, 8)
                        ForEach(byCity[city]!) { s in
                            NavigationLink(value: s) { PlaceRow(save: s) }.buttonStyle(.plain)
                        }
                    }
                default:
                    ForEach(items) { s in
                        NavigationLink(value: s) { RecipeRow(save: s) }.buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var emptyTitle: String {
        switch tab {
        case .buy: "Nothing to get"
        case .cook: "No recipes yet"
        case .attend: "No events yet"
        default: "No places yet"
        }
    }
    private var emptyHint: String {
        switch tab {
        case .buy: "Products and gear you save land here as a list you can tick off."
        case .cook: "Save a recipe reel. You get the ingredients and steps in cook mode."
        case .attend: "Save a reel about a meetup, concert or fight night. It shows here by date."
        default: "Cafés, restaurants and spots you save, grouped by city."
        }
    }
}

// MARK: - Rows (shared with Today)

struct RowShell<Lead: View>: View {
    @ViewBuilder let lead: Lead
    let title: String
    let sub: String
    var body: some View {
        HStack(spacing: 12) {
            lead
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.ink).lineLimit(2)
                if !sub.isEmpty { Text(sub).font(.system(size: 13)).foregroundStyle(Theme.mute).lineLimit(2) }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.line)
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.hair).frame(height: 1) }
        .contentShape(Rectangle())
    }
}

struct Badge: View {
    let symbol: String
    var body: some View {
        Image(systemName: symbol).font(.system(size: 15)).foregroundStyle(Theme.signal)
            .frame(width: 38, height: 38)
            .background(RoundedRectangle(cornerRadius: 10).fill(Theme.raise))
    }
}

struct EventRow: View {
    let save: Save
    var body: some View {
        RowShell(lead: { DateBadge(date: save.details.eventDate) }, title: save.name,
                 sub: [save.details.time, save.details.whereLine.nilIfEmpty].compactMap { $0 }.joined(separator: " · "))
    }
}

struct DateBadge: View {
    let date: Date?
    var body: some View {
        VStack(spacing: 1) {
            Text(date?.formatted(.dateTime.month(.abbreviated)).uppercased() ?? "TBA")
                .font(Theme.mono(8.5, .medium)).foregroundStyle(Theme.signal)
            Text(date?.formatted(.dateTime.day()) ?? "–")
                .font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.ink)
        }
        .frame(width: 38, height: 38)
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.raise))
    }
}

struct PlaceRow: View {
    let save: Save
    var body: some View {
        RowShell(lead: { Badge(symbol: Kind.visit.symbol) }, title: save.name,
                 sub: [save.details.kind?.capitalized, save.details.why ?? save.summary.nilIfEmpty].compactMap { $0 }.joined(separator: " · "))
    }
}

struct BuyRow: View {
    let save: Save
    var body: some View {
        RowShell(lead: { Badge(symbol: Kind.buy.symbol) }, title: save.name,
                 sub: [save.details.brand, save.details.price].compactMap { $0 }.joined(separator: " · "))
    }
}

struct RecipeRow: View {
    let save: Save
    var body: some View {
        RowShell(lead: { Badge(symbol: Kind.cook.symbol) }, title: save.name,
                 sub: [save.details.minutes.map { "\($0) min" }, save.details.ingredients.map { "\($0.count) ingredients" }]
                    .compactMap { $0 }.joined(separator: " · "))
    }
}
