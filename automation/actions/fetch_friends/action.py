"""Action implementation for FETCH_FRIENDS."""

import time
from typing import Any

from automation.actions.base_action import BaseAction
from automation.actions.fetch_friends.pages import (
    DismissBitmojiMenuTrayPage,
    FriendsListReadyFinalPage,
    MainCameraOpenProfilePage,
    ProfileClickMyFriendsPage,
    ProfileScrollToMyFriendsPage,
)
from automation.common.models import ActionResult, Element, Location, Point
from automation.common.pages_service import PagesService
from automation.common.phone_controller import PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


def extract_friends_from_xml(xml: Element, include_my_ai: bool = False) -> list[str]:
    """Extract friend names from the My Friends RecyclerView."""
    friends: list[str] = []
    rvs = xml.get_elements_by_class("androidx.recyclerview.widget.RecyclerView")
    root = rvs[0] if rvs else xml

    for node in root.children:
        txt = node.text.strip()
        if not txt:
            continue
        p1, p2 = node.bounds
        # Friend name labels sit in the main column (120 <= x1 <= 400, y1 >= 350)
        # Alphabet section headers have x1 ~ 45 and len == 1; right-side emojis/index bar have x1 > 850
        if p1.x < 120 or p1.x > 500 or p1.y < 350:
            continue
        if txt in ("My Friends", "Find friends", "Currently no friends"):
            continue
        if not include_my_ai and txt.lower() == "my ai":
            continue
        if txt not in friends:
            friends.append(txt)

    return friends


class FetchFriendsAction(BaseAction):
    """Navigates to Profile -> My Friends, scrolls through the friends list, and returns all friends."""

    action_name = "FETCH_FRIENDS"
    success_status = "FRIENDS_FETCHED"
    failure_status = "FETCH_FRIENDS_FAILED"
    allowed_start_locations = (
        Location.MAIN_PAGE,
        Location.PROFILE_PAGE,
        Location.FRIENDS_LIST_PAGE,
    )

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        include_my_ai = bool(params.get("include_my_ai", False))
        max_scrolls = int(params.get("max_scrolls", 8))

        service = PagesService(
            pages=[
                *COMMON_POPUP_PAGES,
                MainCameraOpenProfilePage(),
                DismissBitmojiMenuTrayPage(),
                ProfileScrollToMyFriendsPage(),
                ProfileClickMyFriendsPage(),
            ],
            final_pages=[FriendsListReadyFinalPage()],
            timeout=35,
            execute_last_page=True,
            max_executions_same_page=3,
        )
        service.execute(controller)
        controller.set_location(Location.FRIENDS_LIST_PAGE)

        controller.report_status("Reading friends list...")
        all_friends: list[str] = []

        for scroll_idx in range(max_scrolls):
            xml = controller.fetch_xml()
            visible = extract_friends_from_xml(xml, include_my_ai=include_my_ai)
            added_new = False
            for f in visible:
                if f not in all_friends:
                    all_friends.append(f)
                    added_new = True

            # Only scroll if there are multiple items near the bottom of the screen
            if not added_new or len(visible) < 5:
                break

            controller.swipe(Point(500, 1850), Point(500, 550), duration_ms=380)
            time.sleep(1.0)

        controller.set_location(Location.FRIENDS_LIST_PAGE)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={
                "friends": all_friends,
                "count": len(all_friends),
            },
            location=Location.FRIENDS_LIST_PAGE,
        )
