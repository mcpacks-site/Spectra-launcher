name: Build Spectra Launcher

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            name: Windows
            asset: SpectraLauncher-Setup.exe
          - os: macos-latest
            name: macOS
            asset: SpectraLauncher.dmg
          - os: ubuntu-latest
            name: Linux
            asset: SpectraLauncher-Linux.zip
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Tk (Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y python3-tk

      - name: Install PyInstaller
        run: python -m pip install pyinstaller

      - name: Build installer (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          $ver = "${{ github.ref_name }}".TrimStart("v")
          if (-not ($ver -match '^\d+(\.\d+)*$')) { $ver = "0.0.0" }
          pyinstaller --noconfirm --windowed --onedir --icon icon.ico --name SpectraLauncher fabric_launcher.py
          choco install innosetup -y --no-progress
          $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
          if (-not (Test-Path $iscc)) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
          Write-Host "Using $iscc"
          Get-ChildItem dist\SpectraLauncher | Select-Object -First 5
          (Get-Content installer\SpectraLauncher.iss -Raw).Replace("@APPVERSION@", $ver) | Set-Content installer\build.iss -Encoding utf8
          & $iscc "/O$PWD\installer_out" installer\build.iss
          if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE (see the errors above)" }
          Move-Item installer_out\SpectraLauncher-Setup.exe SpectraLauncher-Setup.exe

      - name: Build disk image (macOS)
        if: runner.os == 'macOS'
        run: |
          pyinstaller --noconfirm --windowed --icon icon.icns --osx-bundle-identifier com.spectralauncher.app --name SpectraLauncher fabric_launcher.py
          # Let macOS ask for microphone access on behalf of the launcher (needed for Simple Voice Chat etc.)
          PLIST=dist/SpectraLauncher.app/Contents/Info.plist
          /usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Spectra Launcher needs microphone access so mods like Simple Voice Chat can use your microphone.'" "$PLIST"
          /usr/libexec/PlistBuddy -c "Add :NSCameraUsageDescription string 'Spectra Launcher needs camera access for mods that use it.'" "$PLIST"
          # Re-sign (ad-hoc) after editing the plist
          codesign --force --deep --sign - dist/SpectraLauncher.app
          # Branded drag-to-Applications disk image
          brew install create-dmg
          mkdir dmg_root
          cp -R dist/SpectraLauncher.app dmg_root/
          create-dmg --volname "Spectra Launcher" --volicon icon.icns \
            --background installer/dmg_background.png \
            --window-pos 200 120 --window-size 660 400 --icon-size 100 --text-size 13 \
            --icon "SpectraLauncher.app" 165 210 --hide-extension "SpectraLauncher.app" \
            --app-drop-link 495 210 --no-internet-enable \
            ${{ matrix.asset }} dmg_root \
          || { echo "create-dmg failed, using a plain disk image"; rm -f ${{ matrix.asset }}; ln -s /Applications dmg_root/Applications; hdiutil create -volname "Spectra Launcher" -srcfolder dmg_root -ov -format UDZO ${{ matrix.asset }}; }

      - name: Build (Linux)
        if: runner.os == 'Linux'
        run: |
          pyinstaller --noconfirm --onefile --name SpectraLauncher fabric_launcher.py
          cd dist && zip ../${{ matrix.asset }} SpectraLauncher

      - uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.name }}
          path: ${{ matrix.asset }}

      - name: Attach to release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ matrix.asset }}