from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .client import HueBridgeClient

REF_RE = re.compile(r"/(lights|sensors|groups|scenes|rules|schedules|resourcelinks)/([^/]+)")
MIGRATABLE_REF_PREFIXES = ("/lights/", "/sensors/", "/groups/", "/scenes/")
V2_PERIMETER_TYPES = {
    "room",
    "zone",
    "device",
    "light",
    "grouped_light",
    "button",
    "relative_rotary",
    "motion",
    "temperature",
    "light_level",
    "contact",
    "scene",
    "smart_scene",
}
PAIRING_FIELD_NAMES = {
    "serial_number",
    "serialnumber",
    "setup_code",
    "pairing_code",
    "manual_code",
    "install_code",
}
CLIP_SENSOR_TYPES = {
    "CLIPGenericFlag",
    "CLIPGenericStatus",
    "CLIPPresence",
    "CLIPLightLevel",
    "CLIPTemperature",
    "CLIPHumidity",
    "CLIPOpenClose",
    "CLIPSwitch",
}
WRITABLE_CLIP_STATE = {
    "CLIPGenericFlag": {"flag"},
    "CLIPGenericStatus": {"status"},
    "CLIPPresence": {"presence"},
    "CLIPLightLevel": {"lightlevel"},
    "CLIPTemperature": {"temperature"},
    "CLIPHumidity": {"humidity"},
    "CLIPOpenClose": {"open"},
    "CLIPSwitch": {"buttonevent"},
}


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
    match = re.fullmatch(r"/(lights|sensors|groups|scenes)/([^/]+)", path)
    return (match.group(1), match.group(2)) if match else None


def _extract_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        refs.update(f"/{kind}/{rid}" for kind, rid in REF_RE.findall(value))
    elif isinstance(value, dict):
        for key, child in value.items():
            refs.update(_extract_refs(child))
            if key == "scene" and isinstance(child, str):
                refs.add(f"/scenes/{child}")
    elif isinstance(value, list):
        for child in value:
            refs.update(_extract_refs(child))
    return refs


def _selected_v1_paths(rooms: list[dict], devices: list[dict], scenes: list[dict]) -> set[str]:
    paths: set[str] = set()
    for room in rooms:
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


def _room_devices(room: dict, by_id: dict[str, dict]) -> list[dict]:
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
    return devices


def _room_membership(resources: list[dict], v1: dict) -> dict[str, set[str]]:
    by_id = _resource_index(resources)
    membership: dict[str, set[str]] = {}
    for room in (r for r in resources if r.get("type") == "room"):
        name = room.get("metadata", {}).get("name", "?")
        if room.get("id_v1"):
            membership.setdefault(room["id_v1"], set()).add(name)
        for device in _room_devices(room, by_id):
            for service in device.get("services_expanded", []):
                if service.get("id_v1"):
                    membership.setdefault(service["id_v1"], set()).add(name)

    for gid, group in v1.get("groups", {}).items():
        room_name = group.get("name", f"Group {gid}")
        group_path = f"/groups/{gid}"
        membership.setdefault(group_path, set()).add(room_name)
        for lid in group.get("lights", []):
            membership.setdefault(f"/lights/{lid}", set()).add(room_name)
        for sid in group.get("sensors", []):
            membership.setdefault(f"/sensors/{sid}", set()).add(room_name)

    for sid, scene in v1.get("scenes", {}).items():
        gid = scene.get("group")
        if gid is not None:
            group_names = membership.get(f"/groups/{gid}", set())
            membership.setdefault(f"/scenes/{sid}", set()).update(group_names)
    return membership


def _ref_info(ref: str, v1: dict, membership: dict[str, set[str]]) -> dict:
    parsed = _parse_v1_path(ref)
    label = ref
    resource_type = "unknown"
    if parsed:
        section, rid = parsed
        resource_type = section[:-1]
        payload = v1.get(section, {}).get(rid, {})
        label = payload.get("name") or payload.get("type") or ref
    return {
        "ref": ref,
        "type": resource_type,
        "label": label,
        "rooms": sorted(membership.get(ref, set())),
    }


def _v2_membership(resources: list[dict]) -> dict[str, set[str]]:
    by_id = _resource_index(resources)
    membership: dict[str, set[str]] = {}
    rooms_by_id = {
        room["id"]: room.get("metadata", {}).get("name", "?")
        for room in resources
        if room.get("type") == "room" and room.get("id")
    }
    for room_id, room_name in rooms_by_id.items():
        room = by_id[room_id]
        membership.setdefault(room_id, set()).add(room_name)
        for device in _room_devices(room, by_id):
            membership.setdefault(device["id"], set()).add(room_name)
            for service in device.get("services_expanded", []):
                if service.get("id"):
                    membership.setdefault(service["id"], set()).add(room_name)

    for scene in resources:
        if scene.get("type") not in {"scene", "smart_scene"}:
            continue
        room_name = rooms_by_id.get(scene.get("group", {}).get("rid"))
        if room_name and scene.get("id"):
            membership.setdefault(scene["id"], set()).add(room_name)
    return membership


def _extract_v2_ref_ids(value: Any, known_ids: set[str]) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        if value in known_ids:
            refs.add(value)
    elif isinstance(value, dict):
        rid = value.get("rid")
        if isinstance(rid, str) and rid in known_ids:
            refs.add(rid)
        for key, child in value.items():
            if isinstance(key, str) and key in known_ids:
                refs.add(key)
            refs.update(_extract_v2_ref_ids(child, known_ids))
    elif isinstance(value, list):
        for child in value:
            refs.update(_extract_v2_ref_ids(child, known_ids))
    return refs


def _v2_ref_info(rid: str, by_id: dict[str, dict], membership: dict[str, set[str]]) -> dict:
    resource = by_id.get(rid, {})
    product = resource.get("product_data", {})
    metadata = resource.get("metadata", {})
    return {
        "rid": rid,
        "rtype": resource.get("type", "unknown"),
        "label": metadata.get("name")
        or product.get("product_name")
        or resource.get("type")
        or rid,
        "rooms": sorted(membership.get(rid, set())),
    }


def _find_pairing_fields(value: Any, path: str = "") -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key.lower() in PAIRING_FIELD_NAMES and child not in (None, ""):
                found.append({"field": child_path, "value": str(child)})
            found.extend(_find_pairing_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_pairing_fields(child, f"{path}[{index}]"))
    return found


def _device_identifiers(device: dict, v1: dict) -> dict:
    uniqueids: list[str] = []
    zigbee_macs: list[str] = []
    exposed_pairing_fields = _find_pairing_fields(device)
    for service in device.get("services_expanded", []):
        id_v1 = service.get("id_v1")
        parsed = _parse_v1_path(id_v1) if isinstance(id_v1, str) else None
        if parsed:
            section, rid = parsed
            uniqueid = v1.get(section, {}).get(rid, {}).get("uniqueid")
            if uniqueid and uniqueid not in uniqueids:
                uniqueids.append(uniqueid)
        if service.get("type") == "zigbee_connectivity" and service.get("mac_address"):
            mac = service["mac_address"]
            if mac not in zigbee_macs:
                zigbee_macs.append(mac)
        exposed_pairing_fields.extend(_find_pairing_fields(service))

    deduped_fields: list[dict] = []
    seen_fields: set[tuple[str, str]] = set()
    for item in exposed_pairing_fields:
        key = (item["field"], item["value"])
        if key not in seen_fields:
            deduped_fields.append(item)
            seen_fields.add(key)
    return {
        "zigbee_macs": zigbee_macs,
        "v1_uniqueids": uniqueids,
        "pairing_fields": deduped_fields,
        "pairing_serial_available": bool(deduped_fields),
    }


def inventory_tree(client: HueBridgeClient) -> dict:
    resources = client.v2_resources()
    v1 = client.v1_all()
    by_id = _resource_index(resources)
    known_ids = set(by_id)
    membership = _room_membership(resources, v1)
    membership_v2 = _v2_membership(resources)
    rules = v1.get("rules", {})
    behavior_instances = [r for r in resources if r.get("type") == "behavior_instance"]
    behavior_scripts = {
        r["id"]: r for r in resources if r.get("type") == "behavior_script" and r.get("id")
    }

    room_nodes: list[dict] = []
    for room in sorted(
        (r for r in resources if r.get("type") == "room"),
        key=lambda r: r.get("metadata", {}).get("name", "").lower(),
    ):
        name = room.get("metadata", {}).get("name", "?")
        devices = _room_devices(room, by_id)
        room_scenes = [
            s
            for s in resources
            if s.get("type") in {"scene", "smart_scene"}
            and s.get("group", {}).get("rid") == room.get("id")
        ]
        paths = _selected_v1_paths([room], devices, room_scenes)
        selected_v2_ids = {room.get("id")}
        for device in devices:
            selected_v2_ids.add(device.get("id"))
            selected_v2_ids.update(
                service.get("id") for service in device.get("services_expanded", [])
            )
        selected_v2_ids.update(scene.get("id") for scene in room_scenes)
        selected_v2_ids.discard(None)

        scenes = [
            {
                "id": scene.get("id"),
                "id_v1": scene.get("id_v1"),
                "name": scene.get("metadata", {}).get("name", "?"),
                "actions": len(scene.get("actions", [])),
            }
            for scene in room_scenes
        ]

        rule_nodes = []
        for rid, rule in rules.items():
            refs = _extract_refs(rule)
            if not (refs & paths):
                continue
            rule_nodes.append(
                {
                    "id": rid,
                    "name": rule.get("name", f"Rule {rid}"),
                    "status": rule.get("status", "enabled"),
                    "references": [
                        _ref_info(ref, v1, membership) for ref in sorted(refs)
                    ],
                }
            )

        automation_nodes = []
        for instance in behavior_instances:
            refs = _extract_v2_ref_ids(instance.get("configuration", {}), known_ids)
            if not (refs & selected_v2_ids):
                continue
            script = behavior_scripts.get(instance.get("script_id"), {})
            automation_nodes.append(
                {
                    "id": instance.get("id"),
                    "name": instance.get("metadata", {}).get("name")
                    or script.get("metadata", {}).get("name")
                    or instance.get("id"),
                    "enabled": instance.get("enabled"),
                    "status": instance.get("status"),
                    "script_id": instance.get("script_id"),
                    "script_name": script.get("metadata", {}).get("name"),
                    "references": [
                        _v2_ref_info(ref, by_id, membership_v2) for ref in sorted(refs)
                    ],
                    "configuration": copy.deepcopy(instance.get("configuration", {})),
                }
            )

        device_nodes = []
        for device in devices:
            services = []
            for service in device.get("services_expanded", []):
                services.append(
                    {
                        "id": service.get("id"),
                        "id_v1": service.get("id_v1"),
                        "type": service.get("type"),
                    }
                )
            product = device.get("product_data", {})
            device_nodes.append(
                {
                    "id": device.get("id"),
                    "name": device.get("metadata", {}).get("name")
                    or product.get("product_name")
                    or device.get("id"),
                    "model": product.get("model_id"),
                    "product": product.get("product_name"),
                    "services": services,
                    "identifiers": _device_identifiers(device, v1),
                }
            )

        room_nodes.append(
            {
                "id": room.get("id"),
                "id_v1": room.get("id_v1"),
                "name": name,
                "devices": device_nodes,
                "scenes": scenes,
                "rules": rule_nodes,
                "automations_v2": automation_nodes,
            }
        )

    config = v1.get("config", {})
    return {
        "bridge": {
            key: config.get(key)
            for key in ("name", "bridgeid", "modelid", "swversion", "apiversion")
        },
        "rooms": room_nodes,
    }

def create_selection_snapshot(client: HueBridgeClient, room_names: list[str]) -> dict:
    wanted = {name for name in room_names if name}
    if not wanted:
        raise MigrationError("Select at least one room")

    resources = client.v2_resources()
    by_id = _resource_index(resources)
    known_ids = set(by_id)
    matches = [
        r
        for r in resources
        if r.get("type") == "room" and r.get("metadata", {}).get("name") in wanted
    ]
    found = {r.get("metadata", {}).get("name") for r in matches}
    missing_rooms = sorted(wanted - found)
    if missing_rooms:
        raise MigrationError(f"Room(s) not found: {', '.join(missing_rooms)}")

    rooms = [copy.deepcopy(room) for room in matches]
    devices_by_id: dict[str, dict] = {}
    for room in rooms:
        for device in _room_devices(room, by_id):
            devices_by_id[device["id"]] = device
    devices = list(devices_by_id.values())

    room_ids = {room.get("id") for room in rooms}
    scenes = [
        copy.deepcopy(r)
        for r in resources
        if r.get("type") in {"scene", "smart_scene"}
        and r.get("group", {}).get("rid") in room_ids
    ]

    selected_v2_ids = set(room_ids)
    for device in devices:
        selected_v2_ids.add(device.get("id"))
        selected_v2_ids.update(
            service.get("id") for service in device.get("services_expanded", [])
        )
    selected_v2_ids.update(scene.get("id") for scene in scenes)
    selected_v2_ids.discard(None)

    behavior_instances: list[dict] = []
    behavior_ref_ids: set[str] = set()
    for instance in resources:
        if instance.get("type") != "behavior_instance":
            continue
        refs = _extract_v2_ref_ids(instance.get("configuration", {}), known_ids)
        if refs & selected_v2_ids:
            behavior_instances.append(copy.deepcopy(instance))
            behavior_ref_ids.update(refs)

    behavior_scripts: dict[str, dict] = {}
    for instance in behavior_instances:
        script_id = instance.get("script_id")
        script = by_id.get(script_id)
        if script and script.get("type") == "behavior_script":
            behavior_scripts[script_id] = copy.deepcopy(script)
            behavior_ref_ids.add(script_id)

    v2_references = {
        rid: copy.deepcopy(by_id[rid])
        for rid in behavior_ref_ids
        if rid in by_id
    }

    v1 = client.v1_all()
    selected_paths = _selected_v1_paths(rooms, devices, scenes)
    selected_v1: dict[str, dict] = {"lights": {}, "sensors": {}}
    for path in list(selected_paths):
        parsed = _parse_v1_path(path)
        if not parsed:
            continue
        section, rid = parsed
        if section in selected_v1 and rid in v1.get(section, {}):
            selected_v1[section][rid] = copy.deepcopy(v1[section][rid])

    rules: dict[str, dict] = {}
    virtual_sensors: dict[str, dict] = {}
    changed = True
    while changed:
        changed = False
        for rid, rule in v1.get("rules", {}).items():
            refs = _extract_refs(rule)
            if not (refs & selected_paths):
                continue
            if rid not in rules:
                rules[rid] = copy.deepcopy(rule)
                changed = True
            for ref in refs:
                parsed = _parse_v1_path(ref)
                if not parsed or parsed[0] != "sensors" or ref in selected_paths:
                    continue
                sensor = v1.get("sensors", {}).get(parsed[1], {})
                if sensor.get("type") in CLIP_SENSOR_TYPES:
                    virtual_sensors[parsed[1]] = copy.deepcopy(sensor)
                    selected_paths.add(ref)
                    changed = True

    membership = _room_membership(resources, v1)
    membership_v2 = _v2_membership(resources)
    selected_rule_paths = {f"/rules/{rid}" for rid in rules}
    resourcelinks = {
        rid: copy.deepcopy(link)
        for rid, link in v1.get("resourcelinks", {}).items()
        if set(link.get("links", [])) & (selected_paths | selected_rule_paths)
    }

    dependency_report: list[dict] = []
    for rid, rule in rules.items():
        refs = {ref for ref in _extract_refs(rule) if ref.startswith(MIGRATABLE_REF_PREFIXES)}
        external = refs - selected_paths
        dependency_report.append(
            {
                "rule_id": rid,
                "name": rule.get("name", f"Rule {rid}"),
                "internal": [_ref_info(ref, v1, membership) for ref in sorted(refs & selected_paths)],
                "external": [_ref_info(ref, v1, membership) for ref in sorted(external)],
            }
        )

    behavior_dependencies: list[dict] = []
    for instance in behavior_instances:
        refs = _extract_v2_ref_ids(instance.get("configuration", {}), known_ids)
        external = {
            rid
            for rid in refs - selected_v2_ids
            if by_id.get(rid, {}).get("type") in V2_PERIMETER_TYPES
        }
        behavior_dependencies.append(
            {
                "behavior_id": instance.get("id"),
                "name": instance.get("metadata", {}).get("name")
                or behavior_scripts.get(instance.get("script_id"), {}).get("metadata", {}).get("name")
                or instance.get("id"),
                "script_id": instance.get("script_id"),
                "internal": [
                    _v2_ref_info(rid, by_id, membership_v2)
                    for rid in sorted(refs & selected_v2_ids)
                ],
                "external": [
                    _v2_ref_info(rid, by_id, membership_v2)
                    for rid in sorted(external)
                ],
            }
        )

    config = v1.get("config", {})
    return {
        "schema": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_bridge": {
            key: config.get(key)
            for key in ("name", "bridgeid", "modelid", "swversion")
        },
        "rooms": rooms,
        "devices": devices,
        "scenes": scenes,
        "behavior_instances": behavior_instances,
        "behavior_scripts": behavior_scripts,
        "v2_references": v2_references,
        "v1": {
            "lights": selected_v1["lights"],
            "sensors": selected_v1["sensors"],
            "virtual_sensors": virtual_sensors,
            "rules": rules,
            "resourcelinks": resourcelinks,
        },
        "dependencies": dependency_report,
        "behavior_dependencies": behavior_dependencies,
    }

def create_snapshot(client: HueBridgeClient, room_name: str) -> dict:
    return create_selection_snapshot(client, [room_name])


def save_snapshot(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalise_snapshot(payload: dict) -> dict:
    if payload.get("schema") == 3:
        return payload

    result = copy.deepcopy(payload)
    if result.get("schema") == 1 and result.get("room"):
        result["rooms"] = [result.pop("room")]
    elif result.get("schema") != 2:
        raise MigrationError(f"Unsupported snapshot schema: {result.get('schema')!r}")

    result["schema"] = 3
    result.setdefault("v1", {}).setdefault("virtual_sensors", {})
    result.setdefault("v1", {}).setdefault("resourcelinks", {})
    result.setdefault("dependencies", [])
    result.setdefault("behavior_instances", [])
    result.setdefault("behavior_scripts", {})
    result.setdefault("v2_references", {})
    result.setdefault("behavior_dependencies", [])
    return result

def load_snapshot(path: Path) -> dict:
    return _normalise_snapshot(json.loads(path.read_text(encoding="utf-8")))


@dataclass(slots=True)
class MappingPlan:
    v1_map: dict[str, str]
    v2_map: dict[str, dict]
    missing: list[dict]

    @property
    def complete(self) -> bool:
        return not self.missing


def build_mapping_plan(snapshot: dict, dest_v1: dict, dest_v2: list[dict]) -> MappingPlan:
    snapshot = _normalise_snapshot(snapshot)
    dest_unique = {
        **_uniqueid_index(dest_v1.get("lights", {}), "lights"),
        **_uniqueid_index(dest_v1.get("sensors", {}), "sensors"),
    }
    dest_by_v1 = _id_v1_index(dest_v2)
    dest_by_id = _resource_index(dest_v2)

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

    v2_map: dict[str, dict] = {}
    for source_id, source in snapshot.get("v2_references", {}).items():
        destination = dest_by_id.get(source_id)
        if destination and destination.get("type") == source.get("type"):
            v2_map[source_id] = destination

    for source_id, resource in source_v2.items():
        id_v1 = resource.get("id_v1")
        if id_v1 in v1_map and v1_map[id_v1] in dest_by_v1:
            v2_map[source_id] = dest_by_v1[v1_map[id_v1]]

    # A device UUID changes between bridges. Infer it from the owner of a mapped service.
    for device in snapshot.get("devices", []):
        owner_ids = {
            mapped.get("owner", {}).get("rid")
            for service in device.get("services_expanded", [])
            if (mapped := v2_map.get(service.get("id")))
            and mapped.get("owner", {}).get("rtype") == "device"
            and mapped.get("owner", {}).get("rid")
        }
        if len(owner_ids) == 1:
            owner_id = next(iter(owner_ids))
            if owner_id in dest_by_id:
                v2_map[device["id"]] = dest_by_id[owner_id]

    # Map remaining services by device owner and unique service type when no v1 id exists.
    for device in snapshot.get("devices", []):
        mapped_device = v2_map.get(device.get("id"))
        if not mapped_device:
            continue
        dest_device_id = mapped_device.get("id")
        candidates = [
            resource
            for resource in dest_v2
            if resource.get("owner", {}).get("rid") == dest_device_id
        ]
        for service in device.get("services_expanded", []):
            if service.get("id") in v2_map:
                continue
            same_type = [candidate for candidate in candidates if candidate.get("type") == service.get("type")]
            if len(same_type) == 1:
                v2_map[service["id"]] = same_type[0]

    return MappingPlan(v1_map=v1_map, v2_map=v2_map, missing=missing)

def _destination_device_children(device_ids: set[str], snapshot: dict, plan: MappingPlan) -> list[dict]:
    children: list[dict] = []
    seen: set[str] = set()
    for device in snapshot.get("devices", []):
        if device.get("id") not in device_ids:
            continue
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
    return str(rid)


def _new_v1_id(result: Any) -> str:
    if not result or not isinstance(result, list) or "success" not in result[0]:
        raise MigrationError(f"Cannot read created v1 resource id from {result!r}")
    success = result[0]["success"]
    if "id" in success:
        return str(success["id"])
    for value in success.values():
        return str(value).rstrip("/").split("/")[-1]
    raise MigrationError(f"Cannot read created v1 resource id from {result!r}")


def _room_source_device_ids(room: dict) -> set[str]:
    return {
        child.get("rid")
        for child in room.get("children", [])
        if child.get("rtype") == "device" and child.get("rid")
    }


def _merge_rooms(client: HueBridgeClient, snapshot: dict, plan: MappingPlan) -> dict[str, dict]:
    existing_by_name = {
        room.get("metadata", {}).get("name"): room
        for room in client.v2_get("room")
    }
    result: dict[str, dict] = {}
    for source_room in snapshot.get("rooms", []):
        name = source_room.get("metadata", {}).get("name", "Migrated room")
        children = _destination_device_children(
            _room_source_device_ids(source_room), snapshot, plan
        )
        existing = existing_by_name.get(name)
        if existing:
            merged = {tuple(sorted(child.items())) for child in existing.get("children", [])}
            merged.update(tuple(sorted(child.items())) for child in children)
            client.v2_put(
                "room",
                existing["id"],
                {"children": [dict(items) for items in sorted(merged)]},
            )
            destination = client.v2_get("room", existing["id"])[0]
        else:
            metadata = copy.deepcopy(source_room.get("metadata", {}))
            metadata["name"] = name
            rid = _new_resource_id(
                client.v2_post(
                    "room",
                    {"type": "room", "children": children, "metadata": metadata},
                )
            )
            destination = client.v2_get("room", rid)[0]
            existing_by_name[name] = destination
        result[source_room["id"]] = destination
        plan.v2_map[source_room["id"]] = destination
        if source_room.get("id_v1") and destination.get("id_v1"):
            plan.v1_map[source_room["id_v1"]] = destination["id_v1"]
    return result


def _scene_body(scene: dict, destination_room: dict, plan: MappingPlan) -> dict:
    actions: list[dict] = []
    for action in scene.get("actions", []):
        target = action.get("target", {})
        mapped = plan.v2_map.get(target.get("rid"))
        if not mapped:
            raise MigrationError(
                f"Scene {scene.get('metadata', {}).get('name')} has an unmapped target {target}"
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
    destination_rooms: dict[str, dict],
    plan: MappingPlan,
) -> dict[str, str]:
    existing_scenes = client.v2_get("scene")
    scene_map: dict[str, str] = {}
    for source_scene in snapshot.get("scenes", []):
        source_room_id = source_scene.get("group", {}).get("rid")
        destination_room = destination_rooms.get(source_room_id)
        if not destination_room:
            continue
        name = source_scene.get("metadata", {}).get("name")
        existing = next(
            (
                scene
                for scene in existing_scenes
                if scene.get("group", {}).get("rid") == destination_room["id"]
                and scene.get("metadata", {}).get("name") == name
            ),
            None,
        )
        if existing:
            dest_scene = existing
        else:
            rid = _new_resource_id(
                client.v2_post("scene", _scene_body(source_scene, destination_room, plan))
            )
            dest_scene = client.v2_get("scene", rid)[0]
            existing_scenes.append(dest_scene)
        if source_scene.get("id"):
            plan.v2_map[source_scene["id"]] = dest_scene
        if source_scene.get("id_v1") and dest_scene.get("id_v1"):
            scene_map[source_scene["id_v1"]] = dest_scene["id_v1"]
    return scene_map


def _map_behavior_script(
    source_script_id: str,
    snapshot: dict,
    destination_resources: list[dict],
) -> str | None:
    destination_scripts = [
        resource
        for resource in destination_resources
        if resource.get("type") == "behavior_script"
    ]
    exact = next(
        (resource for resource in destination_scripts if resource.get("id") == source_script_id),
        None,
    )
    if exact:
        return exact["id"]

    source = snapshot.get("behavior_scripts", {}).get(source_script_id, {})
    source_metadata = source.get("metadata", {})
    source_name = source_metadata.get("name")
    source_category = source_metadata.get("category")
    source_version = source.get("version")
    candidates = [
        resource
        for resource in destination_scripts
        if resource.get("metadata", {}).get("name") == source_name
        and (
            not source_category
            or resource.get("metadata", {}).get("category") == source_category
        )
        and (not source_version or resource.get("version") == source_version)
    ]
    return candidates[0].get("id") if len(candidates) == 1 else None


_PRUNE_V2 = object()


def rewrite_behavior_configuration(
    configuration: dict,
    v2_map: dict[str, dict],
    known_source_ids: set[str],
    *,
    prune_external: bool,
) -> tuple[dict | None, set[str], list[dict]]:
    unresolved: set[str] = set()
    pruned: list[dict] = []

    def missing(source_id: str, path: tuple[str, ...]) -> object:
        if prune_external:
            pruned.append({"rid": source_id, "path": ".".join(path)})
            return _PRUNE_V2
        unresolved.add(source_id)
        return source_id

    def walk(value: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(value, str) and value in known_source_ids:
            mapped = v2_map.get(value)
            return mapped.get("id") if mapped else missing(value, path)

        if isinstance(value, list):
            output = []
            for index, child in enumerate(value):
                rewritten = walk(child, path + (str(index),))
                if rewritten is not _PRUNE_V2:
                    output.append(rewritten)
            return output if output else _PRUNE_V2

        if not isinstance(value, dict):
            return copy.deepcopy(value)

        rid = value.get("rid")
        rtype = value.get("rtype")
        if isinstance(rid, str) and rid in known_source_ids and isinstance(rtype, str):
            mapped = v2_map.get(rid)
            if not mapped:
                return missing(rid, path)
            output = copy.deepcopy(value)
            output["rid"] = mapped.get("id", rid)
            output["rtype"] = mapped.get("type", rtype)
            return output

        output: dict = {}
        for key, child in value.items():
            new_key = key
            if isinstance(key, str) and key in known_source_ids:
                mapped = v2_map.get(key)
                if not mapped:
                    if prune_external:
                        pruned.append({"rid": key, "path": ".".join(path + (key,))})
                        continue
                    unresolved.add(key)
                else:
                    new_key = mapped.get("id", key)

            rewritten = walk(child, path + (str(key),))
            if rewritten is _PRUNE_V2:
                # These nodes are resource selectors; losing them invalidates their branch.
                if key in {"device", "group", "target", "recall"}:
                    return _PRUNE_V2
                continue
            output[new_key] = rewritten

        # If pruning emptied a semantically required collection, prune its parent branch.
        for required in ("where", "what", "actions", "slots", "items"):
            if required in value and (
                required not in output
                or output.get(required) is _PRUNE_V2
                or output.get(required) == []
            ):
                return _PRUNE_V2
        if "buttons" in value and value.get("buttons") and not output.get("buttons"):
            return _PRUNE_V2

        return output if output else _PRUNE_V2

    rewritten = walk(configuration)
    if rewritten is _PRUNE_V2 or not isinstance(rewritten, dict):
        return None, unresolved, pruned
    return rewritten, unresolved, pruned


def _create_behavior_instances(
    client: HueBridgeClient,
    snapshot: dict,
    plan: MappingPlan,
    *,
    prune_external: bool,
) -> tuple[int, list[dict], list[dict]]:
    source_instances = snapshot.get("behavior_instances", [])
    if not source_instances:
        return 0, [], []

    destination_resources = client.v2_resources()
    destination_by_id = _resource_index(destination_resources)

    # Built-in/global resources (recipes, scripts, etc.) often keep their UUID.
    for source_id, source in snapshot.get("v2_references", {}).items():
        destination = destination_by_id.get(source_id)
        if destination and destination.get("type") == source.get("type"):
            plan.v2_map.setdefault(source_id, destination)

    known_source_ids = set(snapshot.get("v2_references", {}))
    for room in snapshot.get("rooms", []):
        if room.get("id"):
            known_source_ids.add(room["id"])
    for scene in snapshot.get("scenes", []):
        if scene.get("id"):
            known_source_ids.add(scene["id"])
    for device in snapshot.get("devices", []):
        if device.get("id"):
            known_source_ids.add(device["id"])
        for service in device.get("services_expanded", []):
            if service.get("id"):
                known_source_ids.add(service["id"])

    existing = [
        resource
        for resource in destination_resources
        if resource.get("type") == "behavior_instance"
    ]
    created = 0
    skipped: list[dict] = []
    warnings: list[dict] = []

    for source in source_instances:
        source_script_id = source.get("script_id")
        script_id = _map_behavior_script(source_script_id, snapshot, destination_resources)
        name = source.get("metadata", {}).get("name") or source.get("id")
        if not script_id:
            skipped.append(
                {
                    "id": source.get("id"),
                    "name": name,
                    "reason": "matching behavior_script not found on destination",
                    "script_id": source_script_id,
                }
            )
            continue

        if any(
            instance.get("script_id") == script_id
            and instance.get("metadata", {}).get("name") == name
            for instance in existing
        ):
            skipped.append(
                {
                    "id": source.get("id"),
                    "name": name,
                    "reason": "matching behavior instance already exists",
                }
            )
            continue

        configuration, unresolved, pruned = rewrite_behavior_configuration(
            source.get("configuration", {}),
            plan.v2_map,
            known_source_ids,
            prune_external=prune_external,
        )
        if unresolved:
            skipped.append(
                {
                    "id": source.get("id"),
                    "name": name,
                    "reason": "unresolved v2 graph references",
                    "references": sorted(unresolved),
                }
            )
            continue
        if configuration is None:
            skipped.append(
                {
                    "id": source.get("id"),
                    "name": name,
                    "reason": "automation graph became empty after pruning",
                    "pruned": pruned,
                }
            )
            continue

        body = {
            "type": "behavior_instance",
            "script_id": script_id,
            "enabled": bool(source.get("enabled", True)),
            "configuration": configuration,
            "metadata": {"name": name},
        }
        try:
            result = client.v2_post("behavior_instance", body)
            created_id = _new_resource_id(result)
            created += 1
            if pruned:
                warnings.append(
                    {
                        "id": source.get("id"),
                        "destination_id": created_id,
                        "name": name,
                        "pruned": pruned,
                        "semantic_change": True,
                    }
                )
        except Exception as exc:
            skipped.append(
                {
                    "id": source.get("id"),
                    "name": name,
                    "reason": "destination bridge rejected behavior_instance",
                    "error": str(exc),
                    "pruned": pruned,
                }
            )

    return created, skipped, warnings


def _ensure_virtual_sensors(client: HueBridgeClient, snapshot: dict, plan: MappingPlan) -> list[dict]:
    destination = client.v1_all().get("sensors", {})
    created: list[dict] = []
    for source_id, source in snapshot.get("v1", {}).get("virtual_sensors", {}).items():
        source_path = f"/sensors/{source_id}"
        source_uniqueid = source.get("uniqueid")
        match_id = next(
            (
                sid
                for sid, sensor in destination.items()
                if sensor.get("type") == source.get("type")
                and (
                    (source_uniqueid and sensor.get("uniqueid") == source_uniqueid)
                    or (
                        not source_uniqueid
                        and sensor.get("name") == source.get("name")
                        and sensor.get("modelid") == source.get("modelid")
                    )
                )
            ),
            None,
        )
        if match_id is None:
            body = {
                key: copy.deepcopy(source[key])
                for key in (
                    "name",
                    "type",
                    "modelid",
                    "manufacturername",
                    "swversion",
                    "uniqueid",
                    "recycle",
                )
                if key in source
            }
            match_id = _new_v1_id(client.v1_post("/sensors", body))
            sensor_type = source.get("type")
            writable = WRITABLE_CLIP_STATE.get(sensor_type, set())
            state = {
                key: value
                for key, value in source.get("state", {}).items()
                if key in writable
            }
            if state:
                try:
                    client.v1_put(f"/sensors/{match_id}/state", state)
                except Exception:
                    pass
            created.append({"source": source_path, "destination": f"/sensors/{match_id}"})
        plan.v1_map[source_path] = f"/sensors/{match_id}"
    return created


def _rewrite_value(value: Any, path_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        for ref in _extract_refs(value):
            if ref in path_map:
                value = value.replace(ref, path_map[ref])
        return value
    if isinstance(value, list):
        return [_rewrite_value(item, path_map) for item in value]
    if isinstance(value, dict):
        result = {key: _rewrite_value(child, path_map) for key, child in value.items()}
        if "scene" in result and isinstance(result["scene"], str):
            scene_path = f"/scenes/{result['scene']}"
            if scene_path in path_map:
                result["scene"] = path_map[scene_path].split("/", 2)[2]
        return result
    return value


def rewrite_rule(
    rule: dict,
    path_map: dict[str, str],
    *,
    prune_external: bool = False,
) -> tuple[dict, set[str], dict]:
    unresolved: set[str] = set()
    pruned = {"conditions": [], "actions": []}

    def process(items: list[dict], kind: str) -> list[dict]:
        output: list[dict] = []
        for item in items:
            refs = {
                ref
                for ref in _extract_refs(item)
                if ref.startswith(MIGRATABLE_REF_PREFIXES)
            }
            external = {ref for ref in refs if ref not in path_map}
            if external:
                if prune_external:
                    pruned[kind].append(
                        {"references": sorted(external), "item": copy.deepcopy(item)}
                    )
                    continue
                unresolved.update(external)
            output.append(_rewrite_value(copy.deepcopy(item), path_map))
        return output

    source_conditions = copy.deepcopy(rule.get("conditions", []))
    source_actions = copy.deepcopy(rule.get("actions", []))
    conditions = process(source_conditions, "conditions")
    actions = process(source_actions, "actions")

    body = {
        "name": rule.get("name", "Migrated rule"),
        "conditions": conditions,
        "actions": actions,
    }
    if "recycle" in rule:
        body["recycle"] = rule["recycle"]
    return body, unresolved, pruned


def _create_rules(
    client: HueBridgeClient,
    snapshot: dict,
    path_map: dict[str, str],
    *,
    prune_external: bool,
) -> tuple[int, list[dict], list[dict], dict[str, str]]:
    created = 0
    skipped: list[dict] = []
    warnings: list[dict] = []
    rule_map: dict[str, str] = {}
    existing_names = {rule.get("name") for rule in client.v1_all().get("rules", {}).values()}

    for rule_id, source_rule in snapshot.get("v1", {}).get("rules", {}).items():
        if source_rule.get("name") in existing_names:
            skipped.append({"id": rule_id, "name": source_rule.get("name"), "reason": "name exists"})
            continue

        body, unresolved, pruned = rewrite_rule(
            source_rule,
            path_map,
            prune_external=prune_external,
        )
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
        if source_rule.get("actions") and not body["actions"]:
            skipped.append(
                {
                    "id": rule_id,
                    "name": source_rule.get("name"),
                    "reason": "all actions were outside the selected perimeter",
                }
            )
            continue
        if source_rule.get("conditions") and not body["conditions"]:
            skipped.append(
                {
                    "id": rule_id,
                    "name": source_rule.get("name"),
                    "reason": "all conditions were outside the selected perimeter",
                }
            )
            continue
        if pruned["conditions"] or pruned["actions"]:
            warnings.append(
                {
                    "id": rule_id,
                    "name": source_rule.get("name"),
                    "pruned": pruned,
                    "semantic_change": bool(pruned["conditions"]),
                }
            )

        result = client.v1_post("/rules", body)
        created_id = _new_v1_id(result)
        rule_map[f"/rules/{rule_id}"] = f"/rules/{created_id}"
        created += 1
        if source_rule.get("status") == "disabled":
            client.v1_put(f"/rules/{created_id}", {"status": "disabled"})

    return created, skipped, warnings, rule_map


def _create_resourcelinks(
    client: HueBridgeClient,
    snapshot: dict,
    path_map: dict[str, str],
) -> tuple[int, list[dict]]:
    created = 0
    warnings: list[dict] = []
    existing_names = {
        link.get("name")
        for link in client.v1_all().get("resourcelinks", {}).values()
    }
    for source_id, source in snapshot.get("v1", {}).get("resourcelinks", {}).items():
        if source.get("name") in existing_names:
            warnings.append(
                {
                    "id": source_id,
                    "name": source.get("name"),
                    "reason": "resource link name already exists",
                }
            )
            continue
        links: list[str] = []
        pruned: list[str] = []
        for link in source.get("links", []):
            mapped = path_map.get(link)
            if mapped:
                links.append(mapped)
            else:
                pruned.append(link)
        if not links:
            warnings.append(
                {
                    "id": source_id,
                    "name": source.get("name"),
                    "reason": "resource link has no mapped resources",
                    "pruned": pruned,
                }
            )
            continue
        body = {
            key: copy.deepcopy(source[key])
            for key in ("name", "description", "type", "classid", "recycle")
            if key in source
        }
        body["links"] = links
        client.v1_post("/resourcelinks", body)
        created += 1
        if pruned:
            warnings.append(
                {
                    "id": source_id,
                    "name": source.get("name"),
                    "reason": "out-of-scope metadata links pruned",
                    "pruned": pruned,
                }
            )
    return created, warnings


def analyse(
    snapshot: dict,
    client: HueBridgeClient,
    *,
    allow_same_bridge: bool = False,
) -> dict:
    snapshot = _normalise_snapshot(snapshot)
    dest_v1 = client.v1_all()
    source_bridge_id = snapshot.get("source_bridge", {}).get("bridgeid")
    destination_bridge_id = dest_v1.get("config", {}).get("bridgeid")
    if (
        not allow_same_bridge
        and source_bridge_id
        and source_bridge_id == destination_bridge_id
    ):
        raise MigrationError("Source and destination are the same Hue Bridge")
    plan = build_mapping_plan(snapshot, dest_v1, client.v2_resources())
    external = [dep for dep in snapshot.get("dependencies", []) if dep.get("external")]
    external_v2 = [
        dep for dep in snapshot.get("behavior_dependencies", []) if dep.get("external")
    ]
    return {
        "rooms": [room.get("metadata", {}).get("name") for room in snapshot.get("rooms", [])],
        "lights": len(snapshot.get("v1", {}).get("lights", {})),
        "sensors": len(snapshot.get("v1", {}).get("sensors", {})),
        "virtual_sensors": len(snapshot.get("v1", {}).get("virtual_sensors", {})),
        "devices": len(snapshot.get("devices", [])),
        "scenes": len(snapshot.get("scenes", [])),
        "rules": len(snapshot.get("v1", {}).get("rules", {})),
        "resourcelinks": len(snapshot.get("v1", {}).get("resourcelinks", {})),
        "behavior_instances": len(snapshot.get("behavior_instances", [])),
        "mapped": len(plan.v1_map),
        "missing": plan.missing,
        "external_dependencies": external,
        "external_behavior_dependencies": external_v2,
        "ready": plan.complete,
    }


def apply_snapshot(
    snapshot: dict,
    client: HueBridgeClient,
    *,
    prune_external: bool = True,
    allow_same_bridge: bool = False,
) -> dict:
    snapshot = _normalise_snapshot(snapshot)
    dest_v1 = client.v1_all()
    source_bridge_id = snapshot.get("source_bridge", {}).get("bridgeid")
    destination_bridge_id = dest_v1.get("config", {}).get("bridgeid")
    if (
        not allow_same_bridge
        and source_bridge_id
        and source_bridge_id == destination_bridge_id
    ):
        raise MigrationError("Source and destination are the same Hue Bridge")
    plan = build_mapping_plan(snapshot, dest_v1, client.v2_resources())
    if not plan.complete:
        raise MigrationError(
            "Destination bridge is missing migrated devices; pair them first. "
            f"Missing: {plan.missing}"
        )

    virtual_created = _ensure_virtual_sensors(client, snapshot, plan)
    destination_rooms = _merge_rooms(client, snapshot, plan)
    plan.v1_map.update(_create_scenes(client, snapshot, destination_rooms, plan))
    behavior_created, behavior_skipped, behavior_warnings = _create_behavior_instances(
        client,
        snapshot,
        plan,
        prune_external=prune_external,
    )
    rules_created, rules_skipped, warnings, rule_map = _create_rules(
        client,
        snapshot,
        plan.v1_map,
        prune_external=prune_external,
    )
    plan.v1_map.update(rule_map)
    resourcelinks_created, resourcelink_warnings = _create_resourcelinks(
        client, snapshot, plan.v1_map
    )
    return {
        "destination_rooms": [
            room.get("metadata", {}).get("name") for room in destination_rooms.values()
        ],
        "scenes_total": len(snapshot.get("scenes", [])),
        "virtual_sensors_created": virtual_created,
        "behavior_instances_created": behavior_created,
        "behavior_instances_skipped": behavior_skipped,
        "behavior_warnings": behavior_warnings,
        "rules_created": rules_created,
        "rules_skipped": rules_skipped,
        "resourcelinks_created": resourcelinks_created,
        "resourcelink_warnings": resourcelink_warnings,
        "warnings": warnings,
        "source_untouched": True,
    }
