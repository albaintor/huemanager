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
    delete_empty_room,
    inventory_tree,
    load_snapshot,
    room_deletion_impact,
    save_snapshot,
)

app = FastAPI(title="HueManager", version="0.5.0")
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


class DestinationRequest(BaseModel):
    destination: str


class ApplyRequest(DestinationRequest):
    prune_external: bool = True


class RestoreRequest(DestinationRequest):
    prune_external: bool = False


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


@app.get("/api/snapshots/{snapshot_id}")
def snapshot_details(snapshot_id: str) -> dict:
    snapshot = _load_snapshot(snapshot_id)
    return {
        "id": snapshot_id,
        "created_at": snapshot.get("created_at"),
        "rooms": [room.get("metadata", {}).get("name") for room in snapshot.get("rooms", [])],
        "dependencies": snapshot.get("dependencies", []),
        "behavior_dependencies": snapshot.get("behavior_dependencies", []),
    }


@app.post("/api/snapshots/{snapshot_id}/plan")
def plan_snapshot(snapshot_id: str, request: DestinationRequest) -> dict:
    try:
        return analyse(_load_snapshot(snapshot_id), _client(request.destination))
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/snapshots/{snapshot_id}/apply")
def apply_web_snapshot(snapshot_id: str, request: ApplyRequest) -> dict:
    try:
        return apply_snapshot(
            _load_snapshot(snapshot_id),
            _client(request.destination),
            prune_external=request.prune_external,
        )
    except MigrationError as exc:
        raise _api_error(exc) from exc
    except Exception as exc:
        raise _api_error(exc) from exc


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    uvicorn.run("huemanager.web:app", host=host, port=port, reload=False)
