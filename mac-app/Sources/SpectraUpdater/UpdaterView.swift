import SwiftUI
import AppKit
import SpectraShared

struct UpdaterView: View {
    @ObservedObject var model: UpdateModel

    var body: some View {
        ZStack {
            Backdrop()
            VStack(spacing: 16) {
                Spacer(minLength: 6)
                VStack(spacing: 8) {
                    ZStack {
                        Circle().fill(accentGradient).frame(width: 96, height: 96).blur(radius: 30).opacity(0.7)
                        Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 72, height: 72)
                            .shadow(color: .black.opacity(0.45), radius: 12, y: 6)
                    }
                    Text("Spectra Updater").font(.system(size: 26, weight: .bold, design: .rounded)).foregroundStyle(.white)
                    if let v = model.installedVersion {
                        Text("Installed: Spectra \(v)").font(.system(size: 13)).foregroundStyle(.white.opacity(0.6))
                    }
                }
                content
                    .transition(.opacity.combined(with: .scale(scale: 0.97)))
                Spacer(minLength: 6)
                if model.hasBackup, canRollback {
                    Button("Restore previous version") { Task { await model.rollback() } }
                        .buttonStyle(.link).font(.system(size: 11)).tint(sunB)
                }
            }
            .padding(.horizontal, 36).padding(.vertical, 24)
            .animation(.spring(response: 0.45, dampingFraction: 0.85), value: model.state)
        }
        .environment(\.colorScheme, .dark)
        .frame(width: 520, height: 500)
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
            VStack(spacing: 14) {
                SpinnerRing().frame(width: 44, height: 44)
                Text("Checking for updates…").font(.system(size: 14)).foregroundStyle(.white.opacity(0.8))
            }
        case .upToDate(let v):
            VStack(spacing: 14) {
                CheckBadge()
                Text("Spectra \(v) is up to date").font(.system(size: 15, weight: .medium)).foregroundStyle(.white)
                Button("Check again") { Task { await model.check() } }.buttonStyle(QuietButton())
            }
        case .available(let version, let notes):
            VStack(spacing: 14) {
                Text("Spectra \(version) is available").font(.system(size: 18, weight: .semibold)).foregroundStyle(.white)
                if !notes.isEmpty {
                    ScrollView {
                        Text(notes).font(.system(size: 13)).foregroundStyle(.white.opacity(0.8))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 100).padding(12).glassPanel()
                }
                Text("Spectra will close, update, and reopen. Your instances and worlds aren't touched.")
                    .font(.system(size: 11)).foregroundStyle(.white.opacity(0.55)).multilineTextAlignment(.center)
                Button("Update now") { Task { await model.install() } }
                    .buttonStyle(GradientButton()).keyboardShortcut(.defaultAction)
            }
        case .downloading(let p):
            VStack(spacing: 12) {
                ProgressView(value: p).progressViewStyle(.linear).tint(sunB).frame(width: 280)
                Text("Downloading… \(Int(p * 100))%").font(.system(size: 13)).foregroundStyle(.white.opacity(0.8))
            }
        case .installing(let step):
            VStack(spacing: 14) {
                SpinnerRing().frame(width: 44, height: 44)
                Text(step).font(.system(size: 14)).foregroundStyle(.white.opacity(0.8))
            }
        case .needsPermission(let path):
            VStack(spacing: 12) {
                Label("macOS needs your permission", systemImage: "lock.shield.fill")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                Text("To replace \(path), allow Spectra Updater under Privacy & Security → App Management, then try again.")
                    .font(.system(size: 12)).multilineTextAlignment(.center).foregroundStyle(.white.opacity(0.7))
                HStack {
                    Button("Open settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }.buttonStyle(QuietButton())
                    Button("Try again") { Task { await model.check() } }.buttonStyle(GradientButton())
                }
            }
        case .done(let v):
            VStack(spacing: 14) {
                CheckBadge()
                Text("Updated to Spectra \(v)").font(.system(size: 15, weight: .medium)).foregroundStyle(.white)
                Button("Close") { NSApp.terminate(nil) }.buttonStyle(QuietButton())
            }
        case .failed(let message):
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 30)).foregroundStyle(sunC)
                Text(message).font(.system(size: 13)).multilineTextAlignment(.center).foregroundStyle(.white.opacity(0.85))
                Button("Try again") { Task { await model.check() } }.buttonStyle(GradientButton())
            }
        }
    }
}
