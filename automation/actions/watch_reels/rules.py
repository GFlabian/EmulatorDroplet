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
    # On Spotlight tab: either Spotlight header/view or spotlight tab is selected
    if "Spotlight" in raw and (
        "spotlight" in raw.lower()
        and (
            "com.snapchat.android:id/ngs_spotlight_icon_container" in raw
            or "trending" in raw.lower()
            or "comment" in raw.lower()
        )
    ):
        # Make sure we're not on MAIN_PAGE, CHATS_PAGE, or STORIES_PAGE
        if "com.snapchat.android:id/camera_page" not in raw and "My AI" not in raw:
            return True
    return False


SpotlightReelsPageRule = XmlPageRule(
    include=["com.snapchat.android:id/ngs_spotlight_icon_container"],
    exclude=["com.snapchat.android:id/camera_page", "search-textfield"],
    predicate=_is_on_spotlight_tab,
)

__all__ = ["MainCameraPageRule", "SpotlightReelsPageRule"]
