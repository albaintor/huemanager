from __future__ import annotations

import copy
import json
import os
import ssl
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import requests
import websocket

from .apple_home import (
    _best_fuzzy_match,
    _normalise,
    _normalise_identifier,
    _unique_index,
)
from .config import HomeAssistantProfile


def _now() -> str:
    return datetime.now(UTC).isoformat()


class HomeAssistantApiError(RuntimeError):
    pass


class HomeAssistantClient:
    def __init__(self, profile: HomeAssistantProfile, timeout: float = 12.0) -> None:
        self.profile = profile
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.profile.token}",
            "Content-Type": "application/json",
        }

    def rest_get(self, path: str) -> Any:
        response = self.session.get(
            self.profile.base_url + path,
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.profile.verify_tls,
        )
        if not response.ok:
            raise HomeAssistantApiError(
                f"Home Assistant API {response.status_code} GET {path}: "
                f"{response.text[:300]}"
            )
        return response.json()

    def test_connection(self) -> dict[str, Any]:
        config = self.rest_get("/api/config")
        return {
            "ok": True,
            "name": config.get("location_name"),
            "version": config.get("version"),
            "time_zone": config.get("time_zone"),
            "unit_system": config.get("unit_system"),
        }

    def _ws_connect(self) -> websocket.WebSocket:
        sslopt: dict[str, Any] = {}
        if self.profile.websocket_url.startswith("wss://") and not self.profile.verify_tls:
            sslopt["cert_reqs"] = ssl.CERT_NONE
            sslopt["check_hostname"] = False

        ws = websocket.create_connection(
            self.profile.websocket_url,
            timeout=self.timeout,
            sslopt=sslopt,
        )
        hello = json.loads(ws.recv())
        if hello.get("type") != "auth_required":
            ws.close()
            raise HomeAssistantApiError(
                f"Unexpected Home Assistant WebSocket greeting: {hello!r}"
            )
        ws.send(json.dumps({"type": "auth", "access_token": self.profile.token}))
        auth = json.loads(ws.recv())
        if auth.get("type") != "auth_ok":
            ws.close()
            raise HomeAssistantApiError(
                f"Home Assistant WebSocket authentication failed: {auth!r}"
            )
        return ws

    def registry_inventory(self) -> dict[str, Any]:
        config = self.rest_get("/api/config")
        ws = self._ws_connect()
        try:
            commands = [
                ("areas", "config/area_registry/list"),
                ("devices", "config/device_registry/list"),
                ("entities", "config/entity_registry/list"),
            ]
            result: dict[str, Any] = {}
            for command_id, (key, command_type) in enumerate(commands, start=1):
                ws.send(json.dumps({"id": command_id, "type": command_type}))
                while True:
                    payload = json.loads(ws.recv())
                    if payload.get("id") != command_id:
                        continue
                    if payload.get("type") != "result" or not payload.get("success"):
                        raise HomeAssistantApiError(
                            f"Home Assistant WebSocket command {command_type} failed: "
                            f"{payload!r}"
                        )
                    result[key] = payload.get("result") or []
                    break
        finally:
            ws.close()

        return normalize_home_assistant_inventory(
            config=config,
            areas=result.get("areas", []),
            devices=result.get("devices", []),
            entities=result.get("entities", []),
        )


def _flatten_pairs(values: Any) -> list[str]:
    result: list[str] = []
    for item in values or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            value = item[1]
        else:
            value = item
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def _device_area(
    device: dict[str, Any],
    *,
    device_by_id: dict[str, dict[str, Any]],
    entity_areas_by_device: dict[str, set[str]],
) -> tuple[str | None, str]:
    direct = str(device.get("area_id") or "")
    if direct:
        return direct, "device"

    parent_id = str(device.get("parent_device_id") or "")
    if parent_id:
        parent = device_by_id.get(parent_id)
        if parent:
            parent_area = str(parent.get("area_id") or "")
            if parent_area:
                return parent_area, "parent_device"

    areas = entity_areas_by_device.get(str(device.get("id") or ""), set())
    if len(areas) == 1:
        return next(iter(areas)), "entity"
    if len(areas) > 1:
        return None, "ambiguous_entities"
    return None, "unassigned"


def normalize_home_assistant_inventory(
    *,
    config: dict[str, Any],
    areas: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    area_rows = [
        {
            "id": str(area.get("area_id") or area.get("id") or ""),
            "name": area.get("name"),
            "aliases": list(area.get("aliases") or []),
        }
        for area in areas
        if area.get("area_id") or area.get("id")
    ]
    area_by_id = {row["id"]: row for row in area_rows}

    device_by_id = {
        str(device.get("id")): copy.deepcopy(device)
        for device in devices
        if device.get("id")
    }

    entities_by_device: dict[str, list[dict[str, Any]]] = {}
    entity_areas_by_device: dict[str, set[str]] = {}
    standalone_entities: list[dict[str, Any]] = []
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        device_id = str(entity.get("device_id") or "")
        area_id = str(entity.get("area_id") or "")
        if device_id:
            entities_by_device.setdefault(device_id, []).append(copy.deepcopy(entity))
            if area_id:
                entity_areas_by_device.setdefault(device_id, set()).add(area_id)
        elif area_id:
            standalone_entities.append(copy.deepcopy(entity))

    normalized_devices: list[dict[str, Any]] = []
    for device_id, device in device_by_id.items():
        area_id, area_source = _device_area(
            device,
            device_by_id=device_by_id,
            entity_areas_by_device=entity_areas_by_device,
        )
        serial = str(device.get("serial_number") or "").strip() or None
        identifiers = _flatten_pairs(device.get("identifiers"))
        connections = _flatten_pairs(device.get("connections"))
        reliable_identifiers = [
            value
            for value in [serial, *identifiers, *connections]
            if value
        ]
        linked_entities = entities_by_device.get(device_id, [])
        entity_domains = sorted(
            {
                str(entity.get("entity_id") or "").split(".", 1)[0]
                for entity in linked_entities
                if "." in str(entity.get("entity_id") or "")
            }
        )
        normalized_devices.append(
            {
                "id": device_id,
                "name": device.get("name_by_user") or device.get("name") or device_id,
                "manufacturer": device.get("manufacturer"),
                "model": device.get("model") or device.get("model_id"),
                "serial_number": serial,
                "area_id": area_id,
                "area_name": area_by_id.get(area_id or "", {}).get("name"),
                "area_source": area_source,
                "identifiers": reliable_identifiers,
                "connections": connections,
                "entity_ids": sorted(
                    str(entity.get("entity_id"))
                    for entity in linked_entities
                    if entity.get("entity_id")
                ),
                "entity_domains": entity_domains,
                "parent_device_id": device.get("parent_device_id"),
                "via_device_id": device.get("via_device_id"),
                "config_entry_id": device.get("config_entry_id")
                or device.get("primary_config_entry"),
                "disabled": bool(device.get("disabled_by")),
            }
        )

    # Standalone registry entities have no physical-device metadata. They are
    # included for manual association, but automatic matching remains conservative.
    for entity in standalone_entities:
        entity_id = str(entity.get("entity_id") or "")
        area_id = str(entity.get("area_id") or "")
        normalized_devices.append(
            {
                "id": f"entity:{entity_id}",
                "name": entity.get("name") or entity.get("original_name") or entity_id,
                "manufacturer": None,
                "model": None,
                "serial_number": None,
                "area_id": area_id,
                "area_name": area_by_id.get(area_id, {}).get("name"),
                "area_source": "entity",
                "identifiers": [
                    value
                    for value in [
                        entity.get("unique_id"),
                        entity_id,
                    ]
                    if value
                ],
                "connections": [],
                "entity_ids": [entity_id],
                "entity_domains": [entity_id.split(".", 1)[0]] if "." in entity_id else [],
                "standalone_entity": True,
                "disabled": bool(entity.get("disabled_by")),
            }
        )

    rooms: list[dict[str, Any]] = []
    for area in area_rows:
        room_devices = [
            device
            for device in normalized_devices
            if device.get("area_id") == area["id"] and not device.get("disabled")
        ]
        rooms.append(
            {
                "id": area["id"],
                "name": area.get("name") or area["id"],
                "devices": room_devices,
            }
        )

    return {
        "source_kind": "home_assistant",
        "source_label": "Home Assistant",
        "captured_at": _now(),
        "instance": {
            "name": config.get("location_name"),
            "version": config.get("version"),
            "time_zone": config.get("time_zone"),
        },
        "areas": area_rows,
        "rooms": rooms,
        "devices": normalized_devices,
        "unassigned_devices": [
            device
            for device in normalized_devices
            if not device.get("area_id") and not device.get("disabled")
        ],
    }


def _ha_identifier_candidates(device: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for value in device.get("identifiers", []):
        normalized = _normalise_identifier(str(value))
        if normalized:
            result.add(normalized)
    serial = _normalise_identifier(str(device.get("serial_number") or ""))
    if serial:
        result.add(serial)
    return result


def _apple_candidates(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    bridge_ids = {
        str(item.get("id"))
        for item in inventory.get("bridges", [])
        if item.get("id")
    }
    return [
        accessory
        for accessory in inventory.get("accessories", [])
        if accessory.get("id") and str(accessory.get("id")) not in bridge_ids
    ]


def build_home_assistant_apple_home_sync_plan(
    ha_inventory: dict[str, Any],
    apple_inventory: dict[str, Any],
    *,
    room_map: dict[str, str] | None = None,
    accessory_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    room_map = room_map or {}
    accessory_map = accessory_map or {}
    home = apple_inventory.get("home") or {}
    home_id = str(home.get("id") or "")
    if not home_id:
        raise ValueError("Apple Home inventory has no home id")

    apple_rooms = [
        room for room in apple_inventory.get("rooms", []) if room.get("id")
    ]
    apple_rooms_by_id = {str(room["id"]): room for room in apple_rooms}
    apple_rooms_by_name = _unique_index(
        apple_rooms,
        lambda room: _normalise(room.get("name")),
    )

    accessories = _apple_candidates(apple_inventory)
    accessories_by_id = {str(item["id"]): item for item in accessories}
    accessories_by_serial: dict[str, list[dict[str, Any]]] = {}
    for accessory in accessories:
        serial = _normalise_identifier(str(accessory.get("serial_number") or ""))
        if serial:
            accessories_by_serial.setdefault(serial, []).append(accessory)

    room_rows: list[dict[str, Any]] = []
    desired_room_by_source_id: dict[str, dict[str, Any]] = {}
    room_match_meta: dict[str, dict[str, Any]] = {}

    for room in ha_inventory.get("rooms", []):
        source_room_id = str(room.get("id") or "")
        if not source_room_id:
            continue
        source_name = room.get("name") or source_room_id
        explicit = source_room_id in room_map
        confidence: float | None = None
        suggestions: list[dict[str, Any]] = []
        if explicit:
            target_id = str(room_map.get(source_room_id) or "")
            desired = apple_rooms_by_id.get(target_id) if target_id else None
            method = "manual"
            confidence = 1.0
        else:
            desired = apple_rooms_by_name.get(_normalise(source_name))
            if desired:
                method = "name"
                confidence = 1.0
            else:
                desired, confidence, suggestions = _best_fuzzy_match(
                    source_name,
                    apple_rooms,
                    room=True,
                    threshold=0.72,
                    ambiguity_gap=0.08,
                )
                method = "heuristic" if desired else None

        row = {
            "source_room_id": source_room_id,
            "source_room_name": source_name,
            # Backward-compatible field names consumed by the current web/iOS clients.
            "hue_room_id": source_room_id,
            "hue_room_name": source_name,
            "apple_room_id": str(desired.get("id")) if desired else None,
            "apple_room_name": desired.get("name") if desired else None,
            "method": method,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "suggestions": suggestions,
            "status": "mapped" if desired else "unmapped",
        }
        room_rows.append(row)
        if desired:
            desired_room_by_source_id[source_room_id] = desired
            room_match_meta[source_room_id] = {
                "method": method,
                "confidence": round(confidence, 3) if confidence is not None else None,
            }

    matched_apple_ids: set[str] = set()
    device_rows: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []

    for room in ha_inventory.get("rooms", []):
        room_id = str(room.get("id") or "")
        desired_room = desired_room_by_source_id.get(room_id)
        for device in room.get("devices", []):
            device_id = str(device.get("id") or "")
            if not device_id:
                continue
            device_name = device.get("name") or device_id
            manual_id = str(accessory_map.get(device_id) or "")
            candidates: list[dict[str, Any]] = []
            match_method: str | None = None
            identifiers = _ha_identifier_candidates(device)

            if manual_id:
                manual = accessories_by_id.get(manual_id)
                if manual is None:
                    match_method = "manual_missing"
                elif manual_id in matched_apple_ids:
                    match_method = "manual_conflict"
                else:
                    candidates = [manual]
                    match_method = "manual_accessory"
            else:
                serial_matches: dict[str, dict[str, Any]] = {}
                for identifier in identifiers:
                    for accessory in accessories_by_serial.get(identifier, []):
                        accessory_id = str(accessory.get("id") or "")
                        if accessory_id and accessory_id not in matched_apple_ids:
                            serial_matches[accessory_id] = accessory
                if len(serial_matches) == 1:
                    candidates = list(serial_matches.values())
                    match_method = "serial"
                elif len(serial_matches) > 1:
                    candidates = list(serial_matches.values())
                    match_method = "serial_ambiguous"
                else:
                    name_key = _normalise(device_name)
                    model_key = _normalise(device.get("model"))
                    exact = []
                    for accessory in accessories:
                        accessory_id = str(accessory.get("id") or "")
                        if not accessory_id or accessory_id in matched_apple_ids:
                            continue
                        if _normalise(accessory.get("name")) != name_key:
                            continue
                        accessory_model = _normalise(accessory.get("model"))
                        if model_key and accessory_model and accessory_model != model_key:
                            continue
                        exact.append(accessory)
                    if len(exact) == 1:
                        candidates = exact
                        match_method = "name_model" if model_key else "name"
                    elif len(exact) > 1:
                        candidates = exact
                        match_method = "name_ambiguous"

            if len(candidates) != 1:
                device_rows.append(
                    {
                        "source_device_id": device_id,
                        "source_device_name": device_name,
                        "hue_device_id": device_id,
                        "hue_device_name": device_name,
                        "source_room_id": room_id,
                        "source_room_name": room.get("name"),
                        "hue_room_id": room_id,
                        "hue_room_name": room.get("name"),
                        "status": "ambiguous_accessory" if candidates else "unmatched_accessory",
                        "match_method": match_method,
                        "hue_identifiers": sorted(identifiers),
                        "source_manufacturer": device.get("manufacturer"),
                        "source_model": device.get("model"),
                        "candidates": [
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "room_id": item.get("room_id"),
                                "room_name": item.get("room_name"),
                                "manufacturer": item.get("manufacturer"),
                                "model": item.get("model"),
                            }
                            for item in candidates
                        ],
                    }
                )
                continue

            accessory = candidates[0]
            accessory_id = str(accessory["id"])
            matched_apple_ids.add(accessory_id)
            current_room_id = (
                str(accessory.get("room_id")) if accessory.get("room_id") is not None else None
            )
            if not desired_room:
                status = "missing_home_room"
            elif current_room_id == str(desired_room["id"]):
                status = "already_correct"
            else:
                status = "move"
                moves.append(
                    {
                        "accessory_id": accessory_id,
                        "accessory_name": accessory.get("name"),
                        "from_room_id": current_room_id,
                        "from_room_name": accessory.get("room_name"),
                        "to_room_id": str(desired_room["id"]),
                        "to_room_name": desired_room.get("name"),
                        "source_device_id": device_id,
                        "source_device_name": device_name,
                        "hue_device_id": device_id,
                        "hue_device_name": device_name,
                        "source_room_id": room_id,
                        "source_room_name": room.get("name"),
                        "hue_room_id": room_id,
                        "hue_room_name": room.get("name"),
                        "match_method": match_method,
                        "room_match_method": room_match_meta.get(room_id, {}).get("method"),
                        "room_match_confidence": room_match_meta.get(room_id, {}).get("confidence"),
                    }
                )

            device_rows.append(
                {
                    "source_device_id": device_id,
                    "source_device_name": device_name,
                    "hue_device_id": device_id,
                    "hue_device_name": device_name,
                    "source_room_id": room_id,
                    "source_room_name": room.get("name"),
                    "hue_room_id": room_id,
                    "hue_room_name": room.get("name"),
                    "apple_accessory_id": accessory_id,
                    "apple_accessory_name": accessory.get("name"),
                    "apple_room_id": current_room_id,
                    "apple_room_name": accessory.get("room_name"),
                    "desired_apple_room_id": str(desired_room["id"]) if desired_room else None,
                    "desired_apple_room_name": desired_room.get("name") if desired_room else None,
                    "status": status,
                    "match_method": match_method,
                    "hue_identifiers": sorted(identifiers),
                    "apple_serial_number": accessory.get("serial_number"),
                    "source_manufacturer": device.get("manufacturer"),
                    "source_model": device.get("model"),
                }
            )

    device_rows_by_room: dict[str, list[dict[str, Any]]] = {}
    for row in device_rows:
        device_rows_by_room.setdefault(str(row.get("source_room_id") or ""), []).append(row)

    accessories_by_room: dict[str, list[dict[str, Any]]] = {}
    for accessory in accessories:
        accessories_by_room.setdefault(str(accessory.get("room_id") or ""), []).append(accessory)

    matched_by_apple = {
        str(row["apple_accessory_id"]): row
        for row in device_rows
        if row.get("apple_accessory_id")
    }
    moves_by_room: dict[str, list[dict[str, Any]]] = {}
    for move in moves:
        moves_by_room.setdefault(str(move.get("source_room_id") or ""), []).append(move)

    for room_row in room_rows:
        room_id = str(room_row.get("source_room_id") or "")
        target_room_id = str(room_row.get("apple_room_id") or "")
        source_devices = device_rows_by_room.get(room_id, [])
        room_row["hue_devices"] = [
            {
                "id": row.get("source_device_id"),
                "name": row.get("source_device_name"),
                "status": row.get("status"),
                "match_method": row.get("match_method"),
                "hue_identifiers": row.get("hue_identifiers", []),
                "apple_serial_number": row.get("apple_serial_number"),
                "apple_accessory_id": row.get("apple_accessory_id"),
                "apple_accessory_name": row.get("apple_accessory_name"),
                "apple_current_room_id": row.get("apple_room_id"),
                "apple_current_room_name": row.get("apple_room_name"),
                "manufacturer": row.get("source_manufacturer"),
                "model": row.get("source_model"),
            }
            for row in source_devices
        ]
        target_accessories = accessories_by_room.get(target_room_id, []) if target_room_id else []
        room_row["apple_accessories"] = [
            {
                "id": accessory.get("id"),
                "name": accessory.get("name"),
                "manufacturer": accessory.get("manufacturer"),
                "model": accessory.get("model"),
                "is_bridged": bool(accessory.get("is_bridged")),
                "bridge_id": accessory.get("bridge_id"),
                "bridge_name": accessory.get("bridge_name"),
                "bridge_manufacturer": accessory.get("bridge_manufacturer"),
                "bridge_model": accessory.get("bridge_model"),
                "origin": "home_assistant"
                if str(accessory.get("id") or "") in matched_by_apple
                else "other",
                "matched_hue_device_id": matched_by_apple.get(
                    str(accessory.get("id") or ""), {}
                ).get("source_device_id"),
                "matched_hue_device_name": matched_by_apple.get(
                    str(accessory.get("id") or ""), {}
                ).get("source_device_name"),
            }
            for accessory in target_accessories
        ]
        room_row["planned_moves"] = copy.deepcopy(moves_by_room.get(room_id, []))
        room_row["impact"] = {
            "hue_device_count": len(source_devices),
            "apple_accessory_count": len(target_accessories),
            "move_count": len(room_row["planned_moves"]),
            "already_correct_count": sum(
                row.get("status") == "already_correct" for row in source_devices
            ),
        }

    status_counts: dict[str, int] = {}
    for row in device_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    return {
        "source_kind": "home_assistant",
        "source_label": "Home Assistant",
        "home": copy.deepcopy(home),
        "inventory_received_at": apple_inventory.get("received_at"),
        "source_inventory_captured_at": ha_inventory.get("captured_at"),
        "rooms": room_rows,
        "devices": device_rows,
        "actions": moves,
        "accessory_map": copy.deepcopy(accessory_map),
        "unmatched_apple_accessories": [
            accessory
            for accessory in accessories
            if str(accessory.get("id") or "") not in matched_apple_ids
        ],
        "summary": {
            "source_rooms": len(room_rows),
            "hue_rooms": len(room_rows),
            "mapped_rooms": sum(row["status"] == "mapped" for row in room_rows),
            "unmapped_rooms": sum(row["status"] == "unmapped" for row in room_rows),
            "devices": len(device_rows),
            "moves": len(moves),
            "already_correct": status_counts.get("already_correct", 0),
            "unmatched_accessories": status_counts.get("unmatched_accessory", 0),
            "ambiguous_accessories": status_counts.get("ambiguous_accessory", 0),
            "missing_home_rooms": status_counts.get("missing_home_room", 0),
        },
    }


def profile_from_environment() -> HomeAssistantProfile | None:
    url = os.environ.get("HOME_ASSISTANT_URL", "").strip()
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "").strip()
    if not url or not token:
        return None
    verify_tls = os.environ.get("HOME_ASSISTANT_VERIFY_TLS", "").strip().lower()
    return HomeAssistantProfile(
        url=url,
        token=token,
        verify_tls=verify_tls in {"1", "true", "yes", "on"},
    )
