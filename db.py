"""MySQL / MariaDB Persistence Layer for EmulatorManager & EmulatorDroplet.

Hosted on 89.34.17.131 (database: `timesync_RandomStuff`).
All tables are prefixed with `Emulators_` and indexed for fast lookups:
  - `Emulators_Workers`
  - `Emulators_Instances`
  - `Emulators_Actions`
  - `Emulators_ActionLogs`
  - `Emulators_UnknownPages`
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import xml.etree.ElementTree as ET
from typing import Any, Optional

import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.environ.get("FREYA_DB_HOST", "89.34.17.131")
DB_PORT = int(os.environ.get("FREYA_DB_PORT", "3306"))
DB_USER = os.environ.get("FREYA_DB_USER", "timesync_AI_with_update")
DB_PASS = os.environ.get("FREYA_DB_PASS", "YQQOmI0alLi")
DB_NAME = os.environ.get("FREYA_DB_NAME", "timesync_RandomStuff")

_db_init_lock = threading.Lock()
_db_initialized = False


def get_connection() -> pymysql.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS Emulators_Workers (
        worker_id VARCHAR(64) NOT NULL PRIMARY KEY,
        droplet_id BIGINT NULL,
        name VARCHAR(128) NOT NULL,
        region VARCHAR(32) NOT NULL DEFAULT 'nyc1',
        size_slug VARCHAR(64) NOT NULL DEFAULT 's-4vcpu-8gb',
        public_ip VARCHAR(64) NULL,
        private_ip VARCHAR(64) NULL,
        url VARCHAR(255) NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'PROVISIONING',
        draining TINYINT(1) NOT NULL DEFAULT 0,
        max_emulators INT NOT NULL DEFAULT 2,
        active_emulators INT NOT NULL DEFAULT 0,
        idle_emulators INT NOT NULL DEFAULT 0,
        busy_emulators INT NOT NULL DEFAULT 0,
        cpu_cores INT NOT NULL DEFAULT 0,
        cpu_load_1m DECIMAL(6,2) NOT NULL DEFAULT 0.00,
        ram_total_gb DECIMAL(6,2) NOT NULL DEFAULT 0.00,
        ram_used_gb DECIMAL(6,2) NOT NULL DEFAULT 0.00,
        ram_percent DECIMAL(5,1) NOT NULL DEFAULT 0.0,
        disk_total_gb DECIMAL(8,2) NOT NULL DEFAULT 0.00,
        disk_free_gb DECIMAL(8,2) NOT NULL DEFAULT 0.00,
        git_commit VARCHAR(32) NULL,
        last_error TEXT NULL,
        last_seen_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_ew_status (status),
        INDEX idx_ew_region (region),
        INDEX idx_ew_public_ip (public_ip)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS Emulators_Instances (
        emulator_id VARCHAR(64) NOT NULL PRIMARY KEY,
        avd_name VARCHAR(128) NOT NULL,
        worker_id VARCHAR(64) NULL,
        worker_name VARCHAR(128) NULL,
        worker_ip VARCHAR(64) NULL,
        worker_region VARCHAR(32) NULL,
        serial VARCHAR(64) NULL,
        username VARCHAR(128) NOT NULL,
        android_version INT NOT NULL DEFAULT 16,
        profile_name VARCHAR(64) NOT NULL DEFAULT 'a52s',
        apk_source VARCHAR(512) NOT NULL,
        proxy VARCHAR(255) NULL,
        headless TINYINT(1) NOT NULL DEFAULT 1,
        location VARCHAR(64) NOT NULL DEFAULT 'INITIALIZING',
        action_state VARCHAR(64) NOT NULL DEFAULT 'CREATING',
        status_text VARCHAR(512) NULL,
        last_action_id VARCHAR(64) NULL,
        last_action_json LONGTEXT NULL,
        deleted TINYINT(1) NOT NULL DEFAULT 0,
        final_message TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        deleted_at DATETIME NULL,
        INDEX idx_ei_worker_del (worker_id, deleted),
        INDEX idx_ei_del_created (deleted, created_at),
        INDEX idx_ei_username (username),
        INDEX idx_ei_location (location),
        INDEX idx_ei_action_state (action_state)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS Emulators_Actions (
        action_id VARCHAR(64) NOT NULL PRIMARY KEY,
        emulator_id VARCHAR(64) NOT NULL,
        worker_id VARCHAR(64) NULL,
        username VARCHAR(128) NULL,
        action_type VARCHAR(64) NOT NULL,
        params_json LONGTEXT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
        status VARCHAR(64) NOT NULL DEFAULT 'RUNNING',
        progress VARCHAR(512) NULL,
        start_location VARCHAR(64) NULL,
        end_location VARCHAR(64) NULL,
        error_code VARCHAR(64) NULL,
        error_message TEXT NULL,
        result_data_json LONGTEXT NULL,
        started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at DATETIME NULL,
        duration_ms INT NULL,
        INDEX idx_ea_emulator_started (emulator_id, started_at),
        INDEX idx_ea_worker_started (worker_id, started_at),
        INDEX idx_ea_type_state (action_type, state),
        INDEX idx_ea_status (status),
        INDEX idx_ea_username (username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS Emulators_ActionLogs (
        log_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        action_id VARCHAR(64) NULL,
        emulator_id VARCHAR(64) NULL,
        worker_id VARCHAR(64) NULL,
        username VARCHAR(128) NULL,
        level VARCHAR(16) NOT NULL DEFAULT 'INFO',
        event_type VARCHAR(64) NOT NULL,
        location VARCHAR(64) NULL,
        page_name VARCHAR(128) NULL,
        message TEXT NOT NULL,
        details_json LONGTEXT NULL,
        xml_snippet MEDIUMTEXT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        INDEX idx_eal_action (action_id, created_at),
        INDEX idx_eal_emulator (emulator_id, created_at),
        INDEX idx_eal_level_event (level, event_type, created_at),
        INDEX idx_eal_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS Emulators_UnknownPages (
        unknown_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        action_id VARCHAR(64) NULL,
        emulator_id VARCHAR(64) NOT NULL,
        worker_id VARCHAR(64) NULL,
        username VARCHAR(128) NULL,
        android_version INT NULL,
        action_type VARCHAR(64) NULL,
        expected_pages VARCHAR(512) NULL,
        current_location VARCHAR(64) NULL,
        reason VARCHAR(255) NOT NULL,
        visible_texts_json LONGTEXT NULL,
        xml_dump MEDIUMTEXT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        INDEX idx_eup_emulator (emulator_id, created_at),
        INDEX idx_eup_action (action_id),
        INDEX idx_eup_reason (reason, created_at),
        INDEX idx_eup_action_type (action_type, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
]


def init_db() -> bool:
    """Create all `Emulators_*` tables and indexes if they do not exist."""
    global _db_initialized
    if _db_initialized:
        return True
    with _db_init_lock:
        if _db_initialized:
            return True
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    for stmt in SCHEMA_STATEMENTS:
                        cur.execute(stmt)
                _db_initialized = True
                return True
            finally:
                conn.close()
        except Exception as exc:
            print(f"[db] Warning: init_db failed: {exc}", flush=True)
            return False


def _parse_iso_dt(val: Optional[str]) -> Optional[datetime.datetime]:
    if not val:
        return None
    if isinstance(val, datetime.datetime):
        return val.astimezone(datetime.timezone.utc).replace(tzinfo=None) if val.tzinfo else val
    try:
        dt = datetime.datetime.fromisoformat(str(val))
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def _fmt_dt(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.replace(tzinfo=datetime.timezone.utc).isoformat(timespec="seconds")
    return str(val)


def _json_dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def _json_loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Workers Table (`Emulators_Workers`)
# ---------------------------------------------------------------------------

def upsert_worker(w: dict[str, Any]):
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO Emulators_Workers (
                        worker_id, droplet_id, name, region, size_slug,
                        public_ip, private_ip, url, status, draining,
                        max_emulators, active_emulators, idle_emulators, busy_emulators,
                        cpu_cores, cpu_load_1m, ram_total_gb, ram_used_gb, ram_percent,
                        disk_total_gb, disk_free_gb, git_commit, last_error,
                        last_seen_at, created_at
                    ) VALUES (
                        %(worker_id)s, %(droplet_id)s, %(name)s, %(region)s, %(size_slug)s,
                        %(public_ip)s, %(private_ip)s, %(url)s, %(status)s, %(draining)s,
                        %(max_emulators)s, %(active_emulators)s, %(idle_emulators)s, %(busy_emulators)s,
                        %(cpu_cores)s, %(cpu_load_1m)s, %(ram_total_gb)s, %(ram_used_gb)s, %(ram_percent)s,
                        %(disk_total_gb)s, %(disk_free_gb)s, %(git_commit)s, %(last_error)s,
                        %(last_seen_at)s, %(created_at)s
                    )
                    ON DUPLICATE KEY UPDATE
                        droplet_id = VALUES(droplet_id),
                        name = VALUES(name),
                        region = VALUES(region),
                        size_slug = VALUES(size_slug),
                        public_ip = VALUES(public_ip),
                        private_ip = VALUES(private_ip),
                        url = VALUES(url),
                        status = VALUES(status),
                        draining = VALUES(draining),
                        max_emulators = VALUES(max_emulators),
                        active_emulators = VALUES(active_emulators),
                        idle_emulators = VALUES(idle_emulators),
                        busy_emulators = VALUES(busy_emulators),
                        cpu_cores = VALUES(cpu_cores),
                        cpu_load_1m = VALUES(cpu_load_1m),
                        ram_total_gb = VALUES(ram_total_gb),
                        ram_used_gb = VALUES(ram_used_gb),
                        ram_percent = VALUES(ram_percent),
                        disk_total_gb = VALUES(disk_total_gb),
                        disk_free_gb = VALUES(disk_free_gb),
                        git_commit = VALUES(git_commit),
                        last_error = VALUES(last_error),
                        last_seen_at = VALUES(last_seen_at)
                    """,
                    {
                        "worker_id": w["id"],
                        "droplet_id": w.get("droplet_id"),
                        "name": w.get("name") or w["id"],
                        "region": w.get("region") or "nyc1",
                        "size_slug": w.get("size") or "s-4vcpu-8gb",
                        "public_ip": w.get("public_ip"),
                        "private_ip": w.get("private_ip"),
                        "url": w.get("url"),
                        "status": w.get("status") or "OFFLINE",
                        "draining": 1 if w.get("draining") else 0,
                        "max_emulators": int(w.get("max_emulators") or 2),
                        "active_emulators": int(w.get("active_emulators") or 0),
                        "idle_emulators": int(w.get("idle_emulators") or 0),
                        "busy_emulators": int(w.get("busy_emulators") or 0),
                        "cpu_cores": int(w.get("cpu_cores") or 0),
                        "cpu_load_1m": float(w.get("cpu_load_1m") or 0.0),
                        "ram_total_gb": float(w.get("ram_total_gb") or 0.0),
                        "ram_used_gb": float(w.get("ram_used_gb") or 0.0),
                        "ram_percent": float(w.get("ram_percent") or 0.0),
                        "disk_total_gb": float(w.get("disk_total_gb") or 0.0),
                        "disk_free_gb": float(w.get("disk_free_gb") or 0.0),
                        "git_commit": w.get("git_commit") or "unknown",
                        "last_error": w.get("last_error"),
                        "last_seen_at": _parse_iso_dt(w.get("last_seen")) or datetime.datetime.utcnow(),
                        "created_at": _parse_iso_dt(w.get("created_at")) or datetime.datetime.utcnow(),
                    },
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] upsert_worker error: {exc}", flush=True)


def delete_worker_db(worker_id: str):
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM Emulators_Workers WHERE worker_id = %s", (worker_id,))
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] delete_worker_db error: {exc}", flush=True)


def load_all_workers_db() -> dict[str, dict[str, Any]]:
    init_db()
    out: dict[str, dict[str, Any]] = {}
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM Emulators_Workers ORDER BY created_at ASC")
                for row in cur.fetchall():
                    wid = row["worker_id"]
                    out[wid] = {
                        "id": wid,
                        "droplet_id": row["droplet_id"],
                        "name": row["name"],
                        "region": row["region"],
                        "size": row["size_slug"],
                        "public_ip": row["public_ip"],
                        "private_ip": row["private_ip"],
                        "url": row["url"],
                        "status": row["status"],
                        "draining": bool(row["draining"]),
                        "max_emulators": int(row["max_emulators"]),
                        "active_emulators": int(row["active_emulators"]),
                        "idle_emulators": int(row["idle_emulators"]),
                        "busy_emulators": int(row["busy_emulators"]),
                        "cpu_cores": int(row["cpu_cores"]),
                        "cpu_load_1m": float(row["cpu_load_1m"]),
                        "ram_total_gb": float(row["ram_total_gb"]),
                        "ram_used_gb": float(row["ram_used_gb"]),
                        "ram_percent": float(row["ram_percent"]),
                        "disk_total_gb": float(row["disk_total_gb"]),
                        "disk_free_gb": float(row["disk_free_gb"]),
                        "git_commit": row["git_commit"] or "unknown",
                        "last_error": row["last_error"],
                        "last_seen": _fmt_dt(row["last_seen_at"]),
                        "created_at": _fmt_dt(row["created_at"]),
                        "cached_active_emulators": [],
                        "cached_deleted_emulators": [],
                    }
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] load_all_workers_db error: {exc}", flush=True)
    return out


# ---------------------------------------------------------------------------
# Emulator Instances (`Emulators_Instances`)
# ---------------------------------------------------------------------------

def upsert_emulator(rec: dict[str, Any]):
    init_db()
    try:
        last_act = rec.get("last_action")
        last_act_id = last_act.get("action_id") if isinstance(last_act, dict) else None
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO Emulators_Instances (
                        emulator_id, avd_name, worker_id, worker_name, worker_ip, worker_region,
                        serial, username, android_version, profile_name, apk_source, proxy,
                        headless, location, action_state, status_text,
                        last_action_id, last_action_json, deleted, final_message,
                        created_at, deleted_at
                    ) VALUES (
                        %(emulator_id)s, %(avd_name)s, %(worker_id)s, %(worker_name)s, %(worker_ip)s, %(worker_region)s,
                        %(serial)s, %(username)s, %(android_version)s, %(profile_name)s, %(apk_source)s, %(proxy)s,
                        %(headless)s, %(location)s, %(action_state)s, %(status_text)s,
                        %(last_action_id)s, %(last_action_json)s, %(deleted)s, %(final_message)s,
                        %(created_at)s, %(deleted_at)s
                    )
                    ON DUPLICATE KEY UPDATE
                        worker_id = COALESCE(VALUES(worker_id), worker_id),
                        worker_name = COALESCE(VALUES(worker_name), worker_name),
                        worker_ip = COALESCE(VALUES(worker_ip), worker_ip),
                        worker_region = COALESCE(VALUES(worker_region), worker_region),
                        serial = VALUES(serial),
                        location = VALUES(location),
                        action_state = VALUES(action_state),
                        status_text = VALUES(status_text),
                        last_action_id = COALESCE(VALUES(last_action_id), last_action_id),
                        last_action_json = COALESCE(VALUES(last_action_json), last_action_json),
                        deleted = VALUES(deleted),
                        final_message = COALESCE(VALUES(final_message), final_message),
                        deleted_at = COALESCE(VALUES(deleted_at), deleted_at)
                    """,
                    {
                        "emulator_id": rec["id"],
                        "avd_name": rec.get("name") or f"emu_{rec['id']}",
                        "worker_id": rec.get("worker_id"),
                        "worker_name": rec.get("worker_name"),
                        "worker_ip": rec.get("worker_ip"),
                        "worker_region": rec.get("worker_region"),
                        "serial": rec.get("serial"),
                        "username": rec.get("username") or "",
                        "android_version": int(rec.get("android") or 16),
                        "profile_name": rec.get("profile") or "a52s",
                        "apk_source": rec.get("apk") or "",
                        "proxy": rec.get("proxy"),
                        "headless": 1 if rec.get("headless", True) else 0,
                        "location": rec.get("location") or "INITIALIZING",
                        "action_state": rec.get("action") or "IDLE",
                        "status_text": rec.get("status") or "",
                        "last_action_id": last_act_id,
                        "last_action_json": _json_dumps(last_act) if last_act else None,
                        "deleted": 1 if rec.get("deleted") else 0,
                        "final_message": rec.get("final_message"),
                        "created_at": _parse_iso_dt(rec.get("created_at")) or datetime.datetime.utcnow(),
                        "deleted_at": _parse_iso_dt(rec.get("deleted_at")),
                    },
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] upsert_emulator error: {exc}", flush=True)


def _row_to_emulator_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["emulator_id"],
        "name": row["avd_name"],
        "worker_id": row["worker_id"],
        "worker_name": row["worker_name"],
        "worker_ip": row["worker_ip"],
        "worker_region": row["worker_region"],
        "serial": row["serial"],
        "android": int(row["android_version"]),
        "profile": row["profile_name"],
        "username": row["username"],
        "apk": row["apk_source"],
        "proxy": row["proxy"],
        "headless": bool(row["headless"]),
        "location": row["location"],
        "action": row["action_state"],
        "status": row["status_text"],
        "last_action": _json_loads(row["last_action_json"], None),
        "deleted": bool(row["deleted"]),
        "final_message": row["final_message"],
        "created_at": _fmt_dt(row["created_at"]),
        "deleted_at": _fmt_dt(row["deleted_at"]),
    }


def mark_worker_emulators_cleaned(worker_name_or_id: str):
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE Emulators_Instances
                    SET deleted = 1,
                        action_state = 'DELETED',
                        status_text = 'Deleted on worker restart',
                        serial = NULL,
                        final_message = COALESCE(final_message, 'WORKER_RESTART_CLEANUP'),
                        deleted_at = COALESCE(deleted_at, UTC_TIMESTAMP())
                    WHERE deleted = 0
                      AND (worker_id = %s OR worker_name = %s)
                    """,
                    (worker_name_or_id, worker_name_or_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] mark_worker_emulators_cleaned error: {exc}", flush=True)


def load_deleted_emulators_db(limit: int = 100, worker_name_or_id: Optional[str] = None) -> list[dict[str, Any]]:
    init_db()
    rows_out: list[dict[str, Any]] = []
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                if worker_name_or_id:
                    cur.execute(
                        """
                        SELECT * FROM Emulators_Instances
                        WHERE deleted = 1 AND (worker_id = %s OR worker_name = %s)
                        ORDER BY COALESCE(deleted_at, created_at) DESC
                        LIMIT %s
                        """,
                        (worker_name_or_id, worker_name_or_id, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM Emulators_Instances
                        WHERE deleted = 1
                        ORDER BY COALESCE(deleted_at, created_at) DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                for r in cur.fetchall():
                    rows_out.append(_row_to_emulator_dict(r))
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] load_deleted_emulators_db error: {exc}", flush=True)
    return rows_out


# ---------------------------------------------------------------------------
# Automation Actions (`Emulators_Actions`)
# ---------------------------------------------------------------------------

def upsert_action(
    act: dict[str, Any],
    worker_id: Optional[str] = None,
    username: Optional[str] = None,
    start_location: Optional[str] = None,
    end_location: Optional[str] = None,
    error_code: Optional[str] = None,
):
    init_db()
    try:
        started_dt = _parse_iso_dt(act.get("started_at")) or datetime.datetime.utcnow()
        finished_dt = _parse_iso_dt(act.get("finished_at"))
        duration_ms = None
        if started_dt and finished_dt:
            duration_ms = max(0, int((finished_dt - started_dt).total_seconds() * 1000))

        err_msg = act.get("error")
        if err_msg and not error_code and ":" in str(err_msg):
            prefix = str(err_msg).split(":", 1)[0].strip()
            if prefix.isupper() or "_" in prefix:
                error_code = prefix[:64]

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO Emulators_Actions (
                        action_id, emulator_id, worker_id, username, action_type,
                        params_json, state, status, progress,
                        start_location, end_location, error_code, error_message,
                        result_data_json, started_at, finished_at, duration_ms
                    ) VALUES (
                        %(action_id)s, %(emulator_id)s, %(worker_id)s, %(username)s, %(action_type)s,
                        %(params_json)s, %(state)s, %(status)s, %(progress)s,
                        %(start_location)s, %(end_location)s, %(error_code)s, %(error_message)s,
                        %(result_data_json)s, %(started_at)s, %(finished_at)s, %(duration_ms)s
                    )
                    ON DUPLICATE KEY UPDATE
                        worker_id = COALESCE(VALUES(worker_id), worker_id),
                        username = COALESCE(VALUES(username), username),
                        state = VALUES(state),
                        status = VALUES(status),
                        progress = VALUES(progress),
                        start_location = COALESCE(VALUES(start_location), start_location),
                        end_location = COALESCE(VALUES(end_location), end_location),
                        error_code = COALESCE(VALUES(error_code), error_code),
                        error_message = VALUES(error_message),
                        result_data_json = VALUES(result_data_json),
                        finished_at = VALUES(finished_at),
                        duration_ms = COALESCE(VALUES(duration_ms), duration_ms)
                    """,
                    {
                        "action_id": act["action_id"],
                        "emulator_id": act["emulator_id"],
                        "worker_id": worker_id,
                        "username": username,
                        "action_type": act["action_type"],
                        "params_json": _json_dumps(act.get("params") or {}),
                        "state": act.get("state") or "RUNNING",
                        "status": act.get("status") or "RUNNING",
                        "progress": act.get("progress") or "",
                        "start_location": start_location,
                        "end_location": end_location,
                        "error_code": error_code,
                        "error_message": err_msg,
                        "result_data_json": _json_dumps(act.get("data") or {}),
                        "started_at": started_dt,
                        "finished_at": finished_dt,
                        "duration_ms": duration_ms,
                    },
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] upsert_action error: {exc}", flush=True)


def _row_to_action_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": row["action_id"],
        "emulator_id": row["emulator_id"],
        "worker_id": row["worker_id"],
        "username": row["username"],
        "action_type": row["action_type"],
        "params": _json_loads(row["params_json"], {}),
        "state": row["state"],
        "status": row["status"],
        "progress": row["progress"],
        "start_location": row["start_location"],
        "end_location": row["end_location"],
        "error_code": row["error_code"],
        "error": row["error_message"],
        "data": _json_loads(row["result_data_json"], {}),
        "started_at": _fmt_dt(row["started_at"]),
        "finished_at": _fmt_dt(row["finished_at"]),
        "duration_ms": row["duration_ms"],
    }


def get_action_db(action_id: str) -> Optional[dict[str, Any]]:
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM Emulators_Actions WHERE action_id = %s", (action_id,))
                row = cur.fetchone()
                return _row_to_action_dict(row) if row else None
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] get_action_db error: {exc}", flush=True)
        return None


def list_emulator_actions_db(emulator_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    out: list[dict[str, Any]] = []
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM Emulators_Actions WHERE emulator_id = %s ORDER BY started_at DESC LIMIT %s",
                    (emulator_id, limit),
                )
                for r in cur.fetchall():
                    out.append(_row_to_action_dict(r))
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] list_emulator_actions_db error: {exc}", flush=True)
    return out


# ---------------------------------------------------------------------------
# Action Logs (`Emulators_ActionLogs`) & Unknown Pages (`Emulators_UnknownPages`)
# ---------------------------------------------------------------------------

def summarize_xml_hierarchy(xml_or_element: Any) -> tuple[list[dict[str, Any]], str]:
    """Extract visible UI nodes (text, content-desc, resource-id, bounds) and raw XML string."""
    raw_xml = ""
    root = None
    try:
        if hasattr(xml_or_element, "_element"):
            root = xml_or_element._element
            raw_xml = ET.tostring(root, encoding="unicode")
        elif isinstance(xml_or_element, ET.Element):
            root = xml_or_element
            raw_xml = ET.tostring(root, encoding="unicode")
        elif isinstance(xml_or_element, str):
            raw_xml = xml_or_element
            if raw_xml.strip().startswith("<"):
                root = ET.fromstring(raw_xml)
    except Exception:
        pass

    visible_nodes: list[dict[str, Any]] = []
    if root is not None:
        for node in root.iter():
            txt = (node.get("text") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            rid = (node.get("resource-id") or "").strip()
            if txt or desc or rid:
                visible_nodes.append({
                    "text": txt,
                    "content_desc": desc,
                    "resource_id": rid,
                    "class": node.get("class") or "",
                    "clickable": node.get("clickable") == "true",
                    "bounds": node.get("bounds") or "",
                })
                if len(visible_nodes) >= 120:
                    break
    return visible_nodes, raw_xml


def insert_action_log(
    emulator_id: Optional[str],
    action_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    username: Optional[str] = None,
    level: str = "INFO",
    event_type: str = "STATUS_UPDATE",
    location: Optional[str] = None,
    page_name: Optional[str] = None,
    message: str = "",
    details: Optional[dict[str, Any]] = None,
    xml_snippet: Optional[str] = None,
):
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO Emulators_ActionLogs (
                        action_id, emulator_id, worker_id, username,
                        level, event_type, location, page_name,
                        message, details_json, xml_snippet
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        action_id,
                        emulator_id,
                        worker_id,
                        username,
                        level[:16],
                        event_type[:64],
                        location,
                        page_name,
                        message or "",
                        _json_dumps(details) if details else None,
                        xml_snippet,
                    ),
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] insert_action_log error: {exc}", flush=True)


def insert_unknown_page(
    emulator_id: str,
    reason: str,
    action_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    username: Optional[str] = None,
    android_version: Optional[int] = None,
    action_type: Optional[str] = None,
    expected_pages: Optional[str] = None,
    current_location: Optional[str] = None,
    xml_or_element: Any = None,
):
    init_db()
    visible_nodes, raw_xml = summarize_xml_hierarchy(xml_or_element)
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO Emulators_UnknownPages (
                        action_id, emulator_id, worker_id, username,
                        android_version, action_type, expected_pages,
                        current_location, reason, visible_texts_json, xml_dump
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        action_id,
                        emulator_id,
                        worker_id,
                        username,
                        android_version,
                        action_type,
                        (expected_pages or "")[:512] if expected_pages else None,
                        current_location,
                        reason[:255],
                        _json_dumps(visible_nodes),
                        raw_xml or None,
                    ),
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] insert_unknown_page error: {exc}", flush=True)


def query_action_logs(
    emulator_id: Optional[str] = None,
    action_id: Optional[str] = None,
    level: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_db()
    clauses = []
    args: list[Any] = []
    if emulator_id:
        clauses.append("emulator_id = %s")
        args.append(emulator_id)
    if action_id:
        clauses.append("action_id = %s")
        args.append(action_id)
    if level:
        clauses.append("level = %s")
        args.append(level)
    if event_type:
        clauses.append("event_type = %s")
        args.append(event_type)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(min(500, max(1, int(limit))))

    out: list[dict[str, Any]] = []
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT log_id, action_id, emulator_id, worker_id, username,
                           level, event_type, location, page_name, message,
                           details_json, (xml_snippet IS NOT NULL) AS has_xml, created_at
                    FROM Emulators_ActionLogs
                    {where_sql}
                    ORDER BY log_id DESC
                    LIMIT %s
                    """,
                    tuple(args),
                )
                for r in cur.fetchall():
                    out.append({
                        "log_id": r["log_id"],
                        "action_id": r["action_id"],
                        "emulator_id": r["emulator_id"],
                        "worker_id": r["worker_id"],
                        "username": r["username"],
                        "level": r["level"],
                        "event_type": r["event_type"],
                        "location": r["location"],
                        "page_name": r["page_name"],
                        "message": r["message"],
                        "details": _json_loads(r["details_json"], None),
                        "has_xml": bool(r["has_xml"]),
                        "created_at": _fmt_dt(r["created_at"]),
                    })
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] query_action_logs error: {exc}", flush=True)
    return out


def query_unknown_pages(
    emulator_id: Optional[str] = None,
    action_id: Optional[str] = None,
    include_xml: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    init_db()
    clauses = []
    args: list[Any] = []
    if emulator_id:
        clauses.append("emulator_id = %s")
        args.append(emulator_id)
    if action_id:
        clauses.append("action_id = %s")
        args.append(action_id)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(min(200, max(1, int(limit))))
    xml_col = ", xml_dump" if include_xml else ", CHAR_LENGTH(xml_dump) AS xml_length"

    out: list[dict[str, Any]] = []
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT unknown_id, action_id, emulator_id, worker_id, username,
                           android_version, action_type, expected_pages, current_location,
                           reason, visible_texts_json, created_at{xml_col}
                    FROM Emulators_UnknownPages
                    {where_sql}
                    ORDER BY unknown_id DESC
                    LIMIT %s
                    """,
                    tuple(args),
                )
                for r in cur.fetchall():
                    item = {
                        "unknown_id": r["unknown_id"],
                        "action_id": r["action_id"],
                        "emulator_id": r["emulator_id"],
                        "worker_id": r["worker_id"],
                        "username": r["username"],
                        "android_version": r["android_version"],
                        "action_type": r["action_type"],
                        "expected_pages": r["expected_pages"],
                        "current_location": r["current_location"],
                        "reason": r["reason"],
                        "visible_texts": _json_loads(r["visible_texts_json"], []),
                        "created_at": _fmt_dt(r["created_at"]),
                    }
                    if include_xml:
                        item["xml_dump"] = r.get("xml_dump")
                    else:
                        item["xml_length"] = r.get("xml_length") or 0
                    out.append(item)
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] query_unknown_pages error: {exc}", flush=True)
    return out


def get_unknown_page_by_id(unknown_id: int) -> Optional[dict[str, Any]]:
    init_db()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM Emulators_UnknownPages WHERE unknown_id = %s", (int(unknown_id),))
                r = cur.fetchone()
                if not r:
                    return None
                return {
                    "unknown_id": r["unknown_id"],
                    "action_id": r["action_id"],
                    "emulator_id": r["emulator_id"],
                    "worker_id": r["worker_id"],
                    "username": r["username"],
                    "android_version": r["android_version"],
                    "action_type": r["action_type"],
                    "expected_pages": r["expected_pages"],
                    "current_location": r["current_location"],
                    "reason": r["reason"],
                    "visible_texts": _json_loads(r["visible_texts_json"], []),
                    "xml_dump": r["xml_dump"],
                    "created_at": _fmt_dt(r["created_at"]),
                }
        finally:
            conn.close()
    except Exception as exc:
        print(f"[db] get_unknown_page_by_id error: {exc}", flush=True)
        return None
