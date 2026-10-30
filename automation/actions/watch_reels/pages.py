"""XmlPage implementations for WATCH_REELS."""

import time
from typing import Any

from automation.actions.watch_reels.rules import MainCameraPageRule, SpotlightReelsPageRule
from automation.common.models import AutomationError, Element, Location
from automation.common.phone_controller import PhoneController
from automation.common.xml_page import XmlPage


class MainCameraOpenSpotlightPage(XmlPage):
    """Clicks the Spotlight (Reels) icon in the bottom navigation bar from MAIN_PAGE."""

    def __init__(self):
        super().__init__(MainCameraPageRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        context["_anr_count"] = 0
        btns = xml.get_elements_by_id("com.snapchat.android:id/ngs_spotlight_icon_container")
        if not btns:
            btns = xml.get_elements_by_content_desc("Spotlight")
        if not btns:
            raise AutomationError("SPOTLIGHT_TAB_NOT_FOUND", "Could not find Spotlight tab icon on MAIN_PAGE")
        controller.report_status("Opening Spotlight (Reels)...")
        controller.click_element(btns[0])
        time.sleep(2.0)


class SpotlightReelsReadyFinalPage(XmlPage):
    """Final page confirming the phone is on the Spotlight / Reels feed."""

    def __init__(self):
        super().__init__(SpotlightReelsPageRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.REELS_PAGE)
