"""Registry of all automation actions."""

from typing import Type

from automation.actions.add_friend.action import AddFriendAction
from automation.actions.base_action import BaseAction
from automation.actions.fetch_friends.action import FetchFriendsAction
from automation.actions.send_message.action import SendMessageAction
from automation.actions.send_message_to_ai.action import SendMessageToAiAction
from automation.actions.watch_comments_reel.action import WatchCommentsReelAction
from automation.actions.watch_reels.action import WatchReelsAction
from automation.common.models import AutomationError


ACTION_REGISTRY: dict[str, Type[BaseAction]] = {
    "ADD_FRIEND": AddFriendAction,
    "ADD_USER": AddFriendAction,
    "WATCH_REELS": WatchReelsAction,
    "WATCH_COMMENTS_REEL": WatchCommentsReelAction,
    "SEND_MESSAGE_TO_AI": SendMessageToAiAction,
    "FETCH_FRIENDS": FetchFriendsAction,
    "SEND_MESSAGE": SendMessageAction,
}


def get_action(action_name: str) -> BaseAction:
    """Instantiate an action handler by name (case-insensitive)."""
    key = (action_name or "").strip().upper()
    cls = ACTION_REGISTRY.get(key)
    if cls is None:
        supported = ", ".join(sorted(ACTION_REGISTRY.keys()))
        raise AutomationError("UNKNOWN_ACTION", f"Unknown action {action_name!r}. Supported actions: {supported}")
    instance = cls()
    # Preserve the requested alias if ADD_USER was used
    if key == "ADD_USER":
        instance.action_name = "ADD_USER"
    return instance


def list_supported_actions() -> list[dict]:
    """Return metadata describing all supported actions and their parameters."""
    return [
        {
            "name": "ADD_FRIEND",
            "aliases": ["ADD_USER"],
            "description": "Search for a username, click Add, wait for Added badge, and stay on USER_ADDED_PAGE.",
            "allowed_start_locations": list(AddFriendAction.allowed_start_locations),
            "params": [
                {"name": "username", "type": "string", "required": True, "placeholder": "e.g. john_doe123"},
            ],
            "success_status": AddFriendAction.success_status,
            "failure_status": AddFriendAction.failure_status,
        },
        {
            "name": "WATCH_REELS",
            "aliases": [],
            "description": "Navigate to Spotlight/Reels and scroll through a number of reels with random delay between min_wait and max_wait.",
            "allowed_start_locations": list(WatchReelsAction.allowed_start_locations),
            "params": [
                {"name": "count", "type": "int", "required": True, "default": 3},
                {"name": "min_wait", "type": "float", "required": True, "default": 2.0},
                {"name": "max_wait", "type": "float", "required": True, "default": 5.0},
            ],
            "success_status": WatchReelsAction.success_status,
            "failure_status": WatchReelsAction.failure_status,
        },
        {
            "name": "WATCH_COMMENTS_REEL",
            "aliases": [],
            "description": "Requires phone to already be on REELS_PAGE (errors if not). Opens reel comments, waits wait_time seconds, and closes comments back to REELS_PAGE.",
            "allowed_start_locations": list(WatchCommentsReelAction.allowed_start_locations),
            "strict_start_location": True,
            "params": [
                {"name": "wait_time", "type": "float", "required": True, "default": 5.0},
            ],
            "success_status": WatchCommentsReelAction.success_status,
            "failure_status": WatchCommentsReelAction.failure_status,
        },
        {
            "name": "SEND_MESSAGE_TO_AI",
            "aliases": [],
            "description": "Go to Chats -> My AI, ask a question from input, and return the AI's reply in data.response.",
            "allowed_start_locations": list(SendMessageToAiAction.allowed_start_locations),
            "params": [
                {"name": "message", "type": "string", "required": True, "placeholder": "Ask My AI a question..."},
            ],
            "success_status": SendMessageToAiAction.success_status,
            "failure_status": SendMessageToAiAction.failure_status,
        },
        {
            "name": "FETCH_FRIENDS",
            "aliases": [],
            "description": "Navigate to Profile -> My Friends and return the account's friends list in data.friends.",
            "allowed_start_locations": list(FetchFriendsAction.allowed_start_locations),
            "params": [],
            "success_status": FetchFriendsAction.success_status,
            "failure_status": FetchFriendsAction.failure_status,
        },
        {
            "name": "SEND_MESSAGE",
            "aliases": [],
            "description": "Go to Chats, open a specific friend's conversation, and send the message from input.",
            "allowed_start_locations": list(SendMessageAction.allowed_start_locations),
            "params": [
                {"name": "username", "type": "string", "required": True, "placeholder": "Friend username or display name"},
                {"name": "message", "type": "string", "required": True, "placeholder": "Message to send"},
            ],
            "success_status": SendMessageAction.success_status,
            "failure_status": SendMessageAction.failure_status,
        },
    ]


__all__ = [
    "ACTION_REGISTRY",
    "AddFriendAction",
    "BaseAction",
    "FetchFriendsAction",
    "SendMessageAction",
    "SendMessageToAiAction",
    "WatchCommentsReelAction",
    "WatchReelsAction",
    "get_action",
    "list_supported_actions",
]
