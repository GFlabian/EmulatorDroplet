"""XmlPageRules for the WATCH_REELS action."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.shared_rules import MainCameraPageRule


def _is_on_spotlight_tab(xml: Element) -> bool:
    if MainCameraPageRule.triggered(xml):
        return False
    raw = xml.raw
    if "com.snapchat.android:id/camera_capture_button" in raw:
        return False
    if "com.snapchat.android:id/camera_page" in raw or "My AI" in raw or "chat_input_text_field" in raw:
        return False
    raw_lower = raw.lower()
    if any(
        marker in raw_lower
        for marker in (
            "com.snapchat.android:id/favorite",
            "spotlight",
            "swipe up to next",
            "original sound",
            "trending",
            "#fyp",
        )
    ):
        return True
    if 'text="Camera"' in raw and "com.snapchat.android:id/ngs_spotlight_icon_container" in raw:
        if 'text="Friends"' not in raw and 'text="New Chat"' not in raw:
            return True
    return False


SpotlightReelsPageRule = XmlPageRule(
    include=["com.snapchat.android:id/ngs_spotlight_icon_container"],
    exclude=["com.snapchat.android:id/camera_page", "search-textfield"],
    predicate=_is_on_spotlight_tab,
)

__all__ = ["MainCameraPageRule", "SpotlightReelsPageRule"]
