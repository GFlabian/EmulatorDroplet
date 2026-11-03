from __future__ import annotations

from dataclasses import dataclass
import json
from typing import cast
import uuid


class CodecException(RuntimeError):
    name: str
    message: str
    original_exception: BaseException | None

    def __init__(
        self,
        name: str,
        message: str,
        original_exception: BaseException | None = None,
    ) -> None:
        self.name = name
        self.message = message
        self.original_exception = original_exception
        super().__init__(f"{name}: {message}")


@dataclass(frozen=True)
class EncryptionKeysAuth:
    public_key: str
    private_key: str
    iwek: str
    version: int


@dataclass(frozen=True)
class ArgosAuth:
    token: str
    refresh_at: str


@dataclass(frozen=True)
class DeviceAuth:
    android_id: str
    idp: str
    device_token: str
    cof_device_id: str
    blizzard_client_id: str
    install_id: str
    app_installed_at: str
    app_version: str
    timezone: str
    country_code: str
    model: str
    brand: str
    version_release: str = "14"
    version_incremental: str = ""
    version_sdk: int = 34


@dataclass(frozen=True)
class AccountAuthData:
    user_id: str
    username: str
    display_name: str
    email: str
    password: str
    refresh_token: str
    access_token: str
    age: int
    astrological_sign: int
    device: DeviceAuth
    argos: ArgosAuth
    encryption_keys: EncryptionKeysAuth


def _as_dict(val: object) -> dict[str, object]:
    if isinstance(val, dict):
        return cast(dict[str, object], val)
    return {}


def _as_str(val: object, default: str = "") -> str:
    if isinstance(val, str):
        return val.strip()
    if val is None:
        return default
    return str(val).strip()


def _as_int(val: object, default: int = 0) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, str):
        try:
            return int(val.strip())
        except ValueError:
            return default
    return default


def parse_account_auth(
    username: str,
    display_name: str | None,
    email: str | None,
    password: str | None,
    auth_raw: str | dict[str, object],
) -> AccountAuthData:
    parsed: dict[str, object]
    if isinstance(auth_raw, str):
        raw_str = auth_raw.strip()
        if not raw_str:
            raise CodecException("EMPTY_AUTH", f"Account {username!r} has an empty Auth column in DB")
        try:
            loaded = cast(object, json.loads(raw_str))
        except Exception as exc:
            raise CodecException("INVALID_AUTH_JSON", f"Failed to parse Auth JSON for {username!r}", exc) from exc
        parsed = _as_dict(loaded)
    else:
        parsed = auth_raw

    device_obj = _as_dict(parsed.get("Device"))
    app_info_obj = _as_dict(device_obj.get("SnapchatAppInfo"))
    sign_target_obj = _as_dict(app_info_obj.get("SignTarget"))

    session_obj = _as_dict(parsed.get("Session"))
    account_obj = _as_dict(session_obj.get("Account"))
    argos_obj = _as_dict(session_obj.get("Argos"))
    enc_obj = _as_dict(session_obj.get("EncryptionKeys"))

    user_id = _as_str(account_obj.get("Id")) or _as_str(session_obj.get("Id"))
    if not user_id:
        raise CodecException("MISSING_USER_ID", f"Auth for {username!r} is missing Session.Account.Id")
    try:
        user_id = str(uuid.UUID(user_id))
    except Exception as exc:
        raise CodecException("INVALID_USER_ID", f"Invalid UUID {user_id!r} in Auth for {username!r}", exc) from exc

    refresh_token = _as_str(session_obj.get("RefreshToken"))
    if not refresh_token:
        raise CodecException("MISSING_REFRESH_TOKEN", f"Auth for {username!r} is missing Session.RefreshToken")

    resolved_username = _as_str(account_obj.get("Username")) or username.strip()
    resolved_display = (display_name or "").strip() or resolved_username
    acct_email = _as_str(account_obj.get("Email"))
    resolved_email = (email or "").strip() or (acct_email if acct_email.lower() != "none" else "")
    acct_password = _as_str(account_obj.get("Password"))
    resolved_password = (password or "").strip() or (acct_password if acct_password.lower() != "none" else "")

    pub_key = _as_str(enc_obj.get("PublicKey"))
    priv_key = _as_str(enc_obj.get("PrivateKey"))
    iwek = _as_str(enc_obj.get("Iwek"))
    if not pub_key or not priv_key or not iwek:
        raise CodecException("MISSING_ENCRYPTION_KEYS", f"Auth for {username!r} is missing Fidelius EncryptionKeys")

    enc_keys = EncryptionKeysAuth(
        public_key=pub_key,
        private_key=priv_key,
        iwek=iwek,
        version=_as_int(enc_obj.get("Version"), default=10),
    )

    argos_auth = ArgosAuth(
        token=_as_str(argos_obj.get("Token")),
        refresh_at=_as_str(argos_obj.get("RefreshAt")),
    )

    device_auth = DeviceAuth(
        android_id=_as_str(device_obj.get("AndroidId")) or uuid.uuid4().hex[:16],
        idp=_as_str(device_obj.get("Idp")),
        device_token=_as_str(device_obj.get("DeviceToken")),
        cof_device_id=_as_str(device_obj.get("CofDeviceId")) or str(uuid.uuid4()),
        blizzard_client_id=_as_str(device_obj.get("BlizzardClientId")) or str(uuid.uuid4()),
        install_id=_as_str(app_info_obj.get("InstallId")) or str(uuid.uuid4()),
        app_installed_at=_as_str(app_info_obj.get("AppInstalledAt")),
        app_version=_as_str(sign_target_obj.get("AppVersion")) or "14.30.0.54",
        timezone=_as_str(device_obj.get("Timezone")) or "America/Los_Angeles",
        country_code=_as_str(device_obj.get("AccountCountryCode")) or "US",
        model=_as_str(device_obj.get("Model")) or "SM-A528B",
        brand=_as_str(device_obj.get("Brand")) or "samsung",
        version_release=_as_str(device_obj.get("VersionRelease")) or "14",
        version_incremental=_as_str(device_obj.get("VersionIncremental")),
        version_sdk=_as_int(device_obj.get("VersionSdk"), default=34),
    )

    return AccountAuthData(
        user_id=user_id,
        username=resolved_username,
        display_name=resolved_display,
        email=resolved_email,
        password=resolved_password,
        refresh_token=refresh_token,
        access_token=_as_str(session_obj.get("AccessToken")),
        age=_as_int(session_obj.get("Age"), default=20),
        astrological_sign=_as_int(session_obj.get("AstrologicalSign"), default=8),
        device=device_auth,
        argos=argos_auth,
        encryption_keys=enc_keys,
    )
