"""Action implementation for WATCH_COMMENTS_REEL."""

import time
from typing import Any

from automation.actions.base_action import BaseAction
from automation.actions.watch_comments_reel.pages import (
    BackOnReelFinalPage,
    CloseReelCommentsPage,
    OpenReelCommentsPage,
    ReelCommentsOpenedFinalPage,
)
from automation.actions.watch_reels.pages import MainCameraOpenSpotlightPage
from automation.common.models import ActionResult, AutomationError, Location
from automation.common.pages_service import PagesService
from automation.common.phone_controller import PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


class WatchCommentsReelAction(BaseAction):
    """Requires being on a reel (REELS_PAGE) or MAIN_PAGE; opens comments, waits, and closes comments back to the reel."""

    action_name = "WATCH_COMMENTS_REEL"
    success_status = "COMMENTS_WATCHED"
    failure_status = "WATCH_COMMENTS_FAILED"
    allowed_start_locations = (Location.REELS_PAGE, Location.MAIN_PAGE)
    strict_start_location = False

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        raw_wait = params.get("wait_time", params.get("wait", params.get("duration", 5.0)))
        try:
            wait_time = float(raw_wait)
        except (TypeError, ValueError) as exc:
            raise AutomationError("INVALID_PARAMS", f"Invalid wait_time for WATCH_COMMENTS_REEL: {exc}")

        if wait_time < 0:
            raise AutomationError("INVALID_PARAMS", "wait_time must be >= 0")

        # 1. Open comments (navigates to Spotlight first if currently on MAIN_PAGE)
        open_service = PagesService(
            pages=[*COMMON_POPUP_PAGES, MainCameraOpenSpotlightPage(), OpenReelCommentsPage()],
            final_pages=[ReelCommentsOpenedFinalPage()],
            timeout=45,
            execute_last_page=True,
            max_executions_same_page=5,
        )
        open_service.execute(controller)
        controller.set_location(Location.REEL_COMMENTS_PAGE)

        # 2. Wait the specified duration while viewing comments
        controller.report_status(f"Watching reel comments ({wait_time:.1f}s)...")
        time.sleep(wait_time)

        # 3. Close comments and return to the reel
        close_service = PagesService(
            pages=[*COMMON_POPUP_PAGES, CloseReelCommentsPage()],
            final_pages=[BackOnReelFinalPage()],
            timeout=35,
            execute_last_page=True,
            max_executions_same_page=4,
        )
        close_service.execute(controller)
        controller.set_location(Location.REELS_PAGE)

        return ActionResult(
            status=self.success_status,
            error=None,
            data={"wait_time": wait_time},
            location=Location.REELS_PAGE,
        )
