import SwiftUI
import AppKit

private func bytes(_ n: Int) -> String {
    ByteCountFormatter.string(fromByteCount: Int64(n), countStyle: .file)
}

private func dateText(_ t: Int) -> String {
    let f = DateFormatter()
    f.dateStyle = .medium
    f.timeStyle = .short
    return f.string(from: Date(timeIntervalSince1970: TimeInterval(t)))
}

struct PanelHeader<Trailing: View>: View {
    let title: String
    @ViewBuilder var trailing: () -> Trailing
    var body: some View {
        HStack {
            Text(title.uppercased()).font(.system(size: 11, weight: .semibold)).tracking(1).foregroundStyle(T.dim)
            Spacer()
            trailing()
        }
    }
}

// MARK: - Mods / resource packs / shaders

struct ContentTab: View {
    @EnvironmentObject var store: Store
    let inst: Instance
    let kind: String            // mods | resourcepack | shader | datapack

    @State private var query = ""
    @State private var source = "modrinth"
    @State private var hits: [Pack] = []
    @State private var searching = false
    @State private var world = ""
    private var worldArg: String? { kind == "datapack" ? (world.isEmpty ? nil : world) : nil }

    private var noun: String { ["mods": "mod", "resourcepack": "resource pack", "shader": "shader pack", "datapack": "datapack"][kind] ?? "item" }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            installed
            search
        }
        .frame(height: 470)
        .task(id: "\(inst.id)|\(kind)") {
            hits = []
            if kind == "datapack" {
                await store.loadWorlds(inst)
                if world.isEmpty || !store.worlds.contains(where: { $0.name == world }) { world = store.worlds.first?.name ?? "" }
            }
            if kind != "datapack" || !world.isEmpty { await store.loadContent(inst, kind, world: worldArg) }
        }
        .task(id: world) {
            if kind == "datapack" && !world.isEmpty { await store.loadContent(inst, kind, world: world) }
        }
        .task(id: "\(inst.id)|\(kind)|\(source)|\(query)") {
            try? await Task.sleep(nanoseconds: 350_000_000)
            if Task.isCancelled { return }
            if kind == "datapack" && world.isEmpty { hits = []; return }
            if source == "curseforge" && !store.hasCurseForgeKey { hits = []; return }
            searching = true
            let r = await store.searchContent(inst, kind, query, source)
            if !Task.isCancelled { hits = r }
            searching = false
        }
    }

    private var installed: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "Installed · \(store.content.count)") {
                HStack(spacing: 8) {
                    if kind == "mods" && ["fabric", "quilt", "forge", "neoforge"].contains(inst.loader) && !inst.perf {
                        Button("Add performance mods") { store.boost(inst) }.glassButton().controlSize(.small)
                    }
                    Button("Folder") { store.openContentFolder(inst, kind: kind) }.glassButton().controlSize(.small)
                }
            }
            if kind == "datapack" {
                if store.worlds.isEmpty {
                    Text("Datapacks live inside a world. Start the game once and create a world first.")
                        .font(.callout).foregroundStyle(T.dim)
                } else {
                    Picker("World", selection: $world) {
                        ForEach(store.worlds) { Text($0.name).tag($0.name) }
                    }
                }
            }
            if kind == "mods" { updatesPanel }
            ScrollView {
                LazyVStack(spacing: 6) {
                    ForEach(store.content) { item in
                        HStack(spacing: 10) {
                            Toggle("", isOn: Binding(get: { item.enabled },
                                                     set: { _ in store.toggleContent(inst, kind, item, world: worldArg) }))
                                .toggleStyle(.switch).labelsHidden().tint(T.accent)
                            Text(item.name).lineLimit(1)
                                .foregroundStyle(item.enabled ? Color.primary : T.dim)
                            Spacer(minLength: 0)
                            Button { store.removeContent(inst, kind, item, world: worldArg) } label: { Image(systemName: "trash") }
                                .buttonStyle(.plain).foregroundStyle(T.dim)
                        }
                        .padding(.horizontal, 10).padding(.vertical, 7)
                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.05)))
                    }
                    if store.content.isEmpty {
                        Text("Nothing installed yet. Search on the right.").foregroundStyle(T.dim)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 6)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .glass(cornerRadius: 22)
    }

    private var updatesPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Button(store.checkingUpdates ? "Checking…" : "Check for mod updates") {
                    Task { await store.checkModUpdates(inst) }
                }
                .glassButton().controlSize(.small).disabled(store.checkingUpdates || store.running)
                if !store.modUpdates.isEmpty {
                    Button("Update all (\(store.modUpdates.count))") { store.updateMods(inst, store.modUpdates) }
                        .glassButton(prominent: true).controlSize(.small)
                }
                Spacer()
            }
            if store.modCheckDone && store.modUpdates.isEmpty {
                Text("Everything Spectra installed is up to date.").font(.caption).foregroundStyle(T.dim)
            }
            ForEach(store.modUpdates) { u in
                HStack {
                    Text(u.title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    Text("\(u.current) → \(u.latest)").font(.caption).foregroundStyle(T.dim).lineLimit(1)
                    Spacer()
                    Button("Update") { store.updateMods(inst, [u]) }.glassButton().controlSize(.mini)
                }
            }
        }
    }

    private var search: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "Find \(noun)s") {
                Picker("", selection: $source) {
                    Text("Modrinth").tag("modrinth")
                    Text("CurseForge").tag("curseforge")
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 200)
            }
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(T.dim)
                TextField("Search \(noun)s for Minecraft \(inst.version)", text: $query).textFieldStyle(.plain)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.07)))

            if source == "curseforge" && !store.hasCurseForgeKey {
                VStack(spacing: 8) {
                    Text("CurseForge needs your own free API key.").foregroundStyle(T.dim)
                    Button("Open Settings") { store.tab = .settings }.glassButton(prominent: true)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(hits) { pack in
                            HStack(spacing: 10) {
                                AsyncImage(url: pack.icon) { img in
                                    img.resizable().scaledToFill()
                                } placeholder: {
                                    Rectangle().fill(Color.primary.opacity(0.1))
                                }
                                .frame(width: 40, height: 40)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(pack.title).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                                    Text(pack.summary).font(.caption).foregroundStyle(T.dim).lineLimit(1)
                                }
                                Spacer(minLength: 0)
                                if pack.blocked {
                                    Button("Open") { if let u = pack.url { NSWorkspace.shared.open(u) } }
                                        .glassButton().controlSize(.small)
                                } else {
                                    Button("Install") { store.installContent(inst, kind, pack, world: worldArg) }
                                        .glassButton(prominent: true).controlSize(.small)
                                }
                            }
                        }
                        if searching && hits.isEmpty { ProgressView().padding(20) }
                        if !searching && hits.isEmpty {
                            Text("No results.").foregroundStyle(T.dim).padding(.top, 6)
                        }
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .glass(cornerRadius: 22)
    }
}

// MARK: - Worlds & backups

struct WorldsTab: View {
    @EnvironmentObject var store: Store
    let inst: Instance

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 10) {
                PanelHeader(title: "Worlds · \(store.worlds.count)") {
                    Button("Folder") { store.openContentFolder(inst, kind: "saves") }.glassButton().controlSize(.small)
                }
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(store.worlds) { w in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(w.name).font(.system(size: 14, weight: .semibold)).lineLimit(1)
                                    Text("\(bytes(w.size))  ·  \(dateText(w.played))").font(.caption).foregroundStyle(T.dim)
                                }
                                Spacer()
                                Button("Back up") { store.backupWorld(inst, w) }.glassButton(prominent: true).controlSize(.small)
                                Button(role: .destructive) { store.deleteWorld(inst, w) } label: { Image(systemName: "trash") }
                                    .glassButton().controlSize(.small)
                            }
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.05)))
                        }
                        if store.worlds.isEmpty {
                            Text("No worlds yet. Play once to create one.").foregroundStyle(T.dim)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
            .padding(16).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).glass(cornerRadius: 22)

            VStack(alignment: .leading, spacing: 10) {
                PanelHeader(title: "Backups · \(store.backups.count)") { EmptyView() }
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(store.backups) { b in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(b.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                                    Text("\(bytes(b.size))  ·  \(dateText(b.created))").font(.caption).foregroundStyle(T.dim)
                                }
                                Spacer()
                                Button("Restore") { store.restoreBackup(inst, b) }.glassButton().controlSize(.small)
                            }
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.05)))
                        }
                        if store.backups.isEmpty {
                            Text("No backups yet.").foregroundStyle(T.dim).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
            .padding(16).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).glass(cornerRadius: 22)
        }
        .frame(height: 440)
        .task(id: inst.id) { await store.loadWorlds(inst) }
    }
}
