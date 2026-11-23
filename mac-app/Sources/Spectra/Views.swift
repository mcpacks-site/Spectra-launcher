import SwiftUI
import AppKit
import UniformTypeIdentifiers

private let discordURL = URL(string: "https://discord.gg/rWtmhRpa7s")!
private let sourceURL = URL(string: "https://github.com/mcpacks-site/Spectra-launcher")!
private let siteURL = URL(string: "https://mcpacks-site.github.io/Spectra-launcher/")!

// MARK: - Root

struct RootView: View {
    @EnvironmentObject var store: Store
    @State private var dropping = false

    var body: some View {
        ZStack {
            AppBackground()
            HStack(spacing: 12) {
                SidebarView().frame(width: 252)
                VStack(spacing: 12) {
                    TopBar()
                    Group {
                        switch store.tab {
                        case .home: HomeView()
                        case .library: LibraryView()
                        case .discover: DiscoverView()
                        case .skins: SkinsView()
                        case .cursor: CursorView()
                        case .console: ConsoleView()
                        case .settings: SettingsView()
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    PlayBar()
                }
            }
            .padding(12)

            if store.busy { BusyOverlay() }
            if dropping {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .strokeBorder(T.accent, style: StrokeStyle(lineWidth: 3, dash: [10, 8]))
                    .background(T.accent.opacity(0.08))
                    .overlay(Text("Drop a modpack (.mrpack / .zip) to import").font(.title3.bold()))
                    .padding(8).allowsHitTesting(false).zIndex(9)
            }
            if store.introActive { SplashView(kind: .intro) { store.introActive = false }.zIndex(10) }
            if store.outroActive { SplashView(kind: .outro) { store.finishOutro() }.zIndex(11) }
        }
        .background(WindowAccessor { window in
            guard store.closeInterceptor == nil else { return }
            let i = CloseInterceptor(original: window.delegate) { [weak store] in
                guard let store else { return true }
                return store.quitNow(reply: false)
            }
            store.closeInterceptor = i
            window.delegate = i
        })
        .onContinuousHover { phase in
            if case .active = phase, let c = store.activeCursor { c.set() }
        }
        .sheet(isPresented: $store.showSignIn) { SignInSheet() }
        .sheet(isPresented: $store.showNew) { NewInstanceSheet() }
        .sheet(item: $store.editing) { EditInstanceSheet(inst: $0) }
        .sheet(item: $store.draft) { SkinMakerView(ed: $0) }
        .sheet(item: $store.crash) { CrashSheet(info: $0) }
        .sheet(item: $store.pendingLaunch) { LaunchCheckSheet(pending: $0) }
        .onDrop(of: [.fileURL], isTargeted: $dropping) { providers in
            var took = false
            for p in providers {
                _ = p.loadObject(ofClass: URL.self) { url, _ in
                    guard let url else { return }
                    let ext = url.pathExtension.lowercased()
                    guard ["mrpack", "zip"].contains(ext) else { return }
                    Task { @MainActor in store.importFile(url) }
                }
                took = true
            }
            return took
        }
        .alert("Spectra", isPresented: Binding(get: { store.errorMessage != nil },
                                              set: { if !$0 { store.errorMessage = nil } })) {
            Button("OK") { store.errorMessage = nil }
        } message: { Text(store.errorMessage ?? "") }
    }
}

// MARK: - Sidebar

struct SidebarView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                SpectraLogo(size: 30)
                Text("Spectra").font(.system(size: 22, weight: .bold))
            }
            .padding(.top, 26)         // clears the window buttons
            .padding(.bottom, 6)

            HStack {
                Text("INSTANCES").font(.system(size: 11, weight: .semibold)).tracking(1).foregroundStyle(T.dim)
                Spacer()
                Menu {
                    ForEach(InstanceSort.allCases) { s in
                        Button { store.instanceSort = s } label: {
                            if store.instanceSort == s { Label(s.rawValue, systemImage: "checkmark") } else { Text(s.rawValue) }
                        }
                    }
                } label: {
                    Image(systemName: "arrow.up.arrow.down").font(.system(size: 12, weight: .semibold)).frame(width: 28, height: 28)
                }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help("Sort instances")
                Menu {
                    Button("Import a modpack or instance…") { store.pickImport() }
                    Button("Import a mod list code…") { store.importModList() }
                } label: {
                    Image(systemName: "square.and.arrow.down").font(.system(size: 12, weight: .semibold)).frame(width: 28, height: 28)
                }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help("Import a modpack, instance or mod list")
                Button { store.showNew = true } label: {
                    Image(systemName: "plus").font(.system(size: 13, weight: .semibold)).frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .glassCapsule(interactive: true)
                .help("New instance")
            }

            if store.instances.count > 3 || !store.instanceQuery.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundStyle(T.dim)
                    TextField("Search instances", text: $store.instanceQuery).textFieldStyle(.plain)
                    if !store.instanceQuery.isEmpty {
                        Button { store.instanceQuery = "" } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain).foregroundStyle(T.dim)
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.07)))
            }

            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(store.sidebarSections, id: \.title) { section in
                        if !section.title.isEmpty {
                            Text(section.title.uppercased())
                                .font(.system(size: 10, weight: .semibold)).tracking(1).foregroundStyle(T.dim)
                                .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8).padding(.leading, 6)
                        }
                        ForEach(section.items) { inst in
                            InstanceRow(inst: inst, selected: inst.id == store.selected?.id)
                                .onTapGesture { store.selectedID = inst.id; store.tab = .home }
                        }
                    }
                    if store.visibleInstances.isEmpty && !store.instances.isEmpty {
                        Text("No instances match “\(store.instanceQuery)”.")
                            .font(.callout).foregroundStyle(T.dim)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                    }
                    if store.instances.isEmpty {
                        Text("No instances yet.\nPress + or find a modpack in Discover.")
                            .font(.callout).foregroundStyle(T.dim)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 8)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 9) {
                FooterLink(title: "About", url: siteURL)
                FooterLink(title: "Discord", url: discordURL)
                FooterLink(title: "Source code", url: sourceURL)
                Text("Spectra Launcher").font(.system(size: 11)).foregroundStyle(T.dim.opacity(0.7))
            }
        }
        .padding(14)
        .frame(maxHeight: .infinity)
        .glass(cornerRadius: 28)
    }
}

struct FooterLink: View {
    let title: String
    let url: URL
    var body: some View {
        Button { NSWorkspace.shared.open(url) } label: {
            Text(title).font(.system(size: 13)).foregroundStyle(Color.primary.opacity(0.85))
        }
        .buttonStyle(.plain)
    }
}

struct InstanceIcon: View {
    let inst: Instance
    var size: CGFloat = 40

    var body: some View {
        Group {
            if let p = inst.iconPath, let img = NSImage(contentsOfFile: p) {
                Image(nsImage: img).resizable().scaledToFill()
            } else {
                ZStack {
                    LinearGradient(colors: [inst.accent, inst.accent2], startPoint: .topLeading, endPoint: .bottomTrailing)
                    Text(inst.version)
                        .font(.system(size: size * 0.24, weight: .bold))
                        .minimumScaleFactor(0.5).lineLimit(1)
                        .foregroundStyle(.white).shadow(color: .black.opacity(0.35), radius: 1, y: 1)
                        .padding(.horizontal, 3)
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
            .strokeBorder(.white.opacity(0.25), lineWidth: 1))
    }
}

struct InstanceRow: View {
    let inst: Instance
    let selected: Bool

    var body: some View {
        HStack(spacing: 10) {
            InstanceIcon(inst: inst, size: 42)
            VStack(alignment: .leading, spacing: 2) {
                Text(inst.name).font(.system(size: 14, weight: .semibold)).lineLimit(1)
                Text("\(inst.version)  ·  \(inst.loaderLabel)").font(.system(size: 12)).foregroundStyle(T.dim).lineLimit(1)
            }
            Spacer(minLength: 0)
            if inst.favorite { Image(systemName: "star.fill").font(.system(size: 11)).foregroundStyle(T.accent) }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(T.accent.opacity(selected ? 0.16 : 0)))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(T.accent.opacity(selected ? 0.55 : 0), lineWidth: 1))
        .contentShape(Rectangle())
    }
}

// MARK: - Top bar

struct TopBar: View {
    @EnvironmentObject var store: Store

    var body: some View {
        HStack(spacing: 12) {
            GlassGroup(spacing: 8) {
                HStack(spacing: 2) {
                    ForEach(Tab.allCases) { t in navPill(t.rawValue, selected: store.tab == t) { store.tab = t } }
                }
                .padding(4)
                .glassCapsule()
            }
            Spacer()
            AccountChip()
        }
    }

    private func navPill(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(selected ? Color.white : .white.opacity(0.75))
                .padding(.horizontal, 15).padding(.vertical, 8)
                .background(Capsule().fill(selected ? T.accent.opacity(0.55) : .clear))
                .overlay(Capsule().strokeBorder(selected ? T.accent.opacity(0.6) : .clear, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct AccountChip: View {
    @EnvironmentObject var store: Store
    @State private var showMenu = false

    var body: some View {
        HStack(spacing: 10) {
            if store.account == nil {
                Image(systemName: "person.crop.circle").font(.system(size: 30)).foregroundStyle(Color.primary.opacity(0.85))
            } else {
                SteveFace(size: 34)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(store.account?.username ?? "Not signed in").font(.system(size: 13, weight: .bold))
                Text(store.account == nil ? "Click to sign in" : "Microsoft account")
                    .font(.system(size: 11)).foregroundStyle(store.account == nil ? T.warn : T.dim)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .glass(cornerRadius: 18, interactive: true)
        .onTapGesture {
            if store.account == nil { store.startSignIn() } else { showMenu = true }
        }
        .popover(isPresented: $showMenu, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(store.accounts) { a in
                    Button {
                        store.switchAccount(a)
                        showMenu = false
                    } label: {
                        HStack {
                            Image(systemName: a.id == store.account?.id ? "checkmark.circle.fill" : "circle")
                            Text(a.username)
                            Spacer()
                        }
                        .padding(.horizontal, 10).padding(.vertical, 6).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
                Divider().padding(.vertical, 4)
                Button { showMenu = false; store.startSignIn() } label: {
                    Label("Add account…", systemImage: "plus").padding(.horizontal, 10).padding(.vertical, 6)
                }.buttonStyle(.plain)
                Button { showMenu = false; store.tab = .settings } label: {
                    Label("Manage accounts", systemImage: "gearshape").padding(.horizontal, 10).padding(.vertical, 6)
                }.buttonStyle(.plain)
            }
            .padding(8).frame(minWidth: 220)
        }
    }
}

// MARK: - Buttons

struct PlayButton: View {
    @EnvironmentObject var store: Store
    let inst: Instance
    var compact = false

    var body: some View {
        Button { store.running ? store.stop() : store.play(inst) } label: {
            HStack(spacing: 10) {
                Image(systemName: store.running ? "stop.fill" : "play.fill").font(.system(size: compact ? 11 : 12))
                Text(store.running ? "STOP" : "PLAY").font(.system(size: compact ? 16 : 20, weight: .heavy))
            }
            .foregroundStyle(T.ink)
            .frame(minWidth: compact ? 130 : 168).padding(.vertical, compact ? 11 : 15)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(T.gradient))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(LinearGradient(colors: [.white.opacity(0.7), .white.opacity(0.05)],
                                             startPoint: .top, endPoint: .bottom), lineWidth: 1.2))
            .shadow(color: T.accent.opacity(0.4), radius: 14, y: 6)
        }
        .buttonStyle(.plain)
        .modifier(PlayShortcut(enabled: !compact))
    }
}

struct PlayShortcut: ViewModifier {
    let enabled: Bool
    func body(content: Content) -> some View {
        if enabled { content.keyboardShortcut(.return, modifiers: .command) } else { content }
    }
}

struct Pill: View {
    let text: String
    var body: some View {
        Text(text.uppercased()).font(.system(size: 11, weight: .bold)).tracking(0.5)
            .padding(.horizontal, 10).padding(.vertical, 5)
            .glassCapsule()
    }
}

// MARK: - Home

struct HomeView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        if let inst = store.selected {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    hero(inst)
                    HStack(spacing: 6) {
                        ForEach(InstTab.allCases) { t in
                            tab(t.rawValue, selected: store.instTab == t) { store.instTab = t }
                        }
                        tab("Settings", selected: false) { store.editing = inst }
                        Spacer()
                    }
                    switch store.instTab {
                    case .overview:
                        HStack(spacing: 12) {
                            StatCard(label: "PLAYTIME", value: inst.playtimeText)
                            StatCard(label: "MODS INSTALLED", value: "\(inst.mods)")
                            StatCard(label: "MEMORY", value: "\(inst.ramGB) GB")
                        }
                        ScreenshotsCard(inst: inst, limit: 4)
                    case .mods: ContentTab(inst: inst, kind: "mods")
                    case .packs: ContentTab(inst: inst, kind: "resourcepack")
                    case .shaders: ContentTab(inst: inst, kind: "shader")
                    case .datapacks: ContentTab(inst: inst, kind: "datapack")
                    case .servers: ServersTab(inst: inst)
                    case .worlds: WorldsTab(inst: inst)
                    case .screenshots: ScreenshotsCard(inst: inst, limit: 200)
                    }
                    Text("Not an official Minecraft product. Not affiliated with Mojang or Microsoft.")
                        .font(.system(size: 11)).foregroundStyle(T.dim.opacity(0.8))
                }
                .padding(.bottom, 8)
            }
        } else {
            EmptyHome()
        }
    }

    private func hero(_ inst: Instance) -> some View {
        ZStack(alignment: .topLeading) {
            SkyArt()
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 8) {
                    Pill(text: inst.loaderLabel)
                    Pill(text: "Minecraft \(inst.version)")
                    Pill(text: "\(inst.ramGB) GB")
                    if inst.perf { Pill(text: "Spectra Boost") }
                }
                HStack(spacing: 18) {
                    InstanceIcon(inst: inst, size: 88).shadow(color: .black.opacity(0.35), radius: 14, y: 6)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(inst.name).font(.system(size: 42, weight: .bold)).lineLimit(1)
                            .shadow(color: .black.opacity(0.5), radius: 6, y: 2)
                        Text(inst.playedLine)
                            .font(.system(size: 14)).foregroundStyle(Color.primary.opacity(0.85))
                    }
                }
                Spacer(minLength: 0)
                GlassGroup(spacing: 12) {
                    HStack(spacing: 12) {
                        PlayButton(inst: inst)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("VERSION").font(.system(size: 10, weight: .bold)).tracking(0.6).foregroundStyle(T.dim)
                            Text("\(inst.version)  ·  \(inst.loaderLabel)").font(.system(size: 15, weight: .bold))
                        }
                        .padding(.horizontal, 18).frame(height: 54)
                        .glass(cornerRadius: 18)
                        Button { store.openFolder(inst) } label: {
                            Text("Open folder").font(.system(size: 14, weight: .semibold))
                                .padding(.horizontal, 22).frame(height: 54)
                        }
                        .buttonStyle(.plain).glass(cornerRadius: 18, interactive: true)
                        if !inst.perf && ["fabric", "quilt", "forge", "neoforge"].contains(inst.loader) {
                            Button { store.boost(inst) } label: {
                                Label("Spectra Boost", systemImage: "bolt.fill").font(.system(size: 14, weight: .semibold))
                                    .padding(.horizontal, 18).frame(height: 54)
                            }
                            .buttonStyle(.plain).glass(cornerRadius: 18, tint: T.accent.opacity(0.5), interactive: true)
                        }
                        Spacer(minLength: 0)
                        Menu {
                            Button(inst.favorite ? "Remove from favorites" : "Add to favorites") { store.setFavorite(inst, !inst.favorite) }
                            Button("Set group…") { store.askGroup(inst) }
                            Divider()
                            Button("Duplicate…") { store.duplicate(inst) }
                            Button("Export…") { store.export(inst) }
                            Divider()
                            Button("Copy mod list code") { store.copyModList(inst) }
                            Button("Save mod list file…") { store.saveModList(inst) }
                            Button("Save support file…") { store.saveSupportFile(inst) }
                            Button("Open crash reports") { store.openContentFolder(inst, kind: "crash-reports") }
                        } label: {
                            Image(systemName: "ellipsis").frame(width: 54, height: 54)
                        }
                        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                        .glass(cornerRadius: 18, interactive: true)
                        .disabled(store.running)
                        Button(role: .destructive) { confirmDelete(inst) } label: {
                            Image(systemName: "trash").frame(width: 54, height: 54)
                        }
                        .buttonStyle(.plain).glass(cornerRadius: 18, interactive: true)
                        .disabled(store.running)
                    }
                }
            }
            .padding(24)
        }
        .environment(\.colorScheme, .dark)
        .frame(height: 360)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 28, style: .continuous)
            .strokeBorder(LinearGradient(colors: [.white.opacity(0.4), .white.opacity(0.06)],
                                         startPoint: .top, endPoint: .bottom), lineWidth: 1))
    }

    private func tab(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.system(size: 14, weight: .semibold))
                .foregroundStyle(selected ? T.accent : .white.opacity(0.75))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(selected ? T.accent.opacity(0.14) : .clear))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(selected ? T.accent.opacity(0.4) : .clear, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private func confirmDelete(_ inst: Instance) {
        let a = NSAlert()
        a.messageText = "Delete “\(inst.name)”?"
        a.informativeText = "This removes the instance and its worlds, mods and settings."
        a.addButton(withTitle: "Delete")
        a.addButton(withTitle: "Cancel")
        a.alertStyle = .warning
        if a.runModal() == .alertFirstButtonReturn { store.delete(inst) }
    }
}

struct ScreenshotsCard: View {
    @EnvironmentObject var store: Store
    let inst: Instance
    var limit = 8
    @State private var shots: [URL] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Screenshots").font(.system(size: 17, weight: .bold))
                Spacer()
                Button("Open folder") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: store.root).appendingPathComponent("instances")
                        .appendingPathComponent(inst.id).appendingPathComponent("minecraft/screenshots"))
                }
                .glassButton().controlSize(.small)
            }
            if shots.isEmpty {
                Text("No screenshots yet. Press F2 in the game to take one.").foregroundStyle(Color.primary.opacity(0.8))
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
                    ForEach(shots.prefix(limit), id: \.self) { url in
                        AsyncImage(url: url) { img in
                            img.resizable().scaledToFill()
                        } placeholder: {
                            Rectangle().fill(Color.primary.opacity(0.08))
                        }
                        .frame(height: 118)
                        .frame(maxWidth: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .onTapGesture { NSWorkspace.shared.open(url) }
                    }
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glass(cornerRadius: 20)
        .task(id: inst.id) { load() }
    }

    private func load() {
        let dir = URL(fileURLWithPath: store.root).appendingPathComponent("instances")
            .appendingPathComponent(inst.id).appendingPathComponent("minecraft/screenshots")
        let files = (try? FileManager.default.contentsOfDirectory(
            at: dir, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        shots = files.filter { ["png", "jpg", "jpeg"].contains($0.pathExtension.lowercased()) }
            .sorted {
                let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return a > b
            }
    }
}

struct StatCard: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.system(size: 11, weight: .semibold)).tracking(0.6).foregroundStyle(T.dim)
            Text(value).font(.system(size: 24, weight: .bold))
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glass(cornerRadius: 20)
    }
}

struct EmptyHome: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ZStack {
            SkyArt()
            VStack(spacing: 14) {
                SpectraLogo(size: 54)
                Text("Welcome to Spectra").font(.system(size: 34, weight: .bold))
                Text("Create an instance or install a modpack to get started.").foregroundStyle(Color.primary.opacity(0.85))
                HStack {
                    Button { store.showNew = true } label: { Label("New instance", systemImage: "plus") }
                        .glassButton(prominent: true).controlSize(.large)
                    Button { store.tab = .discover } label: { Label("Browse modpacks", systemImage: "sparkles") }
                        .glassButton().controlSize(.large)
                }
            }
        }
        .environment(\.colorScheme, .dark)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Always-on play bar

struct PlayBar: View {
    @EnvironmentObject var store: Store

    var body: some View {
        if let inst = store.selected {
            HStack(spacing: 14) {
                InstanceIcon(inst: inst, size: 46)
                VStack(alignment: .leading, spacing: 2) {
                    Text(inst.name).font(.system(size: 15, weight: .bold)).lineLimit(1)
                    Text("\(inst.version)  ·  \(inst.loaderLabel)").font(.system(size: 12)).foregroundStyle(T.dim)
                }
                .frame(minWidth: 170, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    Text(store.running ? store.phase : "Ready").font(.system(size: 12)).foregroundStyle(Color.primary.opacity(0.85)).lineLimit(1)
                    if let p = store.progress, p.total > 0 {
                        ProgressView(value: Double(p.done), total: Double(p.total)).tint(T.accent)
                    } else if store.running && store.phase != "Playing" {
                        ProgressView().progressViewStyle(.linear).tint(T.accent)
                    } else {
                        Capsule().fill(Color.primary.opacity(0.12)).frame(height: 4)
                    }
                }
                PlayButton(inst: inst, compact: true)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            .glass(cornerRadius: 24)
        }
    }
}

// MARK: - Library

struct LibraryView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 14)], spacing: 14) {
                ForEach(store.instances) { inst in
                    VStack(alignment: .leading, spacing: 12) {
                        InstanceIcon(inst: inst, size: 72)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(inst.name).font(.system(size: 16, weight: .bold)).lineLimit(1)
                            Text("\(inst.version)  ·  \(inst.loaderLabel)").font(.system(size: 12)).foregroundStyle(T.dim)
                            Text(inst.playtime == 0 ? "Not played yet" : "Played \(inst.playtimeText)")
                                .font(.system(size: 12)).foregroundStyle(T.dim)
                        }
                        Button("Open") { store.selectedID = inst.id; store.tab = .home }.glassButton()
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glass(cornerRadius: 22)
                    .onTapGesture { store.selectedID = inst.id; store.tab = .home }
                }
                Button { store.showNew = true } label: {
                    VStack(spacing: 8) {
                        Image(systemName: "plus").font(.system(size: 26, weight: .semibold))
                        Text("New instance").font(.system(size: 14, weight: .semibold))
                    }
                    .frame(maxWidth: .infinity, minHeight: 190)
                    .glass(cornerRadius: 22, interactive: true)
                }
                .buttonStyle(.plain)
            }
            .padding(2)
        }
    }
}

// MARK: - Discover

struct DiscoverView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 14) {
            HStack(spacing: 10) {
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(T.dim)
                    TextField("Search modpacks", text: $store.query).textFieldStyle(.plain)
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .glass(cornerRadius: 16)

                Picker("", selection: $store.source) {
                    Text("Modrinth").tag("modrinth")
                    Text("CurseForge").tag("curseforge")
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 220)
            }

            if store.source == "curseforge" && !store.hasCurseForgeKey {
                VStack(spacing: 10) {
                    Text("CurseForge needs your own free API key.").font(.headline)
                    Text("Add it in Settings. It stays on this Mac.").foregroundStyle(T.dim)
                    Button("Open Settings") { store.tab = .settings }.glassButton(prominent: true)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 270), spacing: 14)], spacing: 14) {
                        ForEach(store.packs) { PackCard(pack: $0) }
                    }
                    .padding(2)
                    if store.searching && store.packs.isEmpty { ProgressView().padding(40) }
                }
            }
        }
        .task(id: "\(store.source)|\(store.query)") {
            try? await Task.sleep(nanoseconds: 350_000_000)
            if Task.isCancelled { return }
            if store.source == "curseforge" && !store.hasCurseForgeKey { return }
            await store.search()
        }
    }
}

struct PackCard: View {
    @EnvironmentObject var store: Store
    let pack: Pack

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                AsyncImage(url: pack.icon) { img in
                    img.resizable().scaledToFill()
                } placeholder: {
                    Rectangle().fill(Color.primary.opacity(0.15))
                }
                .frame(width: 54, height: 54)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(pack.title).font(.system(size: 15, weight: .bold)).lineLimit(1)
                    Text("by \(pack.author)").font(.caption).foregroundStyle(T.dim).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            Text(pack.summary).font(.callout).foregroundStyle(Color.primary.opacity(0.8)).lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            HStack {
                Label(pack.downloads.formatted(.number.notation(.compactName)), systemImage: "arrow.down.circle")
                    .font(.caption).foregroundStyle(T.dim)
                Spacer()
                if pack.blocked {
                    // the author opted out of third-party downloads: send people to the official page
                    Button("Open on CurseForge") { if let u = pack.url { NSWorkspace.shared.open(u) } }
                        .glassButton()
                } else {
                    Button("Install") { store.install(pack) }.glassButton(prominent: true)
                }
            }
        }
        .padding(14)
        .glass(cornerRadius: 22)
    }
}

// MARK: - Console

struct ConsoleView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(store.console.enumerated()), id: \.offset) { i, line in
                        Text(line).font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(Color.primary.opacity(0.88))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .id(i)
                    }
                    if store.console.isEmpty {
                        Text("Game output appears here when you press Play.").foregroundStyle(T.dim)
                    }
                }
                .textSelection(.enabled)
                .padding(18)
            }
            .onChange(of: store.console.count) { n in
                if n > 0 { proxy.scrollTo(n - 1, anchor: .bottom) }
            }
        }
        .glass(cornerRadius: 26)
    }
}

// MARK: - Overlays & sheets

struct BusyOverlay: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ZStack {
            Color.black.opacity(0.4).ignoresSafeArea()
            VStack(spacing: 14) {
                ProgressView()
                Text(store.busyLabel).font(.callout.weight(.medium)).lineLimit(2).multilineTextAlignment(.center)
                if let p = store.progress, p.total > 0 {
                    ProgressView(value: Double(p.done), total: Double(p.total)).tint(T.accent).frame(width: 240)
                }
            }
            .padding(28)
            .frame(width: 340)
            .glass(cornerRadius: 28)
        }
    }
}

struct SignInSheet: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 16) {
            Text("Sign in with Microsoft").font(.title2.bold())
            if let d = store.device {
                Text("Open the page below and enter this code:").foregroundStyle(.secondary)
                Text(d.code).font(.system(size: 38, weight: .bold, design: .monospaced)).textSelection(.enabled)
                HStack {
                    Button("Copy code") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(d.code, forType: .string)
                    }
                    Button("Open sign-in page") { if let u = URL(string: d.uri) { NSWorkspace.shared.open(u) } }
                        .glassButton(prominent: true)
                }
                Text("Waiting for you to finish in the browser…").font(.caption).foregroundStyle(.secondary)
                ProgressView().controlSize(.small)
            } else {
                ProgressView()
                Text("Getting a code…").foregroundStyle(.secondary)
            }
            Button("Cancel") { store.cancelSignIn() }.keyboardShortcut(.cancelAction)
        }
        .padding(30)
        .frame(width: 420)
    }
}

struct NewInstanceSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var loader = "fabric"
    @State private var versions: [String] = []
    @State private var version = ""
    @State private var boost = true

    private let loaders = ["fabric", "quilt", "forge", "neoforge", "vanilla"]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("New instance").font(.title2.bold())
            TextField("Name", text: $name).textFieldStyle(.roundedBorder)
            Picker("Loader", selection: $loader) {
                ForEach(loaders, id: \.self) { Text($0.capitalized).tag($0) }
            }
            if versions.isEmpty {
                HStack { ProgressView().controlSize(.small); Text("Loading versions…").foregroundStyle(.secondary) }
            } else {
                Picker("Minecraft", selection: $version) {
                    ForEach(versions, id: \.self) { Text($0).tag($0) }
                }
            }
            Toggle("Add Spectra Boost (performance mods)", isOn: $boost)
                .disabled(!["fabric", "quilt", "forge", "neoforge"].contains(loader))
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Create") {
                    store.create(name: name.trimmingCharacters(in: .whitespaces), version: version, loader: loader, boost: boost)
                    dismiss()
                }
                .glassButton(prominent: true)
                .keyboardShortcut(.defaultAction)
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || version.isEmpty)
            }
        }
        .padding(26)
        .frame(width: 420)
        .task(id: loader) {
            versions = []
            version = ""
            versions = await store.versions(for: loader)
            version = versions.first ?? ""
        }
    }
}

struct EditInstanceSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let inst: Instance
    @State private var name = ""
    @State private var ram = 4
    @State private var icon: String?
    @State private var java = ""
    @State private var jvm = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Instance settings").font(.title2.bold())
            HStack(spacing: 14) {
                InstanceIcon(inst: inst, size: 64)
                Button("Change icon…") {
                    let p = NSOpenPanel()
                    p.allowedContentTypes = [.png, .gif]
                    p.allowsMultipleSelection = false
                    if p.runModal() == .OK { icon = p.url?.path }
                }
                if icon != nil { Text("New icon selected").font(.caption).foregroundStyle(.secondary) }
            }
            TextField("Name", text: $name).textFieldStyle(.roundedBorder)
            Stepper("Memory: \(ram) GB", value: $ram, in: 1...32)
            VStack(alignment: .leading, spacing: 4) {
                Text("Java (optional)").font(.caption).foregroundStyle(.secondary)
                HStack {
                    TextField("Automatic", text: $java).textFieldStyle(.roundedBorder)
                    Button("Choose…") {
                        let p = NSOpenPanel()
                        p.allowsMultipleSelection = false
                        p.message = "Choose a Java executable (…/bin/java)"
                        if p.runModal() == .OK, let u = p.url { java = u.path }
                    }
                }
                Text("Extra JVM arguments (optional)").font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                TextField("-XX:+UseZGC", text: $jvm).textFieldStyle(.roundedBorder)
            }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") {
                    store.update(inst, name: name, ram: ram, icon: icon, java: java, jvm: jvm)
                    dismiss()
                }
                .glassButton(prominent: true).keyboardShortcut(.defaultAction)
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(26)
        .frame(width: 460)
        .onAppear { name = inst.name; ram = inst.ramGB; java = inst.java; jvm = inst.jvmArgs }
    }
}


// MARK: - Crash helper

struct CrashSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var store: Store
    let info: CrashInfo

    private var hint: String {
        let t = info.tail.joined(separator: "\n").lowercased()
        if t.contains("outofmemoryerror") { return "Minecraft ran out of memory. Open Settings and give this instance more RAM." }
        if t.contains("unsupportedclassversion") || t.contains("class file version") { return "This needs a different Java version. Leave Java on Automatic in the instance settings." }
        if t.contains("mixin") && t.contains("failed") { return "A mod failed to apply. Try disabling the most recently added mod." }
        if t.contains("incompatible") || t.contains("requires") { return "A mod is missing a dependency or doesn't match this Minecraft version." }
        return "Look at the last lines below. If a mod is named, try turning it off in the Mods tab."
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("\(info.name) closed unexpectedly", systemImage: "exclamationmark.triangle.fill")
                .font(.title3.bold())
            Text("Exit code \(info.code). \(hint)").foregroundStyle(.secondary)
            if let a = store.analysis, !(a.issues.isEmpty && a.suspects.isEmpty) {
                VStack(alignment: .leading, spacing: 8) {
                    Label("What Spectra found", systemImage: "wand.and.stars").font(.system(size: 13, weight: .semibold))
                    ForEach(a.issues, id: \.self) { Text("• \($0)").font(.callout) }
                    ForEach(a.suspects) { s in
                        HStack {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(s.name).font(.system(size: 13, weight: .semibold))
                                Text(s.reason).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("Turn off") { store.disableSuspect(s) }.controlSize(.small)
                        }
                    }
                    Text("Best guesses from the crash report, not certainties.").font(.caption2).foregroundStyle(.secondary)
                }
                .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.06)))
            }
            ScrollView {
                Text(info.tail.joined(separator: "\n"))
                    .font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(10)
            }
            .frame(height: 220)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.06)))
            HStack {
                Button("Copy log") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(info.tail.joined(separator: "\n"), forType: .string)
                }
                if let inst = store.instances.first(where: { $0.name == info.name }) {
                    Button("Open crash reports") { store.openContentFolder(inst, kind: "crash-reports") }
                    Button("Save support file…") { store.saveSupportFile(inst) }
                }
                Spacer()
                Button("Close") { dismiss() }.glassButton(prominent: true).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 560)
    }
}
