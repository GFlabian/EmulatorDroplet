"""Local HTTP API and Web UI server for EmulatorManager + Snapchat UI Automation.

Run with:
    python server.py [--host 127.0.0.1] [--port 8000]
or:
    python emumanager.py server [--host 127.0.0.1] [--port 8000]
"""

import argparse
import datetime
import importlib
import os
import platform
import shutil
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
import uvicorn

from automation import (
    ActionRecord,
    AutomationError,
    Location,
    PhoneController,
    get_action,
    list_supported_actions,
)
import db
from emumanager import ANDROID_IMAGES, EmulatorError, EmulatorManager


class CreateEmulatorRequest(BaseModel):
    apk: str = Field(
        default="http://89.34.17.131/Files/1430unpinned.apk",
        min_length=1,
        description="Direct download URL (or local path) for the APK",
    )
    username: str = Field(..., min_length=1, description="Snapchat username whose session to load")
    android: int = Field(default=16, description="Android version: 14, 15, or 16")
    profile: str = Field(default="a52s", min_length=1, description="Saved device profile name (e.g. a52s)")
    proxy: Optional[str] = Field(
        default="68.183.65.77:37219:geelark:67016a3f075ce9d73f",
        description="Optional proxy host:port or host:port:user:pass",
    )
    headless: bool = Field(default=False, description="Run without an emulator window")


class ShellCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, description="adb shell command to execute")
    timeout: int = Field(default=60, ge=1, le=600, description="Timeout in seconds")


class DeviceInputRequest(BaseModel):
    type: str = Field(..., description="Input type: tap, swipe, text, key, or restart_app")
    x: Optional[int] = Field(default=None, description="X coordinate (0..1080) for tap")
    y: Optional[int] = Field(default=None, description="Y coordinate (0..2400) for tap")
    x1: Optional[int] = Field(default=None, description="Start X coordinate for swipe")
    y1: Optional[int] = Field(default=None, description="Start Y coordinate for swipe")
    x2: Optional[int] = Field(default=None, description="End X coordinate for swipe")
    y2: Optional[int] = Field(default=None, description="End Y coordinate for swipe")
    duration_ms: int = Field(default=300, ge=50, le=5000, description="Swipe duration in ms")
    text: Optional[str] = Field(default=None, description="Text string to type")
    keycode: Optional[int] = Field(default=None, description="Android keycode (e.g. 4=BACK, 3=HOME, 187=RECENTS, 66=ENTER, 67=BACKSPACE)")


class ExecuteActionRequest(BaseModel):
    action: str = Field(..., min_length=1, description="Action name (e.g. ADD_FRIEND, WATCH_REELS, ...)")
    params: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    # Optional convenience top-level fields merged into params if provided
    username: Optional[str] = None
    message: Optional[str] = None
    question: Optional[str] = None
    count: Optional[int] = None
    nr_of_reels: Optional[int] = None
    min_wait: Optional[float] = None
    max_wait: Optional[float] = None
    wait_time: Optional[float] = None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


class EmulatorRegistry:
    """Thread-safe state registry for active/deleted emulators and automation actions."""

    def __init__(self, manager: EmulatorManager):
        self.manager = manager
        self._lock = threading.RLock()
        self._records: dict[str, dict] = {}
        self._controllers: dict[str, PhoneController] = {}
        self._actions: dict[str, ActionRecord] = {}
        self._emu_actions: dict[str, list[str]] = {}
        self._delete_flags: set[str] = set()

    def cleanup_previous_run(self):
        db.init_db()
        node = platform.node()
        db_active = {r["name"]: r for r in db.load_active_emulators_db(worker_name_or_id=node)}
        adopted = 0
        for avd_name in list(self.manager.avds()):
            if self.manager.is_running(avd_name) and avd_name in db_active:
                rec = db_active[avd_name]
                emu_id = rec["id"]
                rec["serial"] = self.manager.serial(avd_name)
                if rec.get("action") != "IDLE":
                    rec["action"] = "IDLE"
                    rec["status"] = "Idle"
                with self._lock:
                    self._records[emu_id] = rec
                    self._emu_actions.setdefault(emu_id, [])
                db.upsert_emulator(rec)
                adopted += 1
            else:
                try:
                    self.manager.delete(avd_name)
                except Exception:
                    pass
        # Mark any DB records that were not running as cleaned up
        for avd_name, rec in db_active.items():
            if rec["id"] not in self._records:
                rec["deleted"] = True
                rec["action"] = "DELETED"
                rec["status"] = "Deleted on worker restart"
                rec["serial"] = None
                rec["final_message"] = rec.get("final_message") or "WORKER_RESTART_CLEANUP"
                rec["deleted_at"] = _now_iso()
                db.upsert_emulator(rec)
        print(f"[server] Adopted {adopted} running emulator(s) from MariaDB.", flush=True)

    def _serialize(self, rec: dict) -> dict:
        data = dict(rec)
        if not data["deleted"]:
            data["serial"] = self.manager.serial(data["name"]) or data.get("serial")
        return data

    def list_active(self) -> list[dict]:
        with self._lock:
            return [self._serialize(r) for r in self._records.values() if not r["deleted"]]

    def list_deleted(self) -> list[dict]:
        with self._lock:
            local_del = {r["id"]: self._serialize(r) for r in self._records.values() if r["deleted"]}
        for d in db.load_deleted_emulators_db(limit=50, worker_name_or_id=platform.node()):
            if d["id"] not in local_del:
                local_del[d["id"]] = d
        return list(local_del.values())

    def get(self, emu_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._records.get(emu_id)
            return self._serialize(rec) if rec else None

    def get_action_record(self, action_id: str) -> Optional[dict]:
        with self._lock:
            act = self._actions.get(action_id)
            if act:
                return act.to_dict()
        return db.get_action_db(action_id)

    def list_emulator_actions(self, emu_id: str) -> list[dict]:
        with self._lock:
            ids = self._emu_actions.get(emu_id, [])
            local_list = [self._actions[aid].to_dict() for aid in reversed(ids) if aid in self._actions]
        if local_list:
            return local_list
        db_list = db.list_emulator_actions_db(emu_id, limit=100)
        if db_list or emu_id in self._records:
            return db_list
        raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")

    def create_async(self, req: CreateEmulatorRequest) -> dict:
        apk = req.apk.strip()
        username = req.username.strip()
        profile = req.profile.strip()
        proxy = req.proxy.strip() if req.proxy and req.proxy.strip() else None

        if not apk or not username or not profile:
            raise HTTPException(status_code=400, detail="apk, username, android, and profile are mandatory")
        if req.android not in ANDROID_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported android version {req.android!r}. Must be one of {sorted(ANDROID_IMAGES)}",
            )
        available_profiles = self.manager.list_profiles()
        if profile not in available_profiles:
            raise HTTPException(
                status_code=400,
                detail=f"Profile {profile!r} not found. Available profiles: {available_profiles}",
            )
        if proxy:
            from emumanager import _proxy_url
            try:
                _proxy_url(proxy)
            except EmulatorError as e:
                raise HTTPException(status_code=400, detail=str(e))

        with self._lock:
            emu_id = uuid.uuid4().hex[:8]
            while emu_id in self._records:
                emu_id = uuid.uuid4().hex[:8]
            avd_name = f"emu_{emu_id}"
            record = {
                "id": emu_id,
                "name": avd_name,
                "serial": None,
                "android": req.android,
                "profile": profile,
                "username": username,
                "apk": apk,
                "proxy": proxy,
                "headless": req.headless,
                "location": Location.INITIALIZING,
                "action": "CREATING",
                "status": "Initializing...",
                "last_action": None,
                "deleted": False,
                "final_message": None,
                "created_at": _now_iso(),
                "deleted_at": None,
                "worker_name": platform.node(),
            }
            self._records[emu_id] = record
            self._emu_actions[emu_id] = []

        db.upsert_emulator(record)
        db.insert_action_log(
            emulator_id=emu_id,
            worker_id=platform.node(),
            username=username,
            level="INFO",
            event_type="LIFECYCLE",
            location=Location.INITIALIZING,
            message=f"Creating emulator {avd_name} (Android {req.android}, profile {profile})",
        )
        thread = threading.Thread(target=self._run_create, args=(emu_id,), daemon=True)
        thread.start()
        return self._serialize(record)

    def _set_status(self, emu_id: str, status: str):
        with self._lock:
            rec = self._records.get(emu_id)
            if not rec or rec["deleted"] or emu_id in self._delete_flags:
                raise EmulatorError("DELETE_REQUESTED")
            rec["status"] = status
            serial = self.manager.serial(rec["name"])
            if serial:
                rec["serial"] = serial
            snap = dict(rec)
        db.upsert_emulator(snap)

    def _set_location(self, emu_id: str, location: str):
        snap = None
        with self._lock:
            rec = self._records.get(emu_id)
            if rec and not rec["deleted"]:
                rec["location"] = location
                snap = dict(rec)
        if snap:
            db.upsert_emulator(snap)

    def _get_or_create_controller(self, emu_id: str) -> PhoneController:
        with self._lock:
            rec = self._records[emu_id]
            ctrl = self._controllers.get(emu_id)
            if ctrl is None:
                ctrl = PhoneController(
                    manager=self.manager,
                    avd_name=rec["name"],
                    on_status=lambda st: self._set_status(emu_id, st),
                    on_location=lambda loc: self._set_location(emu_id, loc),
                    initial_location=rec.get("location") or Location.MAIN_PAGE,
                    username=rec.get("username") or "",
                    emulator_id=emu_id,
                    worker_id=rec.get("worker_id") or platform.node(),
                    android_version=int(rec.get("android") or 16),
                )
                self._controllers[emu_id] = ctrl
            else:
                ctrl._location = rec.get("location") or ctrl.location
                ctrl.username = rec.get("username") or ctrl.username
                ctrl.emulator_id = emu_id
            return ctrl

    def _run_create(self, emu_id: str):
        with self._lock:
            rec = self._records[emu_id]
            avd_name = rec["name"]
            apk = rec["apk"]
            username = rec["username"]
            android = rec["android"]
            profile = rec["profile"]
            proxy = rec["proxy"]
            headless = rec["headless"]

        try:
            dev = self.manager.spawn(
                avd_name,
                apk=apk,
                username=username,
                android=android,
                profile=profile,
                proxy=proxy,
                headless=headless,
                on_status=lambda st: self._set_status(emu_id, st),
            )
            with self._lock:
                if emu_id in self._delete_flags or rec["deleted"]:
                    need_cleanup = True
                else:
                    rec["serial"] = dev.serial
                    rec["location"] = Location.MAIN_PAGE
                    rec["action"] = "IDLE"
                    rec["status"] = "Idle"
                    self._get_or_create_controller(emu_id)
                    need_cleanup = False
                snap = dict(rec)
            db.upsert_emulator(snap)
            if not need_cleanup:
                db.insert_action_log(
                    emulator_id=emu_id,
                    worker_id=platform.node(),
                    username=username,
                    level="INFO",
                    event_type="LIFECYCLE",
                    location=Location.MAIN_PAGE,
                    message=f"Emulator {avd_name} booted and ready on {dev.serial}",
                )
            if need_cleanup:
                try:
                    self.manager.delete(avd_name)
                except Exception:
                    pass
        except BaseException as exc:
            try:
                if avd_name in self.manager.avds() or self.manager._avd_dir(avd_name).exists():
                    self.manager.delete(avd_name)
            except Exception:
                pass
            with self._lock:
                if emu_id in self._delete_flags or str(exc) == "DELETE_REQUESTED":
                    rec["action"] = "DELETED"
                    rec["status"] = "Deleted"
                    rec["deleted"] = True
                    rec["serial"] = None
                    rec["final_message"] = "DELETE_REQUESTED"
                    rec["deleted_at"] = rec["deleted_at"] or _now_iso()
                else:
                    rec["action"] = "DELETED"
                    rec["status"] = f"Failed: {exc}"
                    rec["deleted"] = True
                    rec["serial"] = None
                    rec["final_message"] = f"CREATE_FAILED: {exc}"
                    rec["deleted_at"] = _now_iso()
                snap = dict(rec)
            db.upsert_emulator(snap)
            db.insert_action_log(
                emulator_id=emu_id,
                worker_id=platform.node(),
                username=username,
                level="ERROR",
                event_type="LIFECYCLE",
                location=snap.get("location"),
                message=snap.get("final_message") or str(exc),
            )

    def start_action_async(self, emu_id: str, req: ExecuteActionRequest) -> dict:
        merged_params = dict(req.params or {})
        for key in ("username", "message", "question", "count", "nr_of_reels", "min_wait", "max_wait", "wait_time"):
            val = getattr(req, key, None)
            if val is not None and key not in merged_params:
                merged_params[key] = val

        try:
            action_handler = get_action(req.action)
        except AutomationError as exc:
            raise HTTPException(status_code=400, detail=exc.message)

        with self._lock:
            rec = self._records.get(emu_id)
            if not rec:
                raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
            if rec["deleted"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Emulator {emu_id} is deleted (final_message={rec['final_message']})",
                )
            if rec["action"] != "IDLE":
                raise HTTPException(
                    status_code=409,
                    detail=f"Emulator {emu_id} is currently busy ({rec['action']}: {rec['status']})",
                )

            action_id = uuid.uuid4().hex[:10]
            while action_id in self._actions:
                action_id = uuid.uuid4().hex[:10]

            action_record = ActionRecord(
                action_id=action_id,
                emulator_id=emu_id,
                action_type=action_handler.action_name,
                params=merged_params,
                state="RUNNING",
                status="RUNNING",
                progress="Starting action...",
                error=None,
                data={},
                started_at=_now_iso(),
                finished_at=None,
            )
            self._actions[action_id] = action_record
            self._emu_actions.setdefault(emu_id, []).append(action_id)

            rec["action"] = action_handler.action_name
            rec["status"] = "Starting action..."
            rec["last_action"] = action_record.to_dict()
            rec_snap = dict(rec)
            act_snap = action_record.to_dict()

        db.upsert_action(
            act_snap,
            worker_id=rec_snap.get("worker_id") or platform.node(),
            username=rec_snap.get("username"),
            start_location=rec_snap.get("location"),
        )
        db.upsert_emulator(rec_snap)

        thread = threading.Thread(
            target=self._run_action,
            args=(emu_id, action_id, action_handler, merged_params),
            daemon=True,
        )
        thread.start()
        return act_snap

    def _run_action(self, emu_id: str, action_id: str, action_handler, params: dict[str, Any]):
        ctrl = self._get_or_create_controller(emu_id)
        ctrl.current_action_id = action_id
        ctrl.current_action_type = action_handler.action_name
        start_loc = ctrl.location

        def _on_status(st: str):
            self._set_status(emu_id, st)
            act_snap = None
            rec_snap = None
            with self._lock:
                act = self._actions.get(action_id)
                rec = self._records.get(emu_id)
                if act and act.state == "RUNNING":
                    act.progress = st
                    act_snap = act.to_dict()
                    if rec:
                        rec["last_action"] = act_snap
                        rec_snap = dict(rec)
            if act_snap:
                db.upsert_action(
                    act_snap,
                    worker_id=(rec_snap or {}).get("worker_id") or platform.node(),
                    username=(rec_snap or {}).get("username"),
                    start_location=start_loc,
                )

        ctrl._on_status = _on_status

        try:
            result = action_handler.execute(ctrl, params)
            with self._lock:
                act = self._actions[action_id]
                rec = self._records.get(emu_id)
                is_success = result.error is None
                act.state = "COMPLETED" if is_success else "FAILED"
                act.status = result.status
                act.progress = "Completed" if is_success else f"Failed: {result.error}"
                act.error = result.error
                act.data = result.data or {}
                act.finished_at = _now_iso()
                act_snap = act.to_dict()

                if rec and not rec["deleted"] and emu_id not in self._delete_flags:
                    if result.location:
                        rec["location"] = result.location
                    rec["action"] = "IDLE"
                    rec["status"] = "Idle"
                    rec["last_action"] = act_snap
                rec_snap = dict(rec) if rec else None

            db.upsert_action(
                act_snap,
                worker_id=(rec_snap or {}).get("worker_id") or platform.node(),
                username=(rec_snap or {}).get("username"),
                start_location=start_loc,
                end_location=result.location or ctrl.location,
            )
            if rec_snap:
                db.upsert_emulator(rec_snap)
        except BaseException as exc:
            with self._lock:
                act = self._actions[action_id]
                rec = self._records.get(emu_id)
                act.state = "FAILED"
                act.status = getattr(action_handler, "failure_status", "ACTION_FAILED")
                act.progress = f"Failed: {exc}"
                act.error = str(exc)
                act.finished_at = _now_iso()
                act_snap = act.to_dict()

                if rec and not rec["deleted"] and emu_id not in self._delete_flags:
                    rec["action"] = "IDLE"
                    rec["status"] = "Idle"
                    rec["last_action"] = act_snap
                rec_snap = dict(rec) if rec else None

            db.upsert_action(
                act_snap,
                worker_id=(rec_snap or {}).get("worker_id") or platform.node(),
                username=(rec_snap or {}).get("username"),
                start_location=start_loc,
                end_location=ctrl.location,
            )
            if rec_snap:
                db.upsert_emulator(rec_snap)
        finally:
            ctrl.current_action_id = None
            ctrl.current_action_type = None

    def delete_emulator(self, emu_id: str) -> dict:
        with self._lock:
            rec = self._records.get(emu_id)
            if not rec:
                raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
            if rec["deleted"]:
                return self._serialize(rec)
            self._delete_flags.add(emu_id)
            rec["action"] = "DELETING"
            rec["status"] = "Stopping and deleting emulator..."
            avd_name = rec["name"]

        try:
            if avd_name in self.manager.avds() or self.manager._avd_dir(avd_name).exists():
                self.manager.delete(avd_name)
        except Exception:
            pass

        with self._lock:
            self._controllers.pop(emu_id, None)
            rec["action"] = "DELETED"
            rec["status"] = "Deleted"
            rec["deleted"] = True
            rec["serial"] = None
            rec["final_message"] = "DELETE_REQUESTED"
            rec["deleted_at"] = _now_iso()
            snap = self._serialize(rec)
        db.upsert_emulator(snap)
        db.insert_action_log(
            emulator_id=emu_id,
            worker_id=platform.node(),
            username=snap.get("username"),
            level="INFO",
            event_type="LIFECYCLE",
            location=snap.get("location"),
            message=f"Deleted emulator {avd_name}",
        )
        return snap

    def run_shell(self, emu_id: str, command: str, timeout: int = 60) -> dict:
        with self._lock:
            rec = self._records.get(emu_id)
            if not rec:
                raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
            if rec["deleted"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Emulator {emu_id} is deleted (final_message={rec['final_message']})",
                )
            if rec["action"] != "IDLE":
                raise HTTPException(
                    status_code=409,
                    detail=f"Emulator {emu_id} is currently busy ({rec['action']}: {rec['status']})",
                )
            rec["action"] = "RUNNING_SHELL"
            short_cmd = command if len(command) <= 60 else command[:57] + "..."
            rec["status"] = f"Executing: {short_cmd}"
            avd_name = rec["name"]

        try:
            output = self.manager.adb(avd_name, "shell", command, timeout=timeout)
            return {"id": emu_id, "command": command, "output": output}
        except EmulatorError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Shell command failed: {exc}")
        finally:
            with self._lock:
                if not rec["deleted"] and emu_id not in self._delete_flags:
                    rec["action"] = "IDLE"
                    rec["status"] = "Idle"


emu_manager = EmulatorManager(verbose=True)
registry = EmulatorRegistry(emu_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[server] Cleaning up any emulators left from previous run...", flush=True)
    registry.cleanup_previous_run()
    print("[server] Ready.", flush=True)
    yield


app = FastAPI(
    title="Emulator Manager & Automation API",
    description="Local server API and UI to create, inspect, run automation actions, run shell commands, and delete Android emulators.",
    lifespan=lifespan,
)


def _get_git_version() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def _get_system_metrics() -> dict[str, Any]:
    cpu_cores = os.cpu_count() or 1
    ram_total_gb = 0.0
    ram_used_gb = 0.0
    ram_percent = 0.0
    cpu_load_1m = 0.0
    try:
        if hasattr(os, "getloadavg"):
            cpu_load_1m = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            info = {}
            for line in meminfo.read_text().splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = int(parts[1].strip().split()[0])  # kB
                    info[k] = v
            total_kb = info.get("MemTotal", 0)
            avail_kb = info.get("MemAvailable", info.get("MemFree", 0))
            if total_kb > 0:
                ram_total_gb = round(total_kb / (1024 * 1024), 2)
                ram_used_gb = round((total_kb - avail_kb) / (1024 * 1024), 2)
                ram_percent = round(((total_kb - avail_kb) / total_kb) * 100.0, 1)
    except Exception:
        pass
    disk_total_gb = 0.0
    disk_free_gb = 0.0
    try:
        du = shutil.disk_usage(Path(__file__).resolve().parent)
        disk_total_gb = round(du.total / (1024 ** 3), 2)
        disk_free_gb = round(du.free / (1024 ** 3), 2)
    except Exception:
        pass
    # Estimate max capacity (~1 emulator per 3.5GB RAM or env override)
    default_max = max(1, int(ram_total_gb // 3.5)) if ram_total_gb > 0 else 4
    max_emulators = int(os.environ.get("FREYA_MAX_EMULATORS", default_max))
    return {
        "hostname": platform.node(),
        "platform": platform.system().lower(),
        "cpu_cores": cpu_cores,
        "cpu_load_1m": cpu_load_1m,
        "ram_total_gb": ram_total_gb,
        "ram_used_gb": ram_used_gb,
        "ram_percent": ram_percent,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "max_emulators": max_emulators,
        "git_commit": _get_git_version(),
    }


class WorkerUpdateRequest(BaseModel):
    restart_service: bool = Field(default=False, description="Restart worker service after git pull (WARNING: stops active emulators)")


@app.get("/api/health")
def get_health():
    active = registry.list_active()
    metrics = _get_system_metrics()
    return {
        "status": "ONLINE",
        "active_emulators": len(active),
        "idle_emulators": sum(1 for e in active if e.get("action") == "IDLE"),
        "busy_emulators": sum(1 for e in active if e.get("action") != "IDLE"),
        "deleted_emulators": len(registry.list_deleted()),
        **metrics,
    }


@app.post("/api/admin/update")
def admin_update_worker(req: Optional[WorkerUpdateRequest] = None):
    repo_dir = Path(__file__).resolve().parent
    git_output = ""
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        res = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        git_output = (res.stdout + "\n" + res.stderr).strip()
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(repo_dir / "requirements.txt")],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        git_output = f"git update warning: {exc}"

    # Hot-reload db, emumanager, and automation modules in dependency order
    reloaded = []
    for base_mod in ("db", "emumanager"):
        if base_mod in sys.modules:
            try:
                importlib.reload(sys.modules[base_mod])
                reloaded.append(base_mod)
            except Exception:
                pass
    auto_mods = [m for m in sys.modules.keys() if m == "automation" or m.startswith("automation.")]
    auto_mods.sort(
        key=lambda m: (
            0 if "shared_rules" in m else
            1 if m.startswith("automation.common") else
            2 if m.endswith(".rules") else
            3 if m.endswith(".pages") else
            4 if m.endswith(".action") else
            5 if m.startswith("automation.actions") else
            6,
            m,
        )
    )
    for mod_name in auto_mods:
        try:
            importlib.reload(sys.modules[mod_name])
            reloaded.append(mod_name)
        except Exception:
            pass

    # Rebind top-level symbols and clear cached PhoneController instances so new methods take effect immediately
    global PhoneController, get_action, list_supported_actions, Location, AutomationError, ActionRecord
    if "emumanager" in sys.modules:
        try:
            emu_manager.__class__ = sys.modules["emumanager"].EmulatorManager
        except Exception:
            pass
    if "automation" in sys.modules:
        auto_pkg = sys.modules["automation"]
        PhoneController = getattr(auto_pkg, "PhoneController", PhoneController)
        get_action = getattr(auto_pkg, "get_action", get_action)
        list_supported_actions = getattr(auto_pkg, "list_supported_actions", list_supported_actions)
        Location = getattr(auto_pkg, "Location", Location)
        AutomationError = getattr(auto_pkg, "AutomationError", AutomationError)
        ActionRecord = getattr(auto_pkg, "ActionRecord", ActionRecord)
    with registry._lock:
        registry._controllers.clear()

    if req and req.restart_service and platform.system().lower() == "linux":
        threading.Timer(1.0, lambda: subprocess.Popen(["systemctl", "restart", "freya-worker"])).start()

    return {
        "ok": True,
        "git_output": git_output,
        "git_commit": _get_git_version(),
        "reloaded_modules": reloaded,
        "restarting": bool(req and req.restart_service),
    }


@app.get("/api/meta")
def get_meta():
    cached = sorted(p.name for p in emu_manager.apks_dir.glob("*.apk")) if emu_manager.apks_dir.is_dir() else []
    return {
        "profiles": emu_manager.list_profiles(),
        "android_versions": sorted(ANDROID_IMAGES.keys(), reverse=True),
        "cached_apks": cached,
        "actions": list_supported_actions(),
    }


@app.get("/api/actions")
def get_supported_actions():
    return {"actions": list_supported_actions()}


@app.get("/api/actions/{action_id}")
def get_action_status_global(action_id: str):
    act = registry.get_action_record(action_id)
    if not act:
        raise HTTPException(status_code=404, detail=f"No action with id {action_id!r}")
    return act


@app.get("/api/emulators")
def list_emulators():
    return {
        "emulators": registry.list_active(),
        "deleted": registry.list_deleted(),
    }


@app.get("/api/emulators/{emu_id}")
def get_emulator(emu_id: str):
    rec = registry.get(emu_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
    return rec


@app.get("/api/emulators/{emu_id}/message")
def get_emulator_message(emu_id: str):
    rec = registry.get(emu_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
    return {
        "id": rec["id"],
        "deleted": rec["deleted"],
        "location": rec["location"],
        "action": rec["action"],
        "status": rec["status"],
        "final_message": rec["final_message"],
    }


@app.post("/api/emulators", status_code=202)
def create_emulator(req: CreateEmulatorRequest):
    return registry.create_async(req)


@app.delete("/api/emulators/{emu_id}")
def delete_emulator(emu_id: str):
    return registry.delete_emulator(emu_id)


@app.post("/api/emulators/{emu_id}/delete")
def delete_emulator_post(emu_id: str):
    return registry.delete_emulator(emu_id)


@app.post("/api/emulators/{emu_id}/shell")
def run_shell_command(emu_id: str, req: ShellCommandRequest):
    return registry.run_shell(emu_id, req.command, timeout=req.timeout)


@app.get("/api/emulators/{emu_id}/screenshot")
def get_emulator_screenshot(emu_id: str):
    rec = registry.get(emu_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
    if rec["deleted"]:
        raise HTTPException(status_code=409, detail=f"Emulator {emu_id} is deleted")
    try:
        png_bytes = emu_manager.screenshot_bytes(rec["name"], timeout=12)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
    except EmulatorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {exc}")


@app.post("/api/emulators/{emu_id}/input")
def send_emulator_input(emu_id: str, req: DeviceInputRequest):
    rec = registry.get(emu_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"No emulator with id {emu_id!r}")
    if rec["deleted"]:
        raise HTTPException(status_code=409, detail=f"Emulator {emu_id} is deleted")

    avd_name = rec["name"]
    kind = (req.type or "").strip().lower()
    try:
        if kind == "tap":
            if req.x is None or req.y is None:
                raise HTTPException(status_code=400, detail="tap requires x and y")
            emu_manager.adb(avd_name, "shell", f"input tap {int(req.x)} {int(req.y)}", timeout=15)
            return {"ok": True, "type": "tap", "x": int(req.x), "y": int(req.y)}
        elif kind == "swipe":
            if None in (req.x1, req.y1, req.x2, req.y2):
                raise HTTPException(status_code=400, detail="swipe requires x1, y1, x2, y2")
            dur = max(50, min(5000, int(req.duration_ms or 300)))
            emu_manager.adb(
                avd_name,
                "shell",
                f"input swipe {int(req.x1)} {int(req.y1)} {int(req.x2)} {int(req.y2)} {dur}",
                timeout=15,
            )
            return {"ok": True, "type": "swipe", "x1": int(req.x1), "y1": int(req.y1), "x2": int(req.x2), "y2": int(req.y2), "duration_ms": dur}
        elif kind == "key":
            if req.keycode is None:
                raise HTTPException(status_code=400, detail="key requires keycode")
            emu_manager.adb(avd_name, "shell", f"input keyevent {int(req.keycode)}", timeout=15)
            return {"ok": True, "type": "key", "keycode": int(req.keycode)}
        elif kind == "text":
            if not req.text:
                raise HTTPException(status_code=400, detail="text requires non-empty text")
            ctrl = registry._get_or_create_controller(emu_id)
            ctrl.keyboard(req.text)
            return {"ok": True, "type": "text", "text": req.text}
        elif kind == "restart_app":
            ctrl = registry._get_or_create_controller(emu_id)
            ctrl.restart_app(wait_seconds=2.5)
            return {"ok": True, "type": "restart_app", "location": Location.MAIN_PAGE}
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported input type {req.type!r}. Use tap, swipe, key, text, or restart_app.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Input failed: {exc}")


@app.post("/api/emulators/{emu_id}/actions", status_code=202)
def execute_emulator_action(emu_id: str, req: ExecuteActionRequest):
    return registry.start_action_async(emu_id, req)


@app.get("/api/emulators/{emu_id}/actions")
def list_emulator_actions(emu_id: str):
    return {"actions": registry.list_emulator_actions(emu_id)}


@app.get("/api/emulators/{emu_id}/actions/{action_id}")
def get_emulator_action_status(emu_id: str, action_id: str):
    act = registry.get_action_record(action_id)
    if not act or act["emulator_id"] != emu_id:
        raise HTTPException(status_code=404, detail=f"No action {action_id!r} for emulator {emu_id!r}")
    return act


UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Emulator Control Panel</title>
  <style>
    :root {
      --bg: #0f1117;
      --panel: #171b24;
      --panel-alt: #1e2330;
      --border: #2a3142;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
      --purple: #8b5cf6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }
    .container {
      max-width: 1440px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }
    header h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 8px var(--green);
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }
    .card h2 {
      margin: 0 0 16px 0;
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      align-items: end;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .field.wide {
      grid-column: span 2;
    }
    @media (max-width: 680px) {
      .field.wide { grid-column: span 1; }
    }
    label {
      font-size: 12px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    label .req { color: var(--red); }
    input[type="text"], input[type="number"], select {
      background: var(--panel-alt);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 10px;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
      width: 100%;
    }
    input[type="text"]:focus, input[type="number"]:focus, select:focus {
      border-color: var(--accent);
    }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 38px;
      font-size: 14px;
      color: var(--text);
      cursor: pointer;
    }
    button {
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
      white-space: nowrap;
    }
    button:hover { background: var(--accent-hover); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    button.btn-danger {
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
      border: 1px solid rgba(239, 68, 68, 0.35);
      padding: 6px 12px;
      font-size: 13px;
    }
    button.btn-danger:hover {
      background: var(--red);
      color: #fff;
    }
    button.btn-secondary {
      background: var(--panel-alt);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 12px;
      font-size: 13px;
    }
    button.btn-secondary:hover {
      border-color: var(--accent);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    th {
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 600;
    }
    tr:last-child td { border-bottom: none; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .badge-CREATING {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.35);
    }
    .badge-IDLE {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.35);
    }
    .badge-RUNNING {
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
      border: 1px solid rgba(59, 130, 246, 0.35);
    }
    .badge-LOCATION {
      background: rgba(139, 92, 246, 0.15);
      color: #c4b5fd;
      border: 1px solid rgba(139, 92, 246, 0.35);
    }
    .badge-DELETING, .badge-DELETED {
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
      border: 1px solid rgba(239, 68, 68, 0.35);
    }
    .spinner {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
      animation: pulse 1s infinite ease-in-out;
    }
    @keyframes pulse {
      0%, 100% { opacity: 0.3; transform: scale(0.85); }
      50% { opacity: 1; transform: scale(1.15); }
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .muted { color: var(--muted); font-size: 12px; }
    .action-box {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 280px;
    }
    .action-row {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }
    .action-row select {
      width: auto;
      min-width: 170px;
      flex: 1;
    }
    .action-params {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .action-params input {
      flex: 1;
      min-width: 90px;
    }
    .action-result {
      margin-top: 4px;
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      white-space: pre-wrap;
      max-height: 110px;
      overflow-y: auto;
      color: #d1d5db;
    }
    .action-result.ok { border-color: rgba(16, 185, 129, 0.4); }
    .action-result.err { border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; }
    .shell-bar {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .shell-bar input {
      padding: 6px 10px;
      font-size: 12px;
      min-width: 150px;
    }
    .shell-output {
      margin-top: 6px;
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      white-space: pre-wrap;
      max-height: 120px;
      overflow-y: auto;
      color: #d1d5db;
    }
    .toast {
      margin-top: 12px;
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 13px;
      display: none;
    }
    .toast.error {
      display: block;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fca5a5;
    }
    .empty {
      text-align: center;
      padding: 24px;
      color: var(--muted);
      font-size: 14px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1><span class="dot"></span> Emulator Control Panel</h1>
      <div class="muted" id="meta-info">Connected to local API</div>
    </header>

    <div class="card">
      <h2>Create New Emulator</h2>
      <form id="create-form" onsubmit="handleCreate(event)">
        <div class="form-grid">
          <div class="field wide">
            <label>APK Direct Download Link <span class="req">*</span></label>
            <input type="text" id="apk" value="http://89.34.17.131/Files/1430unpinned.apk" placeholder="https://example.com/snapchat.apk" required />
          </div>
          <div class="field">
            <label>Snapchat Username <span class="req">*</span></label>
            <input type="text" id="username" placeholder="e.g. rachelt8687" required />
          </div>
          <div class="field">
            <label>Android Version <span class="req">*</span></label>
            <select id="android" required>
              <option value="16" selected>Android 16</option>
              <option value="15">Android 15</option>
              <option value="14">Android 14</option>
            </select>
          </div>
          <div class="field">
            <label>Device Profile <span class="req">*</span></label>
            <select id="profile" required>
              <option value="a52s" selected>a52s</option>
            </select>
          </div>
          <div class="field">
            <label>Proxy (Optional)</label>
            <input type="text" id="proxy" value="68.183.65.77:37219:geelark:67016a3f075ce9d73f" placeholder="host:port[:user:pass]" />
          </div>
          <div class="field">
            <label class="checkbox-row">
              <input type="checkbox" id="headless" />
              Headless (no window)
            </label>
          </div>
          <div class="field">
            <button type="submit" id="create-btn">Create Emulator</button>
          </div>
        </div>
        <div id="create-error" class="toast error"></div>
      </form>
    </div>

    <div class="card">
      <h2>
        <span>Currently Running Emulators</span>
        <span class="muted" id="active-count">0 active</span>
      </h2>
      <div id="active-container">
        <div class="empty">No running emulators</div>
      </div>
    </div>

    <div class="card">
      <h2>
        <span>Deleted Emulators (Finished)</span>
        <span class="muted" id="deleted-count">0 deleted</span>
      </h2>
      <div id="deleted-container">
        <div class="empty">No deleted emulators in this session</div>
      </div>
    </div>
  </div>

  <script>
    const shellOutputs = {};
    const shellInputs = {};
    const selectedActions = {};
    const actionParamValues = {};

    async function loadMeta() {
      try {
        const res = await fetch('/api/meta');
        if (!res.ok) return;
        const data = await res.json();
        const profileSelect = document.getElementById('profile');
        if (data.profiles && data.profiles.length > 0) {
          const current = profileSelect.value;
          profileSelect.innerHTML = data.profiles
            .map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
            .join('');
          if (data.profiles.includes(current)) profileSelect.value = current;
        }
        const metaEl = document.getElementById('meta-info');
        metaEl.textContent = `Cached APKs: ${data.cached_apks ? data.cached_apks.length : 0}`;
      } catch (e) {}
    }

    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    async function handleCreate(e) {
      e.preventDefault();
      const errEl = document.getElementById('create-error');
      errEl.style.display = 'none';
      const payload = {
        apk: document.getElementById('apk').value.trim(),
        username: document.getElementById('username').value.trim(),
        android: parseInt(document.getElementById('android').value, 10),
        profile: document.getElementById('profile').value,
        proxy: document.getElementById('proxy').value.trim() || null,
        headless: document.getElementById('headless').checked,
      };
      try {
        const res = await fetch('/api/emulators', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          errEl.textContent = data.detail || 'Failed to create emulator';
          errEl.style.display = 'block';
          return;
        }
        await refreshEmulators();
        await loadMeta();
      } catch (err) {
        errEl.textContent = String(err);
        errEl.style.display = 'block';
      }
    }

    async function handleDelete(id) {
      try {
        await fetch(`/api/emulators/${encodeURIComponent(id)}`, { method: 'DELETE' });
        await refreshEmulators();
      } catch (err) {
        alert('Delete failed: ' + err);
      }
    }

    function onActionChange(id) {
      const sel = document.getElementById(`act-sel-${id}`);
      if (!sel) return;
      saveActionParams(id);
      selectedActions[id] = sel.value;
      renderActionParams(id);
    }

    function saveActionParams(id) {
      if (!actionParamValues[id]) actionParamValues[id] = {};
      document.querySelectorAll(`[data-act-param-emu="${id}"]`).forEach(el => {
        actionParamValues[id][el.getAttribute('data-act-param-name')] = el.value;
      });
    }

    function renderActionParams(id) {
      const container = document.getElementById(`act-params-${id}`);
      if (!container) return;
      const act = selectedActions[id] || 'ADD_FRIEND';
      const saved = actionParamValues[id] || {};
      let html = '';

      if (act === 'ADD_FRIEND') {
        const v = saved.username !== undefined ? saved.username : '';
        html = `<input type="text" data-act-param-emu="${id}" data-act-param-name="username" value="${escapeHtml(v)}" placeholder="Target username..." />`;
      } else if (act === 'WATCH_REELS') {
        const c = saved.count !== undefined ? saved.count : '3';
        const minW = saved.min_wait !== undefined ? saved.min_wait : '2';
        const maxW = saved.max_wait !== undefined ? saved.max_wait : '4';
        html = `
          <input type="number" step="1" min="1" data-act-param-emu="${id}" data-act-param-name="count" value="${escapeHtml(c)}" placeholder="Reels" title="Number of reels" />
          <input type="number" step="0.5" min="0" data-act-param-emu="${id}" data-act-param-name="min_wait" value="${escapeHtml(minW)}" placeholder="Min(s)" title="Min wait seconds" />
          <input type="number" step="0.5" min="0" data-act-param-emu="${id}" data-act-param-name="max_wait" value="${escapeHtml(maxW)}" placeholder="Max(s)" title="Max wait seconds" />
        `;
      } else if (act === 'WATCH_COMMENTS_REEL') {
        const w = saved.wait_time !== undefined ? saved.wait_time : '5';
        html = `<input type="number" step="0.5" min="0" data-act-param-emu="${id}" data-act-param-name="wait_time" value="${escapeHtml(w)}" placeholder="Wait seconds..." />`;
      } else if (act === 'SEND_MESSAGE_TO_AI') {
        const m = saved.message !== undefined ? saved.message : '';
        html = `<input type="text" data-act-param-emu="${id}" data-act-param-name="message" value="${escapeHtml(m)}" placeholder="Question for My AI..." />`;
      } else if (act === 'FETCH_FRIENDS') {
        html = `<span class="muted">No parameters required</span>`;
      } else if (act === 'SEND_MESSAGE') {
        const u = saved.username !== undefined ? saved.username : '';
        const m = saved.message !== undefined ? saved.message : '';
        html = `
          <input type="text" data-act-param-emu="${id}" data-act-param-name="username" value="${escapeHtml(u)}" placeholder="Friend username..." />
          <input type="text" data-act-param-emu="${id}" data-act-param-name="message" value="${escapeHtml(m)}" placeholder="Message text..." />
        `;
      }
      container.innerHTML = html;
    }

    async function handleExecuteAction(id) {
      saveActionParams(id);
      const act = selectedActions[id] || 'ADD_FRIEND';
      const params = Object.assign({}, actionParamValues[id] || {});
      try {
        const res = await fetch(`/api/emulators/${encodeURIComponent(id)}/actions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: act, params }),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.detail || 'Failed to start action');
          return;
        }
        await refreshEmulators();
      } catch (err) {
        alert('Action request failed: ' + err);
      }
    }

    async function handleShell(id) {
      const inputEl = document.getElementById(`shell-in-${id}`);
      if (!inputEl) return;
      const cmd = inputEl.value.trim();
      if (!cmd) return;
      shellInputs[id] = cmd;
      shellOutputs[id] = 'Running...';
      renderShellOutput(id);
      try {
        const res = await fetch(`/api/emulators/${encodeURIComponent(id)}/shell`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd }),
        });
        const data = await res.json();
        if (!res.ok) {
          shellOutputs[id] = `Error: ${data.detail || res.statusText}`;
        } else {
          shellOutputs[id] = data.output || '(no output)';
        }
      } catch (err) {
        shellOutputs[id] = `Error: ${err}`;
      }
      await refreshEmulators();
    }

    function renderShellOutput(id) {
      const outEl = document.getElementById(`shell-out-${id}`);
      if (!outEl) return;
      if (shellOutputs[id] !== undefined) {
        outEl.style.display = 'block';
        outEl.textContent = shellOutputs[id];
      } else {
        outEl.style.display = 'none';
      }
    }

    async function refreshEmulators() {
      try {
        document.querySelectorAll('[data-shell-id]').forEach(el => {
          shellInputs[el.getAttribute('data-shell-id')] = el.value;
        });
        renderedActiveIds.forEach(id => saveActionParams(id));

        const res = await fetch('/api/emulators');
        if (!res.ok) return;
        const data = await res.json();
        renderActive(data.emulators || []);
        renderDeleted(data.deleted || []);
      } catch (e) {}
    }

    let renderedActiveIds = [];

    function renderActive(list) {
      document.getElementById('active-count').textContent = `${list.length} active`;
      const container = document.getElementById('active-container');
      if (list.length === 0) {
        renderedActiveIds = [];
        container.innerHTML = '<div class="empty">No running emulators</div>';
        return;
      }

      const currentIds = list.map(e => e.id);
      const sameStructure =
        currentIds.length === renderedActiveIds.length &&
        currentIds.every((id, idx) => id === renderedActiveIds[idx]);

      if (!sameStructure) {
        renderedActiveIds = currentIds;
        const rows = list.map(emu => {
          const savedCmd = shellInputs[emu.id] !== undefined ? shellInputs[emu.id] : 'getprop ro.product.model';
          const selAct = selectedActions[emu.id] || 'ADD_FRIEND';
          selectedActions[emu.id] = selAct;
          return `
            <tr id="row-${escapeHtml(emu.id)}">
              <td class="mono">
                <strong>${escapeHtml(emu.id)}</strong>
                <div class="muted" id="serial-${escapeHtml(emu.id)}"></div>
              </td>
              <td>
                <div><strong>@${escapeHtml(emu.username)}</strong></div>
                <div class="muted">Android ${escapeHtml(emu.android)} &bull; ${escapeHtml(emu.profile)}</div>
              </td>
              <td id="location-cell-${escapeHtml(emu.id)}"></td>
              <td id="action-cell-${escapeHtml(emu.id)}"></td>
              <td id="status-cell-${escapeHtml(emu.id)}"></td>
              <td>
                <div class="action-box">
                  <div class="action-row">
                    <select id="act-sel-${escapeHtml(emu.id)}" onchange="onActionChange('${escapeHtml(emu.id)}')">
                      <option value="ADD_FRIEND" ${selAct === 'ADD_FRIEND' ? 'selected' : ''}>ADD_FRIEND</option>
                      <option value="WATCH_REELS" ${selAct === 'WATCH_REELS' ? 'selected' : ''}>WATCH_REELS</option>
                      <option value="WATCH_COMMENTS_REEL" ${selAct === 'WATCH_COMMENTS_REEL' ? 'selected' : ''}>WATCH_COMMENTS_REEL</option>
                      <option value="SEND_MESSAGE_TO_AI" ${selAct === 'SEND_MESSAGE_TO_AI' ? 'selected' : ''}>SEND_MESSAGE_TO_AI</option>
                      <option value="FETCH_FRIENDS" ${selAct === 'FETCH_FRIENDS' ? 'selected' : ''}>FETCH_FRIENDS</option>
                      <option value="SEND_MESSAGE" ${selAct === 'SEND_MESSAGE' ? 'selected' : ''}>SEND_MESSAGE</option>
                    </select>
                    <button type="button" id="act-btn-${escapeHtml(emu.id)}" onclick="handleExecuteAction('${escapeHtml(emu.id)}')">Execute</button>
                  </div>
                  <div class="action-params" id="act-params-${escapeHtml(emu.id)}"></div>
                  <div class="action-result" id="act-res-${escapeHtml(emu.id)}" style="display: none"></div>
                </div>
              </td>
              <td>
                <div class="shell-bar">
                  <input
                    type="text"
                    id="shell-in-${escapeHtml(emu.id)}"
                    data-shell-id="${escapeHtml(emu.id)}"
                    value="${escapeHtml(savedCmd)}"
                    placeholder="adb shell command..."
                    onkeydown="if(event.key==='Enter'){event.preventDefault();handleShell('${escapeHtml(emu.id)}');}"
                  />
                  <button
                    type="button"
                    id="shell-btn-${escapeHtml(emu.id)}"
                    class="btn-secondary"
                    onclick="handleShell('${escapeHtml(emu.id)}')"
                  >Run</button>
                </div>
                <div
                  id="shell-out-${escapeHtml(emu.id)}"
                  class="shell-output"
                  style="display: none"
                ></div>
              </td>
              <td>
                <button
                  type="button"
                  id="del-btn-${escapeHtml(emu.id)}"
                  class="btn-danger"
                  onclick="handleDelete('${escapeHtml(emu.id)}')"
                >Delete</button>
              </td>
            </tr>
          `;
        }).join('');

        container.innerHTML = `
          <table>
            <thead>
              <tr>
                <th>ID / Serial</th>
                <th>Config</th>
                <th>Location</th>
                <th>Action</th>
                <th>Current Status</th>
                <th>Automation Actions</th>
                <th>Shell Command</th>
                <th>Manage</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        `;

        list.forEach(emu => renderActionParams(emu.id));
      }

      list.forEach(emu => {
        const busy = emu.action !== 'IDLE';
        const serialEl = document.getElementById(`serial-${emu.id}`);
        if (serialEl) serialEl.textContent = emu.serial || emu.name;

        const locCell = document.getElementById(`location-cell-${emu.id}`);
        if (locCell) {
          locCell.innerHTML = `<span class="badge badge-LOCATION">${escapeHtml(emu.location || 'UNKNOWN')}</span>`;
        }

        const badgeClass =
          emu.action === 'IDLE' ? 'badge-IDLE' :
          emu.action === 'CREATING' ? 'badge-CREATING' :
          (emu.action === 'DELETING' || emu.action === 'DELETED') ? 'badge-DELETING' :
          'badge-RUNNING';

        const actionCell = document.getElementById(`action-cell-${emu.id}`);
        if (actionCell) {
          actionCell.innerHTML = `
            <span class="badge ${badgeClass}">
              ${busy ? '<span class="spinner"></span>' : ''}
              ${escapeHtml(emu.action)}
            </span>
          `;
        }

        const statusCell = document.getElementById(`status-cell-${emu.id}`);
        if (statusCell) statusCell.textContent = emu.status;

        const actBtn = document.getElementById(`act-btn-${emu.id}`);
        if (actBtn) actBtn.disabled = busy;

        const actRes = document.getElementById(`act-res-${emu.id}`);
        if (actRes) {
          if (emu.last_action) {
            actRes.style.display = 'block';
            const la = emu.last_action;
            actRes.className = 'action-result ' + (la.state === 'FAILED' ? 'err' : (la.state === 'COMPLETED' ? 'ok' : ''));
            let summary = `[${la.action_type}] status=${la.status}`;
            if (la.state === 'RUNNING') {
              summary += ` (${la.progress})`;
            } else if (la.error) {
              summary += `\nerror: ${la.error}`;
            } else if (la.data && Object.keys(la.data).length > 0) {
              summary += `\ndata: ${JSON.stringify(la.data)}`;
            }
            actRes.textContent = summary;
          } else {
            actRes.style.display = 'none';
          }
        }

        const shellIn = document.getElementById(`shell-in-${emu.id}`);
        if (shellIn) shellIn.disabled = busy;

        const shellBtn = document.getElementById(`shell-btn-${emu.id}`);
        if (shellBtn) shellBtn.disabled = busy;

        const delBtn = document.getElementById(`del-btn-${emu.id}`);
        if (delBtn) delBtn.disabled = emu.action === 'DELETING';

        renderShellOutput(emu.id);
      });
    }

    function renderDeleted(list) {
      document.getElementById('deleted-count').textContent = `${list.length} deleted`;
      const container = document.getElementById('deleted-container');
      if (list.length === 0) {
        container.innerHTML = '<div class="empty">No deleted emulators in this session</div>';
        return;
      }
      const rows = list.slice().reverse().map(emu => `
        <tr>
          <td class="mono"><strong>${escapeHtml(emu.id)}</strong></td>
          <td>@${escapeHtml(emu.username)} <span class="muted">(Android ${escapeHtml(emu.android)}, ${escapeHtml(emu.profile)})</span></td>
          <td><span class="badge badge-LOCATION">${escapeHtml(emu.location || 'UNKNOWN')}</span></td>
          <td><span class="badge badge-DELETED">${escapeHtml(emu.final_message || 'DELETE_REQUESTED')}</span></td>
          <td class="muted">${escapeHtml(emu.deleted_at || '')}</td>
        </tr>
      `).join('');

      container.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Instance</th>
              <th>Last Location</th>
              <th>Final Message</th>
              <th>Deleted At</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    loadMeta();
    refreshEmulators();
    setInterval(refreshEmulators, 1000);
    setInterval(loadMeta, 5000);
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return UI_HTML


def _kill_existing_server(port: int):
    import os
    import re
    import subprocess
    import time
    from emumanager import _port_free
    if _port_free(port):
        return
    my_pid = os.getpid()
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            if re.fullmatch(r"\d+", parts[4]) and int(parts[4]) != my_pid and int(parts[4]) > 0:
                subprocess.run(["taskkill", "/PID", parts[4], "/T", "/F"], capture_output=True)
    for _ in range(10):
        if _port_free(port):
            break
        time.sleep(0.3)


def run_server(host: str = "127.0.0.1", port: int = 8000):
    _kill_existing_server(port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Emulator Manager HTTP API and Web UI server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
