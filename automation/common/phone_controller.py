"""Phone controller for fetching UIAutomator XML and sending touch/key inputs via ADB."""

from __future__ import annotations

import time
from typing import Callable, Optional
import xml.etree.ElementTree as ET

from emumanager import SNAPCHAT_PACKAGE, EmulatorManager
from automation.common.models import AutomationError, Element, Location, Point


class KeyType:
    BACK = 4
    ENTER = 66
    SPACE = 62
    BACKSPACE = 67
    MOVE_END = 123


class PhoneController:
    """Controls a single running emulator via ADB and tracks its current UI Location."""

    _NULL_ROOT_SIGNATURE = "null root node returned by UiTestAutomationBridge"
    _DUMP_OK_SIGNATURE = "UI hierchary dumped to"
    _DUMP_AND_READ_CMD = (
        "rm -f /data/local/tmp/uidump.xml; "
        "uiautomator dump /data/local/tmp/uidump.xml && "
        "cat /data/local/tmp/uidump.xml"
    )

    def __init__(
        self,
        manager: EmulatorManager,
        avd_name: str,
        on_status: Optional[Callable[[str], None]] = None,
        on_location: Optional[Callable[[str], None]] = None,
        initial_location: str = Location.MAIN_PAGE,
        username: str = "",
    ):
        self.manager = manager
        self.avd_name = avd_name
        self.username = username
        self._on_status = on_status
        self._on_location = on_location
        self._location = initial_location

    @property
    def location(self) -> str:
        return self._location

    def set_location(self, location: str):
        self._location = location
        if self._on_location is not None:
            self._on_location(location)

    def report_status(self, status: str):
        if self._on_status is not None:
            self._on_status(status)

    def shell(self, command: str, timeout: int = 45) -> str:
        return self.manager.adb(self.avd_name, "shell", command, timeout=timeout)

    def fetch_xml(self, max_retries: int = 3, initial_delay: float = 0.7) -> Element:
        """Dump and parse UIAutomator XML hierarchy from the device."""
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                out = self.shell(self._DUMP_AND_READ_CMD, timeout=25)
                xml_str = self._extract_xml(out)
                if xml_str is None:
                    out = self.shell(self._DUMP_AND_READ_CMD, timeout=25)
                    xml_str = self._extract_xml(out)

                if xml_str is None:
                    if self._NULL_ROOT_SIGNATURE in out or "ERROR: could not get idle state" in out:
                        time.sleep(initial_delay)
                        return self.empty_element()
                    raise AutomationError("XML_FETCH_FAILED", f"Could not dump UI XML: {out[:200]}")

                root = ET.fromstring(xml_str)
                return Element(root)
            except Exception as exc:
                last_err = exc
                if attempt < max_retries:
                    time.sleep(initial_delay * (1.5 ** attempt))
                    continue
        if isinstance(last_err, AutomationError):
            raise last_err
        raise AutomationError("XML_FETCH_FAILED", f"Failed to fetch XML: {last_err}")

    @classmethod
    def _extract_xml(cls, output: str) -> Optional[str]:
        start = output.find("<?xml")
        if start != -1 and cls._DUMP_OK_SIGNATURE in output:
            end = output.rfind("</hierarchy>")
            if end != -1:
                return output[start : end + len("</hierarchy>")]
            return output[start:]
        return None

    @staticmethod
    def empty_element() -> Element:
        return Element(ET.Element("hierarchy"))

    def click(self, point: Point):
        self.shell(f"input tap {int(point.x)} {int(point.y)}", timeout=15)

    def click_element(self, element: Element):
        self.click(element.click_point)

    def swipe(self, start: Point, end: Point, duration_ms: int = 350):
        self.shell(
            f"input swipe {int(start.x)} {int(start.y)} {int(end.x)} {int(end.y)} {int(duration_ms)}",
            timeout=20,
        )

    def keyboard(self, text: str):
        """Type text word-by-word via ADB input text + KEYCODE_SPACE."""
        parts = text.split(" ")
        for idx, part in enumerate(parts):
            if idx > 0:
                self.shell(f"input keyevent {KeyType.SPACE}", timeout=15)
            if part:
                escaped = (
                    part.replace("\\", "\\\\")
                    .replace("'", "'\\''")
                    .replace('"', '\\"')
                    .replace(";", "\\;")
                    .replace("&", "\\&")
                    .replace("|", "\\|")
                    .replace("(", "\\(")
                    .replace(")", "\\)")
                    .replace("<", "\\<")
                    .replace(">", "\\>")
                    .replace("$", "\\$")
                    .replace("`", "\\`")
                )
                self.shell(f"input text '{escaped}'", timeout=20)

    def clear_text(self, count: int = 35):
        """Clear text in the currently focused EditText."""
        keys = f"input keyevent {KeyType.MOVE_END}; " + " ".join(
            ["input keyevent --longpress 67 67 67 67 67 67 67 67"] * max(1, count // 8)
        )
        self.shell(keys, timeout=20)

    def send_key(self, key_code: int, times: int = 1):
        if times <= 1:
            self.shell(f"input keyevent {int(key_code)}", timeout=15)
        else:
            cmds = "; ".join(f"input keyevent {int(key_code)}" for _ in range(times))
            self.shell(cmds, timeout=25)

    def sleep(self, seconds: float):
        time.sleep(seconds)

    def ensure_app_foreground(self, package: str = SNAPCHAT_PACKAGE, wait_seconds: float = 3.0):
        """Bring Snapchat to the foreground without force-stopping it."""
        self.manager.start_app(self.avd_name, package)
        time.sleep(wait_seconds)

    def restart_app(self, package: str = SNAPCHAT_PACKAGE, wait_seconds: float = 4.0):
        """Force-stop and relaunch Snapchat, resetting location to MAIN_PAGE."""
        self.report_status("Restarting Snapchat...")
        self.shell(f"am force-stop {package}", timeout=20)
        time.sleep(0.6)
        self.manager.start_app(self.avd_name, package)
        time.sleep(wait_seconds)
        self.set_location(Location.MAIN_PAGE)
