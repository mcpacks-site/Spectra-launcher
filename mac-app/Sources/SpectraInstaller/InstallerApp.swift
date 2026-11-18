import SwiftUI
import AppKit

@MainActor
final class InstallerDelegate: NSObject, NSApplicationDelegate {
    let model = InstallerModel()
    var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 500, height: 440),
                         styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        w.title = "Install Spectra"
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: InstallerView(model: model))
        w.center()
        w.makeKeyAndOrderFront(nil)
        window = w
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
enum InstallerMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = InstallerDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
