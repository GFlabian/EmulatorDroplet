"""Shared XmlPageRules for common Snapchat screens and popups."""

from automation.common.page_rule import XmlPageRule

# Main Camera Screen (MAIN_PAGE)
MainCameraPageRule = XmlPageRule(
    include=[
        "com.snapchat.android:id/camera_page",
        "com.snapchat.android:id/ngs_camera_icon_container",
        "com.snapchat.android:id/hova_header_search_icon",
    ],
    exclude=[
        "search-textfield",
        "unified_profile_dismiss_button",
    ],
)

# Bottom navigation bar visible (present across Map, Chat, Camera, Stories, Spotlight tabs)
BottomNavBarRule = XmlPageRule(
    include=[
        "com.snapchat.android:id/ngs_camera_icon_container",
        "com.snapchat.android:id/ngs_chat_icon_container",
        "com.snapchat.android:id/ngs_spotlight_icon_container",
    ]
)

# Search screen
SearchScreenRule = XmlPageRule(
    include=["search-textfield", "dismiss-button"],
)

# User Added state inside Search screen ("Added" badge or post-add upsell buttons visible)
UserAddedScreenRule = XmlPageRule(
    include=["search-textfield", "dismiss-button"],
    include_any=[
        'text="Added"',
        'content-desc="Added"',
        "quick-add-button-upsell-1",
        "quick-add-button-upsell-2",
    ],
)

# Profile screen
ProfileScreenRule = XmlPageRule(
    include_any=[
        "unified_profile_dismiss_button",
        "unified_profile_icon_button_settings",
    ]
)

# Permission popups
AllowPermissionPopupRule = XmlPageRule(
    include_any=[
        "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
        "com.android.permissioncontroller:id/permission_allow_one_time_button",
        "com.android.permissioncontroller:id/permission_allow_button",
    ]
)

DenyPermissionPopupRule = XmlPageRule(
    include=["com.android.permissioncontroller:id/permission_deny_button"]
)

# Generic upsell / notification popups inside Snapchat
UpsellDismissPopupRule = XmlPageRule(
    include_any=[
        "impala/photo_upsell_tray_dismiss_button",
        "com.google.android.gms:id/cancel",
        "com.snapchat.android:id/okay_button",
    ]
)

# Android System ANR ("System UI isn't responding" / "... isn't responding") dialog
SystemAnrDialogRule = XmlPageRule(
    include_any=[
        "android:id/aerr_wait",
        "android:id/aerr_close",
        "isn't responding",
    ]
)

# Android Home Screen Launcher (if Snapchat was backgrounded by System UI startup)
AndroidLauncherRule = XmlPageRule(
    include_any=[
        "com.google.android.apps.nexuslauncher:id/workspace",
        "com.google.android.apps.nexuslauncher:id/hotseat",
        "com.android.launcher3:id/workspace",
    ],
    exclude=[
        "com.snapchat.android:id/",
    ],
)
