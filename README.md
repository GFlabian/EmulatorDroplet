# emumanager

Spawn lightweight Android emulators from Python with the identity (model, brand, build...)
and screen you want and your app installed, then stop or delete them. One file, standard
library only. It uses the SDK in `..\LightWeight` but keeps its own devices in `.\avds`, so
`lite16` and `EMU1` are never touched.

## Quick start

```python
from emumanager import EmulatorManager

emu = EmulatorManager(verbose=True)          # verbose prints progress to stderr

dev = emu.spawn(model="SM-A528B", brand="samsung", manufacturer="samsung", device="a52sxq",
                width=1080, height=2400, density=450,
                apk=r"C:\Users\flabi\Downloads\1429TestApp.apk", headless=True)

print(dev, dev.serial)                        # emu1 emulator-5554
print(dev.props())                            # model, brand, fingerprint, build id, ...
dev.shell("pm list packages -3")
dev.stop()
dev.start(headless=True)                      # same identity, nothing re-applied
dev.delete()

devs = emu.spawn_many(3, profile="a52s", headless=True)   # boot in parallel
emu.delete_all()
```

`spawn()` returns once the device is ready. If anything goes wrong it deletes the half-made
emulator and raises `EmulatorError`.

## spawn() options

| option | meaning | default |
|---|---|---|
| `name` | emulator name | `emu1`, `emu2`, ... |
| `model`, `brand`, `manufacturer`, `device`, `product`, `build_id`, `fingerprint` | build properties; an unset fingerprint is derived from the others, e.g. `samsung/sdk_gphone64_x86_64/a52sxq:16/...` | the image's own (Google's `sdk_gphone64_x86_64` emulator) |
| `props` | any other properties, e.g. `{"ro.build.display.id": "X", "security_patch": "2026-02-01"}`; short names in `PROP_ALIASES` work too | |
| `profile` | a saved profile (see below) that fills in the screen and properties; explicit options override it | |
| `width`, `height`, `density` | screen | 720 x 1600, 280 dpi |
| `ram_mb`, `cores` | | 2560 (Android 16's minimum), 4 |
| `apk` | path, or list of paths, to install | |
| `username` | username whose Snapchat session (`Sessions/com.snapchat.android/<username>.7z` in object storage) is loaded into `/data/data/com.snapchat.android` | |
| `proxy` | HTTP proxy for this launch only, as `host:port` or `host:port:user:password` (converted to the emulator's `-http-proxy`); not saved — pass it again on later starts, and stop a running device first | |
| `headless` | no emulator window | `False` |
| `slim` | remove 15 preinstalled Google apps and turn off animations on first boot | `True` |
| `android` | Android version: `14`, `15` or `16` (`android-34`, `android-35`, `android-36.1`) | `16` |
| `image` | system image, see `emu.images()` | `android-36.1/google_apis/x86_64` |

A `Device` is the emulator's name as a `str`, so it works anywhere a name does
(`emu.stop(dev)`). It also has `.serial`, `.start()`, `.stop()`, `.delete()`, `.install(apk)`,
`.shell(cmd)`, `.adb(*args)` and `.props(keys)`. Use `emu.device(name)` or `emu.devices()` for
emulators that already exist.

Lower-level calls work too: `create()` then `start()`, plus `set_props()` to change an
existing device and `stop_all()`.

## Profiles

A profile is a `.json` in `.\profiles` with a phone's screen and build properties. Capture
one from a phone plugged in over USB, then spawn emulators from it:

```python
emu.capture_profile("R5CT31JFWLN", "a52s")     # serial from `adb devices`
dev = emu.spawn(profile="a52s", apk=..., headless=True)
```

`profiles\a52s.json` (Samsung Galaxy A52s, SM-A528B) is already captured.

## Local Server API & Web UI

Start the local HTTP server and web control panel (automatically deletes any leftover emulators from previous runs on startup):

```bash
python server.py
# or
python emumanager.py server --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your browser to use the UI, or call the REST API directly:

- `POST /api/emulators` — Create a new emulator asynchronously (`apk`, `username`, `android`, `profile` are mandatory; `proxy` and `headless` are optional). APKs provided as direct download URLs are cached locally in `./apks` so subsequent emulators with the same link skip downloading. Once created, permissions are granted, the Snapchat session is loaded, and `com.snapchat.android` is opened.
- `GET /api/emulators` — List active emulators (with `id`, `action` such as `CREATING` / `IDLE` / `RUNNING_SHELL` / `DELETING`, and granular `status`) as well as `deleted` emulators and their `final_message` (`DELETE_REQUESTED`).
- `GET /api/emulators/{id}` — Inspect a specific active or deleted emulator.
- `GET /api/emulators/{id}/message` — Get a deleted emulator's `final_message` (`DELETE_REQUESTED`).
- `POST /api/emulators/{id}/shell` — Execute an `adb shell` command (`{"command": "..."}`) on an `IDLE` emulator.
- `DELETE /api/emulators/{id}` — Stop and delete an emulator, setting its `final_message` to `DELETE_REQUESTED`.

## Command line

```
python emumanager.py spawn --model SM-A528B --brand samsung --size 1080x2400 --density 450 --apk app.apk --headless
python emumanager.py spawn --profile a52s --count 3 --headless
python emumanager.py spawn --profile a52s --proxy 203.0.113.10:8080:myuser:mypass --headless
python emumanager.py start emu1 --proxy 203.0.113.10:8080
python emumanager.py list
python emumanager.py props emu1                  # show identity
python emumanager.py stop emu1 | --all
python emumanager.py delete emu1 | --all
```

`python emumanager.py -h` lists every command; `spawn -h` lists every option.

## How long it takes

Measured on this PC (headless, Android 16 image):

| step | time |
|---|---|
| `spawn()` with no properties | 55 s |
| `spawn()` with A52s model/brand/device, 1080x2400 screen, Snapchat APK installed | 107 s |
| `spawn_many(2, profile="a52s")`, 48 properties each | 107 s for both |
| `stop()` | 2 s |
| `start()` of an existing device | 21 s |

Properties are written into the device's system image on its first boot. That costs one
extra reboot, once. Every later `start()` is a single plain boot, with nothing re-applied.

## Limits

- The emulator stays Android 16 (API 36) whatever the fingerprint says. Changing
  `ro.build.version.release`/`sdk` on this base breaks apps, so they are left alone.
- `ro.build.version.security_patch` can only go up. An older value than the image's
  (2026-01-05) makes Android reject its own storage keys and the device never finishes
  booting. So an older value, like the A52s's 2025-09-01, is skipped with a warning.
- Don't set `ro.build.type`, `ro.debuggable` or `ro.secure`: they turn off `adb root`, which
  this library needs.
- Devices with changed properties always start with `-writable-system`; that's where the
  properties live.
- Each emulator uses its RAM (2.5 GB by default) and about 1.5 GB of disk. adb supports at
  most 16 local emulators.
