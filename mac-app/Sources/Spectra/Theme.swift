import SwiftUI

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: opacity)
    }
}

/// Accent + theme chosen in Settings (same options as the Python app).
enum Palette {
    static var accent1: UInt32 = 0x4fe39a
    static var accent2: UInt32 = 0x2fc9d4
    static var light = false
    static var glassOn = true
    static let accents: [(key: String, a1: UInt32, a2: UInt32)] = [
        ("green", 0x4fe39a, 0x2fc9d4), ("blue", 0x4aa3ff, 0x4a6cff), ("purple", 0xb07bff, 0x7a5cff),
        ("pink", 0xff6fa8, 0xff5d73), ("orange", 0xffa94d, 0xff7a3d)]

    static func apply(accent: String, theme: String) {
        if let a = accents.first(where: { $0.key == accent }) { accent1 = a.a1; accent2 = a.a2 }
        light = theme == "light"
    }
}

enum T {
    static var bg: Color { Color(hex: Palette.light ? 0xf6f4fb : 0x100a1f) }
    static var accent: Color { Color(hex: Palette.accent1) }
    static var accent2: Color { Color(hex: Palette.accent2) }
    static var card: Color { Color(hex: Palette.light ? 0xffffff : 0x1b1529) }
    static var line: Color { Color(hex: Palette.light ? 0xe4def1 : 0x363143) }
    static let ink = Color(hex: 0x07140e)
    static let warn = Color(hex: 0xffc15a)
    static var dim: Color { Color.primary.opacity(0.62) }
    static var gradient: LinearGradient {
        LinearGradient(colors: [accent, accent2], startPoint: .leading, endPoint: .trailing)
    }
}

struct SeededRNG: RandomNumberGenerator {
    var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

/// The starry sunset-city banner from the Python app's home page.
struct SkyArt: View {
    var body: some View {
        Canvas { ctx, size in
            let w = size.width, h = size.height
            // sky
            ctx.fill(Path(CGRect(origin: .zero, size: size)),
                     with: .linearGradient(Gradient(stops: [
                        .init(color: Color(hex: 0x120a2e), location: 0),
                        .init(color: Color(hex: 0x2c1250), location: 0.35),
                        .init(color: Color(hex: 0x7a2b6e), location: 0.62),
                        .init(color: Color(hex: 0xe0685a), location: 0.85),
                        .init(color: Color(hex: 0xf59a5a), location: 1)]),
                        startPoint: .zero, endPoint: CGPoint(x: 0, y: h)))
            // stars
            var rng = SeededRNG(seed: 11)
            for _ in 0..<90 {
                let x = CGFloat.random(in: 0...w, using: &rng)
                let y = CGFloat.random(in: 0...(h * 0.55), using: &rng)
                let r = CGFloat.random(in: 0.5...1.5, using: &rng)
                let a = Double.random(in: 0.25...0.9, using: &rng)
                ctx.fill(Path(ellipseIn: CGRect(x: x, y: y, width: r * 2, height: r * 2)),
                         with: .color(.white.opacity(a)))
            }
            // sun and rings
            let c = CGPoint(x: w * 0.8, y: h * 0.86)
            for (rad, op) in [(210.0, 0.10), (165.0, 0.16), (125.0, 0.24)] {
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - rad, y: c.y - rad, width: rad * 2, height: rad * 2)),
                         with: .color(Color(hex: 0xff9a7a, opacity: op)))
            }
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 80, y: c.y - 80, width: 160, height: 160)),
                     with: .linearGradient(Gradient(colors: [Color(hex: 0xffd27a), Color(hex: 0xffa65a)]),
                                           startPoint: CGPoint(x: c.x, y: c.y - 80),
                                           endPoint: CGPoint(x: c.x, y: c.y + 80)))
            // skyline: a brown back row, then the dark front row with lit windows
            var back = SeededRNG(seed: 3)
            var bx: CGFloat = -10
            while bx < w {
                let bw = CGFloat.random(in: 40...80, using: &back)
                let bh = CGFloat.random(in: 50...(h * 0.42), using: &back)
                ctx.fill(Path(CGRect(x: bx, y: h - bh, width: bw + 1, height: bh)),
                         with: .color(Color(hex: 0x7c4a48)))
                bx += bw
            }
            var x: CGFloat = -10
            var b = SeededRNG(seed: 5)
            while x < w {
                let bw = CGFloat.random(in: 30...64, using: &b)
                let bh = CGFloat.random(in: 26...(h * 0.26), using: &b)
                let rect = CGRect(x: x, y: h - bh, width: bw + 1, height: bh)
                ctx.fill(Path(rect), with: .color(Color(hex: 0x120d1e)))
                var wy = rect.minY + 8
                while wy < h - 10 {
                    var wx = rect.minX + 6
                    while wx < rect.maxX - 8 {
                        if Int.random(in: 0..<5, using: &b) == 0 {
                            ctx.fill(Path(CGRect(x: wx, y: wy, width: 3, height: 4)),
                                     with: .color(Color(hex: 0xffc15a, opacity: 0.9)))
                        }
                        wx += 11
                    }
                    wy += 14
                }
                x += bw
            }
            ctx.fill(Path(CGRect(x: 0, y: h - 12, width: w, height: 12)), with: .color(Color(hex: 0x120d1e)))
        }
    }
}

/// Little Steve-style face for the account chip (same idea as the Python app's generated avatar).
struct SteveFace: View {
    var size: CGFloat = 34
    private let rows: [[UInt32]] = {
        let h: UInt32 = 0x3b2a1a, s: UInt32 = 0xc98f6b, d: UInt32 = 0xa8704f, e: UInt32 = 0xffffff, i: UInt32 = 0x4a3bb5, m: UInt32 = 0x7a4a33
        return [[h,h,h,h,h,h,h,h],[h,h,h,h,h,h,h,h],[h,s,s,s,s,s,s,h],[s,s,s,s,s,s,s,s],
                [s,e,i,s,s,i,e,s],[s,s,s,d,d,s,s,s],[s,s,m,m,m,m,s,s],[s,s,s,s,s,s,s,s]]
    }()
    var body: some View {
        Canvas { ctx, sz in
            let c = sz.width / 8
            for (y, row) in rows.enumerated() {
                for (x, col) in row.enumerated() {
                    ctx.fill(Path(CGRect(x: CGFloat(x) * c, y: CGFloat(y) * c, width: c + 0.5, height: c + 0.5)),
                             with: .color(Color(hex: col)))
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.2, style: .continuous))
    }
}

struct SpectraLogo: View {
    var size: CGFloat = 30
    var body: some View {
        ZStack {
            Triangle().fill(AngularGradient(colors: [Color(hex: 0xff6b8a), Color(hex: 0xffc15a), T.accent, T.accent2, Color(hex: 0x8a6bff), Color(hex: 0xff6b8a)],
                                            center: .center))
            Triangle().fill(Color.black.opacity(0.55)).scaleEffect(0.45).offset(y: size * 0.07)
        }
        .frame(width: size, height: size)
    }
}

struct Triangle: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.midX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.maxY))
        p.addLine(to: CGPoint(x: r.minX, y: r.maxY))
        p.closeSubpath()
        return p
    }
}
