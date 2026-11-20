import SwiftUI
import AppKit

let sunA = Color(red: 0.55, green: 0.36, blue: 0.98)   // violet
let sunB = Color(red: 0.96, green: 0.45, blue: 0.71)   // pink
let sunC = Color(red: 1.00, green: 0.66, blue: 0.35)   // amber
let accentGradient = LinearGradient(colors: [sunA, sunB, sunC], startPoint: .leading, endPoint: .trailing)

// MARK: - shared look (same as the installer)

struct Backdrop: View {
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

struct GlassPanel: ViewModifier {
    var radius: CGFloat
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(LinearGradient(colors: [.white.opacity(0.35), .white.opacity(0.05)],
                                             startPoint: .top, endPoint: .bottom), lineWidth: 1))
    }
}
extension View {
    func glassPanel(radius: CGFloat = 16) -> some View { modifier(GlassPanel(radius: radius)) }
}

struct GradientButton: ButtonStyle {
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

struct QuietButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .medium)).foregroundStyle(.white.opacity(0.85))
            .padding(.horizontal, 22).frame(height: 46)
            .background(Capsule().fill(.white.opacity(configuration.isPressed ? 0.18 : 0.10)))
            .overlay(Capsule().strokeBorder(.white.opacity(0.2), lineWidth: 1))
    }
}

struct SpinnerRing: View {
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

struct CheckBadge: View {
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
