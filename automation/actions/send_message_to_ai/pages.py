"""XmlPage implementations for SEND_MESSAGE_TO_AI."""

import time
from typing import Any

from automation.actions.send_message_to_ai.rules import (
    AiChatConversationOpenRule,
    ChatsListWithMyAiRule,
    MainCameraPageRule,
    SayHiToMyAiDialogRule,
)
from automation.common.models import AutomationError, Element, Location, Point
from automation.common.phone_controller import PhoneController
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


class ChatsListOpenMyAiPage(XmlPage):
    """Clicks the 'My AI' conversation row on CHATS_PAGE."""

    def __init__(self):
        super().__init__(ChatsListWithMyAiRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Opening My AI chat...")
        ai_nodes = xml.get_elements_by_text("My AI")
        if ai_nodes:
            # In Snapchat 14.30 feed items (ff_item), the row spans full width; tap near x=400 at the row's y
            target_y = ai_nodes[0].center.y
            controller.click(Point(400, target_y))
            time.sleep(1.8)
            return

        # Scroll up to top of chat feed if My AI is not immediately visible
        controller.swipe(Point(540, 500), Point(540, 1600), duration_ms=350)
        time.sleep(1.2)
        xml_after = controller.fetch_xml()
        ai_nodes = xml_after.get_elements_by_text("My AI")
        if not ai_nodes:
            raise AutomationError("MY_AI_NOT_FOUND", "Could not find 'My AI' row in Chats list")
        controller.click(Point(400, ai_nodes[0].center.y))
        time.sleep(1.8)


class DismissSayHiToMyAiDialogPage(XmlPage):
    """Dismisses the first-time 'Say Hi to My AI' modal dialog."""

    def __init__(self):
        super().__init__(SayHiToMyAiDialogRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Accepting My AI intro dialog...")
        # Look for the clickable button at the bottom of the dialog content (around y=2013..2162)
        dialog_clickables = [
            el for el in xml.clickable_elements
            if el.center.y > 1900 and 150 <= el.center.x <= 930
        ]
        if dialog_clickables:
            controller.click_element(dialog_clickables[-1])
        else:
            controller.click(Point(540, 2085))
        time.sleep(1.5)


class AiChatReadyFinalPage(XmlPage):
    """Final page confirming the My AI conversation screen is open and ready for input."""

    def __init__(self):
        super().__init__(AiChatConversationOpenRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.set_location(Location.AI_CHAT_PAGE)
