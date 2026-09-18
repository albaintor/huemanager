from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import HueBridgeClient
from .migration import (
    CLIP_SENSOR_TYPES,
    MigrationError,
    analyse,
    apply_snapshot,
    create_selection_snapshot,
)

BACKUP_SCHEMA = 1
API_PATH_RE = re.compile(r"(/api/)[^/]+/")


def _redact_api_credentials(value: Any) -> Any:
    if isinstance(value, str):
        return API_PATH_RE.sub(r"\1__REDACTED__/", value)
    if isinstance(value, list):
        return [_redact_api_credentials(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_api_credentials(child)
            for key, child in value.items()
        }
    return value


def _redact_v1_credentials(value: Any) -> Any:
    if isinstance(value, str):
        return API_PATH_RE.sub(r"\1__REDACTED__/", value)
    if isinstance(value, list):
        return [_redact_v1_credentials(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                "__REDACTED__"
                if key == "owner" and isinstance(child, str)
                else _redact_v1_credentials(child)
            )
            for key, child in value.items()
        }
    return value


def create_bridge_backup(client: HueBridgeClient) -> dict:
    """Capture a raw bridge dump plus a portable logical restore snapshot."""
    source_v1 = client.v1_all()
    raw_v2 = client.v2_resources()

    # API usernames are authentication credentials. Keep them out of both the
    # raw archive and portable restore payload.
    raw_v1 = _redact_v1_credentials(copy.deepcopy(source_v1))
    config_for_archive = raw_v1.get("config", {})
    whitelist = config_for_archive.pop("whitelist", None)
    if whitelist is not None:
        config_for_archive["whitelist_redacted"] = {
            "count": len(whitelist),
            "reason": "Hue API usernames are credentials and are not backed up",
        }

    room_names = [
        resource.get("metadata", {}).get("name")
        for resource in raw_v2
        if resource.get("type") == "room" and resource.get("metadata", {}).get("name")
    ]

    if room_names:
        logical = create_selection_snapshot(client, room_names)
    else:
        config = source_v1.get("config", {})
        logical = {
            "schema": 3,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_bridge": {
                key: config.get(key)
                for key in ("name", "bridgeid", "modelid", "swversion")
            },
            "rooms": [],
            "devices": [],
            "scenes": [],
            "behavior_instances": [],
            "behavior_scripts": {},
            "v2_references": {},
            "v1": {
                "lights": {},
                "sensors": {},
                "virtual_sensors": {},
                "rules": {},
                "schedules": {},
                "resourcelinks": {},
            },
            "dependencies": [],
            "behavior_dependencies": [],
        }

    by_id = {
        resource["id"]: resource
        for resource in raw_v2
        if resource.get("id")
    }

    # A full bridge backup must include devices that are not assigned to a room.
    devices: list[dict] = []
    for resource in raw_v2:
        if resource.get("type") != "device":
            continue
        device = copy.deepcopy(resource)
        device["services_expanded"] = [
            copy.deepcopy(by_id[service["rid"]])
            for service in resource.get("services", [])
            if service.get("rid") in by_id
        ]
        devices.append(device)

    physical_sensors: dict[str, dict] = {}
    virtual_sensors: dict[str, dict] = {}
    for sensor_id, sensor in source_v1.get("sensors", {}).items():
        if sensor.get("type") in CLIP_SENSOR_TYPES:
            virtual_sensors[sensor_id] = copy.deepcopy(sensor)
        elif sensor.get("uniqueid"):
            physical_sensors[sensor_id] = copy.deepcopy(sensor)

    logical["devices"] = devices
    logical["scenes"] = [
        copy.deepcopy(resource)
        for resource in raw_v2
        if resource.get("type") == "scene"
    ]
    logical["zones"] = [
        copy.deepcopy(resource)
        for resource in raw_v2
        if resource.get("type") == "zone"
    ]
    logical["behavior_instances"] = [
        copy.deepcopy(resource)
        for resource in raw_v2
        if resource.get("type") == "behavior_instance"
    ]
    logical["behavior_scripts"] = {
        resource["id"]: copy.deepcopy(resource)
        for resource in raw_v2
        if resource.get("type") == "behavior_script" and resource.get("id")
    }
    logical["v2_references"] = {
        resource["id"]: copy.deepcopy(resource)
        for resource in raw_v2
        if resource.get("id")
    }

    logical_v1 = logical.setdefault("v1", {})
    logical_v1["lights"] = copy.deepcopy(source_v1.get("lights", {}))
    logical_v1["sensors"] = physical_sensors
    logical_v1["virtual_sensors"] = virtual_sensors
    logical_v1["rules"] = copy.deepcopy(source_v1.get("rules", {}))
    logical_v1["schedules"] = _redact_api_credentials(
        copy.deepcopy(source_v1.get("schedules", {}))
    )
    logical_v1["resourcelinks"] = copy.deepcopy(source_v1.get("resourcelinks", {}))

    # V1 owner fields inside the logical payload are client credentials, while
    # v2 owner objects are resource links. Redact only the v1 branch here.
    logical["v1"] = _redact_v1_credentials(logical.get("v1", {}))
    logical = _redact_api_credentials(logical)

    config = source_v1.get("config", {})
    return {
        "backup_schema": BACKUP_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_bridge": {
            key: config.get(key)
            for key in ("name", "bridgeid", "modelid", "swversion", "apiversion")
        },
        "raw": {
            "clip_v1": raw_v1,
            "clip_v2_resources": raw_v2,
        },
        "logical_restore": logical,
        "restore_scope": {
            "physical_pairing": False,
            "network_key": False,
            "rooms": True,
            "zones": True,
            "device_names": True,
            "scenes": True,
            "smart_scenes": False,
            "behavior_instances": True,
            "clip_virtual_sensors": True,
            "rules": True,
            "schedules": True,
            "resourcelinks": True,
        },
    }


def save_bridge_backup(backup: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(backup, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_bridge_backup(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("backup_schema") != BACKUP_SCHEMA:
        raise MigrationError(
            f"Unsupported bridge backup schema: {payload.get('backup_schema')!r}"
        )
    if "logical_restore" not in payload or "raw" not in payload:
        raise MigrationError("Invalid HueManager bridge backup")
    return payload


def backup_summary(backup: dict) -> dict:
    logical = backup.get("logical_restore", {})
    raw_v1 = backup.get("raw", {}).get("clip_v1", {})
    return {
        "created_at": backup.get("created_at"),
        "source_bridge": backup.get("source_bridge"),
        "lights": len(raw_v1.get("lights", {})),
        "sensors": len(raw_v1.get("sensors", {})),
        "rooms": len(logical.get("rooms", [])),
        "zones": len(logical.get("zones", [])),
        "scenes": len(logical.get("scenes", [])),
        "rules": len(raw_v1.get("rules", {})),
        "schedules": len(raw_v1.get("schedules", {})),
        "behavior_instances": len(logical.get("behavior_instances", [])),
        "restore_scope": backup.get("restore_scope", {}),
    }


def analyse_bridge_restore(backup: dict, client: HueBridgeClient) -> dict:
    result = analyse(
        backup["logical_restore"],
        client,
        allow_same_bridge=True,
    )
    result["backup"] = backup_summary(backup)
    result["requires_physical_repairing"] = True
    return result


def restore_bridge_backup(
    backup: dict,
    client: HueBridgeClient,
    *,
    prune_external: bool = False,
) -> dict:
    result = apply_snapshot(
        backup["logical_restore"],
        client,
        prune_external=prune_external,
        allow_same_bridge=True,
    )
    result["backup"] = backup_summary(backup)
    result["raw_archive_preserved"] = True
    result["physical_pairing_restored"] = False
    return result
