# Code signing setup

The build works without any of this. Each signing step only runs once you add the matching secrets or variables in
**GitHub > your repo > Settings > Secrets and variables > Actions**. Until then Windows shows a SmartScreen warning and
macOS needs right-click > Open.

## Windows: SignPath Foundation (free for open source)

1. Add a LICENSE file to the repo first (SignPath requires an OSI-approved open source license, e.g. MIT).
2. Apply at https://signpath.org and wait for approval. They will ask for your repo, license and build process.
   They may require a short "code signing policy" note in the README, for example:
   "Free code signing provided by SignPath.io, certificate by SignPath Foundation."
3. In SignPath, create a project and an artifact configuration that signs `SpectraLauncher.exe`, plus a signing policy.
4. In GitHub add:
   - Secret `SIGNPATH_API_TOKEN`
   - Variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`
5. Push a tag. The Windows job uploads the unsigned exe, SignPath signs it, and the signed exe is zipped for the release.

Note: a new signing certificate still needs some time to build SmartScreen reputation, so the warning may fade gradually
rather than vanish on day one.

Paid alternatives: Microsoft's Artifact Signing (formerly Trusted Signing) or a certificate from a commercial CA.

## macOS: Developer ID + notarization (Apple Developer Program, paid yearly)

1. Join the Apple Developer Program (https://developer.apple.com/programs/).
2. In Xcode or the developer portal create a **Developer ID Application** certificate, export it from Keychain Access as a
   `.p12` with a password, then run `base64 -i cert.p12 | pbcopy`.
3. Create an app-specific password at https://account.apple.com (Sign-In and Security).
4. In GitHub add these secrets:
   - `MACOS_CERT_P12` (the base64 text), `MACOS_CERT_PASSWORD`
   - `MACOS_SIGN_ID` (for example `Developer ID Application: Your Name (TEAMID)`)
   - `APPLE_ID` (your Apple ID email), `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`
5. Push a tag. The app is signed with the hardened runtime (microphone and camera entitlements are in
   `installer/entitlements.plist`), the disk image is signed, notarized and stapled.
