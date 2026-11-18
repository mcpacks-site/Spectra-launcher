import Foundation
import AppKit
import SpectraShared

enum UpdateState: Equatable {
    case idle
    case checking
    case upToDate(String)
    case available(version: String, notes: String)
    case downloading(Double)
    case installing(String)
    case needsPermission(String)
    case done(String)
    case failed(String)
}

private final class Downloader: NSObject, URLSessionDownloadDelegate {
    private var continuation: CheckedContinuation<URL, Error>?
    private let progress: (Double) -> Void
    private var session: URLSession?

    init(progress: @escaping (Double) -> Void) { self.progress = progress }

    func download(_ url: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { cont in
            continuation = cont
            let s = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
            session = s
            s.downloadTask(with: url).resume()
        }
    }

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask, didWriteData _: Int64,
                    totalBytesWritten written: Int64, totalBytesExpectedToWrite total: Int64) {
        if total > 0 { progress(Double(written) / Double(total)) }
    }

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // the system deletes `location` right after this returns, so move it first
        let keep = FileManager.default.temporaryDirectory.appendingPathComponent("spectra-update-\(UUID().uuidString).zip")
        do {
            if let http = downloadTask.response as? HTTPURLResponse, http.statusCode != 200 {
                throw UpdateError.other("Download failed (HTTP \(http.statusCode)).")
            }
            try FileManager.default.moveItem(at: location, to: keep)
            continuation?.resume(returning: keep)
        } catch { continuation?.resume(throwing: error) }
        continuation = nil
        s.finishTasksAndInvalidate()
    }

    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error, let c = continuation { c.resume(throwing: error); continuation = nil }
    }
}

@MainActor
final class UpdateModel: ObservableObject {
    @Published var state: UpdateState = .idle
    @Published var installedVersion: String?
    @Published var spectraPath: String?
    @Published var hasBackup = false

    private var manifest: UpdateManifest?

    private var backupURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Spectra Updater/Backup/Spectra.app")
    }

    init() { refreshLocal() }

    func refreshLocal() {
        if let app = Locate.spectra() {
            installedVersion = Locate.version(of: app)
            spectraPath = app.path
        } else {
            installedVersion = nil
            spectraPath = nil
        }
        hasBackup = FileManager.default.fileExists(atPath: backupURL.path)
    }

    // MARK: check

    func check() async {
        refreshLocal()
        state = .checking
        do {
            guard spectraPath != nil else { throw UpdateError.notInstalled }
            var req = URLRequest(url: SpectraIDs.manifestURL)
            req.cachePolicy = .reloadIgnoringLocalCacheData
            req.timeoutInterval = 20
            let (data, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
                throw UpdateError.other("Couldn't reach the update server (HTTP \(http.statusCode)). Try again later.")
            }
            let m = try UpdateManifest.decode(data)
            try m.verify(publicKeyBase64: UpdateKey.publicKey)      // never show notes from an unsigned manifest
            manifest = m
            let current = installedVersion.flatMap(SemVer.init) ?? SemVer("0")!
            if let latest = SemVer(m.version), latest > current {
                state = .available(version: m.version, notes: m.notes ?? "")
            } else {
                state = .upToDate(installedVersion ?? "")
            }
        } catch {
            state = .failed(Self.message(error))
        }
    }

    // MARK: install

    func install() async {
        guard let m = manifest, let target = Locate.spectra(), let url = m.downloadURL else { return }
        var cleanup: [URL] = []
        defer { cleanup.forEach { try? FileManager.default.removeItem(at: $0) } }
        do {
            try m.verify(publicKeyBase64: UpdateKey.publicKey)

            state = .downloading(0)
            let zip = try await Downloader { [weak self] p in
                Task { @MainActor in self?.state = .downloading(p) }
            }.download(url)
            cleanup.append(zip)

            state = .installing("Checking the download…")
            let digest = try sha256Hex(of: zip)
            guard digest == m.sha256.lowercased() else { throw UpdateError.badChecksum }

            state = .installing("Unpacking…")
            // unpack on the same volume as Spectra so the swap is atomic
            let work = try FileManager.default.url(for: .itemReplacementDirectory, in: .userDomainMask,
                                                   appropriateFor: target, create: true)
            cleanup.append(work)
            try unzipApp(zip, into: work)
            let fresh = work.appendingPathComponent(SpectraIDs.appFolderName)
            guard FileManager.default.fileExists(atPath: fresh.path) else { throw UpdateError.wrongApp("no Spectra.app inside") }
            guard Locate.bundleID(of: fresh) == SpectraIDs.app else { throw UpdateError.wrongApp("wrong bundle id") }
            guard Locate.version(of: fresh) == m.version else { throw UpdateError.wrongApp("version doesn't match the signed one") }

            state = .installing("Closing Spectra…")
            guard await quitRunning(bundleID: SpectraIDs.app) else { throw UpdateError.stillRunning }

            state = .installing("Replacing Spectra…")
            try keepBackup(of: target)
            do {
                _ = try FileManager.default.replaceItemAt(target, withItemAt: fresh)
            } catch {
                if isPermissionError(error) { state = .needsPermission(target.path); return }
                throw error
            }
            clearQuarantine(target)
            refreshLocal()
            state = .done(m.version)
            relaunch(target)
        } catch {
            if case .needsPermission = state { return }
            state = .failed(Self.message(error))
        }
    }

    private func keepBackup(of app: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: backupURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? fm.removeItem(at: backupURL)
        try fm.copyItem(at: app, to: backupURL)       // best effort; failing to back up doesn't block the update
    }

    func rollback() async {
        guard let target = Locate.spectra(), FileManager.default.fileExists(atPath: backupURL.path) else { return }
        state = .installing("Restoring the previous version…")
        guard await quitRunning(bundleID: SpectraIDs.app) else { state = .failed(UpdateError.stillRunning.localizedDescription); return }
        do {
            let tmp = target.deletingLastPathComponent().appendingPathComponent(".Spectra-restore-\(UUID().uuidString).app")
            try FileManager.default.copyItem(at: backupURL, to: tmp)
            _ = try FileManager.default.replaceItemAt(target, withItemAt: tmp)
            clearQuarantine(target)
            refreshLocal()
            state = .done(installedVersion ?? "")
        } catch {
            if isPermissionError(error) { state = .needsPermission(target.path) } else { state = .failed(Self.message(error)) }
        }
    }

    func relaunch(_ app: URL) {
        let cfg = NSWorkspace.OpenConfiguration()
        NSWorkspace.shared.openApplication(at: app, configuration: cfg) { _, _ in }
    }

    private static func message(_ error: Error) -> String {
        if let e = error as? UpdateError { return e.localizedDescription }
        if (error as NSError).domain == NSURLErrorDomain { return "Couldn't connect to the internet. Check your connection and try again." }
        return error.localizedDescription
    }
}
