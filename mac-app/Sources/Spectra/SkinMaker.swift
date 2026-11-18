import SwiftUI
import AppKit

enum SkinTool: String, CaseIterable, Identifiable {
    case pencil = "Pencil", eraser = "Eraser", fill = "Fill", picker = "Picker"
    var id: String { rawValue }
}

/// A 64x64 RGBA skin being edited (same job as the Python app's skin maker).
@MainActor
final class SkinEditor: ObservableObject, Identifiable {
    let id = UUID()
    @Published var px: [UInt8]
    @Published var name: String
    @Published var slim: Bool
    @Published var tool: SkinTool = .pencil
    @Published var brush = 1
    @Published var color = Color(hex: 0x46e08a)
    @Published var showGuides = true
    @Published var showOverlay = true
    let entryID: String?
    private var undoStack: [[UInt8]] = []
    private var redoStack: [[UInt8]] = []

    init(px: [UInt8], name: String, slim: Bool, entryID: String?) {
        self.px = px.count == 64 * 64 * 4 ? px : [UInt8](repeating: 0, count: 64 * 64 * 4)
        self.name = name
        self.slim = slim
        self.entryID = entryID
    }

    // MARK: pixels

    static func loadPixels(_ path: String) -> [UInt8]? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let rep = NSBitmapImageRep(data: data), rep.pixelsWide == 64, rep.pixelsHigh == 64 else { return nil }
        var out = [UInt8](repeating: 0, count: 64 * 64 * 4)
        for y in 0..<64 {
            for x in 0..<64 {
                guard let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.sRGB) else { continue }
                let i = (y * 64 + x) * 4
                out[i] = UInt8(max(0, min(255, (c.redComponent * 255).rounded())))
                out[i + 1] = UInt8(max(0, min(255, (c.greenComponent * 255).rounded())))
                out[i + 2] = UInt8(max(0, min(255, (c.blueComponent * 255).rounded())))
                out[i + 3] = UInt8(max(0, min(255, (c.alphaComponent * 255).rounded())))
            }
        }
        return out
    }

    var cgImage: CGImage? {
        let data = Data(px) as CFData
        guard let provider = CGDataProvider(data: data) else { return nil }
        return CGImage(width: 64, height: 64, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 256,
                       space: CGColorSpace(name: CGColorSpace.sRGB)!,
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    }

    func pngData() -> Data? {
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 64, pixelsHigh: 64, bitsPerSample: 8,
                                         samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bitmapFormat: [.alphaNonpremultiplied],
                                         bytesPerRow: 256, bitsPerPixel: 32),
              let dst = rep.bitmapData else { return nil }
        _ = px.withUnsafeBytes { memcpy(dst, $0.baseAddress!, 64 * 64 * 4) }
        return rep.representation(using: .png, properties: [:])
    }

    private var rgba: [UInt8] {
        let c = NSColor(color).usingColorSpace(.sRGB) ?? .black
        return [UInt8(c.redComponent * 255), UInt8(c.greenComponent * 255), UInt8(c.blueComponent * 255), 255]
    }

    func beginStroke() {
        undoStack.append(px)
        if undoStack.count > 60 { undoStack.removeFirst() }
        redoStack.removeAll()
    }

    func undo() {
        guard let last = undoStack.popLast() else { return }
        redoStack.append(px)
        px = last
    }

    func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(px)
        px = next
    }

    private func put(_ x: Int, _ y: Int, _ c: [UInt8]) {
        guard (0..<64).contains(x), (0..<64).contains(y) else { return }
        let i = (y * 64 + x) * 4
        px[i] = c[0]; px[i + 1] = c[1]; px[i + 2] = c[2]; px[i + 3] = c[3]
    }

    private func get(_ x: Int, _ y: Int) -> [UInt8] {
        let i = (y * 64 + x) * 4
        return [px[i], px[i + 1], px[i + 2], px[i + 3]]
    }

    func apply(x: Int, y: Int, first: Bool) {
        guard (0..<64).contains(x), (0..<64).contains(y) else { return }
        switch tool {
        case .pencil, .eraser:
            let c: [UInt8] = tool == .eraser ? [0, 0, 0, 0] : rgba
            let half = (brush - 1) / 2
            for dy in 0..<brush {
                for dx in 0..<brush { put(x - half + dx, y - half + dy, c) }
            }
        case .fill:
            if first { flood(x, y, with: rgba) }
        case .picker:
            if first {
                let c = get(x, y)
                if c[3] > 0 {
                    color = Color(.sRGB, red: Double(c[0]) / 255, green: Double(c[1]) / 255, blue: Double(c[2]) / 255)
                    tool = .pencil
                }
            }
        }
    }

    private func flood(_ sx: Int, _ sy: Int, with c: [UInt8]) {
        let target = get(sx, sy)
        if target == c { return }
        var stack = [(sx, sy)]
        var next = px
        while let (x, y) = stack.popLast() {
            guard (0..<64).contains(x), (0..<64).contains(y) else { continue }
            let i = (y * 64 + x) * 4
            if Array(next[i..<i + 4]) != target { continue }
            next[i] = c[0]; next[i + 1] = c[1]; next[i + 2] = c[2]; next[i + 3] = c[3]
            stack.append((x + 1, y)); stack.append((x - 1, y)); stack.append((x, y + 1)); stack.append((x, y - 1))
        }
        px = next
    }
}

// MARK: - Canvas

struct SkinCanvas: View {
    @ObservedObject var ed: SkinEditor
    private let z: CGFloat = 9
    @State private var dragging = false

    var body: some View {
        Canvas { ctx, _ in
            // transparent checkerboard
            ctx.fill(Path(CGRect(x: 0, y: 0, width: 64 * z, height: 64 * z)), with: .color(Color(white: 0.30)))
            for y in 0..<64 {
                for x in 0..<64 where (x + y) % 2 == 0 {
                    ctx.fill(Path(CGRect(x: CGFloat(x) * z, y: CGFloat(y) * z, width: z, height: z)),
                             with: .color(Color(white: 0.36)))
                }
            }
            // pixels
            for y in 0..<64 {
                for x in 0..<64 {
                    let i = (y * 64 + x) * 4
                    let a = ed.px[i + 3]
                    if a == 0 { continue }
                    ctx.fill(Path(CGRect(x: CGFloat(x) * z, y: CGFloat(y) * z, width: z + 0.4, height: z + 0.4)),
                             with: .color(Color(.sRGB, red: Double(ed.px[i]) / 255, green: Double(ed.px[i + 1]) / 255,
                                                blue: Double(ed.px[i + 2]) / 255, opacity: Double(a) / 255)))
                }
            }
            if ed.showGuides { drawGuides(ctx) }
        }
        .frame(width: 64 * z, height: 64 * z)
        .overlay(Rectangle().strokeBorder(Color.white.opacity(0.25), lineWidth: 1))
        .gesture(DragGesture(minimumDistance: 0)
            .onChanged { v in
                let x = Int(v.location.x / z), y = Int(v.location.y / z)
                let first = !dragging
                if first { dragging = true; ed.beginStroke() }
                ed.apply(x: x, y: y, first: first)
            }
            .onEnded { _ in dragging = false })
    }

    /// Faint outlines of each body part's faces so you can see where things go.
    private func drawGuides(_ ctx: GraphicsContext) {
        let aw = ed.slim ? 3 : 4
        // (u, v, w, h, d)
        var boxes: [(Int, Int, Int, Int, Int)] = [(0, 0, 8, 8, 8), (16, 16, 8, 12, 4), (40, 16, aw, 12, 4),
                                                   (32, 48, aw, 12, 4), (0, 16, 4, 12, 4), (16, 48, 4, 12, 4)]
        if ed.showOverlay {
            boxes += [(32, 0, 8, 8, 8), (16, 32, 8, 12, 4), (40, 32, aw, 12, 4),
                      (48, 48, aw, 12, 4), (0, 32, 4, 12, 4), (0, 48, 4, 12, 4)]
        }
        for (u, v, w, h, d) in boxes {
            let faces: [(Int, Int, Int, Int)] = [(u + d, v, w, d), (u + d + w, v, w, d), (u, v + d, d, h),
                                                  (u + d, v + d, w, h), (u + d + w, v + d, d, h), (u + 2 * d + w, v + d, w, h)]
            for (fx, fy, fw, fh) in faces {
                ctx.stroke(Path(CGRect(x: CGFloat(fx) * z, y: CGFloat(fy) * z, width: CGFloat(fw) * z, height: CGFloat(fh) * z)),
                           with: .color(Color.white.opacity(0.35)), lineWidth: 0.8)
            }
        }
    }
}

// MARK: - Editor sheet

struct SkinMakerView: View {
    @EnvironmentObject var store: Store
    @ObservedObject var ed: SkinEditor
    @Environment(\.dismiss) private var dismiss

    private let palette: [UInt32] = [0x000000, 0x3a3a3a, 0x7a7a7a, 0xbdbdbd, 0xffffff, 0x7b4a2a, 0xc98b62, 0xf1c7a4,
                                     0xff5d73, 0xff8a3d, 0xffd23d, 0x46e08a, 0x2cc7b5, 0x38a8ff, 0x5b6cff, 0xa66bff,
                                     0xe05cc0, 0x8a1f2d, 0x1f6b3a, 0x1f3a8a]

    var body: some View {
        HStack(alignment: .top, spacing: 20) {
            controls.frame(width: 240)
            VStack(spacing: 10) {
                SkinCanvas(ed: ed)
                Text("Paint on the flat skin. Outlines show where each part goes.")
                    .font(.caption).foregroundStyle(T.dim)
            }
            preview.frame(width: 190)
        }
        .padding(24)
        .environment(\.colorScheme, .dark)
        .background(AppBackground())
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Skin maker").font(.system(size: 24, weight: .bold))
            FieldLabel(text: "Name")
            TextField("Name", text: $ed.name).textFieldStyle(.roundedBorder)
            Picker("Arms", selection: $ed.slim) {
                Text("Classic").tag(false)
                Text("Slim").tag(true)
            }
            .pickerStyle(.segmented)

            FieldLabel(text: "Tool")
            Picker("", selection: $ed.tool) {
                ForEach(SkinTool.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).labelsHidden()

            FieldLabel(text: "Brush size")
            Picker("", selection: $ed.brush) {
                ForEach(1...4, id: \.self) { Text("\($0)").tag($0) }
            }
            .pickerStyle(.segmented).labelsHidden()

            FieldLabel(text: "Colour")
            LazyVGrid(columns: Array(repeating: GridItem(.fixed(30), spacing: 6), count: 6), spacing: 6) {
                ForEach(palette, id: \.self) { hex in
                    Button { ed.color = Color(hex: hex); ed.tool = ed.tool == .picker ? .pencil : ed.tool } label: {
                        RoundedRectangle(cornerRadius: 6).fill(Color(hex: hex)).frame(width: 30, height: 30)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.white.opacity(0.4), lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
            }
            ColorPicker("Custom colour", selection: $ed.color, supportsOpacity: false)

            Toggle("Show guides", isOn: $ed.showGuides)
            Toggle("Show outer layer guides", isOn: $ed.showOverlay).disabled(!ed.showGuides)

            HStack {
                Button { ed.undo() } label: { Label("Undo", systemImage: "arrow.uturn.backward") }
                    .glassButton().keyboardShortcut("z", modifiers: .command)
                Button { ed.redo() } label: { Label("Redo", systemImage: "arrow.uturn.forward") }
                    .glassButton().keyboardShortcut("z", modifiers: [.command, .shift])
            }
            Spacer(minLength: 0)
            HStack {
                Button("Cancel") { dismiss() }.glassButton().keyboardShortcut(.cancelAction)
                Button("Save to library") { save() }.glassButton(prominent: true)
                    .disabled(ed.name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private var preview: some View {
        VStack(spacing: 14) {
            FieldLabel(text: "Preview")
            SkinFront(image: ed.cgImage, slim: ed.slim, back: false, scale: 6)
            SkinFront(image: ed.cgImage, slim: ed.slim, back: true, scale: 6)
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxHeight: .infinity)
        .glass(cornerRadius: 20)
    }

    private func save() {
        guard let data = ed.pngData() else { return }
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("spectra-skin-\(UUID().uuidString).png")
        do { try data.write(to: tmp) } catch { store.errorMessage = error.localizedDescription; return }
        Task {
            let ok = await store.saveSkin(path: tmp.path, name: ed.name, slim: ed.slim, id: ed.entryID)
            try? FileManager.default.removeItem(at: tmp)
            if ok { dismiss() }
        }
    }
}
