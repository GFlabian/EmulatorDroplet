"""Shared models for XML parsing, UI elements, locations, and action results."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any, Callable, Optional
import xml.etree.ElementTree as ET


class Location:
    """Known UI locations of an emulator inside Snapchat."""

    INITIALIZING = "INITIALIZING"
    MAIN_PAGE = "MAIN_PAGE"
    SEARCH_PAGE = "SEARCH_PAGE"
    USER_ADDED_PAGE = "USER_ADDED_PAGE"
    REELS_PAGE = "REELS_PAGE"
    REEL_COMMENTS_PAGE = "REEL_COMMENTS_PAGE"
    CHATS_PAGE = "CHATS_PAGE"
    CHAT_CONVERSATION_PAGE = "CHAT_CONVERSATION_PAGE"
    AI_CHAT_PAGE = "AI_CHAT_PAGE"
    PROFILE_PAGE = "PROFILE_PAGE"
    FRIENDS_LIST_PAGE = "FRIENDS_LIST_PAGE"
    UNKNOWN = "UNKNOWN"


class AutomationError(RuntimeError):
    """Raised when an automation page flow or step fails."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class Element:
    """Wrapper around an Android UIAutomator XML <node> element."""

    def __init__(self, element: ET.Element):
        self._element: ET.Element = element

    @property
    def resource_id(self) -> str:
        return self._element.get("resource-id", "")

    @property
    def text(self) -> str:
        return self._element.get("text", "")

    @property
    def content_desc(self) -> str:
        return self._element.get("content-desc", "") or ""

    @property
    def class_name(self) -> str:
        return self._element.get("class", "")

    @property
    def package(self) -> str:
        return self._element.get("package", "")

    @property
    def clickable(self) -> bool:
        return self._element.get("clickable", "false") == "true"

    @property
    def enabled(self) -> bool:
        return self._element.get("enabled", "false") == "true"

    @property
    def focusable(self) -> bool:
        return self._element.get("focusable", "false") == "true"

    @property
    def focused(self) -> bool:
        return self._element.get("focused", "false") == "true"

    @property
    def scrollable(self) -> bool:
        return self._element.get("scrollable", "false") == "true"

    @property
    def selected(self) -> bool:
        return self._element.get("selected", "false") == "true"

    @property
    def checked(self) -> bool:
        return self._element.get("checked", "false") == "true"

    @property
    def bounds(self) -> tuple[Point, Point]:
        bounds_str = self._element.get("bounds", "")
        if not bounds_str:
            return Point(0, 0), Point(0, 0)
        parts = [p for p in bounds_str.replace("[", "").replace("]", ",").split(",") if p]
        if len(parts) < 4:
            return Point(0, 0), Point(0, 0)
        return Point(int(parts[0]), int(parts[1])), Point(int(parts[2]), int(parts[3]))

    @property
    def width(self) -> int:
        p1, p2 = self.bounds
        return max(0, p2.x - p1.x)

    @property
    def height(self) -> int:
        p1, p2 = self.bounds
        return max(0, p2.y - p1.y)

    @property
    def center(self) -> Point:
        p1, p2 = self.bounds
        return Point((p1.x + p2.x) // 2, (p1.y + p2.y) // 2)

    @property
    def click_point(self) -> Point:
        min_pt, max_pt = self.bounds
        margin_x = (max_pt.x - min_pt.x) * 0.15
        margin_y = (max_pt.y - min_pt.y) * 0.15
        x = random.uniform(min_pt.x + margin_x, max_pt.x - margin_x)
        y = random.uniform(min_pt.y + margin_y, max_pt.y - margin_y)
        return Point(int(x), int(y))

    def click_point_custom(self, x_pct: float = 0.5, y_pct: float = 0.5) -> Point:
        min_pt, max_pt = self.bounds
        w = max_pt.x - min_pt.x
        h = max_pt.y - min_pt.y
        return Point(int(min_pt.x + w * x_pct), int(min_pt.y + h * y_pct))

    @property
    def raw(self) -> str:
        return ET.tostring(self._element, encoding="unicode")

    @property
    def children(self) -> list[Element]:
        return [Element(child) for child in self._element.findall(".//node")]

    @property
    def direct_children(self) -> list[Element]:
        return [Element(child) for child in self._element.findall("./node")]

    @property
    def clickable_elements(self) -> list[Element]:
        return self.where(lambda e: e.clickable)

    def where(self, predicate: Callable[[Element], bool]) -> list[Element]:
        return [elem for elem in self.children if predicate(elem)]

    def get_elements_by_id(self, resource_id: str) -> list[Element]:
        target = resource_id.lower()
        return self.where(
            lambda e: e.resource_id.lower() == target
            or e.resource_id.lower().endswith(f":id/{target}")
        )

    def get_elements_by_text(self, texts: list[str] | str) -> list[Element]:
        targets = [texts.lower()] if isinstance(texts, str) else [t.lower() for t in texts]
        return self.where(lambda e: e.text.strip().lower() in targets)

    def get_elements_by_text_containing(self, texts: list[str] | str) -> list[Element]:
        targets = [texts.lower()] if isinstance(texts, str) else [t.lower() for t in texts]
        return self.where(lambda e: any(t in e.text.lower() for t in targets))

    def get_elements_by_class(self, class_name: str) -> list[Element]:
        target = class_name.lower()
        return self.where(lambda e: e.class_name.lower() == target)

    def get_elements_by_content_desc(self, content_desc: list[str] | str) -> list[Element]:
        targets = [content_desc.lower()] if isinstance(content_desc, str) else [d.lower() for d in content_desc]
        return self.where(lambda e: e.content_desc.strip().lower() in targets)

    def get_elements_by_content_desc_containing(self, content_desc: list[str] | str) -> list[Element]:
        targets = [content_desc.lower()] if isinstance(content_desc, str) else [d.lower() for d in content_desc]
        return self.where(lambda e: any(d in e.content_desc.lower() for d in targets))


@dataclass
class ActionResult:
    """Outcome returned by an automation action."""

    status: str
    error: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    location: Optional[str] = None


@dataclass
class ActionRecord:
    """Tracked state of an action execution for API polling."""

    action_id: str
    emulator_id: str
    action_type: str
    params: dict[str, Any]
    state: str  # "RUNNING" | "COMPLETED" | "FAILED"
    status: str  # e.g. "RUNNING", "FRIEND_ADDED", "ADD_FAILED", "REELS_WATCHED", ...
    progress: str
    error: Optional[str] = None
    data: Optional[dict[str, Any]] = field(default_factory=dict)
    started_at: str = ""
    finished_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "emulator_id": self.emulator_id,
            "action_type": self.action_type,
            "params": self.params,
            "state": self.state,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "data": self.data,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
