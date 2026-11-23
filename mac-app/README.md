# Spectra for Mac (native, Liquid Glass)

The main Mac version of Spectra. A native SwiftUI app that uses Apple's real Liquid Glass on macOS 26 and
falls back to frosted material on older macOS. **Python is bundled inside the app**, so there is nothing to install.

`../fabric_launcher.py` stays the one place with the launcher logic; the app runs it with `--cli` and reads
JSON lines back. The Windows, Linux and plain Python versions are unchanged.

## What gets built

| Output | What it is |
|---|---|
| `Install Spectra.app` (in `Spectra-Installer.dmg`) | The installer. Carries Spectra and the Updater, puts both in Applications, sets up a daily update check. |
| `Spectra.app` | The launcher. |
| `Spectra Updater.app` | Downloads signed releases from this repo's GitHub releases and swaps them into `Spectra.app`. |
| `Spectra-app.zip`, `latest.json` | What the Updater downloads (the zip) and reads (the signed manifest). Release assets only. |
| `Spectra-Installer-Intel.dmg`, `Spectra-app-intel.zip`, `latest-intel.json` | The same three for Intel Macs. The Intel Updater reads `latest-intel.json`, so each kind of Mac only ever gets its own build. |

## Build

    cd mac-app
    ./build.sh
    open build/Spectra-Installer.dmg

For the Intel version run `ARCH_TAG=intel ./build.sh` (cross-compiles on an Apple Silicon Mac; output goes to `build/` with `-Intel` in the names).

First build downloads Python (cached in `build/cache`). Use Xcode 26+ for real glass. If you get
"permission denied", run `chmod +x build.sh` once.

### In Xcode instead
File > Open the `mac-app` folder, choose the Spectra scheme, Run. For Xcode runs (no bundle) set
`SPECTRA_CORE` to the path of `fabric_launcher.py` and, if you have no system Python, `SPECTRA_PYTHON`.

## Self-updating releases (one-time setup)

Updates are signed with **your own** Ed25519 key. Nothing to do with Apple, no fee.

1. Make the key pair (needs `pip install cryptography`):

       python3 tools/updatekey.py gen private.key update-public.key

2. Commit `mac-app/update-public.key` (public, safe). **Never commit `private.key`.**
3. GitHub repo > Settings > Secrets and variables > Actions > New secret named `SPECTRA_UPDATE_KEY`,
   value = the contents of `private.key`. Keep a backup of that file somewhere safe: if you lose it, existing
   installs can't be updated and people need to reinstall.
4. To release: bump `mac-app/VERSION` (for example `1.0.1`), commit, then publish a GitHub release
   (any tag, e.g. `v1.0.1`). The workflow builds, signs, and attaches `Spectra-Installer.dmg`,
   `Spectra-app.zip` and `latest.json`. The release must be the repo's latest release, because the Updater reads
   `releases/latest/download/latest.json`.

The Updater installs an update only if all of these hold: the manifest signature verifies against the public key
built into the Updater, the download URL is under this repo's `releases/download/`, the zip's SHA-256 matches the
signed one, and the unpacked app has Spectra's bundle id and exactly the signed version. A backup of the previous
version is kept (Updater > "Restore previous version").

If you build locally without `update-public.key`, the Updater is built but refuses to install anything.

## How the Updater is allowed to manage Spectra

The Installer puts `Spectra.app` and `Spectra Updater.app` side by side (in `/Applications`, or `~/Applications` if
that isn't writable) and registers a per-user LaunchAgent that runs the Updater once a day in the background. It
stays invisible unless an update exists. On macOS 13+ an app replacing another app may need
**System Settings > Privacy & Security > App Management** permission; the Installer and the Updater both tell the
user this and have a button that opens that page. (Whether macOS prompts depends on your macOS version and
signing, so this path is the part most worth testing on a clean Mac.)

## Notes
- Unsigned and not notarized: the first time someone opens the **Installer** macOS blocks it. On macOS 15 and later
  they go to System Settings > Privacy & Security > Security and click **Open Anyway** (right-click > Open no longer works there). Apps the Installer places don't carry the download quarantine, so Spectra itself opens normally.
- The Updater updates itself: each release's signed `latest.json` also carries the newest Updater (`Spectra-Updater-app.zip`), which it verifies, swaps in and reopens before checking for Spectra updates.
- CurseForge needs your own free API key (Settings), stored locally only.
- Packs whose authors blocked third-party downloads open their CurseForge page instead of installing.

## Extras added in this version
- **Servers tab** (per instance): save servers and press Join to start Minecraft already connected.
- **Automatic world backups** before each launch (Settings: on/off and how many to keep per world).
- **Crash analysis**: the crash card names likely culprit mods and offers "Turn off".
- **Favorites and groups** in the sidebar (hero "…" menu).
- **Discord Rich Presence** (Settings): needs your own free Discord application ID.
- Java is downloaded automatically for each Minecraft version (nothing to set up).
- **Launch checks** before Play: wrong Java, too much or too little memory, duplicate mods, a missing Fabric API, mods built for another Minecraft version, low disk, each with a one-click fix.
- **Support file** (hero "…" menu and the crash card): a zip with logs, settings and mod list for asking for help. Tokens and your player name are removed; it never includes accounts.
- **Mod list sharing**: copy a short code (or save a file) with just the mods, and a friend imports it from the import menu.
- **Account switcher**: click the account chip to pick between signed-in accounts.
- **Voice chat mods** (Simple Voice Chat etc.): the app now declares microphone access so macOS can ask for permission.
