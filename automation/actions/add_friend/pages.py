"""XmlPage implementations for ADD_FRIEND / ADD_USER."""

import time
from typing import Any

from automation.actions.add_friend.rules import (
    MainCameraPageRule,
    make_search_empty_rule,
    make_search_has_add_button_rule,
    make_search_needs_clear_rule,
    make_search_retry_results_rule,
    make_search_view_all_results_rule,
    make_user_added_final_rule,
)
from automation.common.models import AutomationError, Element, Location, Point
from automation.common.phone_controller import PhoneController
from automation.common.xml_page import XmlPage


class MainCameraOpenSearchPage(XmlPage):
    """Clicks the top search icon from MAIN_PAGE."""

    def __init__(self):
        super().__init__(MainCameraPageRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        btns = xml.get_elements_by_id("com.snapchat.android:id/hova_header_search_icon")
        if not btns:
            btns = xml.get_elements_by_content_desc("Search")
        if not btns:
            raise AutomationError("SEARCH_ICON_NOT_FOUND", "Could not find Search icon on MAIN_PAGE")
        controller.report_status("Opening Search...")
        controller.click_element(btns[0])
        controller.set_location(Location.SEARCH_PAGE)
        time.sleep(1.2)


class SearchClearPreviousPage(XmlPage):
    """Clears previous search query when starting directly from USER_ADDED_PAGE or SEARCH_PAGE."""

    def __init__(self, target_username: str):
        super().__init__(make_search_needs_clear_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Clearing previous search query...")
        clear_btns = xml.get_elements_by_id("clear-button")
        if clear_btns:
            controller.click_element(clear_btns[0])
            controller.set_location(Location.SEARCH_PAGE)
            time.sleep(0.8)
            return
        tfs = xml.get_elements_by_id("search-textfield")
        if tfs:
            controller.click_element(tfs[0])
            time.sleep(0.3)
            controller.clear_text(35)
            controller.set_location(Location.SEARCH_PAGE)
            time.sleep(0.6)


class SearchTypeUsernamePage(XmlPage):
    """Types the target username into the search box and submits the search."""

    def __init__(self, target_username: str):
        super().__init__(make_search_empty_rule(target_username))
        self.target_username = target_username

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs:
            raise AutomationError("SEARCH_INPUT_NOT_FOUND", "search-textfield not found")
        controller.report_status(f"Searching for {self.target_username}...")
        controller.click_element(tfs[0])
        time.sleep(0.4)
        controller.keyboard(self.target_username)
        controller.set_location(Location.SEARCH_PAGE)
        time.sleep(2.5)


class SearchViewAllResultsPage(XmlPage):
    """If only 'View all results for <user>' is visible, taps it to expand results."""

    def __init__(self, target_username: str):
        super().__init__(make_search_view_all_results_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        items = xml.get_elements_by_text_containing("View all results")
        if items:
            controller.report_status("Expanding search results...")
            controller.click_element(items[0])
            time.sleep(2.0)


class SearchRetryResultsPage(XmlPage):
    """If 'Couldn't load results' / 'Try Again' appears on search, clicks Try Again."""

    def __init__(self, target_username: str):
        super().__init__(make_search_retry_results_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        btns = xml.get_elements_by_id("retry-button") or xml.get_elements_by_text("Try Again")
        if btns:
            controller.report_status("Retrying search results load...")
            controller.click_element(btns[0])
            time.sleep(2.5)
        else:
            time.sleep(2.0)


class SearchClickAddUserPage(XmlPage):
    """Clicks the 'Add' button next to the searched user."""

    def __init__(self, target_username: str):
        super().__init__(make_search_has_add_button_rule(target_username))
        self.target_username = target_username

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        target = self.target_username.strip().lower()
        add_btns = (
            xml.get_elements_by_id("add-friend-button")
            + xml.get_elements_by_id("subscribe-button")
            + xml.get_elements_by_text("Add")
            + xml.get_elements_by_content_desc("Add")
        )
        if not add_btns:
            raise AutomationError("ADD_BUTTON_NOT_FOUND", f"No Add button found for {self.target_username}")

        # Prefer the Add button vertically aligned with the target username result-subtitle node if present
        subtitles = [
            n for n in xml.get_elements_by_id("result-subtitle")
            if target in (n.text or "").lower() or target in (n.content_desc or "").lower()
        ]
        user_nodes = subtitles or [
            n for n in xml.get_elements_by_text_containing(target)
            if n.resource_id not in ("search-textfield", "") and "view all results" not in n.text.lower()
        ]
        chosen = add_btns[0]
        if user_nodes:
            user_y = user_nodes[0].center.y
            chosen = min(add_btns, key=lambda b: abs(b.center.y - user_y))

        controller.report_status(f"Clicking Add for {self.target_username}...")
        controller.click_element(chosen)
        time.sleep(2.0)


class UserAddedFinalPage(XmlPage):
    """Final page reached when the user has been added (quick-add-button-upsell-1 / Added badge appears)."""

    def __init__(self, target_username: str):
        super().__init__(make_user_added_final_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.USER_ADDED_PAGE)
