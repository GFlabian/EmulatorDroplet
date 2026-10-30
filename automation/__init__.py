"""Snapchat UI Automation package for FreyaEmulator."""

import importlib
import sys

for _sub in (
    "automation.common.models",
    "automation.common.page_rule",
    "automation.common.xml_page",
    "automation.common.phone_controller",
    "automation.common.shared_rules",
    "automation.common.shared_pages",
    "automation.common.pages_service",
    "automation.common.navigation",
    "automation.common",
    "automation.actions.base_action",
    "automation.actions.add_friend.rules",
    "automation.actions.add_friend.pages",
    "automation.actions.add_friend.action",
    "automation.actions.add_friend",
    "automation.actions",
):
    if _sub in sys.modules:
        try:
            importlib.reload(sys.modules[_sub])
        except Exception:
            pass

from automation.actions import (
    ACTION_REGISTRY,
    AddFriendAction,
    BaseAction,
    FetchFriendsAction,
    SendMessageAction,
    SendMessageToAiAction,
    WatchCommentsReelAction,
    WatchReelsAction,
    get_action,
    list_supported_actions,
)
from automation.common import (
    ActionRecord,
    ActionResult,
    AutomationError,
    Element,
    KeyType,
    Location,
    PagesService,
    PhoneController,
    Point,
    XmlPage,
    XmlPageRule,
    detect_location_from_xml,
    go_to_main_page,
    is_on_main_page,
)

__all__ = [
    "ACTION_REGISTRY",
    "ActionRecord",
    "ActionResult",
    "AddFriendAction",
    "AutomationError",
    "BaseAction",
    "Element",
    "FetchFriendsAction",
    "KeyType",
    "Location",
    "PagesService",
    "PhoneController",
    "Point",
    "SendMessageAction",
    "SendMessageToAiAction",
    "WatchCommentsReelAction",
    "WatchReelsAction",
    "XmlPage",
    "XmlPageRule",
    "detect_location_from_xml",
    "get_action",
    "go_to_main_page",
    "is_on_main_page",
    "list_supported_actions",
]

for _srv_mod_name in ("server", "__main__"):
    _srv_mod = sys.modules.get(_srv_mod_name)
    if _srv_mod is not None and hasattr(_srv_mod, "registry"):
        try:
            if "emumanager" in sys.modules and hasattr(_srv_mod, "emu_manager"):
                _srv_mod.emu_manager.__class__ = sys.modules["emumanager"].EmulatorManager
            for _ctrl in list(_srv_mod.registry._controllers.values()):
                _ctrl.__class__ = PhoneController
        except Exception:
            pass
