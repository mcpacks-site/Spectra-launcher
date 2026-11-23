import SwiftUI
import AppKit

// Launch checks, support file, mod list sharing and account switching.

struct LaunchFix: Hashable {
    let label: String
    let args: [String]
}

struct LaunchCheck: Identifiable, Hashable {
    let id: String
    let level: String
    let message: String
    let fixes: [LaunchFix]

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? UUID().uuidString
        level = d["level"] as? String ?? "info"
        message = d["message"] as? String ?? ""
        fixes = (d["fixes"] as? [[String: Any]] ?? []).map {
            LaunchFix(label: $0["label"] as? String ?? "Fix", args: $0["args"] as? [String] ?? [])
        }
    }
}

struct PendingLaunch: Identifiable {
    let id = UUID()
    let inst: Instance
    let server: String?
    var checks: [LaunchCheck]
}

extension Store {
    func fetchChecks(_ inst: Instance) async -> [LaunchCheck] {
        // A broken check must never stop anyone from playing.
        guard let ev = try? await core.call(["launch-check", inst.id]) else { return [] }
        return (ev.first(where: { $0.type == "checks" })?.list("checks") ?? []).map(LaunchCheck.init)
    }

    func applyFix(_ fix: LaunchFix) async {
        guard var p = pendingLaunch else { return }
        do {
            _ = try await core.call(fix.args)
        } catch {
            errorMessage = error.localizedDescription
        }
        refresh()
        p.checks = await fetchChecks(p.inst)
        if p.checks.contains(where: { $0.level != "info" }) {
            pendingLaunch = p
        } else {
            pendingLaunch = nil
            startPlay(p.inst, server: p.server)
        }
    }

    // MARK: support file

    func saveSupportFile(_ inst: Instance) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "Spectra support - \(inst.name).zip"
        panel.message = "A zip with your log, settings and mod list for asking for help. It never contains your account or sign-in."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        busy = true
        busyLabel = "Collecting support info…"
        Task {
            do {
                _ = try await core.call(["support-bundle", inst.id, "--out", url.path])
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } catch { errorMessage = error.localizedDescription }
            busy = false
        }
    }

    // MARK: mod list sharing

    func copyModList(_ inst: Instance) {
        Task {
            do {
                let ev = try await core.call(["modlist-export", inst.id])
                let code = ev.first(where: { $0.type == "exported" })?.str("code") ?? ""
                guard !code.isEmpty else { errorMessage = "Couldn't build a mod list code."; return }
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(code, forType: .string)
                let a = NSAlert()
                a.messageText = "Mod list code copied"
                a.informativeText = "Send it to a friend. In Spectra they choose the import button, then “Import a mod list code…”. It lists the mods only, not your worlds or settings."
                a.runModal()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func saveModList(_ inst: Instance) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = inst.name + ".spectramods"
        panel.message = "Save the mod list so a friend can import it"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task {
            do {
                _ = try await core.call(["modlist-export", inst.id, "--out", url.path])
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func importModList() {
        let a = NSAlert()
        a.messageText = "Import a mod list"
        a.informativeText = "Paste a mod list code, or choose a saved mod list file. Spectra downloads the same mods from Modrinth."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 340, height: 24))
        field.placeholderString = "SPMOD1:…"
        a.accessoryView = field
        a.addButton(withTitle: "Import")
        a.addButton(withTitle: "Choose file…")
        a.addButton(withTitle: "Cancel")
        switch a.runModal() {
        case .alertFirstButtonReturn:
            let code = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if !code.isEmpty { runModListImport(code) }
        case .alertSecondButtonReturn:
            let p = NSOpenPanel()
            p.allowsMultipleSelection = false
            if p.runModal() == .OK, let u = p.url { runModListImport(u.path) }
        default: break
        }
    }

    private func runModListImport(_ codeOrPath: String) {
        busy = true
        busyLabel = "Importing mod list…"
        progress = nil
        Task {
            do {
                let events = try await core.call(["modlist-import", codeOrPath], onEvent: { [weak self] e in
                    if e.type == "progress" { self?.progress = (e.int("done"), e.int("total"), e.str("label")) }
                    if e.type == "log" { self?.busyLabel = e.str("text") }
                })
                if let d = events.first(where: { $0.type == "instance" })?.dict("instance") {
                    selectedID = Instance(d).id
                    tab = .home
                }
                refresh()
            } catch { errorMessage = error.localizedDescription }
            busy = false
            progress = nil
        }
    }

    // MARK: accounts

    func switchAccount(_ a: Account) {
        currentAccount = a.id
        UserDefaults.standard.set(a.id, forKey: "spectra.account")
    }
}

struct LaunchCheckSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var store: Store
    let pending: PendingLaunch

    private var current: PendingLaunch { store.pendingLaunch ?? pending }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Before you play \(pending.inst.name)", systemImage: "checklist")
                .font(.title3.bold())
            Text("Spectra noticed a few things that could cause trouble.").foregroundStyle(.secondary)
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(current.checks) { c in
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: c.level == "warn" ? "exclamationmark.triangle.fill" : "info.circle.fill")
                                .foregroundStyle(c.level == "warn" ? T.warn : T.dim)
                            VStack(alignment: .leading, spacing: 6) {
                                Text(c.message).font(.callout).fixedSize(horizontal: false, vertical: true)
                                HStack {
                                    ForEach(c.fixes, id: \.self) { f in
                                        Button(f.label) { Task { await store.applyFix(f) } }.controlSize(.small)
                                    }
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.06)))
                    }
                }
            }
            .frame(maxHeight: 280)
            HStack {
                Button("Cancel") { store.pendingLaunch = nil }
                Spacer()
                Button("Play anyway") {
                    let p = current
                    store.pendingLaunch = nil
                    store.startPlay(p.inst, server: p.server)
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22).frame(width: 520)
    }
}
