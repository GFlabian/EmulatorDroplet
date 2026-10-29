"""Action implementation for ADD_FRIEND / ADD_USER."""

from typing import Any

from automation.actions.add_friend.pages import (
    MainCameraOpenSearchPage,
    SearchClearPreviousPage,
    SearchClickAddUserPage,
    SearchTypeUsernamePage,
    SearchViewAllResultsPage,
    UserAddedFinalPage,
)
from automation.actions.base_action import BaseAction
from automation.common.models import ActionResult, AutomationError, Location
from automation.common.pages_service import PagesService
from automation.common.phone_controller import PhoneController
from automation.common.shared_pages import COMMON_POPUP_PAGES


class AddFriendAction(BaseAction):
    """Searches for a username and clicks Add, finishing on USER_ADDED_PAGE."""

    action_name = "ADD_FRIEND"
    success_status = "FRIEND_ADDED"
    failure_status = "ADD_FAILED"
    allowed_start_locations = (
        Location.MAIN_PAGE,
        Location.USER_ADDED_PAGE,
        Location.SEARCH_PAGE,
    )

    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        username = str(params.get("username") or "").strip()
        if not username:
            raise AutomationError("MISSING_USERNAME", "username is required for ADD_FRIEND")

        pages = [
            *COMMON_POPUP_PAGES,
            MainCameraOpenSearchPage(),
            SearchClearPreviousPage(username),
            SearchTypeUsernamePage(username),
            SearchClickAddUserPage(username),
            SearchViewAllResultsPage(username),
        ]
        final_pages = [UserAddedFinalPage(username)]

        service = PagesService(
            pages=pages,
            final_pages=final_pages,
            timeout=40,
            execute_last_page=True,
            max_executions_same_page=4,
        )
        service.execute(controller, context={"username": username})
        controller.set_location(Location.USER_ADDED_PAGE)
        return ActionResult(
            status=self.success_status,
            error=None,
            data={"username": username},
            location=Location.USER_ADDED_PAGE,
        )
