"""Page detection and execution loop service (modeled on FreyaAutomation PagesService)."""

from __future__ import annotations

import time
from typing import Any, Optional

from automation.common.models import AutomationError, Element
from automation.common.phone_controller import PhoneController
from automation.common.xml_page import XmlPage


class PagesService:
    """Polls UIAutomator XML, identifies the active XmlPage, executes it, and stops on final_pages."""

    def __init__(
        self,
        pages: list[XmlPage],
        final_pages: list[XmlPage],
        timeout: int = 60,
        execute_last_page: bool = False,
        max_executions_same_page: int = 10,
        poll_interval: float = 0.6,
    ):
        if not final_pages:
            raise AutomationError("INVALID_PAGES", "final_pages cannot be empty")

        self._final_pages: list[str] = [p.name for p in final_pages]
        seen = set()
        combined: list[XmlPage] = []
        for p in list(pages) + list(final_pages):
            if p.name not in seen:
                seen.add(p.name)
                combined.append(p)
        self._pages: list[XmlPage] = combined
        self._timeout = timeout
        self._execute_last_page = execute_last_page
        self._max_executions_same_page = max_executions_same_page
        self._poll_interval = poll_interval
        self._last_pages_history: list[str] = []
        self._last_detected_page: Optional[XmlPage] = None

    @property
    def pages_history(self) -> list[str]:
        return list(self._last_pages_history)

    @property
    def last_detected_page(self) -> Optional[XmlPage]:
        return self._last_detected_page

    def execute(
        self,
        controller: PhoneController,
        context: Optional[dict[str, Any]] = None,
    ) -> Element:
        ctx = context if context is not None else {}
        last_page_ts = time.monotonic()
        local_history: list[str] = []
        self._last_pages_history = local_history
        self._last_detected_page = None
        unknown_streak = 0
        expected_str = ", ".join(p.name for p in self._pages)

        while True:
            current_xml = controller.fetch_xml()
            detected_page = self._detect_current_page(
                current_xml, last_page_ts, local_history, controller=controller
            )

            if detected_page is None:
                unknown_streak += 1
                raw = current_xml.raw if current_xml is not None else ""
                if "com.google.android.apps.nexuslauncher" in raw:
                    controller.ensure_app_foreground(wait_seconds=4.0)
                    time.sleep(self._poll_interval)
                    continue
                if unknown_streak == 4:
                    controller.record_unknown_page(
                        reason="UNKNOWN_SCREEN_POLLING",
                        expected_pages=expected_str,
                        xml_element=current_xml,
                    )
                elif unknown_streak == 8:
                    # If the screen is blank or unrecognized for 8 polls (~10-15s), nudge Snapchat to foreground
                    if len(raw) < 450:
                        controller.ensure_app_foreground(wait_seconds=3.0)
                time.sleep(self._poll_interval)
                continue

            unknown_streak = 0
            self._last_detected_page = detected_page
            if detected_page.name != "SystemAnrDialogPage":
                ctx["_anr_count"] = 0
            controller.log_event(
                level="INFO",
                event_type="PAGE_MATCHED",
                message=f"Matched page {detected_page.name}",
                page_name=detected_page.name,
                details={"history": list(local_history), "is_final": detected_page.name in self._final_pages},
            )

            if detected_page.name in self._final_pages and not self._execute_last_page:
                return current_xml

            try:
                detected_page.execute(controller, current_xml, ctx)
            finally:
                last_page_ts = time.monotonic()

            if detected_page.name in self._final_pages:
                return current_xml

            time.sleep(self._poll_interval)

    def _detect_current_page(
        self,
        current_xml: Optional[Element],
        last_page_ts: float,
        pages_history: list[str],
        controller: Optional[PhoneController] = None,
    ) -> Optional[XmlPage]:
        detected_pages: list[XmlPage] = [
            p for p in self._pages if current_xml is not None and p.is_detected(current_xml)
        ]
        expected_str = ", ".join(p.name for p in self._pages)

        # Prioritize final pages if detected
        for p in detected_pages:
            if p.name in self._final_pages:
                pages_history.append(p.name)
                return p

        detected_page: Optional[XmlPage] = None
        for p in detected_pages:
            if len(pages_history) == 0 or pages_history[-1] != p.name:
                pages_history.append(p.name)
                detected_page = p
                break
            elif time.monotonic() - last_page_ts > 6.0:
                if pages_history.count(p.name) < self._max_executions_same_page:
                    pages_history.append(p.name)
                    detected_page = p
                    break
                if controller is not None:
                    controller.record_unknown_page(
                        reason=f"STUCK_ON_SAME_PAGE:{p.name}",
                        expected_pages=expected_str,
                        xml_element=current_xml,
                    )
                raise AutomationError(
                    "STUCK_ON_SAME_PAGE",
                    f"Stuck on page {p.name} after {self._max_executions_same_page} attempts",
                )

        if detected_page is not None:
            for page_name in set(pages_history):
                if pages_history.count(page_name) > self._max_executions_same_page:
                    if controller is not None:
                        controller.record_unknown_page(
                            reason=f"REPEATED_PAGE_ERROR:{detected_page.name}",
                            expected_pages=expected_str,
                            xml_element=current_xml,
                        )
                    raise AutomationError(
                        "REPEATED_PAGE_ERROR",
                        f"Page {detected_page.name} executed more than {self._max_executions_same_page} times",
                    )
            return detected_page

        if time.monotonic() - last_page_ts > self._timeout:
            if len(detected_pages) == 0:
                if controller is not None:
                    controller.record_unknown_page(
                        reason="UNKNOWN_PAGE_TIMEOUT",
                        expected_pages=expected_str,
                        xml_element=current_xml,
                    )
                raise AutomationError(
                    "UNKNOWN_PAGE_TIMEOUT",
                    f"Timed out after {self._timeout}s on an unrecognized screen",
                )
            stuck_page = detected_pages[0]
            # Allow one re-execution if stuck on a recognized non-final page before failing
            if pages_history.count(stuck_page.name) < self._max_executions_same_page:
                pages_history.append(stuck_page.name)
                return stuck_page
            if controller is not None:
                controller.record_unknown_page(
                    reason=f"STUCK_ON_SAME_PAGE:{stuck_page.name}",
                    expected_pages=expected_str,
                    xml_element=current_xml,
                )
            raise AutomationError(
                "STUCK_ON_SAME_PAGE",
                f"Stuck on page {stuck_page.name} for over {self._timeout}s",
            )
        return None
