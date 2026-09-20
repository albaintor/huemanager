# HueManager Home Sync for iOS

Companion iPhone/iPad app for HueManager.

Its only Apple-specific responsibility is to access the user's Apple Home database through
HomeKit. HueManager remains responsible for Hue inventory, room matching, heuristics and the
sync plan.

## Generate the Xcode project

This folder uses [XcodeGen](https://github.com/yonaskolb/XcodeGen) so the generated
`.xcodeproj` does not need to be committed.

```bash
brew install xcodegen
cd ios/HueManagerHomeSync
xcodegen generate
open HueManagerHomeSync.xcodeproj
```

## First Xcode setup

1. Select the **HueManagerHomeSync** target.
2. In **Signing & Capabilities**, select your Apple Developer Team.
3. Keep **HomeKit** enabled.
4. If the bundle identifier is already used in your account, change
   `com.albaintor.HueManagerHomeSync` in `project.yml`, regenerate the project and use the
   same value for the background refresh identifier in `Info.plist` and `AppDelegate.swift`.
5. Run the app on your iPhone or iPad.
6. Accept access to **Maison** when iOS asks for it.

No Apple Team ID or signing certificate is stored in this repository.

## App configuration

In the app enter:

- **URL HueManager**: the URL reachable from the iPhone, e.g.
  `http://192.168.1.10:8787` on the LAN or your protected HTTPS URL;
- **Profil Bridge Hue**: the HueManager bridge profile name used by the server;
- **Maison Apple**: the HomeKit home to synchronize.

Use **Tester HueManager** before running the first analysis.

The URL, bridge profile, selected Home and automatic-sync option are stored in iOS
`UserDefaults`.

## Safe automatic mode

Automatic mode only applies a plan when every relevant accessory and room is unambiguous and
the server-side confidence thresholds are satisfied. iOS background execution is best-effort:
`BGAppRefreshTask` is scheduled, but iOS decides when the app is actually woken.

For a migration, the recommended workflow is to keep automatic mode disabled, review the
proposed moves, then apply them manually once. Enable automatic mode only after the mapping is
stable.
