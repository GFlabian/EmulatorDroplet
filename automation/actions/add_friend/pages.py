"""XmlPage implementations for ADD_FRIEND / ADD_USER."""

import time
from typing import Any

from automation.actions.add_friend.rules import (
    MainCameraPageRule,
    make_profile_sheet_add_final_rule,
    make_profile_sheet_dismiss_rule,
    make_search_empty_rule,
    make_search_has_add_button_rule,
    make_search_needs_clear_rule,
    make_search_no_results_yet_rule,
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
    """Clears previous search query and immediately types target_username in one step."""

    def __init__(self, target_username: str):
        super().__init__(make_search_needs_clear_rule(target_username))
        self.target_username = target_username

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status(f"Clearing and searching for {self.target_username}...")
        clear_btns = xml.get_elements_by_id("clear-button")
        if clear_btns:
            controller.click_element(clear_btns[0])
            time.sleep(0.6)
            controller.keyboard(self.target_username)
            controller.set_location(Location.SEARCH_PAGE)
            time.sleep(2.0)
            return
        tfs = xml.get_elements_by_id("search-textfield")
        if tfs:
            controller.click_element(tfs[0])
            time.sleep(0.3)
            controller.clear_text(35)
            time.sleep(0.3)
            controller.keyboard(self.target_username)
            controller.set_location(Location.SEARCH_PAGE)
            time.sleep(2.0)


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
        time.sleep(0.8)
        controller.keyboard(self.target_username)
        controller.set_location(Location.SEARCH_PAGE)
        time.sleep(2.2)


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
    """If 'Couldn't load results' / 'Try Again' appears on search, clicks Try Again or clears and re-types."""

    def __init__(self, target_username: str):
        super().__init__(make_search_retry_results_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        retry_count = int(context.get("_search_retry_count", 0))
        context["_search_retry_count"] = retry_count + 1
        clear_btns = xml.get_elements_by_id("clear-button")
        if retry_count >= 2 and clear_btns:
            controller.report_status("Clearing search box to force fresh search...")
            controller.click_element(clear_btns[0])
            time.sleep(1.0)
            return
        btns = xml.get_elements_by_id("retry-button") or xml.get_elements_by_text("Try Again")
        if btns:
            controller.report_status("Retrying search results load...")
            controller.click_element(btns[0])
            time.sleep(2.5)
        elif clear_btns:
            controller.click_element(clear_btns[0])
            time.sleep(1.0)
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
        attempt_idx = int(context.get("_add_click_attempt", 0))
        context["_add_click_attempt"] = attempt_idx + 1

        chosen = add_btns[0]
        if attempt_idx in (0, 1) and user_nodes:
            user_y = user_nodes[0].center.y
            chosen = min(add_btns, key=lambda b: abs(b.center.y - user_y))
        elif attempt_idx < len(add_btns):
            chosen = add_btns[attempt_idx]
        else:
            chosen = add_btns[-1]

        controller.report_status(f"Clicking Add for {self.target_username} (option {attempt_idx + 1})...")
        controller.click_element(chosen)
        time.sleep(2.6)


class ProfileSheetDismissPage(XmlPage):
    """Dismisses a leftover profile sheet when its username does not match target_username."""

    def __init__(self, target_username: str):
        super().__init__(make_profile_sheet_dismiss_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        dismiss_btns = (
            xml.get_elements_by_id("unified_profile_dismiss_button")
            or xml.get_elements_by_id("upp-close-button")
        )
        controller.report_status("Dismissing profile sheet back to search...")
        if dismiss_btns:
            controller.click_element(dismiss_btns[0])
        else:
            controller.click(Point(78, 136))
        controller.set_location(Location.SEARCH_PAGE)
        time.sleep(1.2)


class ProfileSheetAddFinalPage(XmlPage):
    """Final page if tapping a search result opened target_username's profile sheet: clicks Add and dismisses."""

    def __init__(self, target_username: str):
        super().__init__(make_profile_sheet_add_final_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        add_btns = (
            xml.get_elements_by_id("non_friend_profile_action/non_friend_action_button_single")
            + xml.get_elements_by_id("subscribe-button")
            + xml.get_elements_by_content_desc("AddFriendButton.onRenderAddButton")
            + xml.get_elements_by_content_desc("Add")
            + xml.get_elements_by_text("Add")
        )
        if add_btns:
            controller.report_status("Clicking Add on profile sheet...")
            controller.click_element(add_btns[0])
            time.sleep(1.8)

        dismiss_btns = (
            xml.get_elements_by_id("unified_profile_dismiss_button")
            or xml.get_elements_by_id("upp-close-button")
        )
        controller.report_status("Dismissing profile sheet back to search...")
        if dismiss_btns:
            controller.click_element(dismiss_btns[0])
        else:
            controller.click(Point(78, 136))
        controller.set_location(Location.USER_ADDED_PAGE)
        time.sleep(1.2)


class SearchWaitOrNotFoundPage(XmlPage):
    """Waits briefly for search results to load; if still no Add button after 2 checks (~8-10s), raises USER_NOT_FOUND."""

    def __init__(self, target_username: str):
        super().__init__(make_search_no_results_yet_rule(target_username))
        self.target_username = target_username

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        polls = int(context.get("_no_result_polls", 0)) + 1
        context["_no_result_polls"] = polls
        if polls >= 2:
            raise AutomationError("USER_NOT_FOUND", f"No Add button found in search results for {self.target_username}")
        controller.report_status(f"Waiting for search results for {self.target_username}...")
        time.sleep(2.0)


class UserAddedFinalPage(XmlPage):
    """Final page reached when the user has been added (quick-add-button-upsell-1 / Added badge appears)."""

    def __init__(self, target_username: str):
        super().__init__(make_user_added_final_rule(target_username))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.USER_ADDED_PAGE)
