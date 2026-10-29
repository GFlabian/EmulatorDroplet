"""XmlPageRules for FETCH_FRIENDS."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.shared_rules import MainCameraPageRule

# Bitmoji avatar tray that can pop up if the 3D bitmoji area on Profile is tapped/swiped
BitmojiMenuTrayRule = XmlPageRule(
    include=["bitmoji_profile/menu_tray_dismiss_button"]
)

# Profile screen when "My Friends" row is not yet scrolled into view
ProfileNeedsScrollToMyFriendsRule = XmlPageRule(
    include_any=[
        "unified_profile_dismiss_button",
        "unified_profile_icon_button_settings",
        "profile_scroll_view",
    ],
    exclude=[
        'text="My Friends"',
        "bitmoji_profile/menu_tray_dismiss_button",
        "com.snapchat.android:id/input_field_edit_text",
    ],
)

# Profile screen when "My Friends" row is visible
ProfileHasMyFriendsRowRule = XmlPageRule(
    include=['text="My Friends"'],
    include_any=[
        "unified_profile_dismiss_button",
        "unified_profile_icon_button_settings",
        "profile_scroll_view",
    ],
    exclude=[
        "com.snapchat.android:id/input_field_edit_text",
    ],
)


def _is_friends_list_screen(xml: Element) -> bool:
    if not xml.get_elements_by_id("com.snapchat.android:id/input_field_edit_text"):
        return False
    return bool(xml.get_elements_by_text("My Friends"))


FriendsListScreenRule = XmlPageRule(
    include=[
        "com.snapchat.android:id/input_field_edit_text",
        'text="My Friends"',
    ],
    predicate=_is_friends_list_screen,
)

__all__ = [
    "BitmojiMenuTrayRule",
    "FriendsListScreenRule",
    "MainCameraPageRule",
    "ProfileHasMyFriendsRowRule",
    "ProfileNeedsScrollToMyFriendsRule",
]
