# Spectra Launcher

A free, open-source launcher for **Minecraft: Java Edition** with the **Fabric** mod loader.
Create separate instances, install mods and their dependencies with a click, and sign in with your own Microsoft account.

> Spectra Launcher is **not an official Minecraft product** and is **not approved by or associated with Mojang or Microsoft**. It is also not affiliated with the Fabric project.

Website: https://mcpacks-site.github.io/Spectra-launcher/

## Features

- **Instances** - keep separate installs, each with its own Minecraft version, mods, memory and Java settings
- **Automatic setup** - downloads the game files, Fabric Loader, Fabric API and a matching Java runtime (Eclipse Temurin) if you don't have one
- **Mod manager** - search Modrinth, install mods with their required dependencies, and enable, disable or remove them
- **Custom cursors** - pick a pointer style for the launcher; optionally add the Cursors Extended mod to your instances for in-game pointers. On Windows the pointer can also be applied system-wide while the launcher is open.
- **Your own account** - sign in with the Microsoft account that owns Minecraft: Java Edition. Only accounts that own the game can sign in and launch it. No license, authentication or safety checks are bypassed or disabled.

## Requirements

- A Microsoft account that owns **Minecraft: Java Edition**
- Python 3.8 or newer **with tkinter** (included with the installers from python.org on Windows and macOS; on Debian/Ubuntu install it with `sudo apt install python3-tk`)
- An internet connection for the first launch
- No third-party Python packages are needed

## Run it

```bash
python fabric_launcher.py
```

On some systems the command is `python3 fabric_launcher.py`.

## How to use

1. Run the launcher.
2. Click **Accounts**, then **Add Microsoft account**. A Microsoft page opens and the code is copied to your clipboard. Paste it in and sign in with the account that owns Minecraft.
3. Click **Add instance**, choose a Minecraft version, and create it. Fabric API is installed automatically (you can turn this off).
4. Select the instance and click **Launch** (or double-click it). The first launch downloads everything it needs, which can take a few minutes.
5. Use **Edit / Mods** to change memory and Java settings, and to search for and install mods.

## Where your data is stored

Everything stays on your computer, in the `SpectraLauncher` folder:

| System | Location |
|---|---|
| Windows | `%APPDATA%\SpectraLauncher` |
| macOS | `~/Library/Application Support/SpectraLauncher` |
| Linux | `~/.local/share/SpectraLauncher` |

Your instances (worlds and mods) are in `instances/`. Your sign-in tokens are in `accounts.json` in that folder; keep the folder private and don't share that file.

## Privacy

Spectra Launcher runs entirely on your computer. The project runs no servers and collects no data. The launcher connects only to:

- Microsoft, Xbox Live and Mojang - to sign you in, verify you own Minecraft, and download the game
- Fabric - to download the mod loader
- Modrinth - to search for and download mods
- Adoptium - to download Java if you don't have a suitable version

Sign-in uses Microsoft's standard device code flow with the scope `XboxLive.signin offline_access`. Your Microsoft password is never seen by the launcher. The full policy is on the [website](https://mcpacks-site.github.io/Spectra-launcher/#privacy).

## Troubleshooting

- **"CERTIFICATE_VERIFY_FAILED" on macOS** - the launcher normally handles this itself. If it still happens, open the Python folder in Applications and double-click **Install Certificates.command**.
- **"Minecraft login failed"** - the account you signed in with doesn't own Minecraft: Java Edition.
- **A mod isn't listed** - it may not have a Fabric build for the Minecraft version of that instance.

## Contact

hilderbrandzachary@gmail.com
