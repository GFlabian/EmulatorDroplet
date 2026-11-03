from dataclasses import dataclass
import json
import os
import re
from typing import cast

import pymysql
from pymysql.cursors import DictCursor

from .models import AccountAuthData, CodecException, parse_account_auth

ACCOUNTS_DB_HOST: str = os.environ.get("FREYA_DB_HOST", "89.34.17.131")
ACCOUNTS_DB_PORT: int = int(os.environ.get("FREYA_DB_PORT", "3306"))
ACCOUNTS_DB_USER: str = os.environ.get("FREYA_DB_USER", "timesync_AI_with_update")
ACCOUNTS_DB_PASS: str = os.environ.get("FREYA_DB_PASS", "YQQOmI0alLi")
ACCOUNTS_DB_NAME: str = os.environ.get("FREYA_ACCOUNTS_DB_NAME", "timesync_Freya")

TOOLS_DB_USER: str = os.environ.get("FREYA_TOOLS_DB_USER", "timesync_Freya_User")
TOOLS_DB_PASS: str = os.environ.get("FREYA_TOOLS_DB_PASS", "My31415926")
TOOLS_DB_NAME: str = os.environ.get("FREYA_TOOLS_DB_NAME", "timesync_FreyaTools")


@dataclass(frozen=True)
class ResolvedDeviceConfig:
    auth: AccountAuthData
    brand: str
    manufacturer: str
    model: str
    android: int
    version_release: str
    version_incremental: str
    version_sdk: int
    android_id: str
    timezone: str
    device_label: str
    props: dict[str, str]


def _get_accounts_connection() -> pymysql.Connection[DictCursor]:
    return pymysql.connect(
        host=ACCOUNTS_DB_HOST,
        port=ACCOUNTS_DB_PORT,
        user=ACCOUNTS_DB_USER,
        password=ACCOUNTS_DB_PASS,
        database=ACCOUNTS_DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )


def _get_tools_connection() -> pymysql.Connection[DictCursor]:
    return pymysql.connect(
        host=ACCOUNTS_DB_HOST,
        port=ACCOUNTS_DB_PORT,
        user=TOOLS_DB_USER,
        password=TOOLS_DB_PASS,
        database=TOOLS_DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )


def fetch_account_auth_from_db(username: str) -> AccountAuthData:
    lookup = username.strip()
    if not lookup:
        raise CodecException("EMPTY_USERNAME", "Username cannot be empty when fetching Auth from DB")

    try:
        conn = _get_accounts_connection()
    except Exception as exc:
        raise CodecException(
            "DB_CONNECTION_FAILED",
            f"Could not connect to {ACCOUNTS_DB_HOST}:{ACCOUNTS_DB_PORT}/{ACCOUNTS_DB_NAME}",
            exc,
        ) from exc

    try:
        with conn.cursor() as cur:
            _ = cur.execute(
                """
                SELECT Username, DisplayName, Email, Password, Auth
                FROM Accounts
                WHERE Username = %s OR UsernameChanged = %s
                LIMIT 1
                """,
                (lookup, lookup),
            )
            raw_row = cast(dict[str, object] | None, cur.fetchone())
    except Exception as exc:
        raise CodecException("DB_QUERY_FAILED", f"Failed querying Accounts for {lookup!r}", exc) from exc
    finally:
        conn.close()

    if raw_row is None:
        raise CodecException("ACCOUNT_NOT_FOUND", f"No account row found in {ACCOUNTS_DB_NAME}.Accounts for {lookup!r}")

    auth_col = raw_row.get("Auth")
    if not isinstance(auth_col, str) or not auth_col.strip():
        raise CodecException("MISSING_AUTH_DATA", f"Account {lookup!r} exists in DB but has no saved Auth JSON")

    db_username = str(raw_row.get("Username") or lookup)
    raw_display = raw_row.get("DisplayName")
    raw_email = raw_row.get("Email")
    raw_password = raw_row.get("Password")

    return parse_account_auth(
        username=db_username,
        display_name=str(raw_display) if isinstance(raw_display, str) else None,
        email=str(raw_email) if isinstance(raw_email, str) else None,
        password=str(raw_password) if isinstance(raw_password, str) else None,
        auth_raw=auth_col,
    )


def _parse_android_version(release_str: str, sdk_int: int) -> int:
    m = re.match(r"^\s*(\d+)", str(release_str or ""))
    if m:
        ver = int(m.group(1))
        if ver in (14, 15, 16):
            return ver
        if ver < 14:
            return 14
        return 16
    if sdk_int <= 34:
        return 14
    if sdk_int == 35:
        return 15
    return 16


def _slugify_device(model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", model.lower())
    return slug or "generic"


def resolve_account_device_from_db(username: str) -> ResolvedDeviceConfig:
    """Resolve an account's Auth and full device build.prop settings from the DB."""
    auth = fetch_account_auth_from_db(username)
    dev = auth.device

    brand = (dev.brand or "samsung").strip()
    model = (dev.model or "SM-A528B").strip()
    release = (dev.version_release or "14").strip()
    incremental = (dev.version_incremental or "").strip()
    sdk = int(dev.version_sdk or 34)
    android_ver = _parse_android_version(release, sdk)

    is_pixel = brand.lower() == "google" or model.lower().startswith("pixel")
    manufacturer = "Google" if is_pixel else brand
    device_codename = _slugify_device(model)
    product_name = device_codename
    board_name = ""
    build_id = "UP1A.231005.007"
    build_type = "user"
    tags = "release-keys"
    flavor = ""
    security_patch = ""
    fingerprint = ""

    # Enrich from timesync_FreyaTools (devices + device_builds + device_profiles) if available
    try:
        conn = _get_tools_connection()
        try:
            with conn.cursor() as cur:
                _ = cur.execute(
                    """
                    SELECT d.id, d.manufacturer, d.brand, d.model, d.product, d.device,
                           d.build, d.incremental, d.build_type, d.tags, d.release, d.sdk,
                           b.build_id AS b_build_id, b.fingerprint AS b_fingerprint, b.security_patch AS b_security_patch,
                           p.fingerprint AS p_fingerprint, p.security_patch AS p_security_patch,
                           p.hardware, p.firmware
                    FROM devices d
                    LEFT JOIN device_builds b ON b.device_id = d.id AND (%s <> '' AND b.incremental = %s)
                    LEFT JOIN device_profiles p ON p.device_id = d.id
                    WHERE d.model = %s
                    ORDER BY (b.id IS NOT NULL) DESC, d.id
                    LIMIT 1
                    """,
                    (incremental, incremental, model),
                )
                row = cast(dict[str, object] | None, cur.fetchone())
        finally:
            conn.close()

        if row:
            hw_raw = row.get("hardware")
            fw_raw = row.get("firmware")
            hw = json.loads(hw_raw) if isinstance(hw_raw, str) and hw_raw.strip() else {}
            fw = json.loads(fw_raw) if isinstance(fw_raw, str) and fw_raw.strip() else {}

            db_mfg = str(row.get("manufacturer") or hw.get("manufacturer") or "").strip()
            if db_mfg:
                manufacturer = db_mfg
            db_dev = str(row.get("device") or hw.get("device") or "").strip()
            if db_dev:
                device_codename = db_dev
            db_prod = str(row.get("product") or hw.get("productName") or "").strip()
            if db_prod:
                product_name = db_prod
            else:
                product_name = device_codename
            board_name = str(hw.get("board") or "").strip()

            if not incremental:
                incremental = str(row.get("incremental") or fw.get("versionIncremental") or "").strip()

            db_build_id = str(row.get("b_build_id") or row.get("build") or fw.get("buildId") or "").strip()
            if db_build_id:
                build_id = db_build_id

            db_type = str(row.get("build_type") or "user").strip()
            if db_type:
                build_type = db_type

            db_tags = str(row.get("tags") or fw.get("buildTags") or "release-keys").strip()
            if db_tags:
                tags = db_tags

            flavor = str(fw.get("buildFlavor") or f"{product_name}-{build_type}").strip()
            security_patch = str(
                row.get("b_security_patch")
                or row.get("p_security_patch")
                or fw.get("securityPatch")
                or ""
            ).strip()

            b_fp = str(row.get("b_fingerprint") or "").strip()
            p_fp = str(row.get("p_fingerprint") or fw.get("buildFingerprint") or "").strip()
            if b_fp:
                fingerprint = b_fp
            elif p_fp and incremental and incremental in p_fp:
                fingerprint = p_fp
    except Exception:
        pass

    if not incremental:
        incremental = "A528BXXSBGYI3"
    if not flavor:
        flavor = f"{product_name}-{build_type}"
    if not fingerprint:
        fingerprint = f"{brand}/{product_name}/{device_codename}:{release}/{build_id}/{incremental}:{build_type}/{tags}"

    display_id = build_id if incremental in build_id else f"{build_id}.{incremental}"

    props: dict[str, str] = {
        "ro.build.characteristics": "nosdcard",
        "ro.build.display.id": display_id,
        "ro.build.fingerprint": fingerprint,
        "ro.build.flavor": flavor,
        "ro.build.id": build_id,
        "ro.build.product": device_codename,
        "ro.build.tags": tags,
        "ro.build.version.incremental": incremental,
        "ro.product.brand": brand,
        "ro.product.device": device_codename,
        "ro.product.manufacturer": manufacturer,
        "ro.product.model": model,
        "ro.product.name": product_name,
        "ro.product.odm.brand": brand,
        "ro.product.odm.device": device_codename,
        "ro.product.odm.manufacturer": manufacturer,
        "ro.product.odm.model": model,
        "ro.product.odm.name": product_name,
        "ro.product.product.brand": brand,
        "ro.product.product.device": device_codename,
        "ro.product.product.manufacturer": manufacturer,
        "ro.product.product.model": model,
        "ro.product.product.name": product_name,
        "ro.product.system.brand": brand,
        "ro.product.system.device": device_codename,
        "ro.product.system.manufacturer": manufacturer,
        "ro.product.system.model": model,
        "ro.product.system.name": product_name,
        "ro.product.system_ext.brand": brand,
        "ro.product.system_ext.device": device_codename,
        "ro.product.system_ext.manufacturer": manufacturer,
        "ro.product.system_ext.model": model,
        "ro.product.system_ext.name": product_name,
        "ro.product.vendor.brand": brand,
        "ro.product.vendor.device": device_codename,
        "ro.product.vendor.manufacturer": manufacturer,
        "ro.product.vendor.model": model,
        "ro.product.vendor.name": product_name,
        "ro.product.build.fingerprint": fingerprint,
        "ro.system.build.fingerprint": fingerprint,
        "ro.system_ext.build.fingerprint": fingerprint,
        "ro.odm.build.fingerprint": fingerprint,
        "ro.vendor.build.fingerprint": fingerprint,
        "ro.bootimage.build.fingerprint": fingerprint,
    }
    if board_name:
        props["ro.product.board"] = board_name
        props["ro.board.platform"] = board_name
    if security_patch:
        props["ro.build.version.security_patch"] = security_patch
    if dev.timezone:
        props["persist.sys.timezone"] = dev.timezone

    device_label = f"{brand} {model}".strip()
    return ResolvedDeviceConfig(
        auth=auth,
        brand=brand,
        manufacturer=manufacturer,
        model=model,
        android=android_ver,
        version_release=release,
        version_incremental=incremental,
        version_sdk=sdk,
        android_id=dev.android_id,
        timezone=dev.timezone,
        device_label=device_label,
        props=props,
    )
