"""Abstract base class for an XML-detected screen page."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.phone_controller import PhoneController


class XmlPage(ABC):
    """Represents a screen in the app with detection rules and an execution handler."""

    def __init__(self, page_rule: XmlPageRule | list[XmlPageRule]):
        self._page_rule = page_rule

    def is_detected(self, xml: Element) -> bool:
        if isinstance(self._page_rule, list):
            return any(rule.triggered(xml) for rule in self._page_rule)
        return self._page_rule.triggered(xml)

    def execute(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status(f"Page: {self.name}")
        self._run(controller, xml, context)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        pass
