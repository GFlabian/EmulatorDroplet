"""XmlPage implementations for SEND_MESSAGE."""

import time
from typing import Any

from automation.actions.send_message.rules import (
    ChatsListRule,
    MainCameraPageRule,
    SearchFriendToChatRule,
    make_friend_conversation_open_rule,
)
from automation.common.models import AutomationError, Element, Location, Point
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.xml_page import XmlPage


class MainCameraOpenChatsPage(XmlPage):
    """Clicks the Chat icon in the bottom navigation bar from MAIN_PAGE."""

    def __init__(self):
        super().__init__(MainCameraPageRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        btns = xml.get_elements_by_id("com.snapchat.android:id/ngs_chat_icon_container")
        if not btns:
            btns = xml.get_elements_by_content_desc("Chat")
        if not btns:
            raise AutomationError("CHAT_TAB_NOT_FOUND", "Could not find Chat tab icon on MAIN_PAGE")
        controller.report_status("Opening Chats tab...")
        controller.click_element(btns[0])
        controller.set_location(Location.CHATS_PAGE)
        time.sleep(1.5)


class ChatsListOpenFriendChatPage(XmlPage):
    """Finds and opens the target friend's conversation from CHATS_PAGE (or via Search if not visible in feed)."""

    def __init__(self, target_user: str):
        super().__init__(ChatsListRule)
        self.target_user = target_user

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        target = self.target_user.strip()
        target_lower = target.lower()
        controller.report_status(f"Looking for chat with {target}...")

        # 1. Check if a chat row matching target is visible on CHATS_PAGE
        matches = [
            el for el in xml.get_elements_by_text_containing(target_lower)
            if 220 < el.center.y < 2150
        ]
        if matches:
            controller.click(Point(400, matches[0].center.y))
            time.sleep(1.8)
            return

        # 2. Try scrolling down once in the Chats feed
        if not context.get("scrolled_chats"):
            context["scrolled_chats"] = True
            controller.swipe(Point(540, 1750), Point(540, 550), duration_ms=350)
            time.sleep(1.2)
            xml_after = controller.fetch_xml()
            matches = [
                el for el in xml_after.get_elements_by_text_containing(target_lower)
                if 220 < el.center.y < 2150
            ]
            if matches:
                controller.click(Point(400, matches[0].center.y))
                time.sleep(1.8)
                return

        # 3. Fallback: click the top Search icon on Chats screen to find the friend by username
        search_btns = (
            xml.get_elements_by_id("com.snapchat.android:id/hova_header_search_icon")
            + xml.get_elements_by_content_desc("Search")
        )
        if search_btns:
            controller.report_status(f"Searching for {target} to open chat...")
            controller.click_element(search_btns[0])
            time.sleep(1.4)
            return

        raise AutomationError("CHAT_USER_NOT_FOUND", f"Could not find chat for user {target!r}")


class SearchOpenFriendChatPage(XmlPage):
    """Types the friend's username in Search and taps their row/Chat button to open the conversation."""

    def __init__(self, target_user: str):
        super().__init__(SearchFriendToChatRule)
        self.target_user = target_user

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        target = self.target_user.strip()
        target_lower = target.lower()
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs:
            raise AutomationError("SEARCH_INPUT_NOT_FOUND", "search-textfield not found")

        current_text = tfs[0].text.strip().lower()
        if target_lower not in current_text:
            controller.report_status(f"Typing {target} in search...")
            clear_btns = xml.get_elements_by_id("clear-button")
            if clear_btns:
                controller.click_element(clear_btns[0])
                time.sleep(0.6)
            else:
                controller.click_element(tfs[0])
                time.sleep(0.4)
            controller.keyboard(target)
            time.sleep(0.4)
            controller.click(Point(985, 2195))
            time.sleep(2.0)
            return

        # Look for a "Chat" button or the user's result row
        chat_btns = xml.get_elements_by_text("Chat") + xml.get_elements_by_content_desc("Chat")
        if chat_btns:
            controller.click_element(chat_btns[0])
            time.sleep(1.8)
            return

        user_nodes = [
            n for n in xml.get_elements_by_text_containing(target_lower)
            if n.resource_id != "search-textfield" and "view all results" not in n.text.lower()
        ]
        if user_nodes:
            controller.click(Point(350, user_nodes[0].center.y))
            time.sleep(1.8)
            return

        raise AutomationError("CHAT_USER_NOT_FOUND", f"No chat result found for {target!r}")


class FriendConversationReadyFinalPage(XmlPage):
    """Final page confirming the friend conversation screen is open."""

    def __init__(self, target_user: str):
        super().__init__(make_friend_conversation_open_rule(target_user))

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.CHAT_CONVERSATION_PAGE)
