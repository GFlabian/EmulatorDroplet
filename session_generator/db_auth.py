import os
from typing import cast

import pymysql
from pymysql.cursors import DictCursor

from .models import AccountAuthData, CodecException, parse_account_auth

ACCOUNTS_DB_HOST: str = os.environ.get("FREYA_DB_HOST", "89.34.17.131")
ACCOUNTS_DB_PORT: int = int(os.environ.get("FREYA_DB_PORT", "3306"))
ACCOUNTS_DB_USER: str = os.environ.get("FREYA_DB_USER", "timesync_AI_with_update")
ACCOUNTS_DB_PASS: str = os.environ.get("FREYA_DB_PASS", "YQQOmI0alLi")
ACCOUNTS_DB_NAME: str = os.environ.get("FREYA_ACCOUNTS_DB_NAME", "timesync_Freya")


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
