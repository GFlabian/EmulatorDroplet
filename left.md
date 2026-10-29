# What's left: emulator manager

Status as of 2026-10-29: the library does what it was asked to do. See README.md for usage.

## Done
- `spawn()` / `spawn_many()`: one call creates an emulator, boots it with the given props
  (model, brand, ...), screen and RAM, installs APKs, and returns a `Device`.
  `stop` / `delete` / `stop_all` / `delete_all` remove them again. Same as `spawn` on the CLI.
- The full A52s profile (48 props) bakes in and all of it takes effect. The old blocker was
  `ro.build.version.security_patch`. The A52s's 2025-09-01 is older than the image's
  2026-01-05, and KeyMint rejects its storage keys after a rollback, so the device never
  finishes booting. An older patch is now skipped with a warning.
- Baking costs 1 extra reboot instead of 2. After the first `adb remount` the props go
  straight into the overlay's upper dir (`/mnt/scratch/overlay/product/upper/etc/build.prop`),
  so the verity reboot already brings them up.
- An orphaned `qemu-system-x86_64-headless.exe` (parent `emulator.exe` gone) is now seen by
  `is_running` / `stop` / `delete`.
- Tested end to end: plain spawn 55 s; props + A52s screen + Snapchat APK 107 s (app opens
  to its login screen, `adb root` works); restart 21 s with props kept; 2 parallel A52s
  spawns in 107 s.

## Optional, not started
- **Android 14/15:** only `android-36.1` is installed in `..\LightWeight`. On the android-34
  image the ARM translator crashes the test APK.
- **Faster restarts:** quickboot snapshots could cut `start()` from ~21 s to a few seconds,
  at ~2.5 GB of disk per device. Untested together with `-writable-system`.
- **Split APKs:** `.apks`/`.xapk` bundles would need `adb install-multiple`; `install()`
  takes a single `.apk`.
