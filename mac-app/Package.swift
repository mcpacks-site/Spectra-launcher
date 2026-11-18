// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Spectra",
    platforms: [.macOS(.v13)],
    targets: [
        // shared bits: version compare, signed-manifest checking, where Spectra lives
        .target(name: "SpectraShared", path: "Sources/SpectraShared"),
        // the launcher itself
        .executableTarget(name: "Spectra", dependencies: ["SpectraShared"], path: "Sources/Spectra"),
        // downloads signed updates from the Spectra GitHub releases and swaps them into Spectra.app
        .executableTarget(name: "SpectraUpdater", dependencies: ["SpectraShared"], path: "Sources/SpectraUpdater"),
        // installs Spectra.app + Spectra Updater.app (payload embedded by build.sh)
        .executableTarget(name: "SpectraInstaller", dependencies: ["SpectraShared"], path: "Sources/SpectraInstaller"),
    ]
)
