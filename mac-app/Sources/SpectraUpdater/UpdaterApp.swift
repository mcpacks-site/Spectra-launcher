import SwiftUI
import AppKit
import SpectraShared

@MainActor
final class UpdaterDelegate: NSObject, NSApplicationDelegate {
    let model = UpdateModel()
    var window: NSWindow?
    let background = CommandLine.arguments.contains("--background")

    func applicationDidFinishLaunching(_ notification: Notification) {
        if background {
            // launched by the daily LaunchAgent: stay invisible unless there's something to install
            NSApp.setActivationPolicy(.accessory)
            Task {
                await model.check()
                if case .available = model.state { showWindow() } else { NSApp.terminate(nil) }
            }
        } else {
            showWindow()
            Task { await model.check() }
        }
    }

    func showWindow() {
        NSApp.setActivationPolicy(.regular)
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 500),
                             styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView], backing: .buffered, defer: false)
            w.title = "Spectra Updater"
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isMovableByWindowBackground = true
            w.backgroundColor = NSColor(red: 0.07, green: 0.06, blue: 0.16, alpha: 1)
            w.appearance = NSAppearance(named: .darkAqua)
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: UpdaterView(model: model))
            w.center()
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
enum UpdaterMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = UpdaterDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
