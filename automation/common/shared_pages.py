"""Shared XmlPage implementations for dismissing popups and common transitions."""

from typing import Any

from automation.common.models import AutomationError, Element
from automation.common.phone_controller import KeyType, PhoneController
from automation.common.shared_rules import (
    AccountLoggedOutRule,
    AllowPermissionPopupRule,
    AndroidLauncherRule,
    SubscreenDismissPopupRule,
    SystemAnrDialogRule,
    UpsellDismissPopupRule,
)
from automation.common.xml_page import XmlPage


class AccountLoggedOutPage(XmlPage):
    """Detects when Snapchat has logged out the current session and fails fast."""

    def __init__(self):
        super().__init__(AccountLoggedOutRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        raise AutomationError(
            "ACCOUNT_LOGGED_OUT",
            "Snapchat session is logged out on this device (Login/Signup screen detected)",
        )


class SubscreenDismissPopupPage(XmlPage):
    """Dismisses accidental Spotlight subscreens (e.g. Trending Sounds / Original Sound)."""

    def __init__(self):
        super().__init__(SubscreenDismissPopupRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        btns = xml.get_elements_by_id("com.snapchat.android:id/subscreen_top_left")
        if btns:
            controller.click_element(btns[0])
        else:
            controller.send_key(KeyType.BACK)
        controller.sleep(1.2)


class SystemAnrDialogPage(XmlPage):
    """Automatically dismisses Android 'isn't responding' (ANR) dialogs and recovers Snapchat if hung."""

    def __init__(self):
        super().__init__(SystemAnrDialogRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        anr_count = int(context.get("_anr_count", 0)) + 1
        context["_anr_count"] = anr_count
        is_snapchat_anr = "Snapchat isn't responding" in xml.raw

        # If Snapchat itself has ANR'd 2+ times in the same flow, its UI thread is deadlocked;
        # close the dialog and cleanly restart Snapchat.
        if is_snapchat_anr and anr_count >= 2:
            close_btns = xml.get_elements_by_id("android:id/aerr_close")
            if close_btns:
                controller.click_element(close_btns[0])
                controller.sleep(1.0)
            controller.restart_app(wait_seconds=5.0)
            return

        wait_btns = xml.get_elements_by_id("android:id/aerr_wait")
        if not wait_btns:
            wait_btns = xml.get_elements_by_text(["Wait"])
        if wait_btns:
            controller.click_element(wait_btns[0])
            controller.sleep(4.0 if is_snapchat_anr else 2.0)
            if not is_snapchat_anr:
                controller.ensure_app_foreground(wait_seconds=3.0)
            return

        close_btns = xml.get_elements_by_id("android:id/aerr_close")
        if not close_btns:
            close_btns = xml.get_elements_by_text(["Close app"])
        if close_btns:
            controller.click_element(close_btns[0])
            controller.sleep(1.0)
            controller.restart_app(wait_seconds=5.0)


class AndroidLauncherRecoveryPage(XmlPage):
    """Brings Snapchat back to the foreground if the device is sitting on the Android Home Launcher."""

    def __init__(self):
        super().__init__(AndroidLauncherRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Bringing Snapchat to foreground...")
        controller.ensure_app_foreground(wait_seconds=5.0)


class AllowPermissionPopupPage(XmlPage):
    """Automatically grants any Android runtime permission prompt if one appears."""

    def __init__(self):
        super().__init__(AllowPermissionPopupRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        for rid in (
            "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
            "com.android.permissioncontroller:id/permission_allow_button",
            "com.android.permissioncontroller:id/permission_allow_one_time_button",
        ):
            btns = xml.get_elements_by_id(rid)
            if btns:
                controller.click_element(btns[0])
                return


class UpsellDismissPopupPage(XmlPage):
    """Dismisses upsell trays or Google Play Services cancelable dialogs."""

    def __init__(self):
        super().__init__(UpsellDismissPopupRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        for rid in (
            "impala/photo_upsell_tray_dismiss_button",
            "com.google.android.gms:id/cancel",
            "com.snapchat.android:id/okay_button",
        ):
            btns = xml.get_elements_by_id(rid)
            if btns:
                controller.click_element(btns[0])
                return


COMMON_POPUP_PAGES: list[XmlPage] = [
    AccountLoggedOutPage(),
    SystemAnrDialogPage(),
    AndroidLauncherRecoveryPage(),
    AllowPermissionPopupPage(),
    UpsellDismissPopupPage(),
    SubscreenDismissPopupPage(),
]
