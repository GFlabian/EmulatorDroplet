from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
import re
import sqlite3
from typing import cast
import uuid

import py7zr

from .models import AccountAuthData, CodecException

TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
SNAPCHAT_PACKAGE_NAME: str = "com.snapchat.android"


class BaseSessionBuilder(ABC):
    version_prefix: str = ""
    template_filename: str = ""

    def extract_template(self, target_pkg_dir: Path) -> None:
        if not self.template_filename:
            raise CodecException("MISSING_TEMPLATE_NAME", f"Builder {type(self).__name__} has no template_filename")
        tpl_path = TEMPLATES_DIR / self.template_filename
        if not tpl_path.is_file():
            raise CodecException("TEMPLATE_NOT_FOUND", f"Session template archive not found: {tpl_path}")
        target_pkg_dir.mkdir(parents=True, exist_ok=True)
        try:
            with py7zr.SevenZipFile(tpl_path, "r") as zf:
                if hasattr(zf, "files") and hasattr(zf.files, "files_list"):
                    zf.files.files_list = [f for f in zf.files.files_list if f.get("filename") not in (".", "")]
                zf.extractall(path=target_pkg_dir)
        except Exception as exc:
            raise CodecException("TEMPLATE_EXTRACT_FAILED", f"Failed extracting {tpl_path.name}", exc) from exc

    @abstractmethod
    def build_package_dir(self, auth: AccountAuthData, target_pkg_dir: Path) -> Path:
        raise NotImplementedError

    def build(self, auth: AccountAuthData, output_dir: Path) -> Path:
        pkg_dir = output_dir / SNAPCHAT_PACKAGE_NAME
        return self.build_package_dir(auth, pkg_dir)


_BUILDER_REGISTRY: dict[str, type[BaseSessionBuilder]] = {}


def register_session_builder(
    version_prefix: str,
) -> Callable[[type[BaseSessionBuilder]], type[BaseSessionBuilder]]:
    norm = normalize_version_prefix(version_prefix)

    def _decorator(cls: type[BaseSessionBuilder]) -> type[BaseSessionBuilder]:
        cls.version_prefix = norm
        _BUILDER_REGISTRY[norm] = cls
        return cls

    return _decorator


def normalize_version_prefix(version_str: str | None) -> str:
    if not version_str:
        return ""
    raw = version_str.strip()
    m_dotted = re.search(r"(\d+)\.(\d+)", raw)
    if m_dotted:
        return f"{int(m_dotted.group(1))}.{int(m_dotted.group(2))}"
    m_compact = re.search(r"(?<!\d)(\d{2})(\d{2})(?!\d)", raw)
    if m_compact:
        return f"{int(m_compact.group(1))}.{int(m_compact.group(2))}"
    return raw


def _version_sort_key(prefix: str) -> tuple[int, int]:
    parts = prefix.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]))
    return (0, 0)


def list_supported_versions() -> list[str]:
    return sorted(_BUILDER_REGISTRY.keys(), key=_version_sort_key)


def get_session_builder(
    app_version: str | None = None,
    strict: bool = False,
) -> BaseSessionBuilder:
    if not _BUILDER_REGISTRY:
        raise CodecException("NO_SESSION_BUILDERS", "No session builders are registered")

    norm = normalize_version_prefix(app_version)
    if norm and norm in _BUILDER_REGISTRY:
        return _BUILDER_REGISTRY[norm]()

    if strict and norm:
        supported = ", ".join(list_supported_versions())
        raise CodecException(
            "UNSUPPORTED_APP_VERSION",
            f"No session builder registered for version {app_version!r} (normalized {norm!r}); supported: {supported}",
        )

    latest_key = max(_BUILDER_REGISTRY.keys(), key=_version_sort_key)
    return _BUILDER_REGISTRY[latest_key]()


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def uuid_to_bytes(uuid_str: str) -> bytes:
    return uuid.UUID(uuid_str).bytes


def replace_bytes_in_sqlite(cur: sqlite3.Cursor, old_bytes: bytes, new_bytes: bytes) -> None:
    if len(old_bytes) != len(new_bytes):
        raise CodecException(
            "SQLITE_REPLACE_LENGTH_MISMATCH",
            f"Replacement must be length-preserving ({len(old_bytes)} != {len(new_bytes)})",
        )
    old_str: str | None
    new_str: str | None
    try:
        old_str = old_bytes.decode("ascii")
        new_str = new_bytes.decode("ascii")
    except UnicodeDecodeError:
        old_str = None
        new_str = None

    _ = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    table_rows = cast(list[tuple[str]], cur.fetchall())
    for (table_name,) in table_rows:
        _ = cur.execute(f"PRAGMA table_info([{table_name}])")
        col_rows = cast(list[tuple[int, str, str, int, object, int]], cur.fetchall())
        for col in col_rows:
            col_name = col[1]
            col_type = (col[2] or "").upper()
            is_pk = col[5]
            if is_pk and col_type == "INTEGER":
                continue
            try:
                _ = cur.execute(f"SELECT rowid, [{col_name}] FROM [{table_name}]")
                cell_rows = cast(list[tuple[int, object]], cur.fetchall())
            except sqlite3.OperationalError:
                continue
            for rowid, cell_val in cell_rows:
                if isinstance(cell_val, str):
                    if old_str is not None and new_str is not None and old_str in cell_val:
                        updated_str = cell_val.replace(old_str, new_str)
                        _ = cur.execute(
                            f"UPDATE [{table_name}] SET [{col_name}] = ? WHERE rowid = ?",
                            (updated_str, rowid),
                        )
                elif isinstance(cell_val, (bytes, bytearray)):
                    raw_cell = bytes(cell_val)
                    if old_bytes in raw_cell:
                        updated_bytes = raw_cell.replace(old_bytes, new_bytes)
                        _ = cur.execute(
                            f"UPDATE [{table_name}] SET [{col_name}] = ? WHERE rowid = ?",
                            (updated_bytes, rowid),
                        )
