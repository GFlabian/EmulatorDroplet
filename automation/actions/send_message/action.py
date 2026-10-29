"""Action implementation for SEND_MESSAGE."""

import time
from typing import Any

from automation.actions.base_action import BaseAction
from automation.actions.send_message.pages import (
    ChatsListOpenFriendChatPage,
    FriendConversationReadyFinalPage,
    MainCameraOpenChatsPage,
    SearchOpenFriendChatPage,
)
from automation.common.models import ActionResult, AutomationError, Location, Point
from automation.common.pages_service import PagesService
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


class SendMessageAction(BaseAction):
    """Navigates to Chats, enters a specific user's chat, and sends the message from input."""

    action_name = "SEND_MESSAGE"
    success_status = "MESSAGE_SENT"
    failure_status = "SEND_MESSAGE_FAILED"
    allowed_start_locations = (
        Location.MAIN_PAGE,
        Location.CHATS_PAGE,
        Location.CHAT_CONVERSATION_PAGE,
    )

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        target_user = str(
            params.get("username")
            or params.get("friend")
            or params.get("user")
            or params.get("recipient")
            or ""
        ).strip()
        message = str(params.get("message") or params.get("text") or "").strip()

        if not target_user:
            raise AutomationError("MISSING_USERNAME", "username (or friend) is required for SEND_MESSAGE")
        if not message:
            raise AutomationError("MISSING_MESSAGE", "message is required for SEND_MESSAGE")

        # If we are already inside a different user's conversation, back out to CHATS_PAGE first
        if controller.location == Location.CHAT_CONVERSATION_PAGE:
            cur_xml = controller.fetch_xml()
            if not cur_xml.get_elements_by_text_containing(target_user.lower()):
                controller.send_key(KeyType.BACK)
                time.sleep(1.2)
                controller.set_location(Location.CHATS_PAGE)

        service = PagesService(
            pages=[
                *COMMON_POPUP_PAGES,
                MainCameraOpenChatsPage(),
                ChatsListOpenFriendChatPage(target_user),
                SearchOpenFriendChatPage(target_user),
            ],
            final_pages=[FriendConversationReadyFinalPage(target_user)],
            timeout=35,
            execute_last_page=True,
            max_executions_same_page=3,
        )
        service.execute(controller)
        controller.set_location(Location.CHAT_CONVERSATION_PAGE)

        chat_xml = controller.fetch_xml()
        tfs = chat_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if not tfs:
            raise AutomationError("CHAT_INPUT_NOT_FOUND", "chat_input_text_field not found in conversation")

        controller.report_status(f"Typing message to {target_user}...")
        controller.click_element(tfs[0])
        time.sleep(0.8)

        check_xml = controller.fetch_xml()
        check_tfs = check_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if check_tfs:
            existing_txt = check_tfs[0].text.strip()
            if existing_txt and existing_txt.lower() != "send a chat":
                controller.clear_text(len(existing_txt) + 10)
                time.sleep(0.4)

        controller.keyboard(message)
        time.sleep(0.6)

        controller.report_status(f"Sending message to {target_user}...")
        controller.click(Point(985, 2195))
        time.sleep(1.5)

        post_xml = controller.fetch_xml()
        post_tfs = post_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if post_tfs and post_tfs[0].text.strip().lower() not in ("", "send a chat"):
            controller.click(Point(985, 2195))
            time.sleep(1.2)
            post_xml2 = controller.fetch_xml()
            post_tfs2 = post_xml2.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
            if post_tfs2 and post_tfs2[0].text.strip().lower() not in ("", "send a chat"):
                controller.send_key(KeyType.ENTER)
                time.sleep(1.0)

        controller.set_location(Location.CHAT_CONVERSATION_PAGE)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={
                "username": target_user,
                "message": message,
            },
            location=Location.CHAT_CONVERSATION_PAGE,
        )
