import SwiftUI
import AppKit
import SpectraShared

private let sunA = Color(red: 0.55, green: 0.36, blue: 0.98)   // violet
private let sunB = Color(red: 0.96, green: 0.45, blue: 0.71)   // pink
private let sunC = Color(red: 1.00, green: 0.66, blue: 0.35)   // amber
private let accentGradient = LinearGradient(colors: [sunA, sunB, sunC], startPoint: .leading, endPoint: .trailing)

struct InstallerView: View {
    @ObservedObject var model: InstallerModel

    var body: some View {
        ZStack {
            Backdrop()
            VStack(spacing: 18) {
                Spacer(minLength: 8)
                header
                content
                    .transition(.opacity.combined(with: .scale(scale: 0.97)))
                Spacer(minLength: 8)
                Text("Not an official Minecraft product. Not affiliated with Mojang or Microsoft.")
                    .font(.system(size: 10)).foregroundStyle(.white.opacity(0.4))
            }
            .padding(.horizontal, 40).padding(.vertical, 28)
            .animation(.spring(response: 0.45, dampingFraction: 0.85), value: model.step)
        }
        .environment(\.colorScheme, .dark)
        .frame(width: 560, height: 560)
    }

    private var header: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle().fill(accentGradient).frame(width: 118, height: 118).blur(radius: 34).opacity(0.7)
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable().frame(width: 92, height: 92)
                    .shadow(color: .black.opacity(0.45), radius: 14, y: 8)
            }
            Text("Spectra").font(.system(size: 36, weight: .bold, design: .rounded)).foregroundStyle(.white)
            Text(subtitle).font(.system(size: 14)).foregroundStyle(.white.opacity(0.65))
        }
    }

    private var subtitle: String {
        switch model.step {
        case .welcome: return "A Minecraft launcher, made for Mac"
        case .working: return "Setting things up"
        case .done: return "You're all set"
        case .failed: return "Something went wrong"
        }
    }

    @ViewBuilder private var content: some View {
        switch model.step {
        case .welcome: welcome
        case .working(let what): working(what)
        case .done(let location): done(location)
        case .failed(let message, let permission): failed(message, permission)
        }
    }

    // MARK: steps

    private var welcome: some View {
        VStack(spacing: 18) {
            HStack(spacing: 10) {
                chip("sparkles", "Liquid Glass")
                chip("arrow.triangle.2.circlepath", "Auto updates")
                chip("checkmark.shield", "Signed releases")
            }
            Toggle(isOn: $model.autoCheck) {
                Text("Check for updates automatically once a day").font(.system(size: 13)).foregroundStyle(.white.opacity(0.85))
            }
            .toggleStyle(.switch).tint(sunB)
            .padding(.horizontal, 16).padding(.vertical, 12)
            .glassPanel()
            Button { Task { await model.install() } } label: {
                Text(model.payloadVersion.isEmpty ? "Install" : "Install  ·  v\(model.payloadVersion)")
            }
            .buttonStyle(GradientButton())
            .keyboardShortcut(.defaultAction)
            Text("Installs Spectra and Spectra Updater into your Applications folder.")
                .font(.system(size: 11)).foregroundStyle(.white.opacity(0.5))
        }
    }

    private func working(_ what: String) -> some View {
        VStack(spacing: 18) {
            SpinnerRing().frame(width: 54, height: 54)
            Text(what).font(.system(size: 14, weight: .medium)).foregroundStyle(.white.opacity(0.85))
        }
        .padding(.vertical, 24)
    }

    private func done(_ location: String) -> some View {
        VStack(spacing: 16) {
            CheckBadge()
            Text("Installed in \(location)").font(.system(size: 13)).foregroundStyle(.white.opacity(0.7))
            VStack(alignment: .leading, spacing: 6) {
                Label("One permission to know about", systemImage: "lock.shield").font(.system(size: 13, weight: .semibold))
                Text("To replace Spectra when an update is ready, macOS may ask you to allow Spectra Updater under System Settings → Privacy & Security → App Management.")
                    .font(.system(size: 12)).foregroundStyle(.white.opacity(0.65)).fixedSize(horizontal: false, vertical: true)
                Button("Open App Management settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }
                    .buttonStyle(.link).font(.system(size: 12)).tint(sunB)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14).glassPanel()
            HStack(spacing: 12) {
                Button("Open Spectra") { model.openSpectra() }
                    .buttonStyle(GradientButton()).keyboardShortcut(.defaultAction)
                Button("Quit") { NSApp.terminate(nil) }.buttonStyle(QuietButton())
            }
        }
    }

    private func failed(_ message: String, _ permission: Bool) -> some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 34)).foregroundStyle(sunC)
            Text(message).font(.system(size: 13)).multilineTextAlignment(.center)
                .foregroundStyle(.white.opacity(0.85)).fixedSize(horizontal: false, vertical: true)
            if permission {
                Text("Allow this installer under System Settings → Privacy & Security → App Management (or Full Disk Access), then try again.")
                    .font(.system(size: 12)).multilineTextAlignment(.center).foregroundStyle(.white.opacity(0.6))
                Button("Open App Management settings") { NSWorkspace.shared.open(SpectraIDs.privacyAppManagementURL) }
                    .buttonStyle(QuietButton())
            }
            Button("Try again") { Task { await model.install() } }.buttonStyle(GradientButton())
        }
    }

    private func chip(_ symbol: String, _ text: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: 11, weight: .semibold)).foregroundStyle(accentGradient)
            Text(text).font(.system(size: 12, weight: .medium)).foregroundStyle(.white.opacity(0.85))
        }
        .padding(.horizontal, 12).padding(.vertical, 7)
        .glassPanel(radius: 20)
    }
}

// MARK: - pieces

private struct Backdrop: View {
    @State private var drift = false
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.07, green: 0.06, blue: 0.16),
                                    Color(red: 0.15, green: 0.08, blue: 0.30),
                                    Color(red: 0.28, green: 0.11, blue: 0.34)],
                           startPoint: .top, endPoint: .bottom)
            Circle().fill(sunA.opacity(0.55)).frame(width: 340, height: 340).blur(radius: 90)
                .offset(x: drift ? -150 : -90, y: drift ? -190 : -140)
            Circle().fill(sunB.opacity(0.45)).frame(width: 300, height: 300).blur(radius: 90)
                .offset(x: drift ? 170 : 120, y: drift ? 200 : 150)
            Circle().fill(sunC.opacity(0.30)).frame(width: 220, height: 220).blur(radius: 80)
                .offset(x: drift ? 120 : 170, y: drift ? -150 : -210)
        }
        .ignoresSafeArea()
        .onAppear { withAnimation(.easeInOut(duration: 7).repeatForever(autoreverses: true)) { drift = true } }
    }
}

private struct GlassPanel: ViewModifier {
    var radius: CGFloat
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(LinearGradient(colors: [.white.opacity(0.35), .white.opacity(0.05)],
                                             startPoint: .top, endPoint: .bottom), lineWidth: 1))
    }
}
private extension View {
    func glassPanel(radius: CGFloat = 16) -> some View { modifier(GlassPanel(radius: radius)) }
}

private struct GradientButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
            .padding(.horizontal, 34).frame(height: 46)
            .background(Capsule().fill(accentGradient))
            .overlay(Capsule().strokeBorder(.white.opacity(0.35), lineWidth: 1))
            .shadow(color: sunB.opacity(0.5), radius: configuration.isPressed ? 6 : 16, y: 6)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

private struct QuietButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .medium)).foregroundStyle(.white.opacity(0.85))
            .padding(.horizontal, 22).frame(height: 46)
            .background(Capsule().fill(.white.opacity(configuration.isPressed ? 0.18 : 0.10)))
            .overlay(Capsule().strokeBorder(.white.opacity(0.2), lineWidth: 1))
    }
}

private struct SpinnerRing: View {
    @State private var spin = false
    var body: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.12), lineWidth: 5)
            Circle().trim(from: 0, to: 0.28)
                .stroke(accentGradient, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                .rotationEffect(.degrees(spin ? 360 : 0))
        }
        .onAppear { withAnimation(.linear(duration: 1).repeatForever(autoreverses: false)) { spin = true } }
    }
}

private struct CheckBadge: View {
    @State private var shown = false
    var body: some View {
        ZStack {
            Circle().fill(accentGradient).frame(width: 58, height: 58)
                .shadow(color: sunB.opacity(0.6), radius: 18)
            Image(systemName: "checkmark").font(.system(size: 26, weight: .bold)).foregroundStyle(.white)
        }
        .scaleEffect(shown ? 1 : 0.3).opacity(shown ? 1 : 0)
        .onAppear { withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) { shown = true } }
    }
}
