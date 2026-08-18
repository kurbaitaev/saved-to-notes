import SwiftUI

/// The edit-suite palette: near-black ground, warm paper text, one amber signal
/// borrowed from a level meter. Verbatim text is always monospaced — exact
/// wording is the thing this app exists to protect, so it should look exact.
enum Theme {
    static let ground = Color(red: 0.055, green: 0.067, blue: 0.075)   // #0E1113
    static let raise  = Color(red: 0.090, green: 0.106, blue: 0.118)   // #171B1E
    static let sunk   = Color(red: 0.063, green: 0.078, blue: 0.090)   // #101417
    static let line   = Color(red: 0.149, green: 0.173, blue: 0.192)   // #262C31
    static let hair   = Color(red: 0.118, green: 0.141, blue: 0.153)   // #1E2427
    static let ink    = Color(red: 0.914, green: 0.902, blue: 0.875)   // #E9E6DF
    static let mute   = Color(red: 0.545, green: 0.573, blue: 0.592)   // #8B9297
    static let signal = Color(red: 0.949, green: 0.757, blue: 0.306)   // #F2C14E
    static let ok     = Color(red: 0.388, green: 0.698, blue: 0.494)   // #63B27E

    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

/// Uppercase mono label used for every piece of metadata in the app.
struct Eyebrow: View {
    let text: String
    var color: Color = Theme.mute
    var body: some View {
        Text(text.uppercased())
            .font(Theme.mono(9.5))
            .tracking(1.3)
            .foregroundStyle(color)
    }
}
