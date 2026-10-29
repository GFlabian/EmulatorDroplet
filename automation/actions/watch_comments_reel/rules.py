"""XmlPageRules for WATCH_COMMENTS_REEL."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule


def _is_comments_sheet_open(xml: Element) -> bool:
    raw_lower = xml.raw.lower()
    if "add a comment" in raw_lower or "send a comment" in raw_lower or "no comments yet" in raw_lower:
        return True
    # Check for a Comments title header near the top/middle of the sheet
    for el in xml.get_elements_by_text_containing(["comment", "comments"]) + xml.get_elements_by_content_desc_containing(["close", "dismiss"]):
        if el.text.strip().lower().endswith("comments") or el.text.strip().lower() == "comments":
            return True
    return False


def _is_reel_without_comments_sheet(xml: Element) -> bool:
    if _is_comments_sheet_open(xml):
        return False
    raw = xml.raw
    return (
        "com.snapchat.android:id/ngs_spotlight_icon_container" in raw
        and "com.snapchat.android:id/camera_page" not in raw
    )


ReelCommentsOpenRule = XmlPageRule(predicate=_is_comments_sheet_open)

ReelViewActiveRule = XmlPageRule(predicate=_is_reel_without_comments_sheet)

__all__ = ["ReelCommentsOpenRule", "ReelViewActiveRule"]
