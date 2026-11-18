import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - Skin drawing (cropped from the real texture)

func loadCGImage(_ path: String) -> CGImage? {
    NSImage(contentsOfFile: path)?.cgImage(forProposedRect: nil, context: nil, hints: nil)
}

private typealias SkinPart = (sx: Int, sy: Int, w: Int, h: Int, dx: CGFloat, dy: CGFloat)

private func skinParts(modern: Bool, slim: Bool, back: Bool) -> [SkinPart] {
    let aw = slim ? 3 : 4
    let ax: CGFloat = slim ? 1 : 0
    var p: [SkinPart] = []
    if !back {
        p = [(8, 8, 8, 8, 4, 0), (20, 20, 8, 12, 4, 8), (44, 20, aw, 12, ax, 8),
             modern ? (36, 52, aw, 12, 12, 8) : (44, 20, aw, 12, 12, 8),
             (4, 20, 4, 12, 4, 20), modern ? (20, 52, 4, 12, 8, 20) : (4, 20, 4, 12, 8, 20)]
        if modern {
            p += [(40, 8, 8, 8, 4, 0), (20, 36, 8, 12, 4, 8), (44, 36, aw, 12, ax, 8),
                  (52, 52, aw, 12, 12, 8), (4, 36, 4, 12, 4, 20), (4, 52, 4, 12, 8, 20)]
        }
    } else {
        p = [(24, 8, 8, 8, 4, 0), (32, 20, 8, 12, 4, 8),
             modern ? (40 + aw, 52, aw, 12, ax, 8) : (48 + aw, 20, aw, 12, ax, 8),
             (48 + aw, 20, aw, 12, 12, 8),
             modern ? (28, 52, 4, 12, 4, 20) : (12, 20, 4, 12, 4, 20), (12, 20, 4, 12, 8, 20)]
        if modern {
            p += [(56, 8, 8, 8, 4, 0), (32, 36, 8, 12, 4, 8), (56 + aw, 52, aw, 12, ax, 8),
                  (48 + aw, 36, aw, 12, 12, 8), (12, 52, 4, 12, 4, 20), (12, 36, 4, 12, 8, 20)]
        }
    }
    return p
}

struct SkinFront: View {
    let image: CGImage?
    let slim: Bool
    var back = false
    var scale: CGFloat = 8

    init(path: String, slim: Bool, back: Bool = false, scale: CGFloat = 8) {
        self.image = loadCGImage(path)
        self.slim = slim; self.back = back; self.scale = scale
    }

    init(image: CGImage?, slim: Bool, back: Bool = false, scale: CGFloat = 8) {
        self.image = image
        self.slim = slim; self.back = back; self.scale = scale
    }

    var body: some View {
        if let cg = image {
            let parts = skinParts(modern: cg.height >= 64, slim: slim, back: back)
            Canvas { ctx, _ in
                for p in parts {
                    guard let c = cg.cropping(to: CGRect(x: p.sx, y: p.sy, width: p.w, height: p.h)) else { continue }
                    ctx.draw(Image(decorative: c, scale: 1).interpolation(.none),
                             in: CGRect(x: p.dx * scale, y: p.dy * scale, width: CGFloat(p.w) * scale, height: CGFloat(p.h) * scale))
                }
            }
            .frame(width: 16 * scale, height: 32 * scale)
        } else {
            Rectangle().fill(Color.primary.opacity(0.08)).frame(width: 16 * scale, height: 32 * scale)
        }
    }
}

/// Just the face, for tiles.
struct SkinHead: View {
    let path: String
    var size: CGFloat = 56
    var body: some View {
        if let cg = loadCGImage(path) {
            Canvas { ctx, _ in
                for (sx, sy) in [(8, 8), (40, 8)] where sy + 8 <= cg.height {
                    if let c = cg.cropping(to: CGRect(x: sx, y: sy, width: 8, height: 8)) {
                        ctx.draw(Image(decorative: c, scale: 1).interpolation(.none),
                                 in: CGRect(x: 0, y: 0, width: size, height: size))
                    }
                }
            }
            .frame(width: size, height: size)
        } else {
            Rectangle().fill(Color.primary.opacity(0.08)).frame(width: size, height: size)
        }
    }
}

struct CapeFront: View {
    let path: String
    var scale: CGFloat = 6
    var body: some View {
        if let cg = loadCGImage(path), let c = cg.cropping(to: CGRect(x: 1, y: 1, width: 10, height: 16)) {
            Image(decorative: c, scale: 1).interpolation(.none).resizable()
                .frame(width: 10 * scale, height: 16 * scale)
        } else {
            Rectangle().fill(Color.primary.opacity(0.08)).frame(width: 10 * scale, height: 16 * scale)
        }
    }
}

// MARK: - Skins page

struct SkinsView: View {
    @EnvironmentObject var store: Store
    @State private var selection = "account"
    @State private var back = false

    private var selectedSaved: SavedSkin? { store.library.first { $0.id == selection } }
    private var previewPath: String? { selectedSaved?.path ?? store.skin?.path }
    private var previewSlim: Bool { selectedSaved?.slim ?? store.skin?.slim ?? false }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("WARDROBE").font(.system(size: 12, weight: .bold)).tracking(1).foregroundStyle(T.accent)
                        Text("Skins").font(.system(size: 40, weight: .bold))
                        Text("Change your look. Upload a PNG or design one in the skin maker.").foregroundStyle(T.dim)
                    }
                    Spacer()
                    GlassGroup(spacing: 10) {
                        HStack(spacing: 10) {
                            Button("Upload PNG") { pickFile() }.glassButton().controlSize(.large)
                            Button("Skin maker") { store.openSkinMaker(from: nil) }.glassButton(prominent: true).controlSize(.large)
                        }
                    }
                }

                if store.account == nil {
                    VStack(spacing: 12) {
                        Text("Sign in to change your skin and cape.").font(.headline)
                        Button("Sign in with Microsoft") { store.startSignIn() }.glassButton(prominent: true)
                    }
                    .frame(maxWidth: .infinity).padding(40).glass(cornerRadius: 24)
                } else {
                    HStack(alignment: .top, spacing: 14) {
                        previewCard
                        VStack(alignment: .leading, spacing: 18) {
                            mySkins
                            myCapes
                        }
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }
            }
            .padding(4)
        }
        .task(id: store.account?.id ?? "") {
            await store.loadSkin()
            await store.loadLibrary()
        }
    }

    // MARK: pieces

    private var previewCard: some View {
        VStack(spacing: 12) {
            Picker("", selection: $back) {
                Text("Front").tag(false)
                Text("Back").tag(true)
            }
            .pickerStyle(.segmented).labelsHidden().frame(width: 150)
            if let path = previewPath {
                SkinFront(path: path, slim: previewSlim, back: back, scale: 9).id("\(path)|\(back)|\(store.skin?.stamp.timeIntervalSince1970 ?? 0)")
            } else if store.skinLoading {
                ProgressView().frame(width: 144, height: 288)
            } else {
                Rectangle().fill(Color.primary.opacity(0.06)).frame(width: 144, height: 288)
            }
            VStack(spacing: 2) {
                Text(selectedSaved?.name ?? store.skin?.username ?? "").font(.system(size: 17, weight: .bold))
                Text("\(previewSlim ? "Slim" : "Classic") arms").font(.caption).foregroundStyle(T.dim)
            }
            if let saved = selectedSaved {
                Button { store.useSkin(path: saved.path, slim: saved.slim) } label: {
                    Text("Use this skin").font(.system(size: 15, weight: .bold)).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .glassButton(prominent: true).controlSize(.large)
                HStack {
                    Button("Edit") { store.openSkinMaker(from: saved) }.glassButton()
                    Button(role: .destructive) {
                        store.deleteSkin(saved); selection = "account"
                    } label: { Text("Delete") }.glassButton()
                    Button("Import") { store.importCurrentSkin() }.glassButton()
                }
            } else {
                Text("This is the skin on your account right now.").font(.caption).foregroundStyle(T.dim)
                    .multilineTextAlignment(.center)
                HStack {
                    Button("Edit") {
                        if let s = store.skin { store.openSkinMaker(from: nil, accountPath: s.path, accountSlim: s.slim, name: s.username) }
                    }.glassButton()
                    Button("Import") { store.importCurrentSkin() }.glassButton()
                }
            }
        }
        .padding(22).frame(width: 320).glass(cornerRadius: 24)
    }

    private var mySkins: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "My skins") { EmptyView() }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 12)], spacing: 12) {
                if let s = store.skin {
                    tile(id: "account", path: s.path, title: s.username, sub: "On your account")
                }
                ForEach(store.library) { sk in
                    tile(id: sk.id, path: sk.path, title: sk.name, sub: sk.slim ? "Slim" : "Classic")
                }
            }
            if store.library.isEmpty {
                Text("Your saved skins appear here. Press “Upload PNG”, “Skin maker” or “Import”.")
                    .font(.callout).foregroundStyle(T.dim)
            }
        }
    }

    private func tile(id: String, path: String, title: String, sub: String) -> some View {
        let sel = selection == id
        return Button { selection = id } label: {
            VStack(spacing: 8) {
                SkinHead(path: path, size: 64)
                Text(title).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                Text(sub).font(.caption).foregroundStyle(T.dim)
            }
            .padding(12).frame(maxWidth: .infinity)
            .glass(cornerRadius: 16, tint: sel ? T.accent.opacity(0.35) : nil, interactive: true)
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(sel ? T.accent : .clear, lineWidth: 2))
        }
        .buttonStyle(.plain)
    }

    private var myCapes: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "My capes") { EmptyView() }
            let capes = store.skin?.capes ?? []
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 12)], spacing: 12) {
                VStack(spacing: 8) {
                    Text("No cape").foregroundStyle(T.dim).frame(height: 96)
                    Text("None").font(.system(size: 12, weight: .semibold))
                    if capes.contains(where: { $0.active }) {
                        Button("Hide cape") { store.setCape(nil) }.glassButton().controlSize(.small)
                    } else {
                        Text("EQUIPPED").font(.system(size: 10, weight: .bold)).foregroundStyle(T.accent)
                    }
                }
                .padding(12).frame(maxWidth: .infinity).glass(cornerRadius: 16)
                ForEach(capes) { cape in
                    VStack(spacing: 8) {
                        CapeFront(path: cape.path, scale: 6)
                        Text(cape.alias).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                        if cape.active {
                            Text("EQUIPPED").font(.system(size: 10, weight: .bold)).foregroundStyle(T.accent)
                        } else {
                            Button("Equip") { store.setCape(cape.id) }.glassButton().controlSize(.small)
                        }
                    }
                    .padding(12).frame(maxWidth: .infinity).glass(cornerRadius: 16)
                }
            }
        }
    }

    private func pickFile() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.png]
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let u = p.url { store.addSkinFile(u) }
    }
}

// MARK: - Cursor page

struct CursorArt: View {
    let style: CursorStyle
    var cell: CGFloat = 6
    var body: some View {
        Canvas { ctx, _ in
            for (y, row) in style.grid.enumerated() {
                for (x, hex) in row.enumerated() {
                    guard let hex, let v = UInt32(hex.replacingOccurrences(of: "#", with: ""), radix: 16) else { continue }
                    ctx.fill(Path(CGRect(x: CGFloat(x) * cell, y: CGFloat(y) * cell, width: cell, height: cell)),
                             with: .color(Color(hex: v)))
                }
            }
        }
        .frame(width: 16 * cell, height: 16 * cell)
    }
}

struct CursorView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Cursor").font(.system(size: 28, weight: .bold))
                Text("Choose how your pointer looks, and where it applies.").foregroundStyle(T.dim)

                PanelHeader(title: "Where should it apply?") { EmptyView() }
                HStack(spacing: 12) {
                    scope("launcher", "Launcher only", "Changes the pointer inside Spectra. Nothing else is touched.")
                    scope("minecraft", "Launcher + Minecraft",
                          "Also adds the Cursors Extended mod to your Fabric instances so Minecraft gets custom pointers too. Pick its look in game.")
                }

                PanelHeader(title: "Style") { EmptyView() }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 12)], spacing: 12) {
                    ForEach(store.cursorStyles) { st in
                        let sel = st.id == store.cursorStyle
                        Button { store.setCursor(style: st.id) } label: {
                            VStack(spacing: 10) {
                                if st.id == "default" {
                                    Image(systemName: "cursorarrow").font(.system(size: 44)).frame(width: 96, height: 96)
                                } else {
                                    CursorArt(style: st, cell: 6)
                                }
                                Text(st.label).font(.system(size: 13, weight: .semibold))
                            }
                            .padding(16).frame(maxWidth: .infinity)
                            .glass(cornerRadius: 18, tint: sel ? T.accent.opacity(0.45) : nil, interactive: true)
                            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                                .strokeBorder(sel ? T.accent : .clear, lineWidth: 2))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding(4)
        }
        .task { await store.loadCursors() }
    }

    private func scope(_ id: String, _ title: String, _ text: String) -> some View {
        let sel = store.cursorScope == id
        return Button { store.setCursor(scope: id) } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: sel ? "largecircle.fill.circle" : "circle").foregroundStyle(sel ? T.accent : T.dim)
                    Text(title).font(.system(size: 15, weight: .bold))
                }
                Text(text).font(.callout).foregroundStyle(T.dim).multilineTextAlignment(.leading)
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .glass(cornerRadius: 18, tint: sel ? T.accent.opacity(0.3) : nil, interactive: true)
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(sel ? T.accent : .clear, lineWidth: 2))
        }
        .buttonStyle(.plain)
    }
}
