"""XmlPageRules for SEND_MESSAGE_TO_AI."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.shared_rules import MainCameraPageRule

# Chats list screen showing "My AI" row
ChatsListWithMyAiRule = XmlPageRule(
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

# "Say Hi to My AI" first-time onboarding dialog inside My AI chat
SayHiToMyAiDialogRule = XmlPageRule(
    include_any=[
        'text="Say Hi to My AI"',
        "Here’s what you need to know before you use My AI",
        "built on generative AI technology",
    ]
)


def _is_ai_chat_open(xml: Element) -> bool:
    if not xml.get_elements_by_id("com.snapchat.android:id/chat_input_text_field"):
        return False
    if xml.get_elements_by_text("Say Hi to My AI"):
        return False
    return bool(
        xml.get_elements_by_text("My AI")
        or xml.get_elements_by_text("MY AI")
        or xml.get_elements_by_text("Customize my personality!")
    )


AiChatConversationOpenRule = XmlPageRule(
    include=["com.snapchat.android:id/chat_input_text_field"],
    exclude=['text="Say Hi to My AI"'],
    predicate=_is_ai_chat_open,
)

__all__ = [
    "AiChatConversationOpenRule",
    "ChatsListWithMyAiRule",
    "MainCameraPageRule",
    "SayHiToMyAiDialogRule",
]
