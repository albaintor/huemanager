from __future__ import annotations

import re
import uuid
from importlib.resources import files
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .client import HueBridgeClient
from .config import BridgeProfile, ConfigStore
from .migration import (
    MigrationError,
    analyse,
    apply_snapshot,
    create_selection_snapshot,
    inventory_tree,
    load_snapshot,
    save_snapshot,
)

app = FastAPI(title="HueManager", version="0.2.0")
SNAPSHOT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class PairRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    host: str = Field(min_length=1, max_length=255)
    verify_tls: bool = False


class SnapshotRequest(BaseModel):
    source: str
    rooms: list[str] = Field(min_length=1)


class DestinationRequest(BaseModel):
    destination: str


class ApplyRequest(DestinationRequest):
    prune_external: bool = True


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


def _api_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return files("huemanager.webapp").joinpath("index.html").read_text(encoding="utf-8")


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


@app.post("/api/snapshots")
def create_web_snapshot(request: SnapshotRequest) -> dict:
    try:
        snapshot = create_selection_snapshot(_client(request.source), request.rooms)
        snapshot_id = uuid.uuid4().hex
        save_snapshot(snapshot, _snapshot_path(snapshot_id))
        external = [dep for dep in snapshot.get("dependencies", []) if dep.get("external")]
        return {
            "id": snapshot_id,
            "rooms": request.rooms,
            "devices": len(snapshot.get("devices", [])),
            "scenes": len(snapshot.get("scenes", [])),
            "rules": len(snapshot.get("v1", {}).get("rules", {})),
            "virtual_sensors": len(snapshot.get("v1", {}).get("virtual_sensors", {})),
            "external_dependencies": external,
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
