"""XmlPage implementations for WATCH_COMMENTS_REEL."""

import time
from typing import Any

from automation.actions.watch_comments_reel.rules import (
    ReelCommentsOpenRule,
    ReelViewActiveRule,
)
from automation.common.models import Element, Location, Point
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.xml_page import XmlPage


class OpenReelCommentsPage(XmlPage):
    """Clicks the Comments button on an active Spotlight reel."""

    def __init__(self):
        super().__init__(ReelViewActiveRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Opening reel comments...")
        # Dismiss "Swipe Up to Next Story" overlay if present
        ok_btns = xml.get_elements_by_id("com.snapchat.android:id/okay_button")
        if ok_btns:
            controller.click_element(ok_btns[0])
            time.sleep(1.2)
            xml = controller.fetch_xml()

        # On Spotlight 14.30, the favorite (heart) button has id="com.snapchat.android:id/favorite" at y=1177..1348,
        # and the Comments button is immediately below it on the right rail at x=940..1066, y=1348..1519.
        favs = xml.get_elements_by_id("com.snapchat.android:id/favorite")
        if favs:
            fav_bottom = favs[0].bounds[1].y
            below_fav = [
                el for el in xml.clickable_elements
                if el.center.x > 900 and fav_bottom <= el.center.y <= fav_bottom + 220
            ]
            if below_fav:
                controller.click_element(below_fav[0])
                time.sleep(1.8)
                return
            controller.click(Point(1000, fav_bottom + 85))
            time.sleep(1.8)
            return

        # Fallback: right-side action rail clickable elements sorted by vertical position
        rail_clickables = [
            el for el in xml.clickable_elements
            if el.center.x > 880 and 1150 < el.center.y < 2050
        ]
        rail_clickables.sort(key=lambda e: e.center.y)
        if len(rail_clickables) >= 2:
            # On Spotlight action rail: [Heart/Favorite, Comments, Share/Send, ...]
            controller.click_element(rail_clickables[1])
        elif rail_clickables:
            controller.click_element(rail_clickables[0])
        else:
            controller.click(Point(1000, 1430))
        time.sleep(1.8)


class ReelCommentsOpenedFinalPage(XmlPage):
    """Final page confirming the reel comments drawer is open."""

    def __init__(self):
        super().__init__(ReelCommentsOpenRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.REEL_COMMENTS_PAGE)


class CloseReelCommentsPage(XmlPage):
    """Closes the reel comments drawer to return to the reel."""

    def __init__(self):
        super().__init__(ReelCommentsOpenRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Closing reel comments...")
        close_btns = (
            xml.get_elements_by_id("dismiss-button")
            + xml.get_elements_by_content_desc(["Close", "Dismiss", "Back"])
        )
        if close_btns:
            controller.click_element(close_btns[0])
        else:
            controller.send_key(KeyType.BACK)
        time.sleep(1.4)


class BackOnReelFinalPage(XmlPage):
    """Final page confirming comments are closed and phone is back on the reel."""

    def __init__(self):
        super().__init__(ReelViewActiveRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.REELS_PAGE)
