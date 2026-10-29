"""UPDATE_SESSION action: extract /data/data/com.snapchat.android, compress to .7z, and upload to DigitalOcean Spaces."""

from __future__ import annotations

import time
from typing import Any

from automation.actions.base_action import BaseAction
from automation.common.models import ActionResult, AutomationError, Location
from automation.common.phone_controller import PhoneController


class UpdateSessionAction(BaseAction):
    """Extract and upload /data/data/com.snapchat.android in place of the existing session in Spaces."""

    action_name = "UPDATE_SESSION"
    success_status = "SESSION_UPDATED"
    failure_status = "UPDATE_SESSION_FAILED"
    allowed_start_locations = (
        Location.MAIN_PAGE,
        Location.SEARCH_PAGE,
        Location.USER_ADDED_PAGE,
        Location.REELS_PAGE,
        Location.REEL_COMMENTS_PAGE,
        Location.CHATS_PAGE,
        Location.CHAT_CONVERSATION_PAGE,
        Location.AI_CHAT_PAGE,
        Location.PROFILE_PAGE,
        Location.FRIENDS_LIST_PAGE,
        Location.UNKNOWN,
    )

    def prepare_start_position(self, controller: PhoneController, params: dict[str, Any]):
        # No UI navigation required before extracting /data/data/com.snapchat.android
        return

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        target_username = str(params.get("username") or controller.username or "").strip()
        if not target_username:
            raise AutomationError("MISSING_PARAMETER", "UPDATE_SESSION requires 'username' (or emulator account username)")

        info = controller.manager.save_snapchat_session(
            controller.avd_name,
            target_username,
            on_status=controller.report_status,
        )
        time.sleep(2.5)
        controller.set_location(Location.MAIN_PAGE)
        return ActionResult(
            status=self.success_status,
            location=Location.MAIN_PAGE,
            data=info,
        )
