import SwiftUI
import AppKit
import SpectraShared

struct UpdaterView: View {
    @ObservedObject var model: UpdateModel

    var body: some View {
        VStack(spacing: 16) {
            Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 64, height: 64)
            Text("Spectra Updater").font(.title2.bold())
            if let v = model.installedVersion {
                Text("Installed: Spectra \(v)").font(.callout).foregroundStyle(.secondary)
            }
            content
            Spacer(minLength: 0)
            if model.hasBackup, canRollback {
                Button("Restore previous version") { Task { await model.rollback() } }
                    .buttonStyle(.link).font(.caption)
            }
        }
        .padding(26)
        .frame(width: 460, height: 380)
    }

    private var canRollback: Bool {
        switch model.state {
        case .downloading, .installing, .checking: return false
        default: return true
        }
    }

    @ViewBuilder private var content: some View {
        switch model.state {
        case .idle, .checking:
            ProgressView("Checking for updates…")
        case .upToDate(let v):
            Label("Spectra \(v) is up to date", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
            Button("Check again") { Task { await model.check() } }
        case .available(let version, let notes):
            Text("Spectra \(version) is available").font(.headline)
            if !notes.isEmpty {
                ScrollView { Text(notes).frame(maxWidth: .infinity, alignment: .leading).font(.callout) }
                    .frame(maxHeight: 110)
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.06)))
            }
            Text("Spectra will close, update, and reopen. Your instances and worlds aren't touched.")
                .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("Update now") { Task { await model.install() } }
                .keyboardShortcut(.defaultAction).controlSize(.large)
        case .downloading(let p):
            ProgressView(value: p) { Text("Downloading…") }
        case .installing(let step):
            ProgressView(step)
        case .needsPermission(let path):
            VStack(spacing: 10) {
                Label("macOS needs your permission", systemImage: "lock.shield.fill").font(.headline)
                Text("To replace \(path), allow Spectra Updater under Privacy & Security → App Management, then try again.")
                    .font(.callout).multilineTextAlignment(.center)
                HStack {
                    Button("Open settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }
                    Button("Try again") { Task { await model.check() } }
                }
            }
        case .done(let v):
            Label("Updated to Spectra \(v)", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            Button("Close") { NSApp.terminate(nil) }
        case .failed(let message):
            VStack(spacing: 10) {
                Label("Couldn't update", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                Text(message).font(.callout).multilineTextAlignment(.center)
                Button("Try again") { Task { await model.check() } }
            }
        }
    }
}
