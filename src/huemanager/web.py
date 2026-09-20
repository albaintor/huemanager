from __future__ import annotations

import re
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .apple_home import (
    build_apple_home_sync_plan,
    get_room_map,
    load_apple_home_state,
    record_sync_result,
    save_apple_home_state,
    store_inventory,
    store_room_map,
)
from .backup import (
    analyse_bridge_restore,
    backup_summary,
    create_bridge_backup,
    load_bridge_backup,
    restore_bridge_backup,
    save_bridge_backup,
)
from .client import HueApiError, HueBridgeClient
from .config import BridgeProfile, ConfigStore
from .migration import (
    MigrationError,
    analyse,
    apply_snapshot,
    audit_bridge,
    create_selection_snapshot,
    delete_audit_issue,
    delete_audit_issues,
    delete_empty_room,
    inventory_tree,
    load_snapshot,
    room_deletion_impact,
    save_snapshot,
)
from .session import (
    load_migration_session,
    new_migration_session,
    record_plan,
    record_restore,
    record_search,
    record_source_release,
    release_source_resources,
    save_migration_session,
    session_summary,
)

app = FastAPI(title="HueManager", version="0.7.0")
SNAPSHOT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
BACKUP_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class PairRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    host: str = Field(min_length=1, max_length=255)
    verify_tls: bool = False


class SnapshotRequest(BaseModel):
    source: str
    rooms: list[str] = Field(min_length=1)


class BackupRequest(BaseModel):
    bridge: str


class ImportBackupRequest(BaseModel):
    backup: dict[str, Any]


class SourceRequest(BaseModel):
    source: str


class DestinationRequest(BaseModel):
    destination: str


class ApplyRequest(DestinationRequest):
    prune_external: bool = True
    force_partial: bool = False


class RestoreRequest(DestinationRequest):
    prune_external: bool = False


class AuditCleanupRequest(BaseModel):
    issue_ids: list[str] = Field(min_length=1, max_length=200)
    force_risky: bool = False


class AppleHomeInventoryRequest(BaseModel):
    home: dict[str, Any]
    rooms: list[dict[str, Any]] = Field(default_factory=list)
    accessories: list[dict[str, Any]] = Field(default_factory=list)


class AppleHomeRoomMapRequest(BaseModel):
    home_id: str = Field(min_length=1)
    room_map: dict[str, str] = Field(default_factory=dict)


class AppleHomeSyncResultRequest(BaseModel):
    home_id: str
    bridge_profile: str
    moved: int = 0
    failed: list[dict[str, Any]] = Field(default_factory=list)


def _store() -> ConfigStore:
    return ConfigStore()


def _client(name: str) -> HueBridgeClient:
    try:
        return HueBridgeClient(_store().get_bridge(name))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _snapshot_dir() -> Path:
    path = _store().path.parent / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_path(snapshot_id: str) -> Path:
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise HTTPException(status_code=400, detail="Invalid snapshot id")
    return _snapshot_dir() / f"{snapshot_id}.json"


def _load_snapshot(snapshot_id: str) -> dict:
    path = _snapshot_path(snapshot_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return load_snapshot(path)


def _session_dir() -> Path:
    path = _store().path.parent / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(snapshot_id: str) -> Path:
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise HTTPException(status_code=400, detail="Invalid snapshot id")
    return _session_dir() / f"{snapshot_id}.json"


def _load_session(snapshot_id: str, *, source_profile: str | None = None) -> dict:
    return load_migration_session(
        _session_path(snapshot_id),
        source_profile=source_profile,
    )


def _save_session(snapshot_id: str, session: dict) -> None:
    save_migration_session(session, _session_path(snapshot_id))


def _backup_dir() -> Path:
    path = _store().path.parent / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_path(backup_id: str) -> Path:
    if not BACKUP_ID_RE.fullmatch(backup_id):
        raise HTTPException(status_code=400, detail="Invalid backup id")
    return _backup_dir() / f"{backup_id}.json"


def _load_backup(backup_id: str) -> dict:
    path = _backup_path(backup_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return load_bridge_backup(path)


def _apple_home_path() -> Path:
    return _store().path.parent / "apple-home.json"


def _load_apple_home() -> dict:
    return load_apple_home_state(_apple_home_path())


def _save_apple_home(state: dict) -> None:
    save_apple_home_state(state, _apple_home_path())


def _api_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return files("huemanager.webapp").joinpath("index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/bridges")
def bridges() -> dict:
    return {
        "bridges": [
            {"name": name, "host": profile.host, "verify_tls": profile.verify_tls}
            for name, profile in _store().list_bridges().items()
        ]
    }


@app.get("/api/discover")
def discover() -> dict:
    try:
        return {"bridges": HueBridgeClient.discover()}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/pair")
def pair(request: PairRequest) -> dict:
    try:
        credentials = HueBridgeClient.pair(
            request.host,
            device_type="huemanager#web",
            verify_tls=request.verify_tls,
        )
        _store().save_bridge(
            request.name,
            BridgeProfile(
                host=request.host,
                app_key=credentials["username"],
                client_key=credentials.get("clientkey"),
                verify_tls=request.verify_tls,
            ),
        )
        tree = inventory_tree(_client(request.name))
        return {
            "ok": True,
            "bridge": {
                "name": request.name,
                "host": request.host,
                "info": tree.get("bridge", {}),
            },
        }
    except Exception as exc:
        raise _api_error(exc) from exc



@app.get("/api/apple-home")
def apple_home_status() -> dict:
    state = _load_apple_home()
    inventory = state.get("inventory")
    return {
        "connected": bool(inventory),
        "inventory": inventory,
        "last_sync": state.get("last_sync"),
    }


@app.post("/api/apple-home/inventory")
def update_apple_home_inventory(request: AppleHomeInventoryRequest) -> dict:
    try:
        state = store_inventory(_load_apple_home(), request.model_dump())
        _save_apple_home(state)
        inventory = state["inventory"]
        return {
            "ok": True,
            "home": inventory.get("home"),
            "rooms": len(inventory.get("rooms", [])),
            "accessories": len(inventory.get("accessories", [])),
            "received_at": inventory.get("received_at"),
        }
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/apple-home/sync-result")
def update_apple_home_sync_result(request: AppleHomeSyncResultRequest) -> dict:
    try:
        state = record_sync_result(_load_apple_home(), request.model_dump())
        _save_apple_home(state)
        return {"ok": True, "last_sync": state.get("last_sync")}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/bridges/{bridge_name}/apple-home/plan")
def apple_home_plan(bridge_name: str) -> dict:
    try:
        state = _load_apple_home()
        inventory = state.get("inventory")
        if not inventory:
            raise MigrationError(
                "No Apple Home inventory available. Open HueManager Home Sync on an Apple device first."
            )
        home_id = str((inventory.get("home") or {}).get("id") or "")
        room_map = get_room_map(state, bridge_name, home_id)
        return build_apple_home_sync_plan(
            inventory_tree(_client(bridge_name)),
            inventory,
            room_map=room_map,
        )
    except Exception as exc:
        raise _api_error(exc) from exc


@app.put("/api/bridges/{bridge_name}/apple-home/room-map")
def update_apple_home_room_map(
    bridge_name: str,
    request: AppleHomeRoomMapRequest,
) -> dict:
    try:
        state = store_room_map(
            _load_apple_home(),
            bridge_name,
            request.home_id,
            request.room_map,
        )
        _save_apple_home(state)
        inventory = state.get("inventory")
        if not inventory:
            return {"ok": True, "room_map": request.room_map}
        plan = build_apple_home_sync_plan(
            inventory_tree(_client(bridge_name)),
            inventory,
            room_map=get_room_map(state, bridge_name, request.home_id),
        )
        return {"ok": True, "room_map": request.room_map, "plan": plan}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/bridges/{bridge_name}/tree")
def bridge_tree(bridge_name: str) -> dict:
    try:
        return inventory_tree(_client(bridge_name))
    except Exception as exc:
        raise _api_error(exc) from exc



@app.get("/api/bridges/{bridge_name}/audit")
def bridge_audit(bridge_name: str) -> dict:
    try:
        return audit_bridge(_client(bridge_name))
    except (
        MigrationError,
        HueApiError,
        OSError,
        ValueError,
        KeyError,
        IndexError,
    ) as exc:
        raise _api_error(exc) from exc


@app.delete("/api/bridges/{bridge_name}/audit/{issue_id}")
def cleanup_bridge_issue(
    bridge_name: str,
    issue_id: str,
    force: bool = False,
) -> dict:
    try:
        return delete_audit_issue(
            _client(bridge_name),
            issue_id,
            force=force,
        )
    except (
        MigrationError,
        HueApiError,
        OSError,
        ValueError,
        KeyError,
        IndexError,
    ) as exc:
        raise _api_error(exc) from exc


@app.post("/api/bridges/{bridge_name}/audit/cleanup")
def cleanup_bridge_issues(
    bridge_name: str,
    request: AuditCleanupRequest,
) -> dict:
    try:
        return delete_audit_issues(
            _client(bridge_name),
            request.issue_ids,
            force_risky=request.force_risky,
        )
    except (
        MigrationError,
        HueApiError,
        OSError,
        ValueError,
        KeyError,
        IndexError,
    ) as exc:
        raise _api_error(exc) from exc


@app.get("/api/bridges/{bridge_name}/rooms/{room_id}/delete-impact")
def room_delete_impact(bridge_name: str, room_id: str) -> dict:
    try:
        return room_deletion_impact(_client(bridge_name), room_id)
    except (MigrationError, HueApiError, OSError, ValueError, KeyError, IndexError) as exc:
        raise _api_error(exc) from exc


@app.delete("/api/bridges/{bridge_name}/rooms/{room_id}")
def delete_room(
    bridge_name: str,
    room_id: str,
    confirm_dependencies: bool = False,
) -> dict:
    try:
        return delete_empty_room(
            _client(bridge_name),
            room_id,
            confirm_dependencies=confirm_dependencies,
        )
    except (MigrationError, HueApiError, OSError, ValueError, KeyError, IndexError) as exc:
        raise _api_error(exc) from exc


@app.post("/api/bridges/{bridge_name}/search/{kind}")
def search_devices(bridge_name: str, kind: str) -> dict:
    client = _client(bridge_name)
    try:
        if kind == "lights":
            result = client.v1_post("/lights", {})
        elif kind == "sensors":
            result = client.v1_post("/sensors", {})
        else:
            raise HTTPException(status_code=404, detail="Use lights or sensors")
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/backups")
def list_backups() -> dict:
    items = []
    for path in _backup_dir().glob("*.json"):
        try:
            backup = load_bridge_backup(path)
            items.append(
                {
                    "id": path.stem,
                    **backup_summary(backup),
                }
            )
        except (MigrationError, OSError, ValueError):
            items.append(
                {
                    "id": path.stem,
                    "invalid": True,
                    "created_at": "",
                }
            )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"backups": items}


@app.post("/api/backups")
def create_web_backup(request: BackupRequest) -> dict:
    try:
        backup = create_bridge_backup(_client(request.bridge))
        backup_id = uuid.uuid4().hex
        save_bridge_backup(backup, _backup_path(backup_id))
        return {"id": backup_id, **backup_summary(backup)}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/backups/import")
def import_backup(request: ImportBackupRequest) -> dict:
    try:
        payload = request.backup
        if payload.get("backup_schema") != 1:
            raise MigrationError("Unsupported or invalid HueManager backup")
        backup_id = uuid.uuid4().hex
        save_bridge_backup(payload, _backup_path(backup_id))
        # Re-read through the normal validator before exposing it.
        backup = load_bridge_backup(_backup_path(backup_id))
        return {"id": backup_id, **backup_summary(backup)}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/backups/{backup_id}")
def backup_details(backup_id: str) -> dict:
    backup = _load_backup(backup_id)
    return {"id": backup_id, **backup_summary(backup)}


@app.get("/api/backups/{backup_id}/download")
def download_backup(backup_id: str) -> FileResponse:
    path = _backup_path(backup_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"huemanager-backup-{backup_id}.json",
    )


@app.post("/api/backups/{backup_id}/plan")
def plan_backup_restore(backup_id: str, request: DestinationRequest) -> dict:
    try:
        return analyse_bridge_restore(
            _load_backup(backup_id),
            _client(request.destination),
        )
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/backups/{backup_id}/restore")
def restore_backup(backup_id: str, request: RestoreRequest) -> dict:
    try:
        return restore_bridge_backup(
            _load_backup(backup_id),
            _client(request.destination),
            prune_external=request.prune_external,
        )
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/snapshots")
def create_web_snapshot(request: SnapshotRequest) -> dict:
    try:
        snapshot = create_selection_snapshot(_client(request.source), request.rooms)
        snapshot_id = uuid.uuid4().hex
        save_snapshot(snapshot, _snapshot_path(snapshot_id))
        _save_session(snapshot_id, new_migration_session(request.source))
        external = [dep for dep in snapshot.get("dependencies", []) if dep.get("external")]
        external_v2 = [
            dep for dep in snapshot.get("behavior_dependencies", []) if dep.get("external")
        ]
        return {
            "id": snapshot_id,
            "rooms": request.rooms,
            "devices": len(snapshot.get("devices", [])),
            "scenes": len(snapshot.get("scenes", [])),
            "rules": len(snapshot.get("v1", {}).get("rules", {})),
            "virtual_sensors": len(snapshot.get("v1", {}).get("virtual_sensors", {})),
            "resourcelinks": len(snapshot.get("v1", {}).get("resourcelinks", {})),
            "entertainment_configurations": len(
                snapshot.get("entertainment_configurations", [])
            ),
            "behavior_instances": len(snapshot.get("behavior_instances", [])),
            "external_dependencies": external,
            "external_behavior_dependencies": external_v2,
        }
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/snapshots")
def list_snapshots() -> dict:
    items = []
    for path in _snapshot_dir().glob("*.json"):
        try:
            snapshot = load_snapshot(path)
            session = _load_session(path.stem)
            items.append(
                {
                    "id": path.stem,
                    "created_at": snapshot.get("created_at"),
                    "source_bridge": snapshot.get("source_bridge", {}),
                    "rooms": [
                        room.get("metadata", {}).get("name")
                        for room in snapshot.get("rooms", [])
                    ],
                    "devices": len(snapshot.get("devices", [])),
                    "session": session_summary(session),
                }
            )
        except (MigrationError, OSError, ValueError):
            items.append({"id": path.stem, "invalid": True, "created_at": ""})
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"snapshots": items}


@app.get("/api/snapshots/{snapshot_id}")
def snapshot_details(snapshot_id: str) -> dict:
    snapshot = _load_snapshot(snapshot_id)
    session = _load_session(snapshot_id)
    return {
        "id": snapshot_id,
        "created_at": snapshot.get("created_at"),
        "rooms": [room.get("metadata", {}).get("name") for room in snapshot.get("rooms", [])],
        "devices": len(snapshot.get("devices", [])),
        "dependencies": snapshot.get("dependencies", []),
        "behavior_dependencies": snapshot.get("behavior_dependencies", []),
        "session": session_summary(session),
    }


@app.post("/api/snapshots/{snapshot_id}/release-source")
def release_snapshot_source(snapshot_id: str, request: SourceRequest) -> dict:
    try:
        snapshot = _load_snapshot(snapshot_id)
        session = _load_session(snapshot_id, source_profile=request.source)
        session["source_profile"] = request.source
        release = release_source_resources(snapshot, _client(request.source))
        session = record_source_release(session, release)
        _save_session(snapshot_id, session)
        return {"release": release, "session": session_summary(session)}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/snapshots/{snapshot_id}/search/{kind}")
def search_snapshot_devices(snapshot_id: str, kind: str, request: DestinationRequest) -> dict:
    try:
        if kind not in {"lights", "sensors"}:
            raise MigrationError("Use lights or sensors")
        client = _client(request.destination)
        result = client.v1_post(f"/{kind}", {})
        session = record_search(
            _load_session(snapshot_id),
            request.destination,
            kind,
        )
        _save_session(snapshot_id, session)
        return {"ok": True, "result": result, "session": session_summary(session)}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/snapshots/{snapshot_id}/plan")
def plan_snapshot(snapshot_id: str, request: DestinationRequest) -> dict:
    try:
        result = analyse(_load_snapshot(snapshot_id), _client(request.destination))
        session = record_plan(
            _load_session(snapshot_id),
            request.destination,
            result,
        )
        _save_session(snapshot_id, session)
        result["session"] = session_summary(session)
        return result
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/snapshots/{snapshot_id}/apply")
def apply_web_snapshot(snapshot_id: str, request: ApplyRequest) -> dict:
    try:
        snapshot = _load_snapshot(snapshot_id)
        result = apply_snapshot(
            snapshot,
            _client(request.destination),
            prune_external=request.prune_external,
            force_partial=request.force_partial,
        )
        session = record_restore(
            _load_session(snapshot_id),
            request.destination,
            result,
        )
        _save_session(snapshot_id, session)
        result["session"] = session_summary(session)
        return result
    except MigrationError as exc:
        raise _api_error(exc) from exc
    except Exception as exc:
        raise _api_error(exc) from exc


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    uvicorn.run("huemanager.web:app", host=host, port=port, reload=False)
