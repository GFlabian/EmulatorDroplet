"""Base class for all emulator automation actions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from automation.common.models import ActionResult, AutomationError, Location
from automation.common.navigation import go_to_main_page
from automation.common.phone_controller import PhoneController


class BaseAction(ABC):
    """Base contract for a high-level Snapchat action."""

    action_name: str = "BASE_ACTION"
    success_status: str = "COMPLETED"
    failure_status: str = "FAILED"

    # Locations from which this action can start directly without resetting to MAIN_PAGE.
    allowed_start_locations: tuple[str, ...] = (Location.MAIN_PAGE,)

    # If True, requires controller.location to already be in allowed_start_locations
    # and raises an error instead of navigating to MAIN_PAGE when not there.
    strict_start_location: bool = False

    def prepare_start_position(self, controller: PhoneController, params: dict[str, Any]):
        """Ensure the phone is in a valid starting location for this action."""
        current_loc = controller.location
        if current_loc in self.allowed_start_locations:
            return
        if self.strict_start_location:
            raise AutomationError(
                "INVALID_START_LOCATION",
                f"{self.action_name} requires location in {self.allowed_start_locations}, "
                f"but phone is currently at {current_loc!r}",
            )
        go_to_main_page(controller)

    def execute(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        """Validate start position, run the action, and return a structured ActionResult."""
        try:
            self.prepare_start_position(controller, params)
            return self.run(controller, params)
        except AutomationError as exc:
            return ActionResult(
                status=self.failure_status,
                error=f"{exc.code}: {exc.message}",
                location=controller.location,
            )
        except Exception as exc:
            return ActionResult(
                status=self.failure_status,
                error=str(exc),
                location=controller.location,
            )

    @abstractmethod
    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        pass
