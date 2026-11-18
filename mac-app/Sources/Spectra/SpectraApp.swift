import SwiftUI
import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)      // lets `swift run` builds get a window and a Dock icon
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Store.shared.quitNow(reply: true) ? .terminateNow : .terminateLater
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        let recent = Store.shared.instances.filter { $0.lastPlayed > 0 }.sorted { $0.lastPlayed > $1.lastPlayed }.prefix(5)
        for inst in recent {
            let item = NSMenuItem(title: "Play \(inst.name)", action: #selector(dockPlay(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = inst.id
            menu.addItem(item)
        }
        return menu.items.isEmpty ? nil : menu
    }

    @objc private func dockPlay(_ item: NSMenuItem) {
        if let id = item.representedObject as? String { Store.shared.playByID(id) }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct SpectraApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var store = Store.shared

    var body: some Scene {
        WindowGroup("Spectra Launcher") {
            RootView()
                .id("\(store.accent)|\(store.theme)|\(store.liquidGlass)")
                .environmentObject(store)
                .frame(minWidth: 980, minHeight: 640)
                .preferredColorScheme(store.theme == "light" ? .light : .dark)
                .task { store.refresh(); await store.loadCursors() }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1180, height: 740)
    }
}
