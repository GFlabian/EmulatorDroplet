"""Common utilities, XML page engine, and phone controls for Snapchat automation."""

from automation.common.models import (
    ActionRecord,
    ActionResult,
    AutomationError,
    Element,
    Location,
    Point,
)
from automation.common.navigation import (
    detect_location_from_xml,
    go_to_main_page,
    is_on_main_page,
)
from automation.common.page_rule import XmlPageRule
from automation.common.pages_service import PagesService
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.xml_page import XmlPage

__all__ = [
    "ActionRecord",
    "ActionResult",
    "AutomationError",
    "Element",
    "KeyType",
    "Location",
    "PagesService",
    "PhoneController",
    "Point",
    "XmlPage",
    "XmlPageRule",
    "detect_location_from_xml",
    "go_to_main_page",
    "is_on_main_page",
]
