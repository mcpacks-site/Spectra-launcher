import Foundation

/// One JSON line printed by `fabric_launcher.py --cli`.
struct Event: @unchecked Sendable {
    let raw: [String: Any]
    var type: String { raw["type"] as? String ?? "" }
    func str(_ k: String) -> String { raw[k] as? String ?? "" }
    func int(_ k: String) -> Int { (raw[k] as? NSNumber)?.intValue ?? 0 }
    func bool(_ k: String) -> Bool { (raw[k] as? NSNumber)?.boolValue ?? false }
    func dict(_ k: String) -> [String: Any]? { raw[k] as? [String: Any] }
    func list(_ k: String) -> [[String: Any]] { raw[k] as? [[String: Any]] ?? [] }
}

enum CoreError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let m): return m }
    }
}

final class CoreHandle {
    fileprivate let process: Process
    fileprivate let stdin: Pipe
    fileprivate init(process: Process, stdin: Pipe) { self.process = process; self.stdin = stdin }

    /// Ask the core to stop (used to abort the sign-in wait).
    func cancel() {
        stdin.fileHandleForWriting.write(Data("cancel\n".utf8))
        try? stdin.fileHandleForWriting.close()
    }
    func terminate() { if process.isRunning { process.terminate() } }
}

private final class LineBuffer {
    private var data = Data()
    func feed(_ chunk: Data) -> [String] {
        data.append(chunk)
        var lines: [String] = []
        while let nl = data.firstIndex(of: 0x0A) {
            let lineData = data.subdata(in: data.startIndex..<nl)
            data.removeSubrange(data.startIndex...nl)
            if let s = String(data: lineData, encoding: .utf8), !s.trimmingCharacters(in: .whitespaces).isEmpty {
                lines.append(s)
            }
        }
        return lines
    }
}

/// Runs the Python launcher core and turns its output into events.
/// The core stays the single source of launcher logic; this app is only a front end.
final class CoreClient {
    // MARK: locating things

    static func python() -> URL? {
        let fm = FileManager.default
        // The app ships its own Python (build.sh bundles one per CPU type), so nothing needs installing.
        #if arch(arm64)
        let arch = "arm64"
        #else
        let arch = "x86_64"
        #endif
        if let res = Bundle.main.resourceURL {
            let bundled = res.appendingPathComponent("python-\(arch)/bin/python3")
            if fm.isExecutableFile(atPath: bundled.path) { return bundled }
        }
        let env = ProcessInfo.processInfo.environment["SPECTRA_PYTHON"]
        let candidates = [env, "/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                          "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
                          "/usr/bin/python3"].compactMap { $0 }
        return candidates.first(where: { fm.isExecutableFile(atPath: $0) }).map { URL(fileURLWithPath: $0) }
    }

    static func script() -> URL? {
        let fm = FileManager.default
        if let p = ProcessInfo.processInfo.environment["SPECTRA_CORE"], fm.fileExists(atPath: p) {
            return URL(fileURLWithPath: p)
        }
        if let r = Bundle.main.resourceURL?.appendingPathComponent("fabric_launcher.py"),
           fm.fileExists(atPath: r.path) {
            return r
        }
        // Running from the repo (swift run / Xcode): walk up looking for the core.
        var starts = [URL(fileURLWithPath: fm.currentDirectoryPath)]
        if let exe = Bundle.main.executableURL { starts.append(exe.deletingLastPathComponent()) }
        for start in starts {
            var dir = start
            for _ in 0..<8 {
                let f = dir.appendingPathComponent("fabric_launcher.py")
                if fm.fileExists(atPath: f.path) { return f }
                dir = dir.deletingLastPathComponent()
            }
        }
        return nil
    }

    // MARK: running

    @discardableResult
    func spawn(_ args: [String],
               onEvent: @escaping (Event) -> Void,
               onExit: @escaping (Int32) -> Void) throws -> CoreHandle {
        guard let py = Self.python() else {
            throw CoreError.message("Python was not found inside the app. Rebuild with build.sh, or install Python 3 and set SPECTRA_PYTHON.")
        }
        guard let script = Self.script() else {
            throw CoreError.message("Couldn't find fabric_launcher.py. Rebuild the app with build.sh or set SPECTRA_CORE.")
        }
        let process = Process()
        process.executableURL = py
        process.arguments = [script.path, "--cli"] + args
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        process.environment = env
        let out = Pipe(), inp = Pipe()
        process.standardOutput = out
        process.standardError = out
        process.standardInput = inp

        let buffer = LineBuffer()
        out.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                for line in buffer.feed(d) { onEvent(Self.parse(line)) }
            }
        }
        process.terminationHandler = { p in
            // give the last readability callbacks a moment to land on the main queue
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                out.fileHandleForReading.readabilityHandler = nil
                let rest = out.fileHandleForReading.availableData
                if !rest.isEmpty { for line in buffer.feed(rest + Data("\n".utf8)) { onEvent(Self.parse(line)) } }
                onExit(p.terminationStatus)
            }
        }
        try process.run()
        return CoreHandle(process: process, stdin: inp)
    }

    private static func parse(_ line: String) -> Event {
        if let d = line.data(using: .utf8),
           let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
            return Event(raw: obj)
        }
        return Event(raw: ["type": "log", "text": line])
    }

    /// Runs a command to completion and returns every event. Throws the core's error message.
    func call(_ args: [String], onEvent: ((Event) -> Void)? = nil) async throws -> [Event] {
        try await withCheckedThrowingContinuation { cont in
            var events: [Event] = []
            do {
                try spawn(args, onEvent: { e in
                    events.append(e)
                    onEvent?(e)
                }, onExit: { code in
                    if let err = events.first(where: { $0.type == "error" }) {
                        cont.resume(throwing: CoreError.message(err.str("message")))
                    } else if code != 0 {
                        cont.resume(throwing: CoreError.message("The launcher core stopped unexpectedly (code \(code))."))
                    } else {
                        cont.resume(returning: events)
                    }
                })
            } catch {
                cont.resume(throwing: error)
            }
        }
    }
}
