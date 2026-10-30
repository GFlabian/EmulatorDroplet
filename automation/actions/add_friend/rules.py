"""XmlPageRules for the ADD_FRIEND / ADD_USER action."""

from automation.common.models import Element
from automation.common.page_rule import XmlPageRule
from automation.common.shared_rules import MainCameraPageRule


def _has_added_indicator(xml: Element) -> bool:
    return bool(
        xml.get_elements_by_id("quick-add-button-upsell-1")
        or xml.get_elements_by_id("quick-add-button-upsell-2")
        or xml.get_elements_by_id("added-friend-button")
        or xml.get_elements_by_id("subscribed-button")
        or xml.get_elements_by_text("Added")
        or xml.get_elements_by_content_desc("Added")
    )


def _has_add_button(xml: Element) -> bool:
    return bool(
        xml.get_elements_by_id("add-friend-button")
        + xml.get_elements_by_id("subscribe-button")
        + xml.get_elements_by_text("Add")
        + xml.get_elements_by_content_desc("Add")
    )


def make_search_needs_clear_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs:
            return False
        current = tfs[0].text.strip().lower()
        return bool(current) and current != "search" and current != target

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


def make_search_empty_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs:
            return False
        current = tfs[0].text.strip().lower()
        return (not current or current == "search") and current != target

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


def make_search_has_add_button_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs or tfs[0].text.strip().lower() != target:
            return False
        if _has_added_indicator(xml):
            return False
        return _has_add_button(xml)

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


def make_search_view_all_results_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs or tfs[0].text.strip().lower() != target:
            return False
        if _has_added_indicator(xml) or _has_add_button(xml):
            return False
        return len(xml.get_elements_by_text_containing("View all results")) > 0

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


def make_search_retry_results_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs or tfs[0].text.strip().lower() != target:
            return False
        if _has_added_indicator(xml) or _has_add_button(xml):
            return False
        return bool(
            xml.get_elements_by_id("retry-button")
            or xml.get_elements_by_text("Try Again")
            or xml.get_elements_by_text_containing("Couldn't load results")
        )

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


def make_user_added_final_rule(target_username: str) -> XmlPageRule:
    target = target_username.strip().lower()

    def _pred(xml: Element) -> bool:
        tfs = xml.get_elements_by_id("search-textfield")
        if not tfs or tfs[0].text.strip().lower() != target:
            return False
        return _has_added_indicator(xml)

    return XmlPageRule(include=["search-textfield"], predicate=_pred)


__all__ = [
    "MainCameraPageRule",
    "make_search_empty_rule",
    "make_search_has_add_button_rule",
    "make_search_needs_clear_rule",
    "make_search_retry_results_rule",
    "make_search_view_all_results_rule",
    "make_user_added_final_rule",
]
