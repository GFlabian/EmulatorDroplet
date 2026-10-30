"""Action implementation for WATCH_REELS."""

import random
import time
from typing import Any

from automation.actions.base_action import BaseAction
from automation.actions.watch_reels.pages import (
    MainCameraOpenSpotlightPage,
    SpotlightReelsReadyFinalPage,
)
from automation.common.models import ActionResult, AutomationError, Location, Point
from automation.common.pages_service import PagesService
from automation.common.phone_controller import PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


class WatchReelsAction(BaseAction):
    """Navigates to Spotlight/Reels and scrolls through a specified number of reels with random delays."""

    action_name = "WATCH_REELS"
    success_status = "REELS_WATCHED"
    failure_status = "WATCH_REELS_FAILED"
    allowed_start_locations = (Location.MAIN_PAGE, Location.REELS_PAGE)

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        raw_count = params.get("count", params.get("nr_of_reels", params.get("reels_count", 3)))
        try:
            count = int(raw_count)
            min_wait = float(params.get("min_wait", 2.0))
            max_wait = float(params.get("max_wait", max(min_wait, 5.0)))
        except (TypeError, ValueError) as exc:
            raise AutomationError("INVALID_PARAMS", f"Invalid WATCH_REELS parameters: {exc}")

        if count < 1:
            raise AutomationError("INVALID_PARAMS", "count (nr_of_reels) must be >= 1")
        if min_wait < 0 or max_wait < min_wait:
            raise AutomationError("INVALID_PARAMS", "Require 0 <= min_wait <= max_wait")

        service = PagesService(
            pages=[*COMMON_POPUP_PAGES, MainCameraOpenSpotlightPage()],
            final_pages=[SpotlightReelsReadyFinalPage()],
            timeout=60,
            execute_last_page=True,
        )
        service.execute(controller)
        controller.set_location(Location.REELS_PAGE)

        total_waited = 0.0
        for idx in range(1, count + 1):
            wait_s = random.uniform(min_wait, max_wait)
            controller.report_status(f"Watching reel {idx}/{count} ({wait_s:.1f}s)")
            time.sleep(wait_s)
            total_waited += wait_s
            if idx < count:
                controller.report_status(f"Scrolling to reel {idx + 1}/{count}")
                x = random.randint(460, 620)
                start_y = random.randint(1350, 1520)
                end_y = random.randint(420, 540)
                controller.swipe(Point(x, start_y), Point(x, end_y), duration_ms=random.randint(280, 380))
                time.sleep(0.8)

        # Return to MAIN_PAGE (Camera tab) after watching reels so the emulator does not
        # continuously decode 60 FPS Spotlight video in the background while IDLE.
        final_loc = Location.REELS_PAGE
        try:
            xml_end = controller.fetch_xml(max_retries=1)
            cam_btns = xml_end.get_elements_by_id("com.snapchat.android:id/ngs_camera_icon_container")
            if cam_btns:
                controller.click_element(cam_btns[0])
                time.sleep(1.0)
                final_loc = Location.MAIN_PAGE
        except Exception:
            pass
        controller.set_location(final_loc)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={
                "reels_watched": count,
                "min_wait": min_wait,
                "max_wait": max_wait,
                "total_wait_seconds": round(total_waited, 2),
            },
            location=final_loc,
        )
