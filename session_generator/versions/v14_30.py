import base64
import datetime
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import struct
import time
from typing import cast, override
import uuid

from ..base import (
    BaseSessionBuilder,
    register_session_builder,
    replace_bytes_in_sqlite,
    uuid_to_bytes,
    xml_escape,
)
from ..crypto import (
    FideliusCryptoMaterial,
    build_argos_token_bin,
    compute_fidelius_material,
    synthesize_birthday,
)
from ..models import AccountAuthData, CodecException

BAKED_USER_ID: str = "03209183-962e-426d-856b-07ab09779db1"
BAKED_USERNAME: str = "elenaradian1560"
BAKED_DISPLAY_NAME: str = "Elena radiant"

FIDELIUS_SCHEMA_STATEMENTS: tuple[str, ...] = (
    "PRAGMA user_version = 9",
    "CREATE TABLE IF NOT EXISTS android_metadata (locale TEXT)",
    """CREATE TABLE IF NOT EXISTS fidelius_friend_device_info (
    their_out_beta TEXT PRIMARY KEY,
    user_id TEXT,
    mystique BLOB,
    version INTEGER
)""",
    """CREATE TABLE IF NOT EXISTS fidelius_snap_encryption_key_table (
    snap_id TEXT PRIMARY KEY,
    snap_key TEXT,
    snap_timestamp INTEGER
)""",
    """CREATE TABLE IF NOT EXISTS arroyo_message_encryption_key_table (
    encrypted_conversation_id BLOB NOT NULL,
    encrypted_message_id BLOB NOT NULL,
    encrypted_key BLOB NOT NULL,
    timestamp INTEGER NOT NULL,
    purge_policy TEXT NOT NULL,
    PRIMARY KEY(encrypted_conversation_id, encrypted_message_id)
)""",
    """CREATE TABLE IF NOT EXISTS fidelius_user_device_table (
    hashed_out_beta TEXT UNIQUE,
    database_name TEXT
)""",
    """CREATE TABLE IF NOT EXISTS fidelius_user_identity (
    hashed_beta TEXT PRIMARY KEY,
    out_beta BLOB,
    in_beta BLOB,
    version INTEGER DEFAULT NULL
)""",
    "CREATE INDEX IF NOT EXISTS fidelius_friend_device_info_user_id_index ON fidelius_friend_device_info(user_id)",
    "CREATE INDEX IF NOT EXISTS snap_encryption_key_table_timestamp_index ON fidelius_snap_encryption_key_table(snap_timestamp)",
    "CREATE INDEX IF NOT EXISTS arroyo_encryption_key_table_timestamp_index ON arroyo_message_encryption_key_table(timestamp)",
)


def _parse_install_timestamp_ms(iso_str: str, fallback_ms: int) -> int:
    if not iso_str:
        return fallback_ms
    try:
        norm = iso_str.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(norm)
        ts_ms = int(dt.timestamp() * 1000)
        return ts_ms if ts_ms > 0 else fallback_ms
    except Exception:
        return fallback_ms


def _write_xml_map(path: Path, body_lines: list[str]) -> None:
    lines = ["<?xml version='1.0' encoding='utf-8' standalone='yes' ?>", "<map>", *body_lines, "</map>", ""]
    _ = path.write_text("\n".join(lines), encoding="utf-8")


@register_session_builder("14.30")
class SessionBuilderV1430(BaseSessionBuilder):
    version_prefix: str = "14.30"
    template_filename: str = "v14_30.7z"

    @override
    def build_package_dir(self, auth: AccountAuthData, target_pkg_dir: Path) -> Path:
        self.extract_template(target_pkg_dir)

        fidelius_db_name = f"{uuid.uuid4()}_fidelius.db"
        fidelius = compute_fidelius_material(auth.encryption_keys, fidelius_db_name)

        databases_dir = target_pkg_dir / "databases"
        shared_prefs_dir = target_pkg_dir / "shared_prefs"
        files_dir = target_pkg_dir / "files"

        self.build_fidelius_databases(databases_dir, fidelius)
        self.patch_main_db(databases_dir / "main.db", auth)
        self.patch_core_db(databases_dir / "core.db", auth)
        self.patch_lockscreen_core_db(databases_dir / "lock_screen" / "core.db", auth)
        self.patch_arroyo_db(databases_dir / "arroyo.db", auth)
        self.patch_feature_db(databases_dir / "feature")
        self.write_shared_prefs(shared_prefs_dir, auth, fidelius)
        self.write_device_files(files_dir, auth)

        return target_pkg_dir

    def build_fidelius_databases(self, databases_dir: Path, fidelius: FideliusCryptoMaterial) -> None:
        databases_dir.mkdir(parents=True, exist_ok=True)
        for existing in databases_dir.glob("*_fidelius.db*"):
            existing.unlink(missing_ok=True)

        master_db = databases_dir / "fidelius_database.db"
        conn_master = sqlite3.connect(master_db)
        try:
            cur = conn_master.cursor()
            for stmt in FIDELIUS_SCHEMA_STATEMENTS:
                _ = cur.execute(stmt)
            _ = cur.execute("DELETE FROM fidelius_user_device_table")
            _ = cur.execute("DELETE FROM fidelius_user_identity")
            _ = cur.execute(
                "INSERT INTO fidelius_user_device_table (hashed_out_beta, database_name) VALUES (?, ?)",
                (fidelius.hashed_out_beta_b64, fidelius.database_name),
            )
            conn_master.commit()
        except Exception as exc:
            raise CodecException("FIDELIUS_MASTER_DB_FAILED", "Failed writing fidelius_database.db", exc) from exc
        finally:
            conn_master.close()

        user_db = databases_dir / fidelius.database_name
        conn_user = sqlite3.connect(user_db)
        try:
            cur = conn_user.cursor()
            for stmt in FIDELIUS_SCHEMA_STATEMENTS:
                _ = cur.execute(stmt)
            _ = cur.execute("DELETE FROM android_metadata")
            _ = cur.execute("INSERT INTO android_metadata (locale) VALUES ('en_US')")
            _ = cur.execute(
                """
                INSERT INTO fidelius_user_identity (hashed_beta, out_beta, in_beta, version)
                VALUES (?, ?, ?, ?)
                """,
                (
                    fidelius.hashed_beta_cipher_b64,
                    fidelius.out_beta_cipher,
                    fidelius.in_beta_cipher,
                    fidelius.version,
                ),
            )
            conn_user.commit()
        except Exception as exc:
            raise CodecException("FIDELIUS_USER_DB_FAILED", f"Failed writing {fidelius.database_name}", exc) from exc
        finally:
            conn_user.close()

    def patch_main_db(self, db_path: Path, auth: AccountAuthData) -> None:
        if not db_path.is_file():
            raise CodecException("MAIN_DB_MISSING", f"Missing main.db at {db_path}")
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            _ = cur.execute("DELETE FROM SnapToken")
            _ = cur.execute(
                "INSERT INTO SnapToken (_id, userId, accessTokens, refreshToken, accessTokensPb) VALUES (?, ?, ?, ?, ?)",
                (1, auth.user_id, "", auth.refresh_token, None),
            )
            _ = cur.execute(
                """
                UPDATE CombinedUsername
                SET originalUsername = ?, mutableUsername = ?, encodedUsername = ?
                WHERE originalUsername = ?
                """,
                (auth.username, auth.username, f"{auth.username}|{auth.username}", BAKED_USERNAME),
            )
            _ = cur.execute(
                """
                UPDATE Friend
                SET username = ?, userId = ?, displayName = ?, serverDisplayName = ?
                WHERE userId = ? OR username = ?
                """,
                (auth.username, auth.user_id, auth.display_name, auth.display_name, BAKED_USER_ID, BAKED_USERNAME),
            )
            _ = cur.execute(
                "UPDATE Story SET userId = ? WHERE userId = ?",
                (auth.user_id, BAKED_USER_ID),
            )
            _ = cur.execute("DELETE FROM PostableContentDestination WHERE storyKind = 6")
            conn.commit()
        except Exception as exc:
            raise CodecException("MAIN_DB_PATCH_FAILED", f"Failed patching {db_path.name}", exc) from exc
        finally:
            conn.close()

    def patch_core_db(self, db_path: Path, auth: AccountAuthData) -> None:
        if not db_path.is_file():
            raise CodecException("CORE_DB_MISSING", f"Missing core.db at {db_path}")
        now_ms = int(time.time() * 1000)
        birthday_str = synthesize_birthday(auth.age, auth.astrological_sign)
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            replace_bytes_in_sqlite(cur, BAKED_USER_ID.encode("ascii"), auth.user_id.encode("ascii"))

            _ = cur.execute("UPDATE ConfigEtag SET etag = ? WHERE _id IN (2, 3)", (auth.device.country_code,))

            _ = cur.execute("UPDATE SnapUserStore SET textVal = ? WHERE _id IN (1, 20)", (auth.username,))
            _ = cur.execute("UPDATE SnapUserStore SET textVal = ? WHERE _id = 2", (auth.display_name,))
            _ = cur.execute("UPDATE SnapUserStore SET textVal = ? WHERE _id = 3", (birthday_str,))
            _ = cur.execute(
                "UPDATE SnapUserStore SET textVal = ? WHERE _id = 4",
                (auth.email if auth.email else None,),
            )
            _ = cur.execute("UPDATE SnapUserStore SET intVal = ? WHERE _id = 17", (now_ms,))
            _ = cur.execute("UPDATE SnapUserStore SET textVal = ? WHERE _id = 18", (auth.device.country_code,))
            _ = cur.execute("UPDATE SnapUserStore SET blobVal = NULL WHERE blobVal IS NOT NULL AND LENGTH(blobVal) > 100")

            for pref_key in (
                "CORE~SAMPLING_UUID",
                "SHARING~CONTACT_RANKING_SESSION_ID",
                "SNAPADS~SAID",
                "SPECTACLES~SPECTACLES_USER_ID",
            ):
                _ = cur.execute(
                    "UPDATE Preferences SET stringValue = ? WHERE key = ?",
                    (str(uuid.uuid4()), pref_key),
                )

            for ts_key in (
                "CRASH~LAST_APP_EXIT_TS",
                "CRASH~LAST_NATIVE_APP_EXIT_TS",
                "IDENTITY~LOGIN_TIMESTAMP_MILLISECONDS",
                "IDENTITY~LOGIN_SESSION_ID",
                "IDENTITY~USER_ACTIVITY_INFO_LAST_ACTIVE_TIMESTAMP",
                "BATTERY~LAST_READ_TIME_OF_USAGE_STATS",
                "FEATURE_BADGES~SPOTLIGHT_BADGE_LAST_SYNC_TIMESTAMP_MILLIS",
                "SNAP_PRO~LAST_BUSINESS_PROFILE_SYNC_MS",
            ):
                _ = cur.execute(
                    "UPDATE Preferences SET longValue = ? WHERE key = ?",
                    (now_ms, ts_key),
                )

            notif_key_b64 = base64.b64encode(os.urandom(16)).decode("ascii").replace("=", "\\u003d")
            _ = cur.execute(
                "UPDATE Preferences SET stringValue = ? WHERE key = 'MOBILE_SERVICES_NOTIFICATIONS~ENCRYPTION_MODEL'",
                (f'{{"a":"{notif_key_b64}","b":"ENCRYPTION_V1"}}',),
            )
            conn.commit()
        except Exception as exc:
            raise CodecException("CORE_DB_PATCH_FAILED", f"Failed patching {db_path.name}", exc) from exc
        finally:
            conn.close()

    def patch_lockscreen_core_db(self, db_path: Path, auth: AccountAuthData) -> None:
        if not db_path.is_file():
            return
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            _ = cur.execute("UPDATE ConfigEtag SET etag = ? WHERE _id IN (2, 3)", (auth.device.country_code,))
            conn.commit()
        finally:
            conn.close()

    def patch_arroyo_db(self, db_path: Path, auth: AccountAuthData) -> None:
        if not db_path.is_file():
            raise CodecException("ARROYO_DB_MISSING", f"Missing arroyo.db at {db_path}")
        now_ms = int(time.time() * 1000)
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            _ = cur.execute("SELECT value FROM required_values WHERE key = 'USERID'")
            row = cast(tuple[str] | None, cur.fetchone())
            old_uid = row[0] if row and row[0] else BAKED_USER_ID
            if old_uid != auth.user_id:
                replace_bytes_in_sqlite(cur, old_uid.encode("ascii"), auth.user_id.encode("ascii"))
                replace_bytes_in_sqlite(cur, uuid_to_bytes(old_uid), uuid_to_bytes(auth.user_id))
            _ = cur.execute("UPDATE required_values SET value = ? WHERE key = 'USERID'", (auth.user_id,))
            _ = cur.execute(
                "UPDATE key_values SET value = ? WHERE key = 'LAST_LOGIN_TIMESTAMP_KEY'",
                (str(now_ms),),
            )
            for table_name in (
                "conversation_message",
                "conversation",
                "conversation_identifier",
                "feed_entry",
                "feed_sync",
                "client_feed_pagination",
            ):
                _ = cur.execute(f"DELETE FROM [{table_name}]")
            conn.commit()
        except Exception as exc:
            raise CodecException("ARROYO_DB_PATCH_FAILED", f"Failed patching {db_path.name}", exc) from exc
        finally:
            conn.close()

    def patch_feature_db(self, db_path: Path) -> None:
        if not db_path.is_file():
            return
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            _ = cur.execute("DELETE FROM BusinessProfiles")
            _ = cur.execute("DELETE FROM SendToConversationTimestamps")
            conn.commit()
        except Exception as exc:
            raise CodecException("FEATURE_DB_PATCH_FAILED", f"Failed patching {db_path.name}", exc) from exc
        finally:
            conn.close()

    def write_shared_prefs(
        self,
        prefs_dir: Path,
        auth: AccountAuthData,
        fidelius: FideliusCryptoMaterial,
    ) -> None:
        prefs_dir.mkdir(parents=True, exist_ok=True)
        now_sec = int(time.time())
        now_ms = now_sec * 1000
        install_ms = _parse_install_timestamp_ms(auth.device.app_installed_at, now_ms)
        expiry_ms = now_ms + 180 * 86400 * 1000
        birthday_str = synthesize_birthday(auth.age, auth.astrological_sign)

        user_session_path = prefs_dir / "user_session_shared_pref.xml"
        if user_session_path.is_file():
            content = user_session_path.read_text(encoding="utf-8")
            content = re.sub(
                r'(<string name="key_user_id">)[^<]*(</string>)',
                f"\\g<1>{xml_escape(auth.user_id)}\\g<2>",
                content,
            )
            content = re.sub(
                r'(<string name="key_refresh_token">)[^<]*(</string>)',
                f"\\g<1>{xml_escape(auth.refresh_token)}\\g<2>",
                content,
            )
            content = re.sub(
                r'(<string name="BLIZZARD_AAO_ADVERTISING_INFO_ID">)[^<]*(</string>)',
                f"\\g<1>{uuid.uuid4()}\\g<2>",
                content,
            )
            content = re.sub(
                r'(<long name="BLIZZARD_AAO_ADVERTISING_INFO_ID_TIMESTAMP_SEC" value=")\d+(")',
                f"\\g<1>{now_sec}\\g<2>",
                content,
            )
            _ = user_session_path.write_text(content, encoding="utf-8")

        active_session = json.dumps(
            {
                "user_id": auth.user_id,
                "token": auth.refresh_token,
                "token_expiry_millis": expiry_ms,
            },
            separators=(",", ":"),
        )
        one_tap_users = json.dumps(
            [
                {
                    "userId": auth.user_id,
                    "tokenMetadata": {"username": auth.username, "tokenExpiry": {"a": 0}},
                    "tokenV3": auth.refresh_token,
                    "tokenV3Expiry": expiry_ms,
                    "optinSource": "REGISTRATION_PASSWORD_PAGE",
                    "tenureSeconds": 41,
                    "tfaEnabled": False,
                    "passwordRequired": False,
                    "displayName": auth.display_name,
                }
            ],
            separators=(",", ":"),
        )
        _write_xml_map(
            prefs_dir / "SharedPrefsOneTapLoginUserStore.xml",
            [
                f'    <string name="ActiveUserSession">{xml_escape(active_session)}</string>',
                '    <boolean name="HydrateStartedFlag" value="true" />',
                f'    <string name="OneTapLoginUsers">{xml_escape(one_tap_users)}</string>',
            ],
        )

        _write_xml_map(
            prefs_dir / "user_scoped_identity_keys.xml",
            [
                f'    <string name="in_beta">{xml_escape(auth.encryption_keys.private_key)}</string>',
                f'    <string name="user_id">{xml_escape(auth.user_id)}</string>',
                f'    <string name="iwek">{xml_escape(auth.encryption_keys.iwek)}</string>',
                f'    <string name="out_beta">{xml_escape(auth.encryption_keys.public_key)}</string>',
                f'    <int name="version" value="{auth.encryption_keys.version}" />',
            ],
        )
        _ = (prefs_dir / "user_device_identity_keys.xml").write_text(
            "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map />\n",
            encoding="utf-8",
        )

        _write_xml_map(
            prefs_dir / "fidelius_device_user_records.xml",
            [f'    <string name="records">{xml_escape(fidelius.device_user_records_b64)}</string>'],
        )

        _write_xml_map(
            prefs_dir / "identity_persistent_store.xml",
            [
                f'    <long name="INSTALL_ON_DEVICE_TIMESTAMP" value="{install_ms}" />',
                f'    <long name="LONG_CLIENT_ID_DEVICE_TIMESTAMP" value="{now_ms}" />',
                '    <boolean name="HAS_LOGGED_IN_BEFORE" value="true" />',
                f'    <string name="LAST_LOGGED_IN_USERNAME">{xml_escape(auth.username)}</string>',
                f'    <long name="FIRST_LOGGED_IN_ON_DEVICE_TIMESTAMP" value="{now_ms}" />',
                f'    <string name="LONG_CLIENT_ID">{uuid.uuid4()}</string>',
                '    <boolean name="HAS_VISITED_SPLASH_BEFORE" value="true" />',
            ],
        )

        _write_xml_map(
            prefs_dir / "LoginSignupStore.xml",
            [
                f'    <string name="SIGNUP_USERNAME">{xml_escape(auth.username)}</string>',
                f'    <string name="SIGNUP_FIRST_NAME">{xml_escape(auth.display_name)}</string>',
                '    <string name="SIGNUP_LAST_NAME"></string>',
                f'    <string name="SIGNUP_BIRTHDAY">{birthday_str}</string>',
                f'    <string name="AUTHENTICATION_SESSION_ID">{uuid.uuid4()}</string>',
                f'    <string name="SIGNUP_SESSION_ID">{uuid.uuid4()}</string>',
                f'    <long name="RESUME_REG_DATA_RETENTION_TIMESTAMP" value="{now_ms}" />',
            ],
        )

        _write_xml_map(
            prefs_dir / "UUID_STORE.xml",
            [f'    <string name="INSTANCE_UUID">{xml_escape(auth.device.cof_device_id)}</string>'],
        )

        _write_xml_map(
            prefs_dir / "meow.xml",
            [f'    <string name="installer_id">{xml_escape(auth.device.install_id)}</string>'],
        )

        _write_xml_map(
            prefs_dir / "com.snapchat.android.analytics.framework.com.snapchat.android.xml",
            [
                f'    <string name="com.snapchat.android.analytics.framework.dailyClientId">{xml_escape(auth.device.blizzard_client_id)}</string>',
                f'    <long name="com.snapchat.android.analytics.framework.dailyClientIdTs" value="{now_ms}" />',
            ],
        )

        music_path = prefs_dir / "MusicSharedPreferences.xml"
        if music_path.is_file():
            music_content = music_path.read_text(encoding="utf-8").replace(BAKED_USER_ID, auth.user_id)
            _ = music_path.write_text(music_content, encoding="utf-8")

        _write_xml_map(
            prefs_dir / "Composer.xml",
            [f'    <string name="deviceId">{uuid.uuid4()}</string>'],
        )
        _write_xml_map(
            prefs_dir / "com.google.mlkit.internal.xml",
            [f'    <string name="ml_sdk_instance_id">{uuid.uuid4()}</string>'],
        )
        _write_xml_map(
            prefs_dir / "BLIZZARD_SAMPLING_PREFS.xml",
            [f'    <int name="SAMPLING_MAGIC_NUM" value="{random.randint(1, 999)}" />'],
        )
        _write_xml_map(
            prefs_dir / "whatsapp_otp_handler_prefs.xml",
            [f'    <string name="prev_request_ids">{uuid.uuid4()},{uuid.uuid4()}</string>'],
        )

        gms_path = prefs_dir / "com.google.android.gms.measurement.prefs.xml"
        if gms_path.is_file():
            gms_txt = gms_path.read_text(encoding="utf-8")
            gms_txt = re.sub(
                r'(<string name="app_instance_id">)[^<]*(</string>)',
                f"\\g<1>{uuid.uuid4().hex}\\g<2>",
                gms_txt,
            )
            gms_txt = re.sub(r'(<long name="first_open_time" value=")\d+(")', f"\\g<1>{now_ms}\\g<2>", gms_txt)
            gms_txt = re.sub(r'(<long name="health_monitor:start" value=")\d+(")', f"\\g<1>{now_ms}\\g<2>", gms_txt)
            _ = gms_path.write_text(gms_txt, encoding="utf-8")

        perm_ts_path = prefs_dir / "permission_asked_permission_timestamp_status.xml"
        if perm_ts_path.is_file():
            perm_txt = perm_ts_path.read_text(encoding="utf-8")
            perm_txt = re.sub(r'(<long name="[^"]+" value=")\d+(")', f"\\g<1>{now_ms}\\g<2>", perm_txt)
            _ = perm_ts_path.write_text(perm_txt, encoding="utf-8")

    def write_device_files(self, files_dir: Path, auth: AccountAuthData) -> None:
        files_dir.mkdir(parents=True, exist_ok=True)

        _ = (files_dir / ".argos_aid").write_bytes(auth.device.android_id.encode("ascii"))

        if auth.device.idp and auth.device.device_token:
            snap_dir = files_dir / "Snapchat"
            snap_dir.mkdir(parents=True, exist_ok=True)
            escaped_val = auth.device.device_token.replace("=", "\\u003d")
            dt3_payload = f'{{"mId":"{auth.device.idp}","mValue":"{escaped_val}"}}'
            _ = (snap_dir / "device_token_3").write_bytes(dt3_payload.encode("utf-8"))

        if auth.argos.token:
            argos_user_dir = files_dir / "argos" / auth.user_id
            argos_user_dir.mkdir(parents=True, exist_ok=True)
            token_bin = build_argos_token_bin(auth.argos.token, auth.argos.refresh_at)
            _ = (argos_user_dir / "token.bin").write_bytes(token_bin)

        escaped_tz = auth.device.timezone.replace("/", "\\/")
        settings_payload = "".join(
            [
                '{"play_integrity_enabled":false,"play_integrity_api":false,',
                '"ka_snapreplace":false,"ka_freyatools":false,"ka_api":false,',
                '"skip_ka":false,"random_keys":false,"token_snapreplace":false,',
                '"token_freyatools":true,"spoof_android_id":true,',
                '"api_key":"ST-9c60e4c5-324b-4a62-8be6-f7c669b6fb22",',
                '"experiment_ids":[],"modular_excluded_ids":[],"ruleset":8,',
                f'"play_integrity_keys":[],"ads_id":"{uuid.uuid4()}",',
                f'"country_code":"{auth.device.country_code}","timezone":"{escaped_tz}"}}',
            ]
        )
        _ = (files_dir / "SettingsFromServer").write_bytes(settings_payload.encode("utf-8"))

        valdi_store_dir = files_dir / "valdi_cache" / auth.user_id / "PersistentStores"
        valdi_store_dir.mkdir(parents=True, exist_ok=True)
        uid_bytes = auth.user_id.encode("ascii")
        header = b"".join(
            [
                b"3\xc6\x00\x01t\x00\x00\x00\x0c\x00\x00\x00__manifest__",
                b"(\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00",
                b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                struct.pack("<I", len(uid_bytes)),
                uid_bytes,
                b"\t\x00\x00\x80\x08\x00\x18\xce\xff\xd4\xf3\x994\x00\x00\x00",
            ]
        )
        _ = (valdi_store_dir / "in-app-warning").write_bytes(header)
