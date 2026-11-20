import SwiftUI
import SpectraShared
import AppKit

struct SettingsCard<Content: View>: View {
    @ViewBuilder var content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content() }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glass(cornerRadius: 22)
    }
}

struct FieldLabel: View {
    let text: String
    var body: some View {
        Text(text.uppercased()).font(.system(size: 11, weight: .semibold)).tracking(1).foregroundStyle(T.dim)
    }
}

struct SettingsView: View {
    @EnvironmentObject var store: Store
    @State private var key = ""
    @State private var discordID = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("PREFERENCES").font(.system(size: 12, weight: .bold)).tracking(1).foregroundStyle(T.accent)
                Text("Settings").font(.system(size: 40, weight: .bold))
                Text("Look and feel, CurseForge, accounts, and where your data lives.").foregroundStyle(T.dim)
                    .padding(.bottom, 6)

                SettingsCard {
                    HStack(alignment: .top, spacing: 40) {
                        VStack(alignment: .leading, spacing: 10) {
                            FieldLabel(text: "Theme")
                            HStack(spacing: 8) {
                                themeButton("Dark", "dark")
                                themeButton("Light", "light")
                            }
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            FieldLabel(text: "Accent colour")
                            HStack(spacing: 12) {
                                ForEach(Palette.accents, id: \.key) { a in
                                    Button { store.setLook(accent: a.key) } label: {
                                        ZStack {
                                            Circle().fill(Color(hex: a.a1))
                                            Circle().trim(from: 0.0, to: 0.5).fill(Color(hex: a.a2)).rotationEffect(.degrees(-150))
                                        }
                                        .frame(width: 34, height: 34)
                                        .overlay(Circle().strokeBorder(Color.primary, lineWidth: store.accent == a.key ? 3 : 0).padding(-4))
                                    }
                                    .buttonStyle(.plain).help(a.key.capitalized)
                                }
                            }
                            .padding(4)
                        }
                        Spacer(minLength: 0)
                    }
                }

                SettingsCard {
                    Toggle(isOn: Binding(get: { store.liquidGlass }, set: { store.setGlass($0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Liquid Glass").font(.system(size: 15))
                            Text("See-through glass panels (full effect on macOS 26 or newer). Turn off for plain solid panels.")
                                .font(.caption).foregroundStyle(T.dim)
                        }
                    }
                    .toggleStyle(.switch).tint(T.accent)
                }

                SettingsCard {
                    Toggle(isOn: Binding(get: { store.autoBackup }, set: { store.setAutoBackup($0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Back up worlds before playing").font(.system(size: 15))
                            Text("Saves a zip of any world that changed since its last backup. Restore from the Worlds tab.")
                                .font(.caption).foregroundStyle(T.dim)
                        }
                    }
                    .toggleStyle(.switch).tint(T.accent)
                    if store.autoBackup {
                        Stepper("Keep the last \(store.backupsKeep) automatic backups per world",
                                value: Binding(get: { store.backupsKeep }, set: { store.setBackupsKeep($0) }), in: 1...20)
                            .font(.system(size: 13))
                    }
                }

                SettingsCard {
                    Toggle(isOn: Binding(get: { store.presenceOn }, set: { store.setPresence($0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Discord Rich Presence").font(.system(size: 15))
                            Text("Shows “Playing <instance>” on your Discord profile while the game runs. Only the instance name and Minecraft version are shared.")
                                .font(.caption).foregroundStyle(T.dim)
                        }
                    }
                    .toggleStyle(.switch).tint(T.accent)
                    if store.presenceOn {
                        HStack(spacing: 10) {
                            SecureField(store.discordSet ? "Application ID saved" : "Discord application ID", text: $discordID)
                                .textFieldStyle(.roundedBorder)
                            Button("Save") { store.setDiscordID(discordID); discordID = "" }
                                .glassButton().disabled(discordID.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                        Text("Create a free application at discord.com/developers and paste its Application ID here.")
                            .font(.caption).foregroundStyle(T.dim)
                    }
                }

                SettingsCard {
                    FieldLabel(text: "CurseForge API key")
                    HStack(spacing: 10) {
                        SecureField(store.hasCurseForgeKey ? "Key saved. Paste a new one to replace it" : "Paste your key", text: $key)
                            .textFieldStyle(.plain)
                            .padding(.horizontal, 14).padding(.vertical, 11)
                            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.07)))
                        Button("Save") {
                            if !key.trimmingCharacters(in: .whitespaces).isEmpty { store.saveKey(key); key = "" }
                        }
                        .glassButton(prominent: true).controlSize(.large)
                    }
                    Text("CurseForge only lets apps use its mods and modpacks with a key. Keys are free: sign in at console.curseforge.com, create an API key, and paste it here. It's stored only on this computer and sent only to CurseForge.")
                        .font(.callout).foregroundStyle(T.dim)
                    Button("Get a free key") {
                        if let u = URL(string: "https://console.curseforge.com/") { NSWorkspace.shared.open(u) }
                    }
                    .glassButton().controlSize(.large)
                }

                SettingsCard {
                    Toggle(isOn: Binding(get: { store.splashEnabled }, set: { store.setAnimations(splash: $0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Play the intro animation when Spectra opens").font(.system(size: 15))
                            Text("Click or press any key to skip it.").font(.caption).foregroundStyle(T.dim)
                        }
                    }
                    .toggleStyle(.switch).tint(T.accent)
                    Toggle(isOn: Binding(get: { store.outroEnabled }, set: { store.setAnimations(outro: $0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Play an outro animation when Spectra closes").font(.system(size: 15))
                            Text("Click or press any key to skip it, or close the window again.").font(.caption).foregroundStyle(T.dim)
                        }
                    }
                    .toggleStyle(.switch).tint(T.accent)
                }

                SettingsCard {
                    FieldLabel(text: "Accounts")
                    if store.accounts.isEmpty {
                        Text("No account yet.").foregroundStyle(T.dim)
                        Button("Sign in with Microsoft") { store.startSignIn() }.glassButton(prominent: true).controlSize(.large)
                    } else {
                        ForEach(store.accounts) { a in
                            HStack {
                                SteveFace(size: 30)
                                Text(a.username).font(.system(size: 15, weight: .semibold))
                                Spacer()
                                Button("Sign out") { store.signOut(a) }.glassButton()
                            }
                        }
                    }
                }

                SettingsCard {
                    FieldLabel(text: "Data folder")
                    Text(store.root).font(.system(size: 13, design: .monospaced)).foregroundStyle(T.dim).textSelection(.enabled)
                    Button("Open folder") { NSWorkspace.shared.open(URL(fileURLWithPath: store.root)) }
                        .glassButton().controlSize(.large)
                }

                SettingsCard {
                    FieldLabel(text: "Updates")
                    Text("Spectra \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev")")
                        .font(.system(size: 13)).foregroundStyle(T.dim)
                    if let updater = Locate.updater() {
                        Button("Check for updates") {
                            NSWorkspace.shared.openApplication(at: updater, configuration: NSWorkspace.OpenConfiguration()) { _, _ in }
                        }
                        .glassButton().controlSize(.large)
                    } else {
                        Text("Updates are handled by Spectra Updater, which the Spectra installer sets up.")
                            .font(.caption).foregroundStyle(T.dim)
                    }
                }

                SettingsCard {
                    FieldLabel(text: "Core")
                    Text("Python: \(CoreClient.python()?.path ?? "not found")").font(.caption).foregroundStyle(T.dim).textSelection(.enabled)
                    Text("Script: \(CoreClient.script()?.path ?? "not found")").font(.caption).foregroundStyle(T.dim).textSelection(.enabled)
                }
            }
            .padding(.bottom, 8)
        }
    }

    private func themeButton(_ title: String, _ id: String) -> some View {
        let sel = store.theme == id
        return Button { store.setLook(theme: id) } label: {
            Text(title).font(.system(size: 14, weight: .semibold))
                .foregroundStyle(sel ? T.ink : Color.primary)
                .frame(width: 92, height: 38)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(sel ? AnyShapeStyle(T.gradient) : AnyShapeStyle(Color.primary.opacity(0.08))))
        }
        .buttonStyle(.plain)
    }
}
