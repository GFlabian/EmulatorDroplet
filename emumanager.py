"""Spawn, stop and delete lightweight Android emulators.

Uses the Android SDK in ..\\LightWeight (emulator, adb, system images) but keeps its
own virtual devices in .\\avds, so devices created elsewhere are never touched.

From Python:
    from emumanager import EmulatorManager
    emu = EmulatorManager()
    dev = emu.spawn(model="SM-A528B", brand="samsung", manufacturer="samsung",
                    width=1080, height=2400, density=450, apk=r"C:\\path\\app.apk", headless=True)
    print(dev, dev.serial, dev.props())      # emu1 emulator-5554 {...}
    dev.shell("pm list packages -3")
    dev.stop(); dev.start()                  # props persist, no re-injection
    dev.delete()                             # or emu.delete_all()

    devs = emu.spawn_many(3, profile="a52s")  # several in parallel

The first boot of an emulator with changed properties bakes them into its system
image, which costs extra reboots once; every later start is a single plain boot.

A profile is a .json file in .\\profiles holding a device's screen and build
properties; capture one from a phone plugged in over USB with capture_profile().

Command line:
    python emumanager.py spawn [NAME] [--model X --brand Y ...] [--size WxH] [--apk FILE] [--headless] [--proxy HOST:PORT[:USER:PASS]]
    python emumanager.py spawn --profile a52s --count 3 --headless
    python emumanager.py create [NAME] [same options]       create without starting
    python emumanager.py start NAME [--headless] [--apk FILE]
    python emumanager.py list | images | profiles
    python emumanager.py capture-profile SERIAL [--name N]  snapshot a connected device
    python emumanager.py props NAME                         show model, brand, build ID, ...
    python emumanager.py props NAME --model X --brand Y [--profile P] [--set ro.some.prop=value]
    python emumanager.py stop NAME | --all
    python emumanager.py delete NAME | --all                stops it first
"""

import argparse
import concurrent.futures
import ctypes
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import py7zr

HERE = Path(__file__).resolve().parent
_default_sdk_fallback = Path("/opt/android-sdk") if (not IS_WINDOWS and Path("/opt/android-sdk").exists()) else (HERE.parent / "LightWeight")
DEFAULT_SDK = Path(
    os.environ.get("EMU_SDK_ROOT")
    or os.environ.get("ANDROID_SDK_ROOT")
    or os.environ.get("ANDROID_HOME")
    or _default_sdk_fallback
)
DEFAULT_AVD_HOME = Path(os.environ.get("EMU_AVD_HOME") or os.environ.get("ANDROID_AVD_HOME") or (HERE / "avds"))
PROFILES_DIR = Path(os.environ.get("EMU_PROFILES", HERE / "profiles"))
APKS_DIR = Path(os.environ.get("EMU_APKS_DIR", HERE / "apks"))
# Android 16 QPR2: its ARM translator runs ARM-only apps that crash on the Android 14 image
DEFAULT_IMAGE = "android-36.1/google_apis/x86_64"
ANDROID_IMAGES = {
    14: "android-34/google_apis/x86_64",
    15: "android-35/google_apis/x86_64",
    16: "android-36.1/google_apis/x86_64",
}
SNAPCHAT_PACKAGE = "com.snapchat.android"

# DigitalOcean Spaces object storage (same bucket/credentials as SnapchatCreationAutomation)
DO_SPACES_BUCKET = os.environ.get("DO_SPACES_BUCKET", "freyafiles")
DO_SPACES_REGION = os.environ.get("DO_SPACES_REGION", "fra1")
DO_SPACES_ENDPOINT = os.environ.get("DO_SPACES_ENDPOINT", f"https://{DO_SPACES_REGION}.digitaloceanspaces.com")
DO_SPACES_ACCESS_KEY = os.environ.get("DO_SPACES_ACCESS_KEY", "DO004M38Y8AD2X6W39D6")
DO_SPACES_SECRET_KEY = os.environ.get("DO_SPACES_SECRET_KEY", "SjOuMnZQkp3jM3Gm1Xi6wEOD9HZX40YOxe7OsUri7Ho")
DO_SPACES_PREFIX = os.environ.get("DO_SPACES_PREFIX", "Sessions")

# adb only auto-detects emulators whose console port is in this range (16 devices)
CONSOLE_PORTS = range(5554, 5586, 2)
STATE_FILE = "emumanager.json"

# Removed on first boot for user 0; restore one with `cmd package install-existing <pkg>`
BLOAT = (
    "com.android.chrome", "com.google.android.apps.docs", "com.google.android.apps.maps",
    "com.google.android.apps.messaging", "com.google.android.apps.photos",
    "com.google.android.apps.wellbeing", "com.google.android.apps.youtube.music",
    "com.google.android.calendar", "com.google.android.contacts", "com.google.android.deskclock",
    "com.google.android.dialer", "com.google.android.feedback", "com.google.android.gm",
    "com.google.android.googlequicksearchbox", "com.google.android.youtube",
)

PERMISSIONS = [
    "android.permission.READ_CONTACTS",
    "android.permission.READ_PHONE_STATE",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
]

# Friendly names for set_props(); any other full property name works too
PROP_ALIASES = {
    "model": "ro.product.model", "brand": "ro.product.brand", "manufacturer": "ro.product.manufacturer",
    "device": "ro.product.device", "product": "ro.product.name", "fingerprint": "ro.build.fingerprint",
    "build_id": "ro.build.id", "display_id": "ro.build.display.id",
    "incremental": "ro.build.version.incremental", "security_patch": "ro.build.version.security_patch",
}
# Writable build.prop files; overrides go into the product one because init loads it last
PROP_FILES = ("/system/build.prop", "/system_ext/etc/build.prop", "/vendor/build.prop", "/product/etc/build.prop")
PROP_TARGET = "/product/etc/build.prop"
# The same file in the upper dir of the overlay that `adb remount` puts over /product
PROP_TARGET_UPPER = "/mnt/scratch/overlay/product/upper/etc/build.prop"
# KeyMint binds its keys, including the ones that unlock /data, to this patch level and rejects
# them once it goes back: an older value than the image's leaves the device stuck at boot with
# adb offline. So it is only ever raised, never lowered.
PATCH_PROP = "ro.build.version.security_patch"

# Properties captured into a profile from a real device. Deliberately excludes
# ro.build.type / ro.debuggable / ro.secure (which would turn off `adb root` and lock the
# device) and ro.build.version.release|sdk (changing these on a different base breaks apps).
CAPTURE_PROP_RE = re.compile(
    r"^ro\.("
    r"product\.([a-z_]+\.)?(model|brand|manufacturer|device|name)"
    r"|build\.(fingerprint|id|display\.id|tags|flavor|product|characteristics"
    r"|version\.(incremental|security_patch))"
    r"|(system|system_ext|vendor|odm|product|bootimage)\.build\.fingerprint"
    r"|product\.board|board\.platform|soc\.(manufacturer|model))$")

class EmulatorError(RuntimeError):
    pass


if IS_WINDOWS:
    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong), ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong), ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_wchar * 260)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    _k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    _k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _k32.CreateToolhelp32Snapshot.argtypes = (ctypes.c_ulong, ctypes.c_ulong)
    _k32.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W))
    _k32.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W))
    _k32.CloseHandle.argtypes = (ctypes.c_void_p,)

    def _alive(pid):
        handle = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(_k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            _k32.CloseHandle(handle)

    def _processes():
        """(pid, parent pid, lower-case exe name) of every process."""
        snap = _k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _PROCESSENTRY32W(dwSize=ctypes.sizeof(_PROCESSENTRY32W))
            found = []
            ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                found.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile.lower()))
                ok = _k32.Process32NextW(snap, ctypes.byref(entry))
            return found
        finally:
            _k32.CloseHandle(snap)
else:
    def _alive(pid):
        if not pid or pid <= 0:
            return False
        try:
            status_file = Path(f"/proc/{pid}/status")
            if status_file.is_file():
                for line in status_file.read_text(errors="ignore").splitlines():
                    if line.startswith("State:") and "Z" in line:
                        return False
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _processes():
        """(pid, parent pid, lower-case exe name) of every process on Linux/POSIX."""
        found = []
        proc_root = Path("/proc")
        if proc_root.is_dir():
            for entry in proc_root.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    stat_text = (entry / "stat").read_text(errors="ignore")
                    lparen = stat_text.find("(")
                    rparen = stat_text.rfind(")")
                    if lparen == -1 or rparen == -1:
                        continue
                    comm = stat_text[lparen + 1 : rparen].lower()
                    rest = stat_text[rparen + 2 :].split()
                    ppid = int(rest[1])
                    found.append((int(entry.name), ppid, comm))
                except Exception:
                    continue
        return found


def _kill_pid(pid):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        for child_pid, parent_pid, _exe in _processes():
            if parent_pid == pid:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _emulator_pids(pid):
    """Live processes of the emulator launched as pid: emulator(.exe) and its qemu-system process."""
    if not pid:
        return []
    return [p for p, parent, exe in _processes()
            if ((p == pid and (exe in ("emulator.exe", "emulator") or exe.startswith("qemu-system")))
                or (parent == pid and exe.startswith("qemu-system")))
            and _alive(p)]


def _port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _clear_readonly(func, path, exc):
    """rmtree error handler: the emulator creates some files read-only (e.g. pstore.bin)."""
    if not isinstance(exc, PermissionError):
        raise exc
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _sh_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def _read_props(path):
    props = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    return props


def _proxy_url(proxy):
    """Convert host:port[:user:password] to the emulator's HTTP proxy URL."""
    if proxy is None:
        return None
    parts = proxy.split(":", 3)
    if (len(parts) not in (2, 4) or not all(parts)
            or not re.fullmatch(r"[A-Za-z0-9._-]+", parts[0])
            or not re.fullmatch(r"[0-9]{1,5}", parts[1])
            or not 1 <= int(parts[1]) <= 65535
            or any(ord(c) < 32 or ord(c) == 127 for c in proxy)):
        raise EmulatorError("proxy must be host:port or host:port:user:password (port 1-65535)")
    host, port = parts[:2]
    auth = f"{parts[2]}:{parts[3]}@" if len(parts) == 4 else ""
    return f"http://{auth}{host}:{port}"


class Device(str):
    """An emulator's name with shortcuts to its EmulatorManager methods.

    Being a str, it can be passed anywhere a name is expected (emu.stop(dev), f"{dev}").
    """

    def __new__(cls, manager, name):
        dev = super().__new__(cls, name)
        dev.manager = manager
        return dev

    def __repr__(self):
        return f"Device({str(self)!r}, serial={self.serial!r})"

    @property
    def name(self):
        return str(self)

    @property
    def serial(self):
        return self.manager.serial(self)

    def start(self, **options):
        return self.manager.start(self, **options)

    def stop(self):
        return self.manager.stop(self)

    def delete(self):
        self.manager.delete(self)

    def install(self, apk):
        self.manager.install(self, apk)

    def load_snapchat_session(self, username):
        self.manager.load_snapchat_session(self, username)

    def start_app(self, package=SNAPCHAT_PACKAGE):
        self.manager.start_app(self, package)

    def adb(self, *args, timeout=60):
        return self.manager.adb(self, *args, timeout=timeout)

    def shell(self, command, timeout=60):
        return self.manager.adb(self, "shell", command, timeout=timeout)

    def props(self, keys=None):
        return self.manager.get_props(self, keys)


class EmulatorManager:
    def __init__(self, sdk_root=DEFAULT_SDK, avd_home=DEFAULT_AVD_HOME, profiles_dir=PROFILES_DIR,
                 apks_dir=APKS_DIR, verbose=False):
        self.sdk_root = Path(sdk_root)
        self.avd_home = Path(avd_home)
        self.profiles_dir = Path(profiles_dir)
        self.apks_dir = Path(apks_dir)
        self.verbose = verbose
        self._baking = set()
        self._lock = threading.RLock()  # parallel spawns: one at a time picks a name/port
        self._apk_locks = {}
        emu_bin = "emulator.exe" if IS_WINDOWS else "emulator"
        adb_bin = "adb.exe" if IS_WINDOWS else "adb"
        self.emulator_exe = self.sdk_root / "emulator" / emu_bin
        self.adb_exe = self.sdk_root / "platform-tools" / adb_bin
        for exe in (self.emulator_exe, self.adb_exe):
            if not exe.is_file():
                raise EmulatorError(f"missing {exe} (is sdk_root correct?)")
        self.avd_home.mkdir(parents=True, exist_ok=True)
        self.apks_dir.mkdir(parents=True, exist_ok=True)
        # Put our platform-tools first on PATH so the emulator spawns THIS adb, not another
        # version elsewhere on PATH: two adb versions fight over the server and knock devices
        # offline (seen with a 37.0.0 adb in the user's PATH vs our 37.0.1).
        self.env = {**os.environ, "ANDROID_SDK_ROOT": str(self.sdk_root),
                    "ANDROID_HOME": str(self.sdk_root), "ANDROID_AVD_HOME": str(self.avd_home),
                    "PATH": str(self.adb_exe.parent) + os.pathsep + os.environ.get("PATH", "")}
        self._server_started = False
        if not IS_WINDOWS:
            self._enable_linux_host_memory_optimizations()

    @staticmethod
    def _enable_linux_host_memory_optimizations():
        """Enable host-level KSM (Kernel Samepage Merging) and zswap on Linux workers.
        Operates purely in the Linux host kernel with zero change to the Android guest.
        """
        tunables = (
            ("/sys/kernel/mm/ksm/pages_to_scan", "800"),
            ("/sys/kernel/mm/ksm/sleep_millisecs", "100"),
            ("/sys/kernel/mm/ksm/use_zero_pages", "1"),
            ("/sys/kernel/mm/ksm/run", "1"),
            ("/sys/module/zswap/parameters/max_pool_percent", "25"),
            ("/sys/module/zswap/parameters/enabled", "Y"),
        )
        for sysfs_path, val in tunables:
            try:
                p = Path(sysfs_path)
                if p.exists():
                    p.write_text(val, encoding="utf-8")
            except Exception:
                pass

    # ---- profiles ------------------------------------------------------------

    def list_profiles(self):
        """Names of saved device profiles."""
        return sorted(p.stem for p in self.profiles_dir.glob("*.json")) if self.profiles_dir.is_dir() else []

    def load_profile(self, name):
        path = self.profiles_dir / f"{name}.json"
        if not path.is_file():
            raise EmulatorError(f"no profile {name!r} in {self.profiles_dir}; have: "
                                f"{', '.join(self.list_profiles()) or 'none'}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_profile(self, name, data):
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        (self.profiles_dir / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return name

    def capture_profile(self, serial, name, description=None):
        """Read a connected device (any adb serial, e.g. a USB phone) into a profile file."""
        raw = self._run_adb("-s", serial, "shell", "getprop", timeout=30)
        if raw.returncode != 0:
            raise EmulatorError(f"cannot read {serial}: {(raw.stderr or raw.stdout).strip()}")
        found = dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]$", raw.stdout, re.M))
        props = {k: found[k] for k in sorted(found) if CAPTURE_PROP_RE.match(k) and found[k]}
        if not props:
            raise EmulatorError(f"{serial} returned no recognizable build properties")
        hardware = {}
        size = self._run_adb("-s", serial, "shell", "wm", "size", timeout=15).stdout
        if m := re.search(r"Physical size:\s*(\d+)x(\d+)", size):
            hardware["width"], hardware["height"] = int(m[1]), int(m[2])
        dens = self._run_adb("-s", serial, "shell", "wm", "density", timeout=15).stdout
        if m := re.search(r"Physical density:\s*(\d+)", dens):
            hardware["density"] = int(m[1])
        data = {
            "name": name,
            "description": description or (f"{found.get('ro.product.manufacturer', '')} "
                                           f"{found.get('ro.product.model', serial)}".strip()),
            "captured": datetime.date.today().isoformat(), "source_serial": serial,
            "hardware": hardware, "props": props,
        }
        self.save_profile(name, data)
        self._log(f"captured profile {name!r} from {serial}: {len(props)} props, {hardware or 'no screen info'}")
        return data

    # ---- queries -------------------------------------------------------------

    def images(self):
        """Installed system images, e.g. 'android-36.1/google_apis/x86_64'."""
        root = self.sdk_root / "system-images"
        return sorted("/".join(p.parent.relative_to(root).parts) for p in root.glob("*/*/*/source.properties"))

    def avds(self):
        """Names of the emulators managed here."""
        return sorted(p.stem for p in self.avd_home.glob("*.ini") if self._avd_dir(p.stem).is_dir())

    def is_running(self, name):
        return bool(_emulator_pids(self._state(name).get("pid")))

    def serial(self, name):
        """adb serial ('emulator-5556') of a running emulator, else None."""
        state = self._state(name)
        return f"emulator-{state['port']}" if _emulator_pids(state.get("pid")) else None

    def status(self):
        rows = []
        for n in self.avds():
            st = self._state(n)
            rows.append({"name": n, "image": st.get("image", "?"), "serial": self.serial(n),
                         "profile": st.get("profile", ""),
                         "pending": bool(st.get("pending_props"))})
        return rows

    # ---- lifecycle -----------------------------------------------------------

    def spawn(self, name=None, *, model=None, brand=None, manufacturer=None, device=None, product=None,
              build_id=None, fingerprint=None, props=None, profile=None, width=None, height=None,
              density=None, ram_mb=None, cores=None, android=None, image=None, apk=None,
              username=None, headless=False, slim=True, timeout=600, proxy=None, on_status=None):
        """Create an emulator, boot it, install apk (URL or path), load session, and start Snapchat.

        apk, username, android, and profile are mandatory.
        apk can be a direct download URL (cached in ./apks) or a local file path.
        """
        def report(msg):
            if on_status is not None:
                on_status(msg)

        apks = [apk] if isinstance(apk, (str, Path)) else list(apk or ())
        apks = [a for a in apks if a is not None and str(a).strip()]
        missing = [flag for flag, val in (("apk", apks), ("username", username and str(username).strip()),
                                          ("android", android), ("profile", profile)) if not val]
        if missing:
            raise EmulatorError(f"missing mandatory parameter(s): {', '.join(missing)}")
        resolved_apks = [self.resolve_apk(a, on_status=on_status) for a in apks]
        named = {"model": model, "brand": brand, "manufacturer": manufacturer, "device": device,
                 "product": product, "build_id": build_id, "fingerprint": fingerprint}
        wanted = {**(props or {}), **{k: v for k, v in named.items() if v is not None}}
        report("Creating AVD")
        name = self.create(name, image, ram_mb, width, height, density, cores, profile=profile, props=wanted,
                           android=android)
        try:
            self.start(name, headless=headless, timeout=timeout, slim=slim, proxy=proxy, on_status=on_status)
            for path in resolved_apks:
                report(f"Installing {Path(path).name} & granting permissions")
                self.install(name, path)
            if username:
                report(f"Loading Snapchat session ({username})")
                self.load_snapchat_session(name, username)
            report("Opening Snapchat")
            self.start_app(name, SNAPCHAT_PACKAGE)
            time.sleep(5)
            self.adb(name, "shell", "input keyevent 3", timeout=15)
        except BaseException:
            self.delete(name)
            raise
        return Device(self, name)

    def spawn_many(self, count, **options):
        """spawn() count emulators at once (same options, names emuN); returns their Devices.

        They boot in parallel, so this takes about as long as one spawn, but each needs its
        RAM (2.5 GB by default). If any fails, the others are kept and the error is raised.
        """
        if options.get("name"):
            raise EmulatorError("spawn_many names emulators itself; don't pass name")
        with concurrent.futures.ThreadPoolExecutor(count) as pool:
            futures = [pool.submit(self.spawn, **options) for _ in range(count)]
        return [f.result() for f in futures]

    def device(self, name):
        """Device handle for an existing emulator."""
        self._require(name)
        return Device(self, name)

    def devices(self):
        return [Device(self, n) for n in self.avds()]

    def create(self, name=None, image=None, ram_mb=None, width=None, height=None,
               density=None, cores=None, data_gb=6, profile=None, props=None, android=None):
        """Create a new emulator (without starting it) and return its name.

        props maps PROP_ALIASES names or full property names to values; profile is a
        profile name (or a loaded dict) whose screen and props are used unless overridden.
        android selects Android 14, 15 or 16 (default 16).
        The props are baked in on the first start, so later starts never re-inject.
        """
        if android is not None and image is not None:
            raise EmulatorError("pass either android or image, not both")
        if android is not None:
            try:
                image = ANDROID_IMAGES[int(android)]
            except (ValueError, KeyError):
                raise EmulatorError(f"unsupported Android version {android!r} (choose 14, 15 or 16)")
        if image is None:
            image = DEFAULT_IMAGE
        prof = self.load_profile(profile) if isinstance(profile, str) else profile
        hw = (prof or {}).get("hardware", {})
        width = width if width is not None else hw.get("width", 720)
        height = height if height is not None else hw.get("height", 1600)
        density = density if density is not None else hw.get("density", 280)
        ram_mb = ram_mb if ram_mb is not None else hw.get("ram", 2560)
        cores = cores if cores is not None else hw.get("cores", 4)
        img = self._resolve_image(image)
        props_wanted = self._normalize_props({**(prof or {}).get("props", {}), **(props or {})})
        source = _read_props(img / "source.properties")
        target = f"android-{source['AndroidVersion.ApiLevel']}"
        abi = source.get("SystemImage.Abi", img.name)
        tag_id = source.get("SystemImage.TagId", img.parent.name)
        with self._lock:
            name = name or self._next_name()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                raise EmulatorError(f"invalid name {name!r} (use letters, digits, '.', '_', '-')")
            if (self.avd_home / f"{name}.ini").exists() or self._avd_dir(name).exists():
                raise EmulatorError(f"{name} already exists")
            config = {
                "AvdId": name, "avd.ini.displayname": name, "avd.ini.encoding": "UTF-8",
                "target": target, "image.sysdir.1": str(img.relative_to(self.sdk_root)).replace("\\", "/") + "/",
                "tag.id": tag_id, "tag.display": source.get("SystemImage.TagDisplay", tag_id),
                "abi.type": abi, "hw.cpu.arch": abi, "hw.cpu.ncore": cores, "PlayStore.enabled": "no",
                "hw.ramSize": f"{ram_mb}M", "vm.heapSize": "228M", "disk.dataPartition.size": f"{data_gb}G",
                "hw.lcd.width": width, "hw.lcd.height": height, "hw.lcd.density": density,
                "hw.gpu.enabled": "yes", "hw.gpu.mode": "auto", "hw.keyboard": "yes", "hw.mainKeys": "no",
                "hw.audioInput": "no", "hw.audioOutput": "no", "hw.camera.back": "emulated",
                "hw.camera.front": "none", "hw.sdCard": "no", "fastboot.forceColdBoot": "yes",
                "showDeviceFrame": "no",
            }
            avd_dir = self._avd_dir(name)
            avd_dir.mkdir(parents=True)
            (avd_dir / "config.ini").write_text("".join(f"{k}={v}\n" for k, v in config.items()), encoding="utf-8")
            (self.avd_home / f"{name}.ini").write_text(
                f"avd.ini.encoding=UTF-8\npath={avd_dir}\ntarget={target}\n", encoding="utf-8")
        state = {"image": "/".join(img.relative_to(self.sdk_root / "system-images").parts)}
        note = ""
        if props_wanted and (img / "build.prop").is_file():
            self._keep_patch_level(name, props_wanted, _read_props(img / "build.prop").get(PATCH_PROP))
        if props_wanted:
            state["pending_props"] = props_wanted
            state["writable_system"] = True   # must be set at launch; baking needs it
            if prof:
                state["profile"] = prof.get("name", profile if isinstance(profile, str) else "custom")
            note = f", {len(props_wanted)} props pending" + (f" (profile {state['profile']})" if prof else "")
        self._save_state(name, **state)
        self._log(f"{name}: created ({target}, {width}x{height}, {ram_mb} MB RAM{note})")
        return name

    def start(self, name, headless=False, writable_system=False, wait=True, timeout=300, slim=True,
              extra_args=(), proxy=None, on_status=None):
        """Launch an emulator (it keeps running after Python exits) and return its adb serial.

        With wait=True this blocks until Android has booted; on the first boot it also
        removes the preinstalled Google apps and turns off animations unless slim=False.
        Emulators changed with set_props() always start with a writable system, because
        their changes only exist there.
        proxy accepts host:port or host:port:user:password; stop a running device first.
        The proxy is not saved: pass it again on subsequent starts.
        """
        self._require(name)
        proxy_url = _proxy_url(proxy)
        if serial := self.serial(name):
            if proxy_url is not None:
                raise EmulatorError(f"{name} is already running; stop it before starting with a proxy")
            return serial
        writable_system = writable_system or self._state(name).get("writable_system", False)
        with self._lock:  # the port counts as taken once the pid is saved
            port = self._free_port()
            args = [str(self.emulator_exe), "-avd", name, "-port", str(port), "-no-boot-anim", "-no-audio",
                    "-no-snapshot", "-feature", "-QuickbootFileBacked"]
            if not IS_WINDOWS:
                args += ["-gpu", "swiftshader_indirect", "-feature", "-WiFiPacketStream"]
            if headless or not IS_WINDOWS:
                args.append("-no-window")
            if writable_system:
                args.append("-writable-system")
            if proxy_url is not None:
                args += ["-http-proxy", proxy_url]
            args += list(extra_args)
            popen_kwargs = {}
            if IS_WINDOWS:
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            log_path = self._avd_dir(name) / "emulator.log"
            with open(log_path, "ab") as log_f:
                proc = subprocess.Popen(args, env=self.env, stdin=subprocess.DEVNULL,
                                        stdout=log_f, stderr=log_f,
                                        **popen_kwargs)
            self._save_state(name, pid=proc.pid, port=port, headless=headless)
        self._log(f"{name}: starting on emulator-{port}")
        if wait:
            self.wait_for_boot(name, timeout, slim, on_status=on_status)
        return f"emulator-{port}"

    def wait_for_boot(self, name, timeout=300, slim=True, on_status=None):
        """Block until Android reports boot completed; apply first-boot slimming."""
        if on_status is not None and slim:
            on_status("Booting Android")
        serial = self.serial(name)
        if not serial:
            raise EmulatorError(f"{name} is not running")
        deadline = time.monotonic() + timeout
        while True:
            if not self.is_running(name):
                log = self._avd_dir(name) / "emulator.log"
                tail = "\n".join(log.read_text(errors="replace").splitlines()[-15:]) if log.exists() else ""
                raise EmulatorError(f"{name} exited while booting (log: {log})\n{tail}")
            try:
                if self._run_adb("-s", serial, "shell", "getprop", "sys.boot_completed", timeout=10).stdout.strip() == "1":
                    break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > deadline:
                raise EmulatorError(f"{name} did not finish booting within {timeout}s")
            time.sleep(2)
        self._log(f"{name}: booted")
        if slim and not self._state(name).get("slimmed"):
            if on_status is not None:
                on_status("Removing bloatware & configuring settings")
            script = "; ".join([f"pm uninstall --user 0 {p} >/dev/null 2>&1" for p in BLOAT] +
                               [f"settings put global {k} 0" for k in
                                ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")] +
                               ["settings put secure stylus_handwriting_enabled 0",
                                "settings put global hide_error_dialogs 0",
                                "settings put secure anr_show_background 0"])
            self._run_adb("-s", serial, "shell", script, timeout=120)
            self._save_state(name, slimmed=True)
            self._log(f"{name}: removed preinstalled apps, animations off")
        if name not in self._baking and self._state(name).get("pending_props"):
            self._baking.add(name)
            try:
                self._bake_pending(name, timeout, on_status=on_status)
            finally:
                self._baking.discard(name)
        return serial

    def _bake_pending(self, name, timeout, on_status=None):
        """One-time: write the build properties given at create() into a fresh device."""
        changes = self._state(name).get("pending_props")
        if not changes:
            return
        self._log(f"{name}: baking in {len(changes)} properties (one time)")
        self._write_props(name, changes, timeout, on_status=on_status)
        self._save_state(name, pending_props=None)
        wrong = {k: v for k, v in self.get_props(name, list(changes)).items() if v != changes[k]}
        if wrong:
            self._log(f"{name}: WARNING, some properties did not take effect: {wrong}")

    def stop(self, name, timeout=60):
        """Shut an emulator down. Returns False if it was not running."""
        self._require(name)
        state = self._state(name)
        pid = state.get("pid")
        pids = _emulator_pids(pid)
        if not pids:
            self._save_state(name, pid=None, port=None)
            return False
        try:
            graceful = "OK" in self._run_adb("-s", f"emulator-{state['port']}", "emu", "kill", timeout=15).stdout
        except subprocess.TimeoutExpired:
            graceful = False
        if not (graceful and self._wait_exit(pid, timeout)):
            for p in _emulator_pids(pid):  # each one: /T misses a qemu whose emulator.exe already exited
                _kill_pid(p)
            if not self._wait_exit(pid, 15):
                raise EmulatorError(f"could not stop {name} (pid {pid})")
        # Ensure any crashpad_handler child of emulator/qemu is also terminated
        tree_parents = set(pids)
        for p, parent, exe in _processes():
            if parent in tree_parents and exe in ("crashpad_handler.exe", "crashpad_handler") and _alive(p):
                _kill_pid(p)
        self._save_state(name, pid=None, port=None)
        self._log(f"{name}: stopped")
        return True

    def _rmtree_retry(self, path: Path, retries: int = 15):
        for attempt in range(retries):
            try:
                shutil.rmtree(path, onexc=_clear_readonly)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt == retries - 1:
                    raise
                time.sleep(1)

    def delete(self, name):
        """Stop an emulator if needed and remove all of its files."""
        self._require(name)
        self.stop(name)
        self._rmtree_retry(self._avd_dir(name))
        (self.avd_home / f"{name}.ini").unlink(missing_ok=True)
        self._log(f"{name}: deleted")

    def stop_all(self):
        """Stop every emulator managed here; returns the names that were running."""
        return [n for n in self.avds() if self.stop(n)]

    def delete_all(self):
        """Stop and delete every emulator managed here (only the ones in avd_home)."""
        names = self.avds()
        for n in names:
            try:
                self.stop(n)
            except Exception:
                pass
        # Kill any lingering netsimd / crashpad_handler / qemu processes holding handles in avd_home
        for p, _parent, exe in _processes():
            if (exe in ("emulator.exe", "emulator", "netsimd.exe", "netsimd", "crashpad_handler.exe", "crashpad_handler")
                    or exe.startswith("qemu-system")) and _alive(p):
                _kill_pid(p)
        for n in names:
            self._rmtree_retry(self._avd_dir(n))
            (self.avd_home / f"{n}.ini").unlink(missing_ok=True)
            self._log(f"{n}: deleted")
        for avd_dir in self.avd_home.glob("*.avd"):
            self._rmtree_retry(avd_dir)
        for ini in self.avd_home.glob("*.ini"):
            ini.unlink(missing_ok=True)

    # ---- device access -------------------------------------------------------

    def resolve_apk(self, apk, on_status=None, timeout=600):
        """Resolve an APK URL (downloading and caching in apks_dir) or local file path."""
        raw = str(apk).strip()
        if not raw:
            raise EmulatorError("apk cannot be empty")
        if raw.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(raw)
            basename = Path(urllib.parse.unquote(parsed.path)).name
            stem = re.sub(r"[^A-Za-z0-9._-]+", "_", basename[:-4] if basename.lower().endswith(".apk") else basename)
            stem = stem.strip("._-") or "app"
            url_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
            target = self.apks_dir / f"{stem}_{url_hash}.apk"
            with self._lock:
                url_lock = self._apk_locks.setdefault(raw, threading.Lock())
            with url_lock:
                if target.is_file() and target.stat().st_size > 0:
                    if on_status is not None:
                        on_status(f"Using cached APK ({target.name})")
                    self._log(f"using cached APK {target.name}")
                    return target
                if on_status is not None:
                    on_status("Downloading APK")
                self._log(f"downloading APK from {raw} -> {target.name}")
                part = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
                try:
                    req = urllib.request.Request(raw, headers={"User-Agent": "Mozilla/5.0 EmuManager/1.0"})
                    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out_f:
                        shutil.copyfileobj(resp, out_f, length=1024 * 1024)
                    if not part.is_file() or part.stat().st_size < 4:
                        raise EmulatorError(f"downloaded APK from {raw} is empty")
                    with open(part, "rb") as f:
                        magic = f.read(4)
                    if magic != b"PK\x03\x04":
                        raise EmulatorError(f"downloaded file from {raw} is not a valid APK archive")
                    os.replace(part, target)
                except EmulatorError:
                    part.unlink(missing_ok=True)
                    raise
                except Exception as e:
                    part.unlink(missing_ok=True)
                    raise EmulatorError(f"downloading APK from {raw} failed: {e}") from e
                return target
        path = Path(raw)
        if not path.is_file():
            raise EmulatorError(f"APK file not found: {raw}")
        return path

    def start_app(self, name, package=SNAPCHAT_PACKAGE):
        """Launch an installed app's main launcher activity on a running emulator."""
        if package == SNAPCHAT_PACKAGE:
            script = (
                "am start -a android.intent.action.MAIN "
                "-c android.intent.category.LAUNCHER "
                "-f 0x10200000 "
                "-n com.snapchat.android/com.snapchat.android.LandingPageActivity"
            )
        else:
            script = f"monkey -p {_sh_quote(package)} -c android.intent.category.LAUNCHER 1"
        out = self.adb(name, "shell", script, timeout=30)
        if "Error:" in out or "Exception" in out or "No activities found" in out:
            raise EmulatorError(f"starting {package} on {name} failed: {out}")
        self._log(f"{name}: started {package}")

    def adb(self, name, *args, timeout=60):
        """Run an adb command against a running emulator and return its output."""
        result = self._run_adb("-s", self._serial_or_raise(name), *args, timeout=timeout)
        return (result.stdout + result.stderr).strip()

    def install(self, name, apk, timeout=600):
        before = set(self._packages_3p(name))
        output = self.adb(name, "install", "-r", str(apk), timeout=timeout)
        if "Success" not in output:
            raise EmulatorError(f"installing {apk} on {name} failed: {output}")
        after = set(self._packages_3p(name))
        pkgs = sorted(after - before) or ([SNAPCHAT_PACKAGE] if SNAPCHAT_PACKAGE in after else sorted(after))
        if pkgs:
            grants = "; ".join(f"pm grant {pkg} {perm} >/dev/null 2>&1" for pkg in pkgs for perm in PERMISSIONS)
            self.adb(name, "shell", grants, timeout=60)
        self._log(f"{name}: installed {Path(apk).name}")

    def _packages_3p(self, name):
        out = self.adb(name, "shell", "pm list packages -3", timeout=30)
        return [line.removeprefix("package:").strip() for line in out.splitlines() if line.startswith("package:")]

    def load_snapchat_session(self, name, username, timeout=300):
        """Download username's Snapchat session from object storage into /data/data/com.snapchat.android."""
        session_name = username.strip().lower()
        if not session_name:
            raise EmulatorError("username cannot be empty")
        self._root(name)
        ls_result = self.adb(name, "shell", f"ls -bdAlZ /data/data/{SNAPCHAT_PACKAGE}")
        parts = ls_result.split()
        if len(parts) < 5 or "No such file" in ls_result:
            raise EmulatorError(f"{name}: {SNAPCHAT_PACKAGE} is not installed (cannot read /data/data/{SNAPCHAT_PACKAGE})")
        user, group, context = parts[2], parts[3], parts[4]
        key = f"{DO_SPACES_PREFIX.strip('/')}/{SNAPCHAT_PACKAGE}/{session_name}.7z"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            archive_path = tmp / f"{session_name}.7z"
            try:
                s3 = boto3.client(
                    "s3", region_name=DO_SPACES_REGION, endpoint_url=DO_SPACES_ENDPOINT,
                    aws_access_key_id=DO_SPACES_ACCESS_KEY, aws_secret_access_key=DO_SPACES_SECRET_KEY,
                    config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
                )
                s3.download_file(DO_SPACES_BUCKET, key, str(archive_path))
            except ClientError as e:
                code = str(e.response.get("Error", {}).get("Code", ""))
                status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code in ("404", "NoSuchKey", "NotFound") or status == 404:
                    raise EmulatorError(f"no Snapchat session in storage for {username!r} ({key})") from e
                raise EmulatorError(f"downloading Snapchat session {key} failed: {e}") from e
            except Exception as e:
                raise EmulatorError(f"downloading Snapchat session {key} failed: {e}") from e
            extract_dir = tmp / "extracted"
            extract_dir.mkdir()
            with py7zr.SevenZipFile(archive_path, "r") as zf:
                zf.extractall(path=extract_dir)
            tar_path = tmp / f"{session_name}.tar"
            with tarfile.open(tar_path, "w") as tar:
                for item in extract_dir.iterdir():
                    tar.add(item, arcname=item.name)
            self.adb(name, "shell", f"am force-stop {SNAPCHAT_PACKAGE}; rm -rf /data/local/tmp/{session_name} /data/local/tmp/{session_name}.tar",
                     timeout=60)
            push_out = self.adb(name, "push", str(tar_path), f"/data/local/tmp/{session_name}.tar", timeout=timeout)
            if "error:" in push_out.lower():
                raise EmulatorError(f"pushing session to {name} failed: {push_out}")
        script = (
            f"mkdir -p /data/local/tmp/{session_name} && "
            f"tar -xf /data/local/tmp/{session_name}.tar -C /data/local/tmp/{session_name} && "
            f"rm -rf /data/data/{SNAPCHAT_PACKAGE} && "
            f"if [ -d /data/local/tmp/{session_name}/{SNAPCHAT_PACKAGE}/{SNAPCHAT_PACKAGE} ]; then "
            f"mv /data/local/tmp/{session_name}/{SNAPCHAT_PACKAGE}/{SNAPCHAT_PACKAGE} /data/data/; "
            f"elif [ -d /data/local/tmp/{session_name}/{SNAPCHAT_PACKAGE} ]; then "
            f"mv /data/local/tmp/{session_name}/{SNAPCHAT_PACKAGE} /data/data/; "
            f"else mv /data/local/tmp/{session_name} /data/data/{SNAPCHAT_PACKAGE}; fi && "
            f"chown -R {user}:{group} /data/data/{SNAPCHAT_PACKAGE} && "
            f"chcon -R {context} /data/data/{SNAPCHAT_PACKAGE} && "
            f"rm -rf /data/local/tmp/{session_name} /data/local/tmp/{session_name}.tar && echo OK"
        )
        out = self.adb(name, "shell", script, timeout=timeout)
        if not out.endswith("OK"):
            raise EmulatorError(f"loading Snapchat session on {name} failed: {out}")
        self._log(f"{name}: loaded Snapchat session for {username!r}")

    def save_snapchat_session(self, name, username, timeout=300, on_status=None):
        """Extract /data/data/com.snapchat.android from emulator, compress as .7z, and upload to DigitalOcean Spaces."""
        session_name = username.strip().lower()
        if not session_name:
            raise EmulatorError("username cannot be empty")
        if on_status is not None:
            on_status(f"Archiving /data/data/{SNAPCHAT_PACKAGE} on device...")
        self._root(name)
        remote_tar = f"/data/local/tmp/{session_name}_out.tar"
        tar_script = (
            f"if [ ! -d /data/data/{SNAPCHAT_PACKAGE} ]; then echo MISSING_DIR; exit 1; fi; "
            f"am force-stop {SNAPCHAT_PACKAGE}; sync; "
            f"rm -f {remote_tar}; "
            f"tar -cf {remote_tar} -C /data/data "
            f"--exclude='{SNAPCHAT_PACKAGE}/lib' "
            f"--exclude='{SNAPCHAT_PACKAGE}/code_cache' "
            f"{SNAPCHAT_PACKAGE} && echo TAR_OK"
        )
        tar_out = self.adb(name, "shell", tar_script, timeout=timeout)
        if "TAR_OK" not in tar_out:
            raise EmulatorError(f"archiving {SNAPCHAT_PACKAGE} on {name} failed: {tar_out}")

        key = f"{DO_SPACES_PREFIX.strip('/')}/{SNAPCHAT_PACKAGE}/{session_name}.7z"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            local_tar = tmp / f"{session_name}_out.tar"
            if on_status is not None:
                on_status("Pulling session archive from emulator...")
            pull_out = self.adb(name, "pull", remote_tar, str(local_tar), timeout=timeout)
            self.adb(name, "shell", f"rm -f {remote_tar}", timeout=30)
            # Relaunch Snapchat immediately so the phone returns to MAIN_PAGE while we compress & upload
            try:
                self.start_app(name, SNAPCHAT_PACKAGE)
            except Exception:
                pass
            if not local_tar.is_file() or local_tar.stat().st_size == 0:
                raise EmulatorError(f"pulling session tar from {name} failed: {pull_out}")

            if on_status is not None:
                on_status(f"Compressing {session_name}.7z...")
            extract_dir = tmp / "extracted"
            extract_dir.mkdir()
            with tarfile.open(local_tar, "r") as tf:
                for member in tf.getmembers():
                    if member.isfile() or member.isdir():
                        try:
                            tf.extract(member, path=extract_dir, set_attrs=False)
                        except TypeError:
                            tf.extract(member, path=extract_dir)
                        except Exception:
                            pass

            pkg_dir = extract_dir / SNAPCHAT_PACKAGE
            if not pkg_dir.is_dir():
                raise EmulatorError(f"extracted tar from {name} is missing {SNAPCHAT_PACKAGE}/ directory")

            archive_path = tmp / f"{session_name}.7z"
            with py7zr.SevenZipFile(archive_path, "w") as zf:
                zf.writeall(pkg_dir, arcname=SNAPCHAT_PACKAGE)

            archive_size = archive_path.stat().st_size
            if on_status is not None:
                on_status(f"Uploading {key} ({archive_size // 1024} KB) to DigitalOcean Spaces...")
            try:
                s3 = boto3.client(
                    "s3", region_name=DO_SPACES_REGION, endpoint_url=DO_SPACES_ENDPOINT,
                    aws_access_key_id=DO_SPACES_ACCESS_KEY, aws_secret_access_key=DO_SPACES_SECRET_KEY,
                    config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
                )
                s3.upload_file(str(archive_path), DO_SPACES_BUCKET, key)
            except Exception as e:
                raise EmulatorError(f"uploading Snapchat session {key} failed: {e}") from e

        self._log(f"{name}: saved & uploaded Snapchat session for {username!r} ({archive_size} bytes)")
        return {
            "username": session_name,
            "bucket": DO_SPACES_BUCKET,
            "key": key,
            "size_bytes": archive_size,
        }

    def screenshot_bytes(self, name, timeout=15) -> bytes:
        """Capture the current screen of a running emulator as raw PNG bytes."""
        serial = self._serial_or_raise(name)
        with self._lock:
            if not self._server_started:
                subprocess.run([str(self.adb_exe), "start-server"], env=self.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                self._server_started = True
        res = subprocess.run(
            [str(self.adb_exe), "-s", serial, "exec-out", "screencap", "-p"],
            env=self.env,
            capture_output=True,
            timeout=timeout,
        )
        if res.returncode != 0 or not res.stdout.startswith(b"\x89PNG"):
            raise EmulatorError(f"screencap failed on {name}")
        return res.stdout

    def get_props(self, name, keys=None):
        """Current values of system properties (default: the PROP_ALIASES ones)."""
        keys = [PROP_ALIASES.get(k, k) for k in (keys or PROP_ALIASES.values())]
        found = dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]$", self.adb(name, "shell", "getprop"), re.M))
        return {k: found.get(k, "") for k in keys}

    def set_props(self, name, props=None, profile=None, timeout=300):
        """Permanently change read-only build properties such as model, brand or build ID.

        props maps PROP_ALIASES names or full property names to values, e.g.
        {"model": "X1", "brand": "acme", "ro.product.board": "x1"}. profile names a saved
        profile whose props are applied first (props then override it). The emulator is
        (re)started with a writable system, edited, rebooted, and left in the state it was
        in before. Returns the values Android reports afterwards.
        """
        self._require(name)
        merged = {}
        if profile is not None:
            merged.update((self.load_profile(profile) if isinstance(profile, str) else profile).get("props", {}))
        merged.update(props or {})
        changes = self._normalize_props(merged)
        if not changes:
            return {}
        was_running = self.is_running(name)
        state = self._state(name)
        if was_running and not state.get("writable_system"):
            self.stop(name)  # the writable system can only be enabled at launch
        self._save_state(name, writable_system=True)
        self.start(name, headless=state.get("headless", True) if was_running else True, timeout=timeout)
        self._keep_patch_level(name, changes, self.get_props(name, [PATCH_PROP])[PATCH_PROP])
        result = {}
        if changes:
            self._write_props(name, changes, timeout)
            result = self.get_props(name, list(changes))
        wrong = {k: v for k, v in result.items() if v != changes[k]}
        if not was_running:
            self.stop(name)
        if wrong:
            raise EmulatorError(f"{name}: properties did not take effect: {wrong}")
        return result

    @staticmethod
    def _normalize_props(props):
        changes = {PROP_ALIASES.get(k, k): str(v) for k, v in props.items()}
        for key, value in changes.items():
            if not re.fullmatch(r"[A-Za-z0-9._-]+", key):
                raise EmulatorError(f"invalid property name {key!r}")
            if "\n" in value or "\r" in value:
                raise EmulatorError(f"value for {key} contains a line break")
        return changes

    def _keep_patch_level(self, name, changes, current):
        """Drop from changes a security patch older than current (see PATCH_PROP)."""
        new = changes.get(PATCH_PROP)
        if new and current and new < current:
            del changes[PATCH_PROP]
            self._log(f"{name}: WARNING, keeping {PATCH_PROP}={current}: the older {new} "
                      f"would stop the device from booting")

    def _write_props(self, name, changes, timeout, on_status=None):
        """Assuming a running, writable-system device: write build.prop overrides and reboot.

        The first remount of a device turns verity off and creates the overlay, which only
        gets mounted at the next boot. The file then goes straight into the overlay's upper
        dir, so a single reboot brings up both instead of one reboot for each.
        """
        if on_status is not None:
            on_status("Enabling writable system")
        folder = PROP_TARGET_UPPER.rsplit("/", 1)[0]
        writable = self._root_and_remount(name)
        if not writable and self.adb(name, "shell", f'[ -d "$(dirname {folder})" ] && echo ok') != "ok":
            self._log(f"{name}: overlay not set up yet, rebooting first")
            if on_status is not None:
                on_status("Rebooting to set up writable overlay")
            self._reboot(name, timeout, on_status=on_status)
            if not (writable := self._root_and_remount(name)):
                raise EmulatorError(f"{name}: system still not writable after a reboot")
        if on_status is not None:
            on_status(f"Injecting {len(changes)} device properties")
        if writable:
            target, files, script = PROP_TARGET, " ".join(PROP_FILES), []
        else:
            target = files = PROP_TARGET_UPPER
            # chmod: adb's umask is 0 and the overlay shows this dir's mode for /product/etc
            script = [f"mkdir -p {folder}", f"chmod 755 {folder}",
                      f"[ -f {target} ] || cp -a {PROP_TARGET} {target}"]
        script += [f"sed -i '/^{key.replace('.', '[.]')}=/d' {files} 2>/dev/null" for key in changes]
        script.append(f"[ -n \"$(tail -c1 {target})\" ] && echo >> {target}")
        script.append("printf '%s\\n' " + " ".join(_sh_quote(f"{k}={v}") for k, v in changes.items())
                      + f" >> {target}")
        script.append("sync")
        self.adb(name, "shell", "; ".join(script), timeout=60)
        self._log(f"{name}: wrote {len(changes)} properties, rebooting")
        if on_status is not None:
            on_status("Rebooting to apply properties")
        self._reboot(name, timeout, on_status=on_status)

    # ---- internals -----------------------------------------------------------

    def _log(self, message):
        if self.verbose:
            print(message, file=sys.stderr, flush=True)

    def _run_adb(self, *args, timeout=60):
        with self._lock:
            if not self._server_started:
                # Clear any server a different adb version left running, then start ours cleanly.
                subprocess.run([str(self.adb_exe), "kill-server"], env=self.env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
                subprocess.run([str(self.adb_exe), "start-server"], env=self.env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
                self._server_started = True
        return subprocess.run([str(self.adb_exe), *args], env=self.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)

    def _root(self, name):
        """Ensure adbd is running as root on the emulator."""
        self.adb(name, "root")
        deadline = time.monotonic() + 60
        while True:  # adbd restarts as root, so the device drops off adb briefly
            try:
                if self.adb(name, "shell", "id", "-u", timeout=15) == "0":
                    break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > deadline:
                raise EmulatorError(f"adb root failed on {name}")
            time.sleep(1)

    def _root_and_remount(self, name):
        """adb root + remount. True if the system is writable now, False if this first
        remount just turned verity off and set up the overlay for the next boot."""
        self._root(name)
        # remount first tries a ~4 GB scratch image on /data, which can't be mapped on the
        # emulator and leaves the (encrypted, unshrinkable) data disk 4 GB bigger before it
        # falls back to free space on super. A file in its place makes that fail instantly.
        self.adb(name, "shell", "[ -f /data/gsi/remount ] || { rm -rf /data/gsi/remount; "
                                "touch /data/gsi/remount; chmod 000 /data/gsi/remount; }")
        output = self.adb(name, "remount", timeout=120)
        if "Remount succeeded" in output:
            return True
        if "reboot" in output.lower():
            self._log(f"{name}: enabled writable system")
            return False
        raise EmulatorError(f"remount failed on {name}: {output}")

    def _reboot(self, name, timeout, on_status=None):
        state = self._state(name)
        try:
            self.adb(name, "reboot", timeout=60)
            self.adb(name, "wait-for-disconnect", timeout=120)
        except Exception:
            pass
        time.sleep(2)
        if not self.is_running(name):
            self._log(f"{name}: process exited on reboot; starting back up")
            self.start(name, headless=state.get("headless", True), writable_system=True, wait=False)
        self.wait_for_boot(name, timeout, slim=False, on_status=on_status)

    def _avd_dir(self, name):
        return self.avd_home / f"{name}.avd"

    def _state(self, name):
        try:
            return json.loads((self._avd_dir(name) / STATE_FILE).read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, name, **changes):
        state = self._state(name)
        state.update(changes)
        (self._avd_dir(name) / STATE_FILE).write_text(json.dumps(state, indent=2))

    def _require(self, name):
        if name not in self.avds():
            raise EmulatorError(f"no emulator named {name!r} in {self.avd_home}")

    def _serial_or_raise(self, name):
        self._require(name)
        serial = self.serial(name)
        if not serial:
            raise EmulatorError(f"{name} is not running")
        return serial

    def _next_name(self):
        existing = set(self.avds())
        n = 1
        while f"emu{n}" in existing or self._avd_dir(f"emu{n}").exists():
            n += 1
        return f"emu{n}"

    def _resolve_image(self, image):
        parts = [p for p in re.split(r"[/;\\]", image.strip()) if p]
        if parts[:1] == ["system-images"]:
            parts = parts[1:]
        if len(parts) == 2:
            parts.append("x86_64")
        path = self.sdk_root.joinpath("system-images", *parts)
        if len(parts) != 3 or not (path / "source.properties").is_file():
            raise EmulatorError(f"system image {image!r} is not installed; available: "
                                f"{', '.join(self.images()) or 'none'}")
        return path

    def _free_port(self):
        taken = {self._state(n).get("port") for n in self.avds() if self.is_running(n)}
        for port in CONSOLE_PORTS:
            if port not in taken and _port_free(port) and _port_free(port + 1):
                return port
        raise EmulatorError("no free emulator port (adb supports at most 16 local emulators)")

    @staticmethod
    def _wait_exit(pid, timeout):
        deadline = time.monotonic() + timeout
        while _emulator_pids(pid):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.5)
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spawn, stop and delete lightweight Android emulators.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def run_options(p, required=False):
        p.add_argument("--headless", action="store_true", help="run without an emulator window")
        p.add_argument("--apk", action="append", default=[], required=required,
                       help="install this APK (direct download URL or file path) once booted")
        p.add_argument("--username", metavar="USERNAME", required=required,
                       help="load this username's Snapchat session from storage into /data/data")
        p.add_argument("--no-slim", action="store_true", help="keep preinstalled Google apps and animations")
        p.add_argument("--proxy", metavar="HOST:PORT[:USER:PASS]",
                       help="HTTP proxy for this launch; stop a running device first")

    def prop_options(p):
        for alias in PROP_ALIASES:
            p.add_argument(f"--{alias.replace('_', '-')}", dest=alias, metavar="VALUE", help=PROP_ALIASES[alias])
        p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="any other property")

    sub.add_parser("images", help="list installed system images")
    sub.add_parser("list", help="list emulators and whether they are running")
    sub.add_parser("profiles", help="list saved device profiles")

    p_srv = sub.add_parser("server", help="run the local HTTP API and web UI server")
    p_srv.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")

    p = sub.add_parser("capture-profile", help="snapshot a connected device into a profile")
    p.add_argument("serial", help="adb serial of the device to read (see `adb devices`)")
    p.add_argument("--name", help="profile name (default: the device model, lower-cased)")
    p.add_argument("--desc", help="free-text description stored in the profile")

    for cmd, text in (("spawn", "create new emulator(s), boot them and install APKs"),
                      ("create", "create new emulator(s) without starting them")):
        is_spawn = cmd == "spawn"
        p = sub.add_parser(cmd, help=text)
        p.add_argument("name", nargs="?", help="default: emu1, emu2, ...")
        p.add_argument("--profile", required=is_spawn,
                       help="stamp with a saved device profile (screen + build props)")
        p.add_argument("--count", type=int, default=1, help="how many (only without a name); they boot in parallel")
        p.add_argument("--android", type=int, choices=sorted(ANDROID_IMAGES), required=is_spawn,
                       help="Android version: 14, 15 or 16")
        p.add_argument("--image", help=f"system image (default {DEFAULT_IMAGE})")
        p.add_argument("--ram", type=int, help="RAM in MB (default 2560 / the profile)")
        p.add_argument("--size", help="screen WIDTHxHEIGHT (default 720x1600 / the profile)")
        p.add_argument("--density", type=int, help="screen dpi (default 280 / the profile)")
        p.add_argument("--cores", type=int, help="CPU cores (default 4 / the profile)")
        prop_options(p)
        if is_spawn:
            run_options(p, required=True)

    p = sub.add_parser("start", help="start an emulator and wait until it has booted")
    p.add_argument("name")
    run_options(p)
    p.add_argument("--writable-system", action="store_true", help="allow editing /system (e.g. build.prop)")

    p = sub.add_parser("props", help="show or change model, brand, build ID, ...")
    p.add_argument("name")
    p.add_argument("--profile", help="apply a saved profile's properties")
    prop_options(p)

    for cmd, text in (("stop", "stop emulator(s)"), ("delete", "stop and delete emulator(s)")):
        p = sub.add_parser(cmd, help=text)
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("name", nargs="?")
        group.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "server":
        from server import run_server
        run_server(host=args.host, port=args.port)
        return
    try:
        emu = EmulatorManager(verbose=True)
        if args.cmd == "images":
            print("\n".join(emu.images()) or "no system images installed")
        elif args.cmd == "list":
            rows = emu.status()
            for row in rows:
                tag = row["profile"] + (" (pending)" if row["pending"] else "")
                print(f"{row['name']:<16}{row['serial'] or 'stopped':<17}{row['image']:<34}{tag}")
            if not rows:
                print("no emulators")
        elif args.cmd == "profiles":
            for n in emu.list_profiles():
                prof = emu.load_profile(n)
                hw = prof.get("hardware", {})
                dims = f"{hw.get('width', '?')}x{hw.get('height', '?')}@{hw.get('density', '?')}"
                print(f"{n:<16}{dims:<18}{len(prof.get('props', {}))} props  {prof.get('description', '')}")
            if not emu.list_profiles():
                print(f"no profiles in {emu.profiles_dir}")
        elif args.cmd == "capture-profile":
            data = emu.capture_profile(args.serial, args.name or _default_profile_name(emu, args.serial), args.desc)
            print(f"saved profile {data['name']!r}: {data['description']} "
                  f"({len(data['props'])} props, {data['hardware'] or 'no screen info'})")
        elif args.cmd in ("spawn", "create"):
            if args.name and args.count != 1:
                raise EmulatorError("--count only works without a name")
            options = {"android": args.android, "image": args.image, "ram_mb": args.ram, "density": args.density,
                       "cores": args.cores, "profile": args.profile, "props": _cli_props(args)}
            if args.size:
                w, h = args.size.lower().split("x")
                options.update(width=int(w), height=int(h))
            if args.cmd == "create":
                for _ in range(args.count):
                    emu.create(args.name, **options)
            else:
                options.update(apk=args.apk, username=args.username,
                               headless=args.headless, slim=not args.no_slim, proxy=args.proxy)
                devs = (emu.spawn_many(args.count, **options) if args.count > 1
                        else [emu.spawn(args.name, **options)])
                for dev in devs:
                    print(f"{dev} ready on {dev.serial}")
        elif args.cmd == "start":
            serial = emu.start(args.name, headless=args.headless, writable_system=args.writable_system,
                               slim=not args.no_slim, proxy=args.proxy)
            for apk in args.apk:
                emu.install(args.name, apk)
            if args.username:
                emu.load_snapchat_session(args.name, args.username)
            print(f"{args.name} ready on {serial}")
        elif args.cmd == "props":
            changes = _cli_props(args)
            if changes or args.profile:
                values = emu.set_props(args.name, changes, profile=args.profile)
            else:
                if not emu.is_running(args.name):
                    raise EmulatorError(f"{args.name} is not running; start it to read its properties")
                values = emu.get_props(args.name)
            for key, value in values.items():
                print(f"{key:<36}{value}")
        elif args.cmd == "stop":
            for name in emu.avds() if args.all else [args.name]:
                if not emu.stop(name):
                    print(f"{name}: was not running")
        elif args.cmd == "delete":
            for name in emu.avds() if args.all else [args.name]:
                emu.delete(name)
    except (EmulatorError, OSError) as e:
        sys.exit(f"error: {e}")


def _default_profile_name(emu, serial):
    model = emu._run_adb("-s", serial, "shell", "getprop", "ro.product.model", timeout=15).stdout.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return slug or serial.lower()


def _cli_props(args):
    changes = {alias: getattr(args, alias) for alias in PROP_ALIASES if getattr(args, alias) is not None}
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep:
            raise EmulatorError(f"--set needs KEY=VALUE, got {item!r}")
        changes[key] = value
    return changes


if __name__ == "__main__":
    main()
