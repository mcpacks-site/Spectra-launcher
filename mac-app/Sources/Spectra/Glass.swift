import SwiftUI

// Liquid Glass lives behind two guards so the same source builds everywhere:
//  - `#if compiler(>=6.2)` : only compiled when the Xcode 26 SDK is present
//  - `#available(macOS 26)`: only used when running on macOS 26 or newer
// Anything older gets a frosted-material look instead.

#if compiler(>=6.2)
@available(macOS 26, *)
private func makeGlass(tint: Color?, interactive: Bool) -> Glass {
    var g = Glass.regular
    if let tint { g = g.tint(tint) }
    if interactive { g = g.interactive() }
    return g
}
#endif

extension View {
    /// Liquid Glass surface (macOS 26+), frosted material before that, flat card when the toggle is off.
    @ViewBuilder
    func glass(cornerRadius: CGFloat = 22, tint: Color? = nil, interactive: Bool = false) -> some View {
        if !Palette.glassOn {
            self.flatSurface(cornerRadius: cornerRadius, tint: tint)
        } else {
            #if compiler(>=6.2)
            if #available(macOS 26, *) {
                self.glassEffect(makeGlass(tint: tint, interactive: interactive),
                                 in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            } else {
                self.frostedFallback(cornerRadius: cornerRadius, tint: tint)
            }
            #else
            self.frostedFallback(cornerRadius: cornerRadius, tint: tint)
            #endif
        }
    }

    @ViewBuilder
    func glassCapsule(tint: Color? = nil, interactive: Bool = false) -> some View {
        if !Palette.glassOn {
            self.background(Capsule().fill(T.card))
                .overlay(Capsule().strokeBorder(T.line, lineWidth: 1))
        } else {
            #if compiler(>=6.2)
            if #available(macOS 26, *) {
                self.glassEffect(makeGlass(tint: tint, interactive: interactive), in: Capsule())
            } else {
                self.background(Capsule().fill(.ultraThinMaterial))
                    .overlay(Capsule().strokeBorder(.white.opacity(0.22), lineWidth: 1))
            }
            #else
            self.background(Capsule().fill(.ultraThinMaterial))
                .overlay(Capsule().strokeBorder(.white.opacity(0.22), lineWidth: 1))
            #endif
        }
    }

    fileprivate func flatSurface(cornerRadius: CGFloat, tint: Color?) -> some View {
        self.background(
            ZStack {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).fill(T.card)
                if let tint {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).fill(tint.opacity(0.25))
                }
            }
        )
        .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).strokeBorder(T.line, lineWidth: 1))
    }

    fileprivate func frostedFallback(cornerRadius: CGFloat, tint: Color?) -> some View {
        self.background(
            ZStack {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).fill(.ultraThinMaterial)
                if let tint {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).fill(tint.opacity(0.25))
                }
            }
        )
        .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .strokeBorder(LinearGradient(colors: [.white.opacity(0.45), .white.opacity(0.08)],
                                         startPoint: .top, endPoint: .bottom), lineWidth: 1))
    }

    /// Glass button; `prominent` is the tinted primary action.
    @ViewBuilder
    func glassButton(prominent: Bool = false) -> some View {
        if !Palette.glassOn {
            if prominent { self.buttonStyle(.borderedProminent).tint(T.accent) } else { self.buttonStyle(.bordered) }
        } else {
            #if compiler(>=6.2)
            if #available(macOS 26, *) {
                if prominent { self.buttonStyle(.glassProminent).tint(T.accent) } else { self.buttonStyle(.glass) }
            } else {
                if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
            }
            #else
            if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
            #endif
        }
    }
}

/// Lets nearby glass shapes blend and morph together on macOS 26.
struct GlassGroup<Content: View>: View {
    var spacing: CGFloat = 16
    @ViewBuilder var content: () -> Content

    var body: some View {
        #if compiler(>=6.2)
        if #available(macOS 26, *), Palette.glassOn {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
        #else
        content()
        #endif
    }
}

/// Dark Spectra backdrop with soft colour so the glass has something to refract.
struct AppBackground: View {
    var body: some View {
        ZStack {
            T.bg
            Circle().fill(T.accent.opacity(0.22)).frame(width: 420, height: 420)
                .blur(radius: 120).offset(x: -380, y: 300)
            Circle().fill(Color(red: 0.45, green: 0.25, blue: 0.85).opacity(Palette.light ? 0.16 : 0.28)).frame(width: 460, height: 460)
                .blur(radius: 130).offset(x: 380, y: -260)
            Circle().fill(T.accent2.opacity(0.16)).frame(width: 340, height: 340)
                .blur(radius: 110).offset(x: 200, y: 330)
        }
        .ignoresSafeArea()
    }
}
