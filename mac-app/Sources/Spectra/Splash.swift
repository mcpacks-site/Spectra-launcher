import SwiftUI
import AppKit

// MARK: - helpers

private func clamp01(_ x: Double) -> Double { max(0, min(1, x)) }
private func ease(_ x: Double) -> Double { let t = clamp01(x); return t * t * (3 - 2 * t) }
private func prog(_ t: Double, _ a: Double, _ b: Double) -> Double { clamp01((t - a) / (b - a)) }

private func mixHex(_ a: UInt32, _ b: UInt32, _ t: Double) -> UInt32 {
    let k = clamp01(t)
    func ch(_ s: UInt32) -> (Double, Double, Double) {
        (Double((s >> 16) & 255), Double((s >> 8) & 255), Double(s & 255))
    }
    let (r1, g1, b1) = ch(a), (r2, g2, b2) = ch(b)
    let r = UInt32((r1 + (r2 - r1) * k).rounded()), g = UInt32((g1 + (g2 - g1) * k).rounded()), bl = UInt32((b1 + (b2 - b1) * k).rounded())
    return (r << 16) | (g << 8) | bl
}

private func mixColor(_ a: UInt32, _ b: UInt32, _ t: Double) -> Color { Color(hex: mixHex(a, b, t)) }

private let splashBG: UInt32 = 0x100a1f

/// The pixel-art sunset (same recipe as the Python app's intro and outro).
private struct SunsetScene {
    struct Box { var rect: CGRect; var color: UInt32 }
    var sky: [Box] = []
    var stars: [Box] = []
    var sun: [Box] = []
    var clouds: [Box] = []
    var land: [Box] = []        // hills, ground, trees (drawn over the sun)

    init(_ W: CGFloat, _ H: CGFloat) {
        var rnd = SeededRNG(seed: 7)
        let B = max(6, Int((W / 150).rounded()))
        let hy = Int(H * 0.72) / B * B
        let stops: [(Double, UInt32)] = [(0.0, 0x0e0820), (0.35, 0x241049), (0.62, 0x6b2b86), (0.83, 0xd04f7e), (1.0, 0xff9b5c)]
        func skyAt(_ p: Double) -> UInt32 {
            for i in 0..<(stops.count - 1) where p <= stops[i + 1].0 {
                return mixHex(stops[i].1, stops[i + 1].1, (p - stops[i].0) / (stops[i + 1].0 - stops[i].0))
            }
            return stops[stops.count - 1].1
        }
        let n = 28
        for i in 0..<n {
            sky.append(Box(rect: CGRect(x: 0, y: CGFloat(i * hy / n), width: W, height: CGFloat(hy / n + 2)),
                           color: skyAt((Double(i) + 0.5) / Double(n))))
        }
        for _ in 0..<46 {
            let x = CGFloat.random(in: 0..<W, using: &rnd), y = CGFloat.random(in: 0..<CGFloat(Double(hy) * 0.5), using: &rnd)
            stars.append(Box(rect: CGRect(x: x, y: y, width: 2, height: 2),
                             color: mixHex(0x0e0820, 0xcdbdff, Double.random(in: 0.4...1, using: &rnd))))
        }
        let R = Int(H * 0.15)
        let cx = Int(W * 0.76) / B * B, cy = hy - Int(Double(R) * 0.2)
        var y = cy - R
        while y < hy {
            let dy = Double(y) + Double(B) / 2 - Double(cy)
            let skip = abs(dy) > Double(R) || (dy > Double(R) * 0.15 && (y / B) % 3 == 0)
            if !skip {
                let half = Int(sqrt(Double(R * R) - dy * dy)) / B * B
                if half > 0 {
                    sun.append(Box(rect: CGRect(x: cx - half, y: y, width: 2 * half, height: B),
                                   color: mixHex(0xfff1a6, 0xff8a4a, Double(y - (cy - R)) / (2.0 * Double(R)))))
                }
            }
            y += B
        }
        for k in 0..<6 {
            let yy = Int(Double(hy) * (0.36 + Double(k) * 0.075)) / B * B
            let x = Int.random(in: 0..<max(1, Int(W) - 24 * B), using: &rnd) / B * B
            clouds.append(Box(rect: CGRect(x: x, y: yy, width: Int.random(in: 8...22, using: &rnd) * B, height: B / 2 + 2),
                              color: mixHex(skyAt(Double(yy) / Double(hy)), 0xffb0d0, 0.38)))
        }
        for (base, col, amp) in [(0.05, UInt32(0x2a1048), 3), (0.02, UInt32(0x150a2a), 2)] {
            var h = Int(Double(H) * base) / B
            var x = 0
            while x < Int(W) {
                h = max(1, min(Int(Double(H) * 0.14) / B, h + Int.random(in: -amp...amp, using: &rnd)))
                land.append(Box(rect: CGRect(x: x, y: hy - h * B + Int(Double(H) * 0.04), width: 4 * B, height: Int(H)), color: col))
                x += 4 * B
            }
        }
        let gy = hy + Int(Double(H) * 0.04)
        land.append(Box(rect: CGRect(x: 0, y: CGFloat(gy), width: W, height: H), color: 0x12081f))
        for _ in 0..<9 {
            let x = Int.random(in: 0..<Int(W), using: &rnd) / B * B
            let h = Int.random(in: 3...6, using: &rnd)
            land.append(Box(rect: CGRect(x: x, y: gy - h * B, width: B, height: h * B + 1), color: 0x0b0614))
            land.append(Box(rect: CGRect(x: x - B, y: gy - h * B + B, width: 3 * B, height: h * B - 2 * B), color: 0x0b0614))
        }
    }
}

// MARK: - the view

struct SplashView: View {
    enum Kind { case intro, outro }
    let kind: Kind
    let onDone: () -> Void

    @State private var start = Date()
    @State private var finished = false
    @State private var monitor: Any?

    private var total: Double { kind == .intro ? 3.6 : 2.85 }

    var body: some View {
        GeometryReader { geo in
            TimelineView(.animation) { tl in
                let t = tl.date.timeIntervalSince(start)
                Canvas { ctx, size in draw(ctx, size, t) }
                    .offset(y: slide(t, geo.size.height))
            }
        }
        .ignoresSafeArea()
        .contentShape(Rectangle())
        .onTapGesture { finish() }
        .onAppear {
            start = Date()
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { _ in finish(); return nil }
        }
        .onDisappear { if let m = monitor { NSEvent.removeMonitor(m) }; monitor = nil }
        .task {
            try? await Task.sleep(nanoseconds: UInt64(total * 1_000_000_000))
            finish()
        }
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        onDone()
    }

    private func slide(_ t: Double, _ H: CGFloat) -> CGFloat {
        switch kind {
        case .intro: return -H * CGFloat(ease(prog(t, 3.1, 3.6)))
        case .outro: return -H * CGFloat(1.0 - ease(prog(t, 0.0, 0.55)))
        }
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize, _ t: Double) {
        let W = size.width, H = size.height
        guard W > 50, H > 50 else { return }
        ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(hex: splashBG)))
        let scene = SunsetScene(W, H)

        var sceneK = 0.0, sunK = 0.0, sunDy: CGFloat = 0, wordAlpha = 1.0
        var letterAlpha: (Int) -> Double
        var tagAlpha = 0.0

        switch kind {
        case .intro:
            let sIn = ease(prog(t, 1.7, 2.6)), sOut = ease(prog(t, 2.6, 3.1))
            sceneK = sIn; sunK = sIn
            sunDy = CGFloat((1 - sIn) * Double(H) * 0.10)
            wordAlpha = 1.0 - 0.55 * sIn - 0.45 * sOut
            letterAlpha = { i in ease(prog(t, 0.25 + Double(i) * 0.07, 0.25 + Double(i) * 0.07 + 0.32)) * wordAlpha }
        case .outro:
            let sett = ease(prog(t, 0.55, 1.55)), fade = ease(prog(t, 2.35, 2.85))
            sceneK = (1.0 - 0.55 * sett) * (1.0 - fade)
            sunK = (1.0 - 0.5 * sett) * (1.0 - fade)
            sunDy = CGFloat(sett * Double(H) * 0.22)
            let wa = ease(prog(t, 0.85, 1.35)) * (1.0 - fade)
            letterAlpha = { _ in wa }
            tagAlpha = ease(prog(t, 1.35, 1.85)) * (1.0 - fade)
        }

        func fill(_ boxes: [SunsetScene.Box], _ k: Double, dy: CGFloat = 0) {
            guard k > 0.001 else { return }
            for b in boxes {
                ctx.fill(Path(b.rect.offsetBy(dx: 0, dy: dy)), with: .color(mixColor(splashBG, b.color, k)))
            }
        }
        if sceneK > 0.001 {
            fill(scene.sky, sceneK)
            fill(scene.stars, sceneK)
            fill(scene.sun, sunK, dy: sunDy)
            fill(scene.clouds, sceneK)
            fill(scene.land, sceneK)
        }

        // wordmark
        let word = Array("SPECTRA")
        let font = Font.system(size: 54, weight: .bold)
        let gap: CGFloat = 14
        let widths: [CGFloat] = word.map { c in
            ctx.resolve(Text(String(c)).font(font)).measure(in: CGSize(width: 200, height: 200)).width
        }
        var x = (W - (widths.reduce(0, +) + gap * CGFloat(word.count - 1))) / 2
        let y = H * 0.40
        for (i, c) in word.enumerated() {
            let a = letterAlpha(i)
            let text = Text(String(c)).font(font).foregroundColor(mixColor(splashBG, 0xffffff, a))
            ctx.draw(text, at: CGPoint(x: x + widths[i] / 2, y: y), anchor: .center)
            x += widths[i] + gap
        }
        if kind == .outro {
            let tag = Text("See you next time").font(.system(size: 15, weight: .bold))
                .foregroundColor(mixColor(splashBG, 0xffd9a8, tagAlpha))
            ctx.draw(tag, at: CGPoint(x: W / 2, y: y + 62), anchor: .center)
        }
    }
}

// MARK: - closing the window plays the outro

@MainActor
final class CloseInterceptor: NSObject, NSWindowDelegate {
    var original: NSWindowDelegate?
    let shouldClose: () -> Bool

    init(original: NSWindowDelegate?, shouldClose: @escaping () -> Bool) {
        self.original = original
        self.shouldClose = shouldClose
    }

    override func responds(to aSelector: Selector!) -> Bool {
        super.responds(to: aSelector) || (original?.responds(to: aSelector) ?? false)
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? { original }

    func windowShouldClose(_ sender: NSWindow) -> Bool { shouldClose() }
}

struct WindowAccessor: NSViewRepresentable {
    let onWindow: (NSWindow) -> Void
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { if let w = v.window { onWindow(w) } }
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
}
