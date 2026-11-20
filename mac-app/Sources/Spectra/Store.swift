import SwiftUI
import AppKit

struct Instance: Identifiable, Hashable {
    let id: String
    var name: String
    var version: String
    var loaderLabel: String
    var loader: String
    var ramGB: Int
    var mods: Int
    var playtime: Int
    var lastPlayed: Int
    var iconPath: String?
    var perf: Bool
    var java: String
    var jvmArgs: String
    var favorite: Bool
    var group: String

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? UUID().uuidString
        name = d["name"] as? String ?? "Instance"
        version = d["version"] as? String ?? ""
        loader = d["loader"] as? String ?? ""
        loaderLabel = d["loader_label"] as? String ?? loader
        ramGB = (d["ram_gb"] as? NSNumber)?.intValue ?? 4
        mods = (d["mods"] as? NSNumber)?.intValue ?? 0
        playtime = (d["playtime_s"] as? NSNumber)?.intValue ?? 0
        lastPlayed = (d["last_played"] as? NSNumber)?.intValue ?? 0
        iconPath = d["icon_path"] as? String
        perf = (d["perf"] as? NSNumber)?.boolValue ?? false
        java = d["java"] as? String ?? ""
        jvmArgs = d["jvm_args"] as? String ?? ""
        favorite = (d["favorite"] as? NSNumber)?.boolValue ?? false
        group = d["group"] as? String ?? ""
    }

    var playtimeText: String {
        let h = playtime / 3600, m = (playtime % 3600) / 60
        if playtime == 0 { return "None yet" }
        return h > 0 ? "\(h) h \(m) min" : "\(max(m, 1)) min"
    }

    var playedLine: String {
        if playtime == 0 { return "Not played yet" }
        var s = "Played \(playtimeText)"
        if lastPlayed > 0 {
            let f = DateFormatter(); f.dateFormat = "MMM d"
            s += "   ·   Last played " + f.string(from: Date(timeIntervalSince1970: TimeInterval(lastPlayed)))
        }
        return s
    }

    private var hue: Double {
        var h = 7
        for u in name.unicodeScalars { h = (h &* 31 &+ Int(u.value)) % 360 }
        return Double(h) / 360
    }
    var accent: Color { Color(hue: hue, saturation: 0.62, brightness: 0.92) }
    var accent2: Color { Color(hue: (hue + 0.14).truncatingRemainder(dividingBy: 1), saturation: 0.75, brightness: 0.62) }
}

struct Account: Identifiable, Hashable {
    let id: String
    let username: String
    init(_ d: [String: Any]) {
        id = d["key"] as? String ?? ""
        username = d["username"] as? String ?? "Player"
    }
}

struct Pack: Identifiable, Hashable {
    let id: String
    let source: String
    let title: String
    let author: String
    let summary: String
    let downloads: Int
    let icon: URL?
    let url: URL?
    let blocked: Bool

    init(_ d: [String: Any]) {
        id = "\(d["source"] as? String ?? "")-\(d["id"] as? String ?? UUID().uuidString)"
        source = d["source"] as? String ?? "modrinth"
        title = d["title"] as? String ?? ""
        author = d["author"] as? String ?? ""
        summary = d["description"] as? String ?? ""
        downloads = (d["downloads"] as? NSNumber)?.intValue ?? 0
        icon = (d["icon"] as? String).flatMap { $0.isEmpty ? nil : URL(string: $0) }
        url = (d["url"] as? String).flatMap { URL(string: $0) }
        blocked = (d["blocked"] as? NSNumber)?.boolValue ?? false
        rawID = d["id"] as? String ?? ""
    }
    let rawID: String
}

struct DeviceInfo: Equatable {
    var code: String
    var uri: String
}

struct ContentItem: Identifiable, Hashable {
    let id: String          // file name on disk
    let name: String
    let enabled: Bool
    init(_ d: [String: Any]) {
        id = d["file"] as? String ?? ""
        name = d["name"] as? String ?? id
        enabled = (d["enabled"] as? NSNumber)?.boolValue ?? true
    }
}

struct World: Identifiable, Hashable {
    var id: String { name }
    let name: String
    let size: Int
    let played: Int
    init(_ d: [String: Any]) {
        name = d["name"] as? String ?? ""
        size = (d["size"] as? NSNumber)?.intValue ?? 0
        played = (d["played"] as? NSNumber)?.intValue ?? 0
    }
}

struct Backup: Identifiable, Hashable {
    var id: String { name }
    let name: String
    let size: Int
    let created: Int
    init(_ d: [String: Any]) {
        name = d["name"] as? String ?? ""
        size = (d["size"] as? NSNumber)?.intValue ?? 0
        created = (d["created"] as? NSNumber)?.intValue ?? 0
    }
}

struct Cape: Identifiable, Hashable {
    let id: String
    let alias: String
    let active: Bool
    let path: String
    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        alias = d["alias"] as? String ?? "Cape"
        active = (d["active"] as? NSNumber)?.boolValue ?? false
        path = d["path"] as? String ?? ""
    }
}

struct SavedSkin: Identifiable, Hashable {
    let id: String
    let name: String
    let slim: Bool
    let path: String
    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? UUID().uuidString
        name = d["name"] as? String ?? id
        slim = (d["slim"] as? NSNumber)?.boolValue ?? false
        path = d["path"] as? String ?? ""
    }
}

struct SkinInfo {
    let username: String
    let path: String
    let slim: Bool
    let capes: [Cape]
    let stamp = Date()
}

struct CursorStyle: Identifiable, Hashable {
    let id: String
    let label: String
    let hotspot: (Int, Int)
    let grid: [[String?]]
    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? "default"
        label = d["label"] as? String ?? id
        let h = d["hotspot"] as? [Int] ?? [0, 0]
        hotspot = (h.first ?? 0, h.last ?? 0)
        grid = (d["grid"] as? [[Any]] ?? []).map { $0.map { $0 as? String } }
    }
    static func == (a: CursorStyle, b: CursorStyle) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }

    /// A real pointer built from the 16x16 art (drawn at 2x so it stays crisp).
    func makeCursor() -> NSCursor? {
        if id == "default" || grid.isEmpty { return nil }
        let cells = grid
        let img = NSImage(size: NSSize(width: 32, height: 32), flipped: true) { _ in
            for (y, row) in cells.enumerated() {
                for (x, hex) in row.enumerated() {
                    guard let hex, let v = UInt32(hex.replacingOccurrences(of: "#", with: ""), radix: 16) else { continue }
                    NSColor(srgbRed: CGFloat((v >> 16) & 255) / 255, green: CGFloat((v >> 8) & 255) / 255,
                            blue: CGFloat(v & 255) / 255, alpha: 1).setFill()
                    NSRect(x: x * 2, y: y * 2, width: 2, height: 2).fill()
                }
            }
            return true
        }
        return NSCursor(image: img, hotSpot: NSPoint(x: hotspot.0 * 2, y: hotspot.1 * 2))
    }
}

struct ModUpdate: Identifiable, Hashable {
    let id: String
    let title: String
    let current: String
    let latest: String
    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        title = d["title"] as? String ?? id
        current = d["current"] as? String ?? ""
        latest = d["latest"] as? String ?? ""
    }
}

struct CrashInfo: Identifiable {
    let id = UUID()
    let name: String
    let code: Int
    let tail: [String]
}

enum InstanceSort: String, CaseIterable, Identifiable {
    case name = "Name", recent = "Last played", played = "Most played"
    var id: String { rawValue }
}

struct SidebarSection {
    let title: String
    let items: [Instance]
}

struct ServerEntry: Identifiable, Hashable {
    var id: String { ip }
    let name: String
    let ip: String
    init(_ d: [String: Any]) {
        ip = d["ip"] as? String ?? ""
        let n = d["name"] as? String ?? ""
        name = n.isEmpty ? ip : n
    }
}

struct CrashSuspect: Identifiable, Hashable {
    var id: String { file }
    let file: String
    let name: String
    let reason: String
    init(_ d: [String: Any]) {
        file = d["file"] as? String ?? ""
        name = d["name"] as? String ?? file
        reason = d["reason"] as? String ?? ""
    }
}

struct CrashAnalysis {
    var issues: [String]
    var suspects: [CrashSuspect]
    var report: String?
}

enum InstTab: String, CaseIterable, Identifiable {
    case overview = "Overview", mods = "Mods", packs = "Resource packs", shaders = "Shaders", datapacks = "Datapacks", servers = "Servers"
    case worlds = "Worlds", screenshots = "Screenshots"
    var id: String { rawValue }
}

enum Tab: String, CaseIterable, Identifiable {
    case home = "Home", library = "Library", discover = "Discover", skins = "Skins", cursor = "Cursor", console = "Console", settings = "Settings"
    var id: String { rawValue }
}

@MainActor
final class Store: ObservableObject {
    static let shared = Store()
    let core = CoreClient()

    @Published var instances: [Instance] = []
    @Published var accounts: [Account] = []
    @Published var currentAccount: String?
    @Published var hasCurseForgeKey = false
    @Published var root = ""
    @Published var selectedID: String?
    @Published var tab: Tab = .home

    @Published var running = false
    @Published var phase = ""
    @Published var progress: (done: Int, total: Int, label: String)?
    @Published var console: [String] = []

    @Published var packs: [Pack] = []
    @Published var searching = false
    @Published var source = "modrinth"
    @Published var query = ""

    @Published var busy = false
    @Published var busyLabel = ""
    @Published var errorMessage: String?

    @Published var showSignIn = false
    @Published var device: DeviceInfo?
    @Published var showNew = false
    @Published var accent = "green"
    @Published var theme = "dark"
    @Published var splashEnabled = true
    @Published var liquidGlass = true
    @Published var outroEnabled = true
    @Published var introActive = true
    @Published var outroActive = false
    var outroPlayed = false
    private var quitReply = false
    var closeInterceptor: CloseInterceptor?
    @Published var editing: Instance?
    @Published var instanceQuery = ""
    @Published var instanceSort: InstanceSort = .name
    @Published var crash: CrashInfo?
    @Published var analysis: CrashAnalysis?
    @Published var servers: [ServerEntry] = []
    @Published var autoBackup = true
    @Published var backupsKeep = 3
    @Published var presenceOn = false
    @Published var discordSet = false
    private var launchingID = ""
    @Published var modUpdates: [ModUpdate] = []
    @Published var modCheckDone = false
    @Published var checkingUpdates = false
    private var lastExit = 0
    private var stopRequested = false
    private var launchingName = ""
    @Published var instTab: InstTab = .overview
    @Published var content: [ContentItem] = []
    @Published var worlds: [World] = []
    @Published var backups: [Backup] = []
    @Published var skin: SkinInfo?
    @Published var skinLoading = false
    @Published var library: [SavedSkin] = []
    @Published var draft: SkinEditor?
    @Published var cursorStyles: [CursorStyle] = []
    @Published var cursorStyle = "default"
    @Published var cursorScope = "launcher"
    var activeCursor: NSCursor?

    private var launchHandle: CoreHandle?
    private var loginHandle: CoreHandle?

    var visibleInstances: [Instance] {
        let q = instanceQuery.trimmingCharacters(in: .whitespaces).lowercased()
        var list = instances.filter {
            q.isEmpty || $0.name.lowercased().contains(q) || $0.version.lowercased().contains(q) || $0.loaderLabel.lowercased().contains(q)
        }
        switch instanceSort {
        case .name: list.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        case .recent: list.sort { $0.lastPlayed > $1.lastPlayed }
        case .played: list.sort { $0.playtime > $1.playtime }
        }
        return list.filter { $0.favorite } + list.filter { !$0.favorite }
    }

    var sidebarSections: [SidebarSection] {
        let list = visibleInstances
        let groups = Set(list.map { $0.group }.filter { !$0.isEmpty })
        if groups.isEmpty { return [SidebarSection(title: "", items: list)] }
        var out: [SidebarSection] = []
        let loose = list.filter { $0.group.isEmpty }
        if !loose.isEmpty { out.append(SidebarSection(title: "", items: loose)) }
        for g in groups.sorted(by: { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }) {
            out.append(SidebarSection(title: g, items: list.filter { $0.group == g }))
        }
        return out
    }

    var selected: Instance? { instances.first { $0.id == selectedID } ?? instances.first }
    var account: Account? { accounts.first { $0.id == currentAccount } ?? accounts.first }

    // MARK: state

    func refresh() {
        Task {
            do {
                let events = try await core.call(["state"])
                guard let s = events.first(where: { $0.type == "state" }) else { return }
                instances = s.list("instances").map(Instance.init)
                accounts = s.list("accounts").map(Account.init)
                currentAccount = s.raw["account"] as? String
                hasCurseForgeKey = s.bool("curseforge_key")
                root = s.str("root")
                let acc = s.str("accent").isEmpty ? "green" : s.str("accent")
                let th = s.str("theme").isEmpty ? "dark" : s.str("theme")
                Palette.apply(accent: acc, theme: th)
                accent = acc
                theme = th
                splashEnabled = s.raw["splash"] as? Bool ?? true
                liquidGlass = s.raw["glass"] as? Bool ?? true
                Palette.glassOn = liquidGlass
                outroEnabled = s.raw["outro"] as? Bool ?? true
                autoBackup = s.raw["auto_backup"] as? Bool ?? true
                backupsKeep = (s.raw["backups_keep"] as? NSNumber)?.intValue ?? 3
                presenceOn = s.raw["presence"] as? Bool ?? false
                discordSet = s.raw["discord_id"] as? Bool ?? false
                if !splashEnabled { introActive = false }
                if selected == nil || !instances.contains(where: { $0.id == selectedID }) {
                    selectedID = instances.first?.id
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    // MARK: playing

    func play(_ inst: Instance, server: String? = nil) {
        guard !running else { return }
        guard account != nil else { startSignIn(); return }
        running = true
        stopRequested = false
        lastExit = 0
        launchingName = inst.name
        launchingID = inst.id
        analysis = nil
        requestNotifications()
        phase = "Preparing…"
        progress = nil
        console.removeAll()
        append("Starting \(inst.name)…")
        var args = ["launch", inst.id]
        if let key = account?.id { args += ["--account", key] }
        if let server, !server.isEmpty { args += ["--server", server] }
        do {
            launchHandle = try core.spawn(args, onEvent: { [weak self] e in self?.handleLaunch(e) },
                                          onExit: { [weak self] _ in self?.finishLaunch() })
        } catch {
            running = false
            phase = ""
            errorMessage = error.localizedDescription
        }
    }

    func stop() { stopRequested = true; launchHandle?.terminate() }

    func openFolder(_ inst: Instance) {
        let url = URL(fileURLWithPath: root).appendingPathComponent("instances").appendingPathComponent(inst.id)
        NSWorkspace.shared.open(url)
    }

    private func handleLaunch(_ e: Event) {
        switch e.type {
        case "log": append(e.str("text"))
        case "game": append(e.str("line"))
        case "phase": phase = "Preparing…"
        case "progress":
            progress = (e.int("done"), e.int("total"), e.str("label"))
            phase = e.str("label")
        case "running": phase = "Playing"; progress = nil
        case "error": errorMessage = e.str("message")
        case "exit": lastExit = e.int("code")
        default: break
        }
    }

    private func finishLaunch() {
        let name = launchingName, code = lastExit
        if code != 0 && !stopRequested && phase != "" {
            crash = CrashInfo(name: name, code: code, tail: Array(console.suffix(80)))
            let id = launchingID
            Task { await analyzeCrash(id) }
        }
        notify(title: code != 0 && !stopRequested ? "\(name) crashed" : "\(name) closed",
               body: code != 0 && !stopRequested ? "Open Spectra to see what happened." : "Thanks for playing.")
        running = false
        phase = ""
        progress = nil
        launchHandle = nil
        refresh()
    }

    func append(_ line: String) {
        console.append(line)
        if console.count > 4000 { console.removeFirst(console.count - 3000) }
    }

    // MARK: sign in

    func startSignIn() {
        showSignIn = true
        device = nil
        do {
            loginHandle = try core.spawn(["login"], onEvent: { [weak self] e in
                guard let self else { return }
                switch e.type {
                case "device": self.device = DeviceInfo(code: e.str("user_code"), uri: e.str("uri"))
                case "account": self.showSignIn = false; self.device = nil
                case "error": self.errorMessage = e.str("message"); self.showSignIn = false
                default: break
                }
            }, onExit: { [weak self] _ in
                self?.loginHandle = nil
                self?.refresh()
            })
        } catch {
            showSignIn = false
            errorMessage = error.localizedDescription
        }
    }

    func cancelSignIn() {
        loginHandle?.cancel()
        showSignIn = false
        device = nil
    }

    // MARK: instances

    func create(name: String, version: String, loader: String, boost: Bool) {
        var args = ["create", "--name", name, "--version", version, "--loader", loader]
        if boost { args.append("--boost") }
        runBusy("Creating \(name)…", args)
    }

    func boost(_ inst: Instance) { runBusy("Adding Spectra Boost…", ["boost", inst.id]) }

    func delete(_ inst: Instance) {
        Task {
            do {
                _ = try await core.call(["delete", inst.id])
                if selectedID == inst.id { selectedID = nil }
                refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func install(_ pack: Pack) {
        runBusy("Installing \(pack.title)…", ["install-pack", "--source", pack.source, pack.rawID])
    }

    private func runBusy(_ label: String, _ args: [String]) {
        busy = true
        busyLabel = label
        progress = nil
        Task {
            do {
                let events = try await core.call(args, onEvent: { [weak self] e in
                    if e.type == "progress" { self?.progress = (e.int("done"), e.int("total"), e.str("label")) }
                    if e.type == "log" { self?.busyLabel = e.str("text") }
                })
                if let inst = events.first(where: { $0.type == "instance" })?.dict("instance") {
                    selectedID = Instance(inst).id
                    tab = .home
                }
                refresh()
            } catch {
                errorMessage = error.localizedDescription
            }
            busy = false
            progress = nil
        }
    }

    // MARK: discover

    func search() async {
        searching = true
        defer { searching = false }
        do {
            var args = ["search", "--source", source, "--limit", "40"]
            if !query.trimmingCharacters(in: .whitespaces).isEmpty { args += ["--query", query] }
            let events = try await core.call(args)
            if Task.isCancelled { return }
            packs = (events.first(where: { $0.type == "packs" })?.list("packs") ?? []).map(Pack.init)
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription; packs = [] }
        }
    }

    func versions(for loader: String) async -> [String] {
        let events = (try? await core.call(["versions", "--loader", loader])) ?? []
        return events.first(where: { $0.type == "versions" })?.list("versions").compactMap { $0["version"] as? String } ?? []
    }

    func signOut(_ acct: Account) {
        Task {
            do { _ = try await core.call(["signout", acct.id]); refresh() }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func update(_ inst: Instance, name: String, ram: Int, icon: String?, java: String = "", jvm: String = "") {
        Task {
            do {
                var args = ["update", inst.id, "--name", name, "--ram", String(ram), "--java=\(java)", "--jvm=\(jvm)"]
                if let icon { args += ["--icon", icon] }
                _ = try await core.call(args)
                refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func setLook(accent: String? = nil, theme: String? = nil) {
        let acc = accent ?? self.accent, th = theme ?? self.theme
        Palette.apply(accent: acc, theme: th)
        self.accent = acc
        self.theme = th
        var args = ["pref-set"]
        if let accent { args += ["--accent", accent] }
        if let theme { args += ["--theme", theme] }
        Task { _ = try? await core.call(args) }
    }

    func setGlass(_ on: Bool) {
        Palette.glassOn = on
        liquidGlass = on
        Task { _ = try? await core.call(["pref-set", "--glass", on ? "on" : "off"]) }
    }

    func setAnimations(splash: Bool? = nil, outro: Bool? = nil) {
        var args = ["pref-set"]
        if let splash { splashEnabled = splash; args += ["--splash", splash ? "on" : "off"] }
        if let outro { outroEnabled = outro; args += ["--outro", outro ? "on" : "off"] }
        Task { _ = try? await core.call(args) }
    }

    // MARK: outro (plays when the window closes or you quit)

    /// Returns true when the app may quit right now.
    func quitNow(reply: Bool) -> Bool {
        if outroActive { finishOutro(); return false }          // pressed again: skip it
        if !outroEnabled || outroPlayed { return true }
        quitReply = reply
        outroActive = true
        return false
    }

    func finishOutro() {
        guard outroActive else { return }
        outroActive = false
        outroPlayed = true
        if quitReply { NSApp.reply(toApplicationShouldTerminate: true) } else { NSApp.terminate(nil) }
    }

    func saveKey(_ key: String) {
        Task {
            do { _ = try await core.call(["set-key", key]); refresh() }
            catch { errorMessage = error.localizedDescription }
        }
    }
}


// MARK: - Instance content, worlds, skins, cursor

extension Store {
    func folder(_ inst: Instance, _ sub: String) -> URL {
        URL(fileURLWithPath: root).appendingPathComponent("instances").appendingPathComponent(inst.id)
            .appendingPathComponent("minecraft").appendingPathComponent(sub)
    }

    func openContentFolder(_ inst: Instance, kind: String) {
        let sub = ["mods": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks", "saves": "saves", "datapack": "saves", "crash-reports": "crash-reports"][kind] ?? "mods"
        let url = folder(inst, sub)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        NSWorkspace.shared.open(url)
    }

    private func worldArgs(_ w: String?) -> [String] { w.map { ["--world", $0] } ?? [] }

    func loadContent(_ inst: Instance, _ kind: String, world: String? = nil) async {
        do {
            let ev = try await core.call(["content-list", inst.id, "--kind", kind] + worldArgs(world))
            content = (ev.first(where: { $0.type == "content" })?.list("items") ?? []).map(ContentItem.init)
        } catch { errorMessage = error.localizedDescription }
    }

    func toggleContent(_ inst: Instance, _ kind: String, _ item: ContentItem, world: String? = nil) {
        Task {
            do {
                _ = try await core.call(["content-toggle", inst.id, "--kind", kind, "--file", item.id] + worldArgs(world))
                await loadContent(inst, kind, world: world)
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func removeContent(_ inst: Instance, _ kind: String, _ item: ContentItem, world: String? = nil) {
        let a = NSAlert()
        a.messageText = "Delete “\(item.name)”?"
        a.addButton(withTitle: "Delete")
        a.addButton(withTitle: "Cancel")
        a.alertStyle = .warning
        guard a.runModal() == .alertFirstButtonReturn else { return }
        Task {
            do {
                _ = try await core.call(["content-remove", inst.id, "--kind", kind, "--file", item.id] + worldArgs(world))
                await loadContent(inst, kind, world: world)
                refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func searchContent(_ inst: Instance, _ kind: String, _ query: String, _ source: String) async -> [Pack] {
        do {
            var args = ["content-search", inst.id, "--kind", kind, "--source", source]
            if !query.trimmingCharacters(in: .whitespaces).isEmpty { args += ["--query", query] }
            let ev = try await core.call(args)
            return (ev.first(where: { $0.type == "packs" })?.list("packs") ?? []).map(Pack.init)
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
            return []
        }
    }

    func installContent(_ inst: Instance, _ kind: String, _ pack: Pack, world: String? = nil) {
        busy = true
        busyLabel = "Installing \(pack.title)…"
        progress = nil
        Task {
            do {
                _ = try await core.call(["content-install", inst.id, "--kind", kind, "--project", pack.rawID,
                                         "--source", pack.source] + worldArgs(world), onEvent: { [weak self] e in
                    if e.type == "log" { self?.busyLabel = e.str("text") }
                    if e.type == "progress" { self?.progress = (e.int("done"), e.int("total"), e.str("label")) }
                })
                await loadContent(inst, kind, world: world)
                refresh()
            } catch { errorMessage = error.localizedDescription }
            busy = false
            progress = nil
        }
    }

    // worlds
    private func applyWorlds(_ ev: [Event]) {
        guard let w = ev.first(where: { $0.type == "worlds" }) else { return }
        worlds = w.list("worlds").map(World.init)
        backups = w.list("backups").map(Backup.init)
    }

    func loadWorlds(_ inst: Instance) async {
        do { applyWorlds(try await core.call(["worlds", inst.id])) }
        catch { errorMessage = error.localizedDescription }
    }

    func worldAction(_ inst: Instance, _ args: [String]) {
        busy = true
        busyLabel = "Working…"
        Task {
            do { applyWorlds(try await core.call(args)) }
            catch { errorMessage = error.localizedDescription }
            busy = false
        }
    }

    func backupWorld(_ inst: Instance, _ w: World) { worldAction(inst, ["world-backup", inst.id, "--world", w.name]) }
    func restoreBackup(_ inst: Instance, _ b: Backup) { worldAction(inst, ["world-restore", inst.id, "--backup", b.name]) }
    func deleteWorld(_ inst: Instance, _ w: World) {
        let a = NSAlert()
        a.messageText = "Delete world “\(w.name)”?"
        a.informativeText = "Make a backup first if you might want it back."
        a.addButton(withTitle: "Delete")
        a.addButton(withTitle: "Cancel")
        a.alertStyle = .warning
        if a.runModal() == .alertFirstButtonReturn { worldAction(inst, ["world-delete", inst.id, "--world", w.name]) }
    }

    // skins
    private func applySkin(_ ev: [Event]) {
        guard let s = ev.first(where: { $0.type == "skin" }) else { return }
        skin = SkinInfo(username: s.str("username"), path: s.str("path"), slim: s.bool("slim"),
                        capes: s.list("capes").map(Cape.init))
    }

    func loadSkin() async {
        guard account != nil else { skin = nil; return }
        skinLoading = true
        defer { skinLoading = false }
        do { applySkin(try await core.call(["skin"] + accountArgs)) }
        catch { errorMessage = error.localizedDescription }
    }

    private var accountArgs: [String] { account.map { ["--account", $0.id] } ?? [] }

    func uploadSkin(path: String, slim: Bool) {
        skinLoading = true
        Task {
            do { applySkin(try await core.call(["skin-upload", path, "--variant", slim ? "slim" : "classic"] + accountArgs)) }
            catch { errorMessage = error.localizedDescription }
            skinLoading = false
        }
    }

    func setCape(_ id: String?) {
        skinLoading = true
        Task {
            do { applySkin(try await core.call(["cape-set", "--cape", id ?? "none"] + accountArgs)) }
            catch { errorMessage = error.localizedDescription }
            skinLoading = false
        }
    }

    // saved skins (the same library the Python app uses)
    private func applyLibrary(_ ev: [Event]) {
        if let l = ev.first(where: { $0.type == "library" }) { library = l.list("skins").map(SavedSkin.init) }
    }

    func loadLibrary() async {
        do { applyLibrary(try await core.call(["skin-library"])) } catch { errorMessage = error.localizedDescription }
    }

    func saveSkin(path: String, name: String, slim: Bool, id: String?) async -> Bool {
        var args = ["skin-save", path, "--name", name]
        if slim { args.append("--slim") }
        if let id { args += ["--id", id] }
        do { applyLibrary(try await core.call(args)); return true }
        catch { errorMessage = error.localizedDescription; return false }
    }

    func deleteSkin(_ s: SavedSkin) {
        let a = NSAlert()
        a.messageText = "Delete “\(s.name)”?"
        a.informativeText = "It is only removed from this launcher. Your Minecraft account keeps whatever skin it has."
        a.addButton(withTitle: "Delete")
        a.addButton(withTitle: "Cancel")
        a.alertStyle = .warning
        guard a.runModal() == .alertFirstButtonReturn else { return }
        Task {
            do { applyLibrary(try await core.call(["skin-delete", s.id])) } catch { errorMessage = error.localizedDescription }
        }
    }

    func importCurrentSkin() {
        skinLoading = true
        Task {
            do { applyLibrary(try await core.call(["skin-import"] + accountArgs)) } catch { errorMessage = error.localizedDescription }
            skinLoading = false
        }
    }

    func addSkinFile(_ url: URL) {
        Task {
            let name = url.deletingPathExtension().lastPathComponent
            _ = await saveSkin(path: url.path, name: name, slim: false, id: nil)
        }
    }

    func openSkinMaker(from skin: SavedSkin?, accountPath: String? = nil, accountSlim: Bool = false, name: String? = nil) {
        Task {
            var path = skin?.path ?? accountPath
            if path == nil {
                path = (try? await core.call(["skin-template"]))?.first(where: { $0.type == "template" })?.str("path")
            }
            let px = path.flatMap { SkinEditor.loadPixels($0) } ?? [UInt8](repeating: 0, count: 64 * 64 * 4)
            draft = SkinEditor(px: px, name: skin?.name ?? name ?? "My skin", slim: skin?.slim ?? accountSlim, entryID: skin?.id)
        }
    }

    func useSkin(path: String, slim: Bool) { uploadSkin(path: path, slim: slim) }

    // cursor
    private func applyCursors(_ ev: [Event], apply: Bool) {
        guard let c = ev.first(where: { $0.type == "cursors" }) else { return }
        cursorStyles = c.list("styles").map(CursorStyle.init)
        cursorStyle = c.str("style")
        cursorScope = c.str("scope")
        // A custom pointer is only used after you pick one in this session, never silently at startup.
        if apply {
            activeCursor = cursorStyles.first(where: { $0.id == cursorStyle })?.makeCursor()
            if activeCursor == nil { NSCursor.arrow.set() }
        }
    }

    func loadCursors() async {
        do { applyCursors(try await core.call(["cursors"]), apply: false) } catch { errorMessage = error.localizedDescription }
    }

    func setCursor(style: String? = nil, scope: String? = nil) {
        Task {
            var args = ["cursor-set"]
            if let style { args += ["--style", style] }
            if let scope { args += ["--scope", scope] }
            do { applyCursors(try await core.call(args), apply: true) } catch { errorMessage = error.localizedDescription }
        }
    }
}


// MARK: - Import, export, duplicate, mod updates, notifications

import UserNotifications

extension Store {
    func importFile(_ url: URL) {
        runBusy("Importing \(url.lastPathComponent)…", ["import", url.path])
    }

    func pickImport() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = false
        p.message = "Choose a modpack (.mrpack or .zip) or a Spectra instance export"
        if p.runModal() == .OK, let u = p.url { importFile(u) }
    }

    func duplicate(_ inst: Instance) {
        let a = NSAlert()
        a.messageText = "Duplicate “\(inst.name)”"
        a.informativeText = "Copies the mods, settings and worlds into a new instance."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24))
        field.stringValue = inst.name + " copy"
        a.accessoryView = field
        a.addButton(withTitle: "Duplicate")
        a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let name = field.stringValue.trimmingCharacters(in: .whitespaces)
        if !name.isEmpty { runBusy("Copying \(inst.name)…", ["duplicate", inst.id, "--name", name]) }
    }

    func export(_ inst: Instance) {
        let p = NSSavePanel()
        p.nameFieldStringValue = inst.name + ".zip"
        p.message = "Export this instance so you can share it or move it to another Mac"
        guard p.runModal() == .OK, let url = p.url else { return }
        busy = true
        busyLabel = "Exporting \(inst.name)…"
        Task {
            do {
                _ = try await core.call(["export", inst.id, "--out", url.path])
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } catch { errorMessage = error.localizedDescription }
            busy = false
        }
    }

    func checkModUpdates(_ inst: Instance) async {
        checkingUpdates = true
        modCheckDone = false
        defer { checkingUpdates = false }
        do {
            let ev = try await core.call(["mods-check", inst.id])
            modUpdates = (ev.first(where: { $0.type == "mod_updates" })?.list("updates") ?? []).map(ModUpdate.init)
            modCheckDone = true
        } catch { errorMessage = error.localizedDescription }
    }

    func updateMods(_ inst: Instance, _ list: [ModUpdate]) {
        var args = ["mods-update", inst.id]
        for u in list { args += ["--project", u.id] }
        modUpdates.removeAll { u in list.contains(where: { $0.id == u.id }) }
        runBusy("Updating mods…", args)
    }

    func playByID(_ id: String) {
        guard let inst = instances.first(where: { $0.id == id }) else { return }
        selectedID = id
        tab = .home
        play(inst)
    }

    // notifications (only when running as a real .app)
    private var canNotify: Bool { Bundle.main.bundleURL.pathExtension == "app" && Bundle.main.bundleIdentifier != nil }

    func requestNotifications() {
        guard canNotify else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func notify(title: String, body: String) {
        guard canNotify, !NSApp.isActive else { return }
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}


// MARK: - Servers, crash analysis, favorites, backups, Discord

extension Store {
    func loadServers(_ inst: Instance) async {
        do {
            let ev = try await core.call(["servers", inst.id])
            servers = (ev.first(where: { $0.type == "servers" })?.list("servers") ?? []).map(ServerEntry.init)
        } catch { errorMessage = error.localizedDescription }
    }

    func addServer(_ inst: Instance, name: String, ip: String) async {
        do {
            let ev = try await core.call(["server-add", inst.id, "--name", name, "--ip", ip])
            servers = (ev.first(where: { $0.type == "servers" })?.list("servers") ?? []).map(ServerEntry.init)
        } catch { errorMessage = error.localizedDescription }
    }

    func removeServer(_ inst: Instance, _ s: ServerEntry) async {
        do {
            let ev = try await core.call(["server-remove", inst.id, "--ip", s.ip])
            servers = (ev.first(where: { $0.type == "servers" })?.list("servers") ?? []).map(ServerEntry.init)
        } catch { errorMessage = error.localizedDescription }
    }

    func analyzeCrash(_ id: String) async {
        guard !id.isEmpty else { return }
        do {
            let ev = try await core.call(["crash-analyze", id])
            guard let e = ev.first(where: { $0.type == "crash_analysis" }) else { return }
            let issues = e.list("issues").compactMap { $0["message"] as? String }
            analysis = CrashAnalysis(issues: issues, suspects: e.list("suspects").map(CrashSuspect.init),
                                     report: e.raw["report"] as? String)
        } catch { /* the plain crash card still shows */ }
    }

    func disableSuspect(_ s: CrashSuspect) {
        let id = launchingID
        Task {
            do {
                _ = try await core.call(["content-toggle", id, "--kind", "mods", "--file", s.file])
                analysis?.suspects.removeAll { $0.file == s.file }
                refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func setFavorite(_ inst: Instance, _ on: Bool) {
        Task {
            _ = try? await core.call(["update", inst.id, "--favorite", on ? "on" : "off"])
            refresh()
        }
    }

    func setGroup(_ inst: Instance, _ name: String) {
        Task {
            _ = try? await core.call(["update", inst.id, "--group", name])
            refresh()
        }
    }

    func askGroup(_ inst: Instance) {
        let a = NSAlert()
        a.messageText = "Group for “\(inst.name)”"
        a.informativeText = "Instances with the same group name are listed together in the sidebar. Leave empty to remove it from its group."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24))
        field.stringValue = inst.group
        a.accessoryView = field
        a.addButton(withTitle: "Save")
        a.addButton(withTitle: "Cancel")
        if a.runModal() == .alertFirstButtonReturn { setGroup(inst, field.stringValue) }
    }

    func setAutoBackup(_ on: Bool) {
        autoBackup = on
        Task { _ = try? await core.call(["pref-set", "--auto-backup", on ? "on" : "off"]) }
    }

    func setBackupsKeep(_ n: Int) {
        backupsKeep = n
        Task { _ = try? await core.call(["pref-set", "--backups-keep", String(n)]) }
    }

    func setPresence(_ on: Bool) {
        presenceOn = on
        Task { _ = try? await core.call(["pref-set", "--presence", on ? "on" : "off"]) }
    }

    func setDiscordID(_ id: String) {
        Task {
            do {
                _ = try await core.call(["pref-set", "--discord-id", id])
                discordSet = !id.trimmingCharacters(in: .whitespaces).isEmpty
            } catch { errorMessage = error.localizedDescription }
        }
    }
}
