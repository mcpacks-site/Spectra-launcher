import Foundation
import AppKit
import CryptoKit

public enum SpectraIDs {
    public static let app = "site.mcpacks.spectra.mac"
    public static let updater = "site.mcpacks.spectra.updater"
    public static let installer = "site.mcpacks.spectra.installer"
    public static let agentLabel = "site.mcpacks.spectra.updater.check"
    public static let appFolderName = "Spectra.app"
    public static let updaterFolderName = "Spectra Updater.app"
    /// The only place updates are ever fetched from.
    public static let manifestURL = URL(string: "https://github.com/mcpacks-site/Spectra-launcher/releases/latest/download/latest.json")!
    public static let allowedDownloadPrefix = "https://github.com/mcpacks-site/Spectra-launcher/releases/download/"
    public static let privacyAppManagementURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AppBundles")!
}

// MARK: - Versions

public struct SemVer: Comparable, CustomStringConvertible {
    public let parts: [Int]

    public init?(_ text: String) {
        var t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.hasPrefix("v") || t.hasPrefix("V") { t.removeFirst() }
        var nums: [Int] = []
        for piece in t.split(separator: ".") {
            let digits = piece.prefix(while: { $0.isNumber })
            guard let n = Int(digits) else { return nil }
            nums.append(n)
        }
        guard !nums.isEmpty else { return nil }
        parts = nums
    }

    private static func compare(_ a: SemVer, _ b: SemVer) -> Int {
        for i in 0..<max(a.parts.count, b.parts.count) {
            let x = i < a.parts.count ? a.parts[i] : 0
            let y = i < b.parts.count ? b.parts[i] : 0
            if x != y { return x < y ? -1 : 1 }
        }
        return 0
    }
    public static func < (a: SemVer, b: SemVer) -> Bool { compare(a, b) < 0 }
    public static func == (a: SemVer, b: SemVer) -> Bool { compare(a, b) == 0 }
    public var description: String { parts.map(String.init).joined(separator: ".") }
}

// MARK: - Signed update manifest

public enum UpdateError: LocalizedError {
    case noKey, badManifest, badURL, badSignature, badChecksum, wrongApp(String), notInstalled
    case stillRunning, permission(String), other(String)

    public var errorDescription: String? {
        switch self {
        case .noKey: return "This build of the updater has no update key, so it can't verify updates."
        case .badManifest: return "The update information couldn't be read."
        case .badURL: return "The update points somewhere other than Spectra's GitHub releases, so it was ignored."
        case .badSignature: return "The update's signature didn't match. It was NOT installed."
        case .badChecksum: return "The download is corrupted (checksum mismatch). It was NOT installed."
        case .wrongApp(let why): return "The downloaded app isn't the expected Spectra (\(why)). It was NOT installed."
        case .notInstalled: return "Spectra isn't installed yet. Run the Spectra installer first."
        case .stillRunning: return "Spectra is still open. Quit it and try again."
        case .permission(let p): return "macOS didn't let the updater change \(p)."
        case .other(let s): return s
        }
    }
}

public struct UpdateManifest: Decodable {
    public let version: String
    public let notes: String?
    public let url: String
    public let sha256: String
    public let sig: String

    public static func decode(_ data: Data) throws -> UpdateManifest {
        do { return try JSONDecoder().decode(UpdateManifest.self, from: data) } catch { throw UpdateError.badManifest }
    }

    /// Exactly what tools/updatekey.py signs.
    public var signedMessage: Data {
        Data("spectra-update\n\(version)\n\(sha256.lowercased())\n\(url)".utf8)
    }

    public var downloadURL: URL? {
        guard url.hasPrefix(SpectraIDs.allowedDownloadPrefix) else { return nil }
        return URL(string: url)
    }

    public func verify(publicKeyBase64: String) throws {
        guard let keyData = Data(base64Encoded: publicKeyBase64.trimmingCharacters(in: .whitespacesAndNewlines)),
              keyData.count == 32,
              let key = try? Curve25519.Signing.PublicKey(rawRepresentation: keyData) else { throw UpdateError.noKey }
        guard downloadURL != nil else { throw UpdateError.badURL }
        guard SemVer(version) != nil else { throw UpdateError.badManifest }
        guard let sigData = Data(base64Encoded: sig), key.isValidSignature(sigData, for: signedMessage) else {
            throw UpdateError.badSignature
        }
    }
}

public func sha256Hex(of file: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: file)
    defer { try? handle.close() }
    var hasher = SHA256()
    while true {
        let chunk = handle.readData(ofLength: 1 << 20)
        if chunk.isEmpty { break }
        hasher.update(data: chunk)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

// MARK: - Where things live, and small helpers

public enum Locate {
    public static var homeApplications: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
    }

    public static func spectra() -> URL? {
        let candidates = [URL(fileURLWithPath: "/Applications/\(SpectraIDs.appFolderName)"),
                          homeApplications.appendingPathComponent(SpectraIDs.appFolderName)]
        if let hit = candidates.first(where: { FileManager.default.fileExists(atPath: $0.path) }) { return hit }
        return NSWorkspace.shared.urlForApplication(withBundleIdentifier: SpectraIDs.app)
    }

    public static func updater() -> URL? {
        let candidates = [URL(fileURLWithPath: "/Applications/\(SpectraIDs.updaterFolderName)"),
                          homeApplications.appendingPathComponent(SpectraIDs.updaterFolderName)]
        if let hit = candidates.first(where: { FileManager.default.fileExists(atPath: $0.path) }) { return hit }
        return NSWorkspace.shared.urlForApplication(withBundleIdentifier: SpectraIDs.updater)
    }

    public static func version(of app: URL) -> String? {
        Bundle(url: app)?.infoDictionary?["CFBundleShortVersionString"] as? String
    }

    public static func bundleID(of app: URL) -> String? { Bundle(url: app)?.bundleIdentifier }
}

@discardableResult
public func runTool(_ exe: String, _ args: [String]) -> (status: Int32, output: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return (-1, error.localizedDescription) }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

/// Unzips with ditto (keeps bundle structure, symlinks and permissions intact).
public func unzipApp(_ zip: URL, into dir: URL) throws {
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let r = runTool("/usr/bin/ditto", ["-x", "-k", zip.path, dir.path])
    if r.status != 0 { throw UpdateError.other("Couldn't unpack the download: \(r.output)") }
}

public func clearQuarantine(_ app: URL) {
    runTool("/usr/bin/xattr", ["-dr", "com.apple.quarantine", app.path])
}

public func isPermissionError(_ error: Error) -> Bool {
    let ns = error as NSError
    if ns.domain == NSCocoaErrorDomain, [NSFileWriteNoPermissionError, NSFileReadNoPermissionError, 513].contains(ns.code) { return true }
    if ns.domain == NSPOSIXErrorDomain, [Int(EPERM), Int(EACCES)].contains(ns.code) { return true }
    if let under = ns.userInfo[NSUnderlyingErrorKey] as? NSError, under !== ns { return isPermissionError(under) }
    return false
}

/// Quits a running app politely and waits for it to go.
@MainActor
public func quitRunning(bundleID: String, timeout: TimeInterval = 30) async -> Bool {
    let apps = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
    if apps.isEmpty { return true }
    apps.forEach { $0.terminate() }
    let end = Date().addingTimeInterval(timeout)
    while Date() < end {
        if NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).isEmpty { return true }
        try? await Task.sleep(nanoseconds: 300_000_000)
    }
    return false
}
