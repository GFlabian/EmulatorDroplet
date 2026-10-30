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
        Location.AI_CHAT_PAGE,
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

        # Navigate to My AI chat screen
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

        # Poll for the AI's new response
        controller.report_status("Waiting for My AI response...")
        poll_start = time.monotonic()
        deadline = poll_start + response_timeout
        ai_reply: Optional[str] = None
        last_candidate: Optional[str] = None
        poll_idx = 0
        did_bg_sync = False
        ai_header_polls = 0

        # Give My AI ~6s to generate its reply on the server before the first poll
        time.sleep(6.0)

        while time.monotonic() < deadline:
            poll_idx += 1
            cur_xml = controller.fetch_xml(max_retries=0)

            # If uiautomator dump was blocked by My AI's continuous typing/Bitmoji animation
            # (empty XML), briefly pause & resume LandingPageActivity to stop the stuck
            # animation and sync the conversation from the server.
            if not cur_xml.children:
                controller.park_in_background()
                time.sleep(1.5)
                controller.ensure_app_foreground(wait_seconds=6.0)
                did_bg_sync = True
                cur_xml = controller.fetch_xml(max_retries=1)

            # Handle Android ANR 'Wait' dialog if one appears during polling
            wait_btns = cur_xml.get_elements_by_id("android:id/aerr_wait")
            if wait_btns:
                controller.click_element(wait_btns[0])
                time.sleep(3.0)
                continue

            # If we are on Profile screen (e.g. accidental header tap), dismiss it
            prof_dismiss = cur_xml.get_elements_by_id("unified_profile_dismiss_button")
            if prof_dismiss:
                controller.click_element(prof_dismiss[0])
                time.sleep(1.5)
                continue

            # If we are on MAIN_PAGE (Camera), open Chat tab
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

            if last_is_ai:
                ai_header_polls += 1
                if cur_responses:
                    latest = cur_responses[-1]
                    if len(cur_responses) > prev_count or latest != prev_last:
                        if not latest.endswith("...") or last_candidate == latest:
                            ai_reply = latest
                            break
                        last_candidate = latest
                        time.sleep(1.5)
                        continue
                # MY AI sender header is at the bottom of chat_message_list, waiting for
                # plugin_content_holder to finish inflating. If it hasn't inflated after 2 polls,
                # pause & resume LandingPageActivity so RecyclerView re-binds plugin_content_holder.
                if ai_header_polls in (2, 5):
                    controller.park_in_background()
                    time.sleep(1.5)
                    controller.ensure_app_foreground(wait_seconds=4.5)
                    did_bg_sync = True
                    continue
                time.sleep(3.0)
                continue

            if last_candidate:
                ai_reply = last_candidate
                break

            # If no MY AI bubble has appeared after ~14s, pause & resume once to force sync
            if not did_bg_sync and (time.monotonic() - poll_start >= 14.0) and not last_is_ai:
                did_bg_sync = True
                controller.park_in_background()
                time.sleep(1.5)
                controller.ensure_app_foreground(wait_seconds=6.0)
                continue

            time.sleep(2.5)

        if not ai_reply and last_candidate:
            ai_reply = last_candidate

        if not ai_reply:
            raise AutomationError("AI_RESPONSE_TIMEOUT", "Timed out waiting for My AI to reply")

        controller.set_location(Location.AI_CHAT_PAGE)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={
                "question": question,
                "response": ai_reply,
            },
            location=Location.AI_CHAT_PAGE,
        )
