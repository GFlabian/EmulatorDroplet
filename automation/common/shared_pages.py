"""Shared XmlPage implementations for dismissing popups and common transitions."""

from typing import Any

from automation.common.models import Element
from automation.common.phone_controller import PhoneController
from automation.common.shared_rules import (
    AllowPermissionPopupRule,
    AndroidLauncherRule,
    SystemAnrDialogRule,
    UpsellDismissPopupRule,
)
from automation.common.xml_page import XmlPage


class SystemAnrDialogPage(XmlPage):
    """Automatically dismisses Android 'isn't responding' (ANR) dialogs and brings Snapchat to foreground."""

    def __init__(self):
        super().__init__(SystemAnrDialogRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        for rid in ("android:id/aerr_wait", "android:id/aerr_close"):
            btns = xml.get_elements_by_id(rid)
            if btns:
                controller.click_element(btns[0])
                controller.sleep(1.0)
                controller.ensure_app_foreground()
                return
        wait_btns = xml.get_elements_by_text(["Wait", "Close app"])
        if wait_btns:
            controller.click_element(wait_btns[0])
            controller.sleep(1.0)
            controller.ensure_app_foreground()


class AndroidLauncherRecoveryPage(XmlPage):
    """Brings Snapchat back to the foreground if the device is sitting on the Android Home Launcher."""

    def __init__(self):
        super().__init__(AndroidLauncherRule)

    def _run(self, controller: PhoneController, xml: Element, context: dict[str, Any]):
        controller.report_status("Bringing Snapchat to foreground...")
        controller.ensure_app_foreground()


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
    SystemAnrDialogPage(),
    AndroidLauncherRecoveryPage(),
    AllowPermissionPopupPage(),
    UpsellDismissPopupPage(),
]
