"""Shared XmlPageRules for common Snapchat screens and popups."""

from automation.common.page_rule import XmlPageRule

# Main Camera Screen (MAIN_PAGE)
MainCameraPageRule = XmlPageRule(
    include=[
        "com.snapchat.android:id/ngs_camera_icon_container",
        "com.snapchat.android:id/hova_header_search_icon",
    ],
    include_any=[
        "com.snapchat.android:id/camera_page",
        "com.snapchat.android:id/camera_capture_button",
        "com.snapchat.android:id/ngs_memories_icon",
        'text="Memories"',
        'content-desc="Memories"',
    ],
    exclude=[
        "search-textfield",
        "unified_profile_dismiss_button",
        "com.snapchat.android:id/favorite",
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
        "upp-close-button",
        "upp-header-bar",
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
        "sponsored_snap_eu_modal_smaller_ads_btn",
        "sponsored_snap_eu_modal_larger_ads_btn",
        'text="Choose Your Ad Experience"',
        "com.snapchat.android:id/alert_dialog_title",
        'text="Say Hi to My AI"',
        "built on generative AI technology",
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

# Subscreen overlay (e.g., Sound / Trending Sounds / Topic page opened from Spotlight)
SubscreenDismissPopupRule = XmlPageRule(
    include_any=[
        "sound_topic_ui/",
        "com.snapchat.android:id/subscreen_top_left",
        'text="Trending Sounds"',
        'text="Use Sound"',
    ],
    exclude=[
        "com.snapchat.android:id/ngs_camera_icon_container",
        "search-textfield",
        "unified_profile_dismiss_button",
    ],
)

# Logged-out Snapchat Welcome / LoginSignup screen
AccountLoggedOutRule = XmlPageRule(
    include_any=[
        "com.snapchat.android:id/login_text",
        "Already have an account? Log In",
        "com.snapchat.android:id/login_button_horizontal",
    ],
    exclude=[
        "com.snapchat.android:id/ngs_camera_icon_container",
    ],
)
