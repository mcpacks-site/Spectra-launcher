import SwiftUI
import AppKit
import SpectraShared

struct InstallerView: View {
    @ObservedObject var model: InstallerModel

    var body: some View {
        VStack(spacing: 16) {
            Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 84, height: 84)
            Text("Install Spectra").font(.title.bold())
            content
            Spacer(minLength: 0)
        }
        .padding(30)
        .frame(width: 500, height: 440)
    }

    @ViewBuilder private var content: some View {
        switch model.step {
        case .welcome:
            VStack(spacing: 14) {
                Text("This installs the Spectra launcher and Spectra Updater into your Applications folder. The updater keeps Spectra current by downloading signed releases from Spectra's GitHub page, and refuses anything that fails its signature check.")
                    .multilineTextAlignment(.center).foregroundStyle(.secondary)
                if !model.payloadVersion.isEmpty {
                    Text("Version \(model.payloadVersion)").font(.caption).foregroundStyle(.secondary)
                }
                Toggle("Check for updates automatically once a day", isOn: $model.autoCheck)
                Button("Install") { Task { await model.install() } }
                    .keyboardShortcut(.defaultAction).controlSize(.large)
            }
        case .working(let what):
            ProgressView(what)
        case .done(let location):
            VStack(spacing: 12) {
                Label("Installed in \(location)", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                GroupBox {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("One permission to know about").font(.headline)
                        Text("To replace Spectra when an update is ready, macOS may ask you to allow Spectra Updater under System Settings → Privacy & Security → App Management. If an update ever says macOS blocked it, that's the place to fix it.")
                            .font(.callout).foregroundStyle(.secondary)
                        Button("Open App Management settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }
                            .buttonStyle(.link)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack {
                    Button("Open Spectra") { model.openSpectra() }.keyboardShortcut(.defaultAction)
                    Button("Quit installer") { NSApp.terminate(nil) }
                }
            }
        case .failed(let message, let permission):
            VStack(spacing: 12) {
                Label("Couldn't finish installing", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                Text(message).multilineTextAlignment(.center)
                if permission {
                    Text("Allow this installer under System Settings → Privacy & Security → App Management (or Full Disk Access), then try again.")
                        .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    Button("Open App Management settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }
                }
                Button("Try again") { Task { await model.install() } }
            }
        }
    }
}
