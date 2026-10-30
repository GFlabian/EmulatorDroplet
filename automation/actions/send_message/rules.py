"""XmlPageRules for SEND_MESSAGE."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.shared_rules import MainCameraPageRule

# Chats list screen
ChatsListRule = XmlPageRule(
    include=[
        "com.snapchat.android:id/ngs_chat_icon_container",
    ],
    include_any=[
        "com.snapchat.android:id/ff_item",
        "com.snapchat.android:id/ptr_container",
        "list-picker-pill-Unread",
    ],
    exclude=[
        "com.snapchat.android:id/camera_page",
        "com.snapchat.android:id/chat_input_text_field",
        "search-textfield",
    ],
)

# Search screen when searching for a friend to chat with
SearchFriendToChatRule = XmlPageRule(
    include=["search-textfield"],
    exclude=["com.snapchat.android:id/chat_input_text_field"],
)


def make_friend_conversation_open_rule(target_user: str) -> XmlPageRule:
    target = target_user.strip().lower()

    def _pred(xml: Element) -> bool:
        if not xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field"):
            return False
        # Confirm we are inside a conversation (either matching target name or any non-AI chat)
        if not target:
            return True
        if xml.get_elements_by_text_containing(target):
            return True
        # Even if display name differs from username, chat_input_text_field + chat_message_list means conversation is open
        return bool(xml.get_elements_by_id("com.snapchat.android:id/chat_message_list"))

    return XmlPageRule(
        include=["com.snapchat.android:id/chat_input_text_field"],
        exclude=[
            "com.snapchat.android:id/alert_dialog_title",
            'text="Say Hi to My AI"',
            "built on generative AI technology",
        ],
        predicate=_pred,
    )


__all__ = [
    "ChatsListRule",
    "MainCameraPageRule",
    "SearchFriendToChatRule",
    "make_friend_conversation_open_rule",
]
