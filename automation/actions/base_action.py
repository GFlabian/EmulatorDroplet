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
        controller.current_action_type = self.action_name
        controller.log_event(
            level="INFO",
            event_type="ACTION_START",
            message=f"Starting action {self.action_name}",
            details={"params": params, "start_location": controller.location},
        )
        try:
            if self.action_name != "UPDATE_SESSION":
                controller.ensure_app_foreground(wait_seconds=2.5)
            self.prepare_start_position(controller, params)
            res = self.run(controller, params)
            controller.log_event(
                level="INFO" if res.error is None else "ERROR",
                event_type="ACTION_COMPLETE" if res.error is None else "ACTION_FAILED",
                message=f"Action {self.action_name} finished with status={res.status}",
                details={"status": res.status, "error": res.error, "location": res.location},
            )
            return res
        except AutomationError as exc:
            controller.log_event(
                level="ERROR",
                event_type="ACTION_ERROR",
                message=f"{exc.code}: {exc.message}",
                details={"code": exc.code, "message": exc.message, "location": controller.location},
                xml_element=controller.last_xml,
            )
            if exc.code not in ("UNKNOWN_PAGE_TIMEOUT", "STUCK_ON_SAME_PAGE", "REPEATED_PAGE_ERROR", "GO_TO_MAIN_PAGE_FAILED"):
                controller.record_unknown_page(
                    reason=f"ACTION_ERROR:{exc.code}",
                    expected_pages=self.action_name,
                    xml_element=controller.last_xml,
                )
            return ActionResult(
                status=self.failure_status,
                error=f"{exc.code}: {exc.message}",
                location=controller.location,
            )
        except Exception as exc:
            controller.log_event(
                level="ERROR",
                event_type="ACTION_EXCEPTION",
                message=str(exc),
                details={"exception": str(exc), "location": controller.location},
                xml_element=controller.last_xml,
            )
            controller.record_unknown_page(
                reason=f"ACTION_EXCEPTION:{type(exc).__name__}",
                expected_pages=self.action_name,
                xml_element=controller.last_xml,
            )
            return ActionResult(
                status=self.failure_status,
                error=str(exc),
                location=controller.location,
            )
        finally:
            if self.action_name != "UPDATE_SESSION":
                controller.park_in_background()

    @abstractmethod
    def run(self, controller: PhoneController, params: dict[str, Any]) -> ActionResult:
        pass
