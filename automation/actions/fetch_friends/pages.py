"""XmlPage implementations for FETCH_FRIENDS."""

import time
from typing import Any

from automation.actions.fetch_friends.rules import (
    BitmojiMenuTrayRule,
    FriendsListScreenRule,
    MainCameraPageRule,
    ProfileHasMyFriendsRowRule,
    ProfileNeedsScrollToMyFriendsRule,
)
from automation.common.models import AutomationError, Element, Location, Point
from automation.common.phone_controller import PhoneController
from automation.common.xml_page import XmlPage


class MainCameraOpenProfilePage(XmlPage):
    """Clicks the top-left avatar on MAIN_PAGE to open Profile."""

    def __init__(self):
        super().__init__(MainCameraPageRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        avatars = xml.get_elements_by_id("com.snapchat.android:id/neon_header_avatar")
        if not avatars:
            raise AutomationError("AVATAR_NOT_FOUND", "Could not find neon_header_avatar on MAIN_PAGE")
        controller.report_status("Opening Profile...")
        controller.click_element(avatars[0])
        controller.set_location(Location.PROFILE_PAGE)
        time.sleep(1.8)


class DismissBitmojiMenuTrayPage(XmlPage):
    """Dismisses the Bitmoji menu tray if it was accidentally opened on Profile."""

    def __init__(self):
        super().__init__(BitmojiMenuTrayRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        btns = xml.get_elements_by_id("bitmoji_profile/menu_tray_dismiss_button")
        if btns:
            controller.click_element(btns[0])
            time.sleep(1.2)


class ProfileScrollToMyFriendsPage(XmlPage):
    """Pulls up the Profile bottom sheet from y=2250 so 'My Friends' becomes visible."""

    def __init__(self):
        super().__init__(ProfileNeedsScrollToMyFriendsRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Scrolling Profile to My Friends...")
        controller.set_location(Location.PROFILE_PAGE)
        # Swipe up starting inside the bottom profile identity card (y=2250 -> y=500)
        controller.swipe(Point(540, 2250), Point(540, 500), duration_ms=400)
        time.sleep(1.4)


class ProfileClickMyFriendsPage(XmlPage):
    """Clicks the 'My Friends' row on the Profile screen."""

    def __init__(self):
        super().__init__(ProfileHasMyFriendsRowRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        rows = xml.get_elements_by_text("My Friends")
        if not rows:
            raise AutomationError("MY_FRIENDS_NOT_FOUND", "Could not find 'My Friends' row on Profile")
        controller.report_status("Opening My Friends list...")
        controller.click_element(rows[0])
        time.sleep(2.0)


class FriendsListReadyFinalPage(XmlPage):
    """Final page confirming the My Friends screen is open."""

    def __init__(self):
        super().__init__(FriendsListScreenRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.FRIENDS_LIST_PAGE)
