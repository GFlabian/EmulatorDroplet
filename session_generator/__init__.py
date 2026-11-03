from pathlib import Path

from .base import (
    BaseSessionBuilder,
    get_session_builder,
    list_supported_versions,
    normalize_version_prefix,
    register_session_builder,
)
from .db_auth import ResolvedDeviceConfig, fetch_account_auth_from_db, resolve_account_device_from_db
from .models import (
    AccountAuthData,
    ArgosAuth,
    CodecException,
    DeviceAuth,
    EncryptionKeysAuth,
    parse_account_auth,
)
from .versions import SessionBuilderV1430


def generate_session_from_auth(
    auth: AccountAuthData,
    output_dir: Path | str,
    app_version: str | None = None,
    strict_version: bool = False,
) -> Path:
    target_version = app_version or auth.device.app_version
    builder = get_session_builder(target_version, strict=strict_version)
    return builder.build(auth, Path(output_dir))


def generate_session_from_db(
    username: str,
    output_dir: Path | str,
    app_version: str | None = None,
    strict_version: bool = False,
    auth: AccountAuthData | None = None,
) -> tuple[Path, AccountAuthData, str]:
    resolved_auth = auth or fetch_account_auth_from_db(username)
    target_version = app_version or resolved_auth.device.app_version
    builder = get_session_builder(target_version, strict=strict_version)
    pkg_dir = builder.build(resolved_auth, Path(output_dir))
    return pkg_dir, resolved_auth, builder.version_prefix


__all__ = [
    "AccountAuthData",
    "ArgosAuth",
    "BaseSessionBuilder",
    "CodecException",
    "DeviceAuth",
    "EncryptionKeysAuth",
    "ResolvedDeviceConfig",
    "SessionBuilderV1430",
    "fetch_account_auth_from_db",
    "generate_session_from_auth",
    "generate_session_from_db",
    "get_session_builder",
    "list_supported_versions",
    "normalize_version_prefix",
    "parse_account_auth",
    "register_session_builder",
    "resolve_account_device_from_db",
]
