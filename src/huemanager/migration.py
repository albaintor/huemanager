from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .client import HueBridgeClient

REF_RE = re.compile(
    r"/(lights|sensors|groups|scenes|rules|schedules|resourcelinks)/(\w+)"
)


class MigrationError(RuntimeError):
    pass


def _resource_index(resources: Iterable[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in resources if r.get("id")}


def _id_v1_index(resources: Iterable[dict]) -> dict[str, dict]:
    return {r["id_v1"]: r for r in resources if r.get("id_v1")}


def _uniqueid_index(section: dict[str, dict], prefix: str) -> dict[str, str]:
    return {
        str(value["uniqueid"]).lower(): f"/{prefix}/{rid}"
        for rid, value in section.items()
        if value.get("uniqueid")
    }


def _parse_v1_path(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/(lights|sensors|groups|scenes)/(\w+)", path)
    return (match.group(1), match.group(2)) if match else None


def _extract_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        refs.update(f"/{kind}/{rid}" for kind, rid in REF_RE.findall(value))
    elif isinstance(value, dict):
        for child in value.values():
            refs.update(_extract_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_extract_refs(child))
    return refs


def _selected_v1_paths(room: dict, devices: list[dict], scenes: list[dict]) -> set[str]:
    paths: set[str] = set()
    if room.get("id_v1"):
        paths.add(room["id_v1"])
    for device in devices:
        for service in device.get("services_expanded", []):
            if service.get("id_v1"):
                paths.add(service["id_v1"])
    for scene in scenes:
        if scene.get("id_v1"):
            paths.add(scene["id_v1"])
    return paths


def create_snapshot(client: HueBridgeClient, room_name: str) -> dict:
    resources = client.v2_resources()
    by_id = _resource_index(resources)
    matches = [
        r
        for r in resources
        if r.get("type") == "room" and r.get("metadata", {}).get("name") == room_name
    ]
    if not matches:
        raise MigrationError(f"Room not found: {room_name}")
    if len(matches) > 1:
        raise MigrationError(f"Multiple rooms named {room_name!r}; rename one before migration")
    room = copy.deepcopy(matches[0])

    devices: list[dict] = []
    for child in room.get("children", []):
        if child.get("rtype") != "device":
            continue
        source = by_id.get(child.get("rid"))
        if not source:
            continue
        device = copy.deepcopy(source)
        device["services_expanded"] = [
            copy.deepcopy(by_id[ref["rid"]])
            for ref in source.get("services", [])
            if ref.get("rid") in by_id
        ]
        devices.append(device)

    scenes = [
        copy.deepcopy(r)
        for r in resources
        if r.get("type") == "scene" and r.get("group", {}).get("rid") == room.get("id")
    ]

    v1 = client.v1_all()
    selected_paths = _selected_v1_paths(room, devices, scenes)
    selected_v1: dict[str, dict] = {"lights": {}, "sensors": {}}
    for path in selected_paths:
        parsed = _parse_v1_path(path)
        if not parsed:
            continue
        section, rid = parsed
        if section in selected_v1 and rid in v1.get(section, {}):
            selected_v1[section][rid] = copy.deepcopy(v1[section][rid])

    rules = {
        rid: copy.deepcopy(rule)
        for rid, rule in v1.get("rules", {}).items()
        if _extract_refs(rule) & selected_paths
    }
    config = v1.get("config", {})
    return {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_bridge": {
            key: config.get(key)
            for key in ("name", "bridgeid", "modelid", "swversion")
        },
        "room": room,
        "devices": devices,
        "scenes": scenes,
        "v1": {
            "lights": selected_v1["lights"],
            "sensors": selected_v1["sensors"],
            "rules": rules,
        },
    }


def save_snapshot(snapshot: dict, path: Path) -> None:
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != 1:
        raise MigrationError(f"Unsupported snapshot schema: {payload.get('schema')!r}")
    return payload


@dataclass(slots=True)
class MappingPlan:
    v1_map: dict[str, str]
    v2_map: dict[str, dict]
    missing: list[dict]

    @property
    def complete(self) -> bool:
        return not self.missing


def build_mapping_plan(snapshot: dict, dest_v1: dict, dest_v2: list[dict]) -> MappingPlan:
    dest_unique = {
        **_uniqueid_index(dest_v1.get("lights", {}), "lights"),
        **_uniqueid_index(dest_v1.get("sensors", {}), "sensors"),
    }
    dest_by_v1 = _id_v1_index(dest_v2)

    source_v1: dict[str, dict] = {}
    for section in ("lights", "sensors"):
        for rid, payload in snapshot.get("v1", {}).get(section, {}).items():
            source_v1[f"/{section}/{rid}"] = payload

    v1_map: dict[str, str] = {}
    missing: list[dict] = []
    for source_path, payload in source_v1.items():
        uniqueid = payload.get("uniqueid")
        dest_path = dest_unique.get(str(uniqueid).lower()) if uniqueid else None
        if dest_path:
            v1_map[source_path] = dest_path
        else:
            missing.append(
                {
                    "source": source_path,
                    "name": payload.get("name"),
                    "uniqueid": uniqueid,
                }
            )

    source_v2: dict[str, dict] = {}
    for device in snapshot.get("devices", []):
        source_v2[device["id"]] = device
        for service in device.get("services_expanded", []):
            source_v2[service["id"]] = service
    for scene in snapshot.get("scenes", []):
        source_v2[scene["id"]] = scene
    source_v2[snapshot["room"]["id"]] = snapshot["room"]

    v2_map: dict[str, dict] = {}
    for source_id, resource in source_v2.items():
        id_v1 = resource.get("id_v1")
        if id_v1 in v1_map and v1_map[id_v1] in dest_by_v1:
            v2_map[source_id] = dest_by_v1[v1_map[id_v1]]

    return MappingPlan(v1_map=v1_map, v2_map=v2_map, missing=missing)


def _destination_device_children(snapshot: dict, plan: MappingPlan) -> list[dict]:
    children: list[dict] = []
    seen: set[str] = set()
    for device in snapshot.get("devices", []):
        ids: set[str] = set()
        for service in device.get("services_expanded", []):
            mapped = plan.v2_map.get(service.get("id"))
            owner = mapped.get("owner", {}) if mapped else {}
            if owner.get("rtype") == "device" and owner.get("rid"):
                ids.add(owner["rid"])
        if len(ids) > 1:
            raise MigrationError(
                f"Source device {device.get('metadata', {}).get('name', device.get('id'))} "
                "mapped to multiple destination devices"
            )
        for rid in ids:
            if rid not in seen:
                children.append({"rid": rid, "rtype": "device"})
                seen.add(rid)
    return children


def _new_resource_id(result: list[dict]) -> str:
    if not result:
        raise MigrationError("Bridge returned no resource identifier")
    rid = result[0].get("rid") or result[0].get("id")
    if not rid:
        raise MigrationError(f"Cannot read created resource id from {result[0]!r}")
    return rid


def _merge_room(
    client: HueBridgeClient,
    snapshot: dict,
    plan: MappingPlan,
    room_name: str | None,
) -> dict:
    name = room_name or snapshot["room"].get("metadata", {}).get("name", "Migrated room")
    existing = [
        room
        for room in client.v2_get("room")
        if room.get("metadata", {}).get("name") == name
    ]
    children = _destination_device_children(snapshot, plan)

    if existing:
        room = existing[0]
        merged = {tuple(sorted(child.items())) for child in room.get("children", [])}
        merged.update(tuple(sorted(child.items())) for child in children)
        client.v2_put(
            "room",
            room["id"],
            {"children": [dict(items) for items in sorted(merged)]},
        )
        return client.v2_get("room", room["id"])[0]

    metadata = copy.deepcopy(snapshot["room"].get("metadata", {}))
    metadata["name"] = name
    rid = _new_resource_id(
        client.v2_post(
            "room",
            {"type": "room", "children": children, "metadata": metadata},
        )
    )
    return client.v2_get("room", rid)[0]


def _scene_body(scene: dict, destination_room: dict, plan: MappingPlan) -> dict:
    actions: list[dict] = []
    for action in scene.get("actions", []):
        target = action.get("target", {})
        mapped = plan.v2_map.get(target.get("rid"))
        if not mapped:
            raise MigrationError(
                f"Scene {scene.get('metadata', {}).get('name')} "
                f"has an unmapped target {target}"
            )
        actions.append(
            {
                "target": {"rid": mapped["id"], "rtype": mapped["type"]},
                "action": copy.deepcopy(action.get("action", {})),
            }
        )

    metadata = {
        key: copy.deepcopy(value)
        for key, value in scene.get("metadata", {}).items()
        if key in {"name", "appdata"}
    }
    body = {
        "type": "scene",
        "metadata": metadata,
        "group": {"rid": destination_room["id"], "rtype": "room"},
        "actions": actions,
    }
    for key in ("palette", "speed", "auto_dynamic"):
        if key in scene:
            body[key] = copy.deepcopy(scene[key])
    return body


def _create_scenes(
    client: HueBridgeClient,
    snapshot: dict,
    destination_room: dict,
    plan: MappingPlan,
) -> dict[str, str]:
    existing = {
        scene.get("metadata", {}).get("name"): scene
        for scene in client.v2_get("scene")
        if scene.get("group", {}).get("rid") == destination_room["id"]
    }
    scene_map: dict[str, str] = {}
    for source_scene in snapshot.get("scenes", []):
        name = source_scene.get("metadata", {}).get("name")
        if name in existing:
            dest_scene = existing[name]
        else:
            rid = _new_resource_id(
                client.v2_post(
                    "scene",
                    _scene_body(source_scene, destination_room, plan),
                )
            )
            dest_scene = client.v2_get("scene", rid)[0]
            existing[name] = dest_scene
        if source_scene.get("id_v1") and dest_scene.get("id_v1"):
            scene_map[source_scene["id_v1"]] = dest_scene["id_v1"]
    return scene_map


def rewrite_rule(rule: dict, path_map: dict[str, str]) -> tuple[dict, set[str]]:
    unresolved: set[str] = set()

    def rewrite(value: Any) -> Any:
        if isinstance(value, str):
            for ref in _extract_refs(value):
                if ref in path_map:
                    value = value.replace(ref, path_map[ref])
                elif ref.startswith(("/lights/", "/sensors/", "/groups/", "/scenes/")):
                    unresolved.add(ref)
            return value
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            result = {key: rewrite(child) for key, child in value.items()}
            if "scene" in result and isinstance(result["scene"], str):
                scene_path = f"/scenes/{result['scene']}"
                if scene_path in path_map:
                    result["scene"] = path_map[scene_path].split("/", 2)[2]
                else:
                    unresolved.add(scene_path)
            return result
        return value

    body = {
        "name": rule.get("name", "Migrated rule"),
        "conditions": rewrite(copy.deepcopy(rule.get("conditions", []))),
        "actions": rewrite(copy.deepcopy(rule.get("actions", []))),
    }
    if "recycle" in rule:
        body["recycle"] = rule["recycle"]
    return body, unresolved


def _create_rules(
    client: HueBridgeClient,
    snapshot: dict,
    path_map: dict[str, str],
) -> tuple[int, list[dict]]:
    created = 0
    skipped: list[dict] = []
    existing_names = {
        rule.get("name")
        for rule in client.v1_all().get("rules", {}).values()
    }

    for rule_id, source_rule in snapshot.get("v1", {}).get("rules", {}).items():
        if source_rule.get("name") in existing_names:
            skipped.append(
                {
                    "id": rule_id,
                    "name": source_rule.get("name"),
                    "reason": "name exists",
                }
            )
            continue

        body, unresolved = rewrite_rule(source_rule, path_map)
        if unresolved:
            skipped.append(
                {
                    "id": rule_id,
                    "name": source_rule.get("name"),
                    "reason": "unresolved references",
                    "references": sorted(unresolved),
                }
            )
            continue

        result = client.v1_post("/rules", body)
        created += 1
        if source_rule.get("status") == "disabled" and result and "success" in result[0]:
            created_id = str(next(iter(result[0]["success"].values()))).split("/")[-1]
            client.v1_put(f"/rules/{created_id}", {"status": "disabled"})

    return created, skipped


def analyse(snapshot: dict, client: HueBridgeClient) -> dict:
    plan = build_mapping_plan(snapshot, client.v1_all(), client.v2_resources())
    return {
        "room": snapshot["room"].get("metadata", {}).get("name"),
        "lights": len(snapshot.get("v1", {}).get("lights", {})),
        "sensors": len(snapshot.get("v1", {}).get("sensors", {})),
        "devices": len(snapshot.get("devices", [])),
        "scenes": len(snapshot.get("scenes", [])),
        "rules": len(snapshot.get("v1", {}).get("rules", {})),
        "mapped": len(plan.v1_map),
        "missing": plan.missing,
        "ready": plan.complete,
    }


def apply_snapshot(
    snapshot: dict,
    client: HueBridgeClient,
    *,
    room_name: str | None = None,
) -> dict:
    plan = build_mapping_plan(snapshot, client.v1_all(), client.v2_resources())
    if not plan.complete:
        raise MigrationError(
            "Destination bridge is missing migrated devices; pair them first. "
            f"Missing: {plan.missing}"
        )

    destination_room = _merge_room(client, snapshot, plan, room_name)
    source_group = snapshot["room"].get("id_v1")
    if source_group and destination_room.get("id_v1"):
        plan.v1_map[source_group] = destination_room["id_v1"]

    plan.v1_map.update(
        _create_scenes(client, snapshot, destination_room, plan)
    )
    rules_created, rules_skipped = _create_rules(
        client,
        snapshot,
        plan.v1_map,
    )
    return {
        "destination_room": destination_room.get("metadata", {}).get("name"),
        "scenes_total": len(snapshot.get("scenes", [])),
        "rules_created": rules_created,
        "rules_skipped": rules_skipped,
        "source_untouched": True,
    }
