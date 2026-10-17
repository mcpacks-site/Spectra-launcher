; Inno Setup script for Spectra Launcher.
; Built by GitHub Actions: iscc /DAppVersion=2.1 installer\SpectraLauncher.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B7C52-3E0A-4C57-9B7E-5A9D2F8E41C3}
AppName=Spectra Launcher
AppVersion={#AppVersion}
AppVerName=Spectra Launcher {#AppVersion}
AppPublisher=Spectra Launcher
AppPublisherURL=https://mcpacks-site.github.io/Spectra-launcher/
AppSupportURL=https://github.com/mcpacks-site/Spectra-launcher/issues
AppUpdatesURL=https://github.com/mcpacks-site/Spectra-launcher/releases
DefaultDirName={autopf}\Spectra Launcher
DefaultGroupName=Spectra Launcher
DisableProgramGroupPage=yes
; Install for the current user by default (no admin prompt); the user can choose "all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\installer_out
OutputBaseFilename=SpectraLauncher-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\SpectraLauncher.exe
UninstallDisplayName=Spectra Launcher
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SpectraLauncher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Spectra Launcher"; Filename: "{app}\SpectraLauncher.exe"
Name: "{autodesktop}\Spectra Launcher"; Filename: "{app}\SpectraLauncher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SpectraLauncher.exe"; Description: "Launch Spectra Launcher"; Flags: nowait postinstall skipifsilent

; Uninstalling removes the program only. Your instances, worlds, mods and sign-in data in
; %APPDATA%\SpectraLauncher are left alone.
