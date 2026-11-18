import Foundation
import AppKit
import SpectraShared

enum InstallStep: Equatable {
    case welcome
    case working(String)
    case done(location: String)
    case failed(String, permission: Bool)
}

@MainActor
final class InstallerModel: ObservableObject {
    @Published var step: InstallStep = .welcome
    @Published var autoCheck = true
    @Published var installedAt: URL?

    var payloadVersion: String {
        (Bundle.main.url(forResource: "payload-version", withExtension: "txt"))
            .flatMap { try? String(contentsOf: $0) }?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    /// /Applications when we can write there, otherwise ~/Applications.
    private func destination() throws -> URL {
        let sys = URL(fileURLWithPath: "/Applications")
        if FileManager.default.isWritableFile(atPath: sys.path) { return sys }
        let home = Locate.homeApplications
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        return home
    }

    func install() async {
        do {
            guard let appZip = Bundle.main.url(forResource: "Spectra-app", withExtension: "zip"),
                  let updZip = Bundle.main.url(forResource: "Spectra-Updater-app", withExtension: "zip") else {
                throw UpdateError.other("This installer is missing its payload. Download it again from the Spectra releases page.")
            }
            let dest = try destination()

            step = .working("Closing Spectra if it's open…")
            guard await quitRunning(bundleID: SpectraIDs.app) else { throw UpdateError.stillRunning }
            _ = await quitRunning(bundleID: SpectraIDs.updater, timeout: 5)

            step = .working("Installing Spectra…")
            try place(zip: appZip, name: SpectraIDs.appFolderName, in: dest)
            step = .working("Installing Spectra Updater…")
            try place(zip: updZip, name: SpectraIDs.updaterFolderName, in: dest)

            let updater = dest.appendingPathComponent(SpectraIDs.updaterFolderName)
            step = .working(autoCheck ? "Setting up daily update checks…" : "Finishing up…")
            if autoCheck { try writeAgent(updater: updater) } else { removeAgent() }

            installedAt = dest.appendingPathComponent(SpectraIDs.appFolderName)
            step = .done(location: dest.path)
        } catch {
            step = .failed((error as? UpdateError)?.localizedDescription ?? error.localizedDescription,
                           permission: isPermissionError(error))
        }
    }

    private func place(zip: URL, name: String, in dest: URL) throws {
        let fm = FileManager.default
        let work = try fm.url(for: .itemReplacementDirectory, in: .userDomainMask,
                              appropriateFor: dest.appendingPathComponent(name), create: true)
        defer { try? fm.removeItem(at: work) }
        try unzipApp(zip, into: work)
        let fresh = work.appendingPathComponent(name)
        guard fm.fileExists(atPath: fresh.path) else { throw UpdateError.other("\(name) wasn't inside the installer payload.") }
        let target = dest.appendingPathComponent(name)
        if fm.fileExists(atPath: target.path) {
            _ = try fm.replaceItemAt(target, withItemAt: fresh)
        } else {
            try fm.moveItem(at: fresh, to: target)
        }
        clearQuarantine(target)
    }

    // MARK: daily update check (a per-user LaunchAgent)

    private var agentPlist: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(SpectraIDs.agentLabel).plist")
    }

    private func writeAgent(updater: URL) throws {
        let exe = updater.appendingPathComponent("Contents/MacOS/SpectraUpdater").path
        let plist: [String: Any] = [
            "Label": SpectraIDs.agentLabel,
            "ProgramArguments": [exe, "--background"],
            "StartInterval": 86400,
            "RunAtLoad": false,
            "ProcessType": "Background",
        ]
        let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try FileManager.default.createDirectory(at: agentPlist.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: agentPlist, options: .atomic)
        let domain = "gui/\(getuid())"
        runTool("/bin/launchctl", ["bootout", domain, agentPlist.path])       // fine if it wasn't loaded
        let r = runTool("/bin/launchctl", ["bootstrap", domain, agentPlist.path])
        if r.status != 0 { runTool("/bin/launchctl", ["load", "-w", agentPlist.path]) }   // older macOS
    }

    private func removeAgent() {
        guard FileManager.default.fileExists(atPath: agentPlist.path) else { return }
        runTool("/bin/launchctl", ["bootout", "gui/\(getuid())", agentPlist.path])
        try? FileManager.default.removeItem(at: agentPlist)
    }

    func openSpectra() {
        guard let app = installedAt else { return }
        NSWorkspace.shared.openApplication(at: app, configuration: NSWorkspace.OpenConfiguration()) { _, _ in
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }
}
