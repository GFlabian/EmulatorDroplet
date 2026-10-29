"""Declarative XML page matching rule (modeled on FreyaAutomation XmlPageRule)."""

from __future__ import annotations

from typing import Callable, Optional
from automation.common.models import Element


class XmlPageRule:
    """Rule that triggers when an XML dump matches all specified conditions."""

    def __init__(
        self,
        include: Optional[list[str]] = None,
        exclude: Optional[list[str]] = None,
        include_any: Optional[list[str]] = None,
        click_elements_nr: Optional[int] = None,
        case_sensitive: bool = True,
        predicate: Optional[Callable[[Element], bool]] = None,
    ):
        self._include = include
        self._exclude = exclude
        self._include_any = include_any
        self._click_elements_nr = click_elements_nr
        self._case_sensitive = case_sensitive
        self._predicate = predicate

    def triggered(self, xml: Element) -> bool:
        content = xml.raw if self._case_sensitive else xml.raw.lower()

        if self._include:
            for inc in self._include:
                term = inc if self._case_sensitive else inc.lower()
                if term not in content:
                    return False

        if self._exclude:
            for exc in self._exclude:
                term = exc if self._case_sensitive else exc.lower()
                if term in content:
                    return False

        if self._click_elements_nr is not None:
            if len(xml.clickable_elements) != self._click_elements_nr:
                return False

        if self._include_any:
            found = False
            for inc in self._include_any:
                term = inc if self._case_sensitive else inc.lower()
                if term in content:
                    found = True
                    break
            if not found:
                return False

        if self._predicate is not None:
            if not self._predicate(xml):
                return False

        return True
