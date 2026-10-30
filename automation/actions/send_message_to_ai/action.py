"""Action implementation for SEND_MESSAGE_TO_AI."""

import time
from typing import Any, Optional

from automation.actions.base_action import BaseAction
from automation.actions.send_message_to_ai.pages import (
    AiChatReadyFinalPage,
    ChatsListOpenMyAiPage,
    DismissSayHiToMyAiDialogPage,
    MainCameraOpenChatsPage,
)
from automation.common.models import ActionResult, AutomationError, Element, Location, Point
from automation.common.pages_service import PagesService
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


def extract_ai_responses(xml: Element) -> list[str]:
    """Extract all My AI response messages currently visible in the chat message list."""
    responses: list[str] = []

    # 1. Primary: nodes inside resource-id="chat_bot_response_message"
    bot_containers = xml.get_elements_by_id("chat_bot_response_message")
    for container in bot_containers:
        texts = [c.text.strip() for c in container.children if c.text and c.text.strip()]
        if texts:
            responses.append(" ".join(texts))
        elif container.text and container.text.strip():
            responses.append(container.text.strip())

    if responses:
        return responses

    # 2. Fallback: look inside chat_message_list for text nodes following a "MY AI" sender label
    msg_lists = xml.get_elements_by_id("com.snapchat.android:id/chat_message_list")
    root = msg_lists[0] if msg_lists else xml
    last_sender: Optional[str] = None
    for node in root.children:
        txt = node.text.strip()
        if not txt:
            continue
        upper = txt.upper()
        if upper == "MY AI":
            last_sender = "AI"
            continue
        if upper == "ME" or upper == "TODAY":
            last_sender = upper
            continue
        if last_sender == "AI" and "ask me a question" not in txt.lower():
            responses.append(txt)
            last_sender = None

    return responses


class SendMessageToAiAction(BaseAction):
    """Navigates to Chats -> My AI, asks a question from input, and returns the AI's response."""

    action_name = "SEND_MESSAGE_TO_AI"
    success_status = "AI_MESSAGE_SENT"
    failure_status = "AI_MESSAGE_FAILED"
    allowed_start_locations = (
        Location.MAIN_PAGE,
        Location.CHATS_PAGE,
    )

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        question = str(
            params.get("message")
            or params.get("question")
            or params.get("prompt")
            or params.get("text")
            or ""
        ).strip()
        if not question:
            raise AutomationError("MISSING_MESSAGE", "message (or question) is required for SEND_MESSAGE_TO_AI")

        response_timeout = float(params.get("timeout", 60.0))

        # If the phone resumed directly inside an existing AI_CHAT_PAGE fragment after
        # KEYCODE_HOME, Snapchat's Composer/Valdi accessibility bridge may not export
        # plugin_content_holder (chat_bot_response_message). Back out to CHATS_PAGE
        # first so ChatsListOpenMyAiPage mounts a fresh AI_CHAT_PAGE fragment.
        initial_xml = controller.fetch_xml(max_retries=1)
        if AiChatReadyFinalPage().is_detected(initial_xml):
            controller.click(Point(62, 147))
            time.sleep(2.5)

        # Navigate to My AI chat screen freshly from MAIN_PAGE / CHATS_PAGE
        service = PagesService(
            pages=[
                *COMMON_POPUP_PAGES,
                MainCameraOpenChatsPage(),
                ChatsListOpenMyAiPage(),
                DismissSayHiToMyAiDialogPage(),
            ],
            final_pages=[AiChatReadyFinalPage()],
            timeout=35,
            execute_last_page=True,
        )
        service.execute(controller)
        controller.set_location(Location.AI_CHAT_PAGE)

        # Snapshot existing AI responses before sending our question
        pre_xml = controller.fetch_xml()
        prev_responses = extract_ai_responses(pre_xml)
        prev_last = prev_responses[-1] if prev_responses else None
        prev_count = len(prev_responses)

        # Focus input bar and type question
        tfs = pre_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if not tfs:
            raise AutomationError("CHAT_INPUT_NOT_FOUND", "Could not find chat_input_text_field in My AI chat")

        controller.report_status(f"Typing question to My AI: {question[:40]}...")
        controller.click_element(tfs[0])
        time.sleep(0.8)

        # If there is stale text inside the input field, clear it first
        check_xml = controller.fetch_xml()
        check_tfs = check_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if check_tfs:
            existing_txt = check_tfs[0].text.strip()
            if existing_txt and existing_txt.lower() != "send a chat":
                controller.clear_text(len(existing_txt) + 10)
                time.sleep(0.4)

        controller.keyboard(question)
        time.sleep(0.6)

        # Submit via Gboard bottom-right Send key (Point(985, 2195))
        controller.report_status("Sending message to My AI...")
        controller.click(Point(985, 2195))
        time.sleep(1.5)

        post_send_xml = controller.fetch_xml(max_retries=1)
        post_tfs = post_send_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
        if post_tfs and post_tfs[0].text.strip().lower() not in ("", "send a chat"):
            # Tap Gboard Send key once more
            controller.click(Point(985, 2195))
            time.sleep(1.2)
            post_send_xml2 = controller.fetch_xml(max_retries=1)
            post_tfs2 = post_send_xml2.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
            if post_tfs2 and post_tfs2[0].text.strip().lower() not in ("", "send a chat"):
                controller.send_key(KeyType.ENTER)
                time.sleep(1.0)

        # Poll for the AI's new response.
        # Wait ~6s for My AI to reply on the server, then pause & resume LandingPageActivity
        # so Snapchat's Composer/Valdi view stops the typing indicator and mounts
        # plugin_content_holder (chat_bot_response_message) into the accessibility hierarchy.
        controller.report_status("Waiting for My AI response...")
        poll_start = time.monotonic()
        deadline = poll_start + response_timeout
        ai_reply: Optional[str] = None
        last_candidate: Optional[str] = None
        poll_idx = 0
        did_second_sync = False

        time.sleep(6.0)
        controller.park_in_background()
        time.sleep(2.0)
        controller.ensure_app_foreground(wait_seconds=4.0)

        while time.monotonic() < deadline:
            poll_idx += 1
            cur_xml = controller.fetch_xml(max_retries=1)

            # Handle Android ANR 'Wait' dialog if one appears during polling
            wait_btns = cur_xml.get_elements_by_id("android:id/aerr_wait")
            if wait_btns:
                controller.click_element(wait_btns[0])
                time.sleep(3.5)
                continue

            # If we are on Profile screen (e.g. accidental header tap), dismiss it
            prof_dismiss = cur_xml.get_elements_by_id("unified_profile_dismiss_button")
            if prof_dismiss:
                controller.click_element(prof_dismiss[0])
                time.sleep(1.5)
                continue

            # If we are on CHATS_PAGE or MAIN_PAGE, navigate back into My AI chat
            in_chat = bool(
                cur_xml.get_elements_by_id("com.snapchat.android:id/chat_message_list")
                or cur_xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field")
            )
            if cur_xml.children and not in_chat:
                ai_nodes = [
                    n for n in cur_xml.get_elements_by_text("My AI")
                    if n.center.y > 250
                ]
                if ai_nodes:
                    controller.click(Point(420, ai_nodes[0].center.y))
                    time.sleep(4.5)
                    continue
                chat_tabs = cur_xml.get_elements_by_id("com.snapchat.android:id/ngs_chat_icon_container")
                if chat_tabs:
                    controller.click_element(chat_tabs[0])
                    time.sleep(3.0)
                    continue

            cur_responses = extract_ai_responses(cur_xml)
            msg_lists = cur_xml.get_elements_by_id("com.snapchat.android:id/chat_message_list")
            root = msg_lists[0] if msg_lists else cur_xml
            senders = [
                n.text.strip().upper()
                for n in root.children
                if n.text and n.text.strip().upper() in ("ME", "MY AI")
            ]
            last_is_ai = bool(senders and senders[-1] == "MY AI")

            if last_is_ai and cur_responses:
                latest = cur_responses[-1]
                if len(cur_responses) > prev_count or latest != prev_last:
                    if not latest.endswith("...") or last_candidate == latest:
                        ai_reply = latest
                        break
                    last_candidate = latest
                    time.sleep(1.5)
                    continue

            if last_candidate:
                ai_reply = last_candidate
                break

            # Fallback: if 22s have elapsed and the new reply bubble hasn't mounted yet,
            # pause and resume LandingPageActivity once more.
            if not did_second_sync and (time.monotonic() - poll_start >= 22.0):
                did_second_sync = True
                controller.park_in_background()
                time.sleep(2.0)
                controller.ensure_app_foreground(wait_seconds=4.5)
                continue

            time.sleep(3.0)

        if not ai_reply and last_candidate:
            ai_reply = last_candidate

        if not ai_reply:
            raise AutomationError("AI_RESPONSE_TIMEOUT", "Timed out waiting for My AI to reply")

        # Leave AI_CHAT_PAGE back to CHATS_PAGE before parking in background
        controller.click(Point(62, 147))
        time.sleep(1.5)
        controller.set_location(Location.CHATS_PAGE)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={
                "question": question,
                "response": ai_reply,
            },
            location=Location.CHATS_PAGE,
        )
