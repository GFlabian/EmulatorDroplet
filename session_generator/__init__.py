from pathlib import Path

from .base import (
    BaseSessionBuilder,
    get_session_builder,
    list_supported_versions,
    normalize_version_prefix,
    register_session_builder,
)
from .db_auth import fetch_account_auth_from_db
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
) -> tuple[Path, AccountAuthData, str]:
    auth = fetch_account_auth_from_db(username)
    target_version = app_version or auth.device.app_version
    builder = get_session_builder(target_version, strict=strict_version)
    pkg_dir = builder.build(auth, Path(output_dir))
    return pkg_dir, auth, builder.version_prefix


__all__ = [
    "AccountAuthData",
    "ArgosAuth",
    "BaseSessionBuilder",
    "CodecException",
    "DeviceAuth",
    "EncryptionKeysAuth",
    "SessionBuilderV1430",
    "fetch_account_auth_from_db",
    "generate_session_from_auth",
    "generate_session_from_db",
    "get_session_builder",
    "list_supported_versions",
    "normalize_version_prefix",
    "parse_account_auth",
    "register_session_builder",
]
