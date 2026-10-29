"""Navigation helpers including go_to_main_page() and location detection."""

from __future__ import annotations

import time
from typing import Optional

from automation.common.models import AutomationError, Element, Location
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES
from automation.common.shared_rules import (
    MainCameraPageRule,
    ProfileScreenRule,
    SearchScreenRule,
    UserAddedScreenRule,
)


def is_on_main_page(xml: Element) -> bool:
    return MainCameraPageRule.triggered(xml)


def detect_location_from_xml(xml: Element, fallback: str = Location.UNKNOWN) -> str:
    """Best-effort identification of the phone's current UI Location from XML."""
    if MainCameraPageRule.triggered(xml):
        return Location.MAIN_PAGE
    if UserAddedScreenRule.triggered(xml):
        return Location.USER_ADDED_PAGE
    if SearchScreenRule.triggered(xml):
        return Location.SEARCH_PAGE
    if ProfileScreenRule.triggered(xml):
        return Location.PROFILE_PAGE
    raw = xml.raw
    if "chat_input_text_field" in raw or "chat_message_list" in raw:
        if "My AI" in raw:
            return Location.AI_CHAT_PAGE
        return Location.CHAT_CONVERSATION_PAGE
    if "My Friends" in raw and ("Search" in raw or "All Friends" in raw):
        return Location.FRIENDS_LIST_PAGE
    if "Comments" in raw and ("Add a comment" in raw or "Send a comment" in raw or "comment" in raw.lower()):
        if "ngs_spotlight_icon_container" not in raw or "spotlight" in raw.lower():
            return Location.REEL_COMMENTS_PAGE
    if "com.snapchat.android:id/ngs_chat_icon_container" in raw and "Chat" in raw and "My AI" in raw:
        return Location.CHATS_PAGE
    if "com.snapchat.android:id/ngs_spotlight_icon_container" in raw and "com.snapchat.android:id/camera_page" not in raw:
        return Location.REELS_PAGE
    return fallback


def go_to_main_page(controller: PhoneController, max_click_attempts: int = 4) -> Element:
    """Navigate back to MAIN_PAGE via normal UI clicks; if that fails, restart Snapchat.

    Updates controller.location to Location.MAIN_PAGE and returns the MAIN_PAGE XML Element.
    """
    controller.report_status("Navigating to MAIN_PAGE...")

    for attempt in range(max_click_attempts):
        try:
            xml = controller.fetch_xml()
        except Exception:
            break

        if is_on_main_page(xml):
            controller.set_location(Location.MAIN_PAGE)
            return xml

        # Handle any common popups first
        popup_handled = False
        for popup_page in COMMON_POPUP_PAGES:
            if popup_page.is_detected(xml):
                popup_page.execute(controller, xml, {})
                popup_handled = True
                break
        if popup_handled:
            time.sleep(1.0)
            continue

        # 1. If the bottom nav bar's Camera icon is visible, click it directly
        camera_tabs = xml.get_elements_by_id("com.snapchat.android:id/ngs_camera_icon_container")
        if camera_tabs:
            controller.click_element(camera_tabs[0])
            time.sleep(1.2)
            xml_after = controller.fetch_xml()
            if is_on_main_page(xml_after):
                controller.set_location(Location.MAIN_PAGE)
                return xml_after

        # 2. If a Search Cancel / Dismiss / Back button is visible, click it
        clicked_back = False
        for rid in (
            "dismiss-button",
            "com.snapchat.android:id/unified_profile_dismiss_button",
            "com.snapchat.android:id/subscreen_top_left",
            "com.snapchat.android:id/chat_input_bar_back",
            "com.snapchat.android:id/back_button",
        ):
            btns = xml.get_elements_by_id(rid)
            if btns:
                controller.click_element(btns[0])
                clicked_back = True
                break

        if not clicked_back:
            cancel_texts = xml.get_elements_by_text(["Cancel", "Close", "Dismiss"])
            if cancel_texts:
                controller.click_element(cancel_texts[0])
                clicked_back = True

        if not clicked_back:
            back_descs = xml.get_elements_by_content_desc(["Back", "Close", "Dismiss", "Cancel", "Leave chat"])
            if back_descs:
                controller.click_element(back_descs[0])
                clicked_back = True

        if not clicked_back:
            controller.send_key(KeyType.BACK)

        time.sleep(1.2)

    # Check once more before restarting app
    try:
        xml = controller.fetch_xml()
        if is_on_main_page(xml):
            controller.set_location(Location.MAIN_PAGE)
            return xml
    except Exception:
        pass

    # Fallback: restart Snapchat and wait for MAIN_PAGE
    controller.restart_app(wait_seconds=3.5)
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline:
        xml = controller.fetch_xml()
        if is_on_main_page(xml):
            controller.set_location(Location.MAIN_PAGE)
            return xml
        for popup_page in COMMON_POPUP_PAGES:
            if popup_page.is_detected(xml):
                popup_page.execute(controller, xml, {})
                break
        # If it opened on Chat tab or another bottom-nav tab, click Camera tab
        camera_tabs = xml.get_elements_by_id("com.snapchat.android:id/ngs_camera_icon_container")
        if camera_tabs:
            controller.click_element(camera_tabs[0])
        time.sleep(1.2)

    raise AutomationError("GO_TO_MAIN_PAGE_FAILED", "Could not reach MAIN_PAGE even after restarting Snapchat")
