from __future__ import annotations

import re
import unicodedata
from collections import Counter
from copy import deepcopy
from typing import Any

HUE_HINTS = ("hue", "philips", "signify")


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _model_key(value: Any) -> str:
    key = _normalise(value)
    if key in {"", "unknown", "na", "none", "null"}:
        return ""
    return key


def _is_hue_bridge(bridge: dict) -> bool:
    model = str(bridge.get("model") or "").upper()
    haystack = (
        f"{bridge.get('manufacturer') or ''} "
        f"{bridge.get('name') or ''} "
        f"{bridge.get('model') or ''}"
    ).lower()
    return model.startswith("BSB") or any(hint in haystack for hint in HUE_HINTS)


def _is_hue_accessory(accessory: dict) -> bool:
    bridge_haystack = (
        f"{accessory.get('bridge_manufacturer') or ''} "
        f"{accessory.get('bridge_name') or ''} "
        f"{accessory.get('bridge_model') or ''}"
    ).lower()
    own_haystack = (
        f"{accessory.get('manufacturer') or ''} "
        f"{accessory.get('name') or ''} "
        f"{accessory.get('model') or ''}"
    ).lower()
    if any(hint in bridge_haystack for hint in HUE_HINTS):
        return True
    return any(hint in own_haystack for hint in HUE_HINTS)


def _bridge_mapping(
    hue_trees: dict[str, dict],
    inventory: dict,
) -> tuple[list[dict], dict[str, str], set[str]]:
    apple_bridges = [
        bridge
        for bridge in inventory.get("bridges", [])
        if bridge.get("id") and _is_hue_bridge(bridge)
    ]
    unused = {str(bridge["id"]) for bridge in apple_bridges}
    apple_to_profile: dict[str, str] = {}
    rows: list[dict] = []

    for profile, tree in sorted(hue_trees.items()):
        hue_info = tree.get("bridge") or {}
        hue_model = _normalise(hue_info.get("modelid"))
        hue_names = {
            _normalise(profile),
            _normalise(hue_info.get("name")),
        } - {""}

        available = [
            bridge
            for bridge in apple_bridges
            if str(bridge["id"]) in unused
        ]
        name_matches = [
            bridge
            for bridge in available
            if _normalise(bridge.get("name")) in hue_names
            and (
                not hue_model
                or _normalise(bridge.get("model")) == hue_model
            )
        ]
        model_matches = [
            bridge
            for bridge in available
            if hue_model and _normalise(bridge.get("model")) == hue_model
        ]

        selected = None
        method = None
        candidates: list[dict] = []
        if len(name_matches) == 1:
            selected = name_matches[0]
            method = "name_model"
        elif len(model_matches) == 1:
            selected = model_matches[0]
            method = "unique_model"
        elif name_matches:
            candidates = name_matches
        elif model_matches:
            candidates = model_matches

        if selected:
            apple_id = str(selected["id"])
            unused.discard(apple_id)
            apple_to_profile[apple_id] = profile

        rows.append(
            {
                "profile": profile,
                "hue_name": hue_info.get("name"),
                "hue_model": hue_info.get("modelid"),
                "hue_bridgeid": hue_info.get("bridgeid"),
                "hue_devices": sum(
                    len(room.get("devices", []))
                    for room in tree.get("rooms", [])
                ),
                "apple_bridge_id": (
                    str(selected.get("id"))
                    if selected
                    else None
                ),
                "apple_bridge_name": (
                    selected.get("name")
                    if selected
                    else None
                ),
                "apple_bridge_model": (
                    selected.get("model")
                    if selected
                    else None
                ),
                "apple_bridge_accessories": (
                    len(selected.get("bridged_accessory_ids", []))
                    if selected
                    else None
                ),
                "match_method": method,
                "status": (
                    "matched"
                    if selected
                    else ("ambiguous" if candidates else "missing")
                ),
                "candidate_apple_bridges": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "model": item.get("model"),
                    }
                    for item in candidates
                ],
            }
        )

    return rows, apple_to_profile, unused


def build_apple_home_multi_bridge_audit(
    hue_trees: dict[str, dict],
    inventory: dict,
    *,
    accessory_maps_by_bridge: dict[str, dict[str, str]] | None = None,
    ignored_devices_by_bridge: dict[str, set[str]] | None = None,
) -> dict:
    """Compare Apple Home with every configured Hue bridge in one read-only view."""

    accessory_maps_by_bridge = accessory_maps_by_bridge or {}
    ignored_devices_by_bridge = ignored_devices_by_bridge or {}

    bridge_rows, apple_bridge_to_profile, unused_bridge_ids = _bridge_mapping(
        hue_trees,
        inventory,
    )

    hue_devices: list[dict] = []
    hue_by_profile_id: dict[tuple[str, str], dict] = {}
    by_name_model: dict[tuple[str, str], list[dict]] = {}
    by_name_model_room: dict[tuple[str, str, str], list[dict]] = {}

    for profile, tree in hue_trees.items():
        for room in tree.get("rooms", []):
            room_name = room.get("name")
            for device in room.get("devices", []):
                device_id = str(device.get("id") or "")
                if not device_id:
                    continue
                row = {
                    "profile": profile,
                    "id": device_id,
                    "name": device.get("name"),
                    "model": device.get("model"),
                    "room_id": room.get("id"),
                    "room_name": room_name,
                }
                hue_devices.append(row)
                hue_by_profile_id[(profile, device_id)] = row

                name_key = _normalise(device.get("name"))
                model_key = _model_key(device.get("model"))
                room_key = _normalise(room_name)
                if name_key and model_key:
                    by_name_model.setdefault(
                        (name_key, model_key),
                        [],
                    ).append(row)
                    if room_key:
                        by_name_model_room.setdefault(
                            (name_key, model_key, room_key),
                            [],
                        ).append(row)

    persistent_by_apple_id: dict[str, list[dict]] = {}
    for profile, mapping in accessory_maps_by_bridge.items():
        for hue_device_id, apple_accessory_id in mapping.items():
            device = hue_by_profile_id.get(
                (profile, str(hue_device_id))
            )
            if device:
                persistent_by_apple_id.setdefault(
                    str(apple_accessory_id),
                    [],
                ).append(device)

    accessories = [
        accessory
        for accessory in inventory.get("accessories", [])
        if accessory.get("id") and _is_hue_accessory(accessory)
    ]

    duplicate_groups: dict[tuple[str, str, str], list[dict]] = {}
    for accessory in accessories:
        key = (
            _normalise(accessory.get("name")),
            _model_key(accessory.get("model")),
            _normalise(accessory.get("room_name")),
        )
        if all(key):
            duplicate_groups.setdefault(key, []).append(accessory)

    items: list[dict] = []
    counts: Counter[str] = Counter()

    for accessory in accessories:
        accessory_id = str(accessory["id"])
        name_key = _normalise(accessory.get("name"))
        model_key = _model_key(accessory.get("model"))
        room_key = _normalise(accessory.get("room_name"))
        parent_bridge_id = str(accessory.get("bridge_id") or "")
        apple_profile = apple_bridge_to_profile.get(parent_bridge_id)

        persistent = persistent_by_apple_id.get(accessory_id, [])
        candidates: list[dict] = []
        match_source = None
        confidence = None

        if len(persistent) == 1:
            candidates = persistent
            match_source = "persistent"
            confidence = 1.0
        elif name_key and model_key:
            room_matches = (
                by_name_model_room.get(
                    (name_key, model_key, room_key),
                    [],
                )
                if room_key
                else []
            )
            exact_matches = by_name_model.get(
                (name_key, model_key),
                [],
            )
            if len(room_matches) == 1:
                candidates = room_matches
                match_source = "exact_name_model_room"
                confidence = 1.0
            elif len(exact_matches) == 1:
                candidates = exact_matches
                match_source = "exact_name_model"
                confidence = 0.95
            else:
                candidates = exact_matches

        expected = candidates[0] if len(candidates) == 1 else None

        duplicate_key = (name_key, model_key, room_key)
        duplicate_group = (
            duplicate_groups.get(duplicate_key, [])
            if all(duplicate_key)
            else []
        )
        duplicate_ids = [
            str(item.get("id"))
            for item in duplicate_group
            if item.get("id")
        ]

        flags: list[str] = []
        if accessory.get("reachable") is False:
            flags.append("unreachable")
        if len(duplicate_group) > 1:
            flags.append("duplicate")

        if expected:
            if apple_profile and expected["profile"] != apple_profile:
                flags.append("migrated")
            elif not apple_profile:
                flags.append("unmapped_bridge")
        elif len(candidates) > 1 or len(persistent) > 1:
            flags.append("ambiguous")
        elif apple_profile and name_key and model_key:
            flags.append("orphan")
        elif not apple_profile:
            flags.append("unmapped_bridge")
        else:
            flags.append("unresolved")

        ignored_power_off = False
        if expected:
            ignored_power_off = (
                expected["id"]
                in ignored_devices_by_bridge.get(
                    expected["profile"],
                    set(),
                )
            )

        if "migrated" in flags and "duplicate" in flags:
            status = "stale_after_migration"
            severity = "warning"
        elif "migrated" in flags:
            status = "migrated"
            severity = "warning"
        elif "orphan" in flags:
            status = "orphan"
            severity = "warning"
        elif "ambiguous" in flags:
            status = "ambiguous"
            severity = "info"
        elif "unmapped_bridge" in flags:
            status = "unmapped_bridge"
            severity = "warning"
        elif "unreachable" in flags and ignored_power_off:
            status = "expected_offline"
            severity = "info"
        elif "unreachable" in flags:
            status = "unreachable"
            severity = "warning"
        elif "duplicate" in flags:
            status = "duplicate"
            severity = "warning"
        elif "unresolved" in flags:
            status = "unresolved"
            severity = "info"
        else:
            status = "ok"
            severity = "good"

        counts[status] += 1
        items.append(
            {
                "apple_accessory_id": accessory_id,
                "name": accessory.get("name"),
                "model": accessory.get("model"),
                "room_id": accessory.get("room_id"),
                "room_name": accessory.get("room_name"),
                "reachable": accessory.get("reachable"),
                "apple_bridge_id": parent_bridge_id or None,
                "apple_bridge_name": accessory.get("bridge_name"),
                "apple_bridge_model": accessory.get("bridge_model"),
                "apple_bridge_profile": apple_profile,
                "expected_bridge_profile": (
                    expected.get("profile")
                    if expected
                    else None
                ),
                "expected_hue_device": deepcopy(expected),
                "match_source": match_source,
                "confidence": confidence,
                "candidate_hue_devices": deepcopy(candidates[:5]),
                "duplicate_apple_accessory_ids": duplicate_ids,
                "duplicate_count": len(duplicate_group),
                "ignored_power_off": ignored_power_off,
                "flags": flags,
                "status": status,
                "severity": severity,
            }
        )

    severity_order = {"warning": 0, "info": 1, "good": 2}
    items.sort(
        key=lambda item: (
            severity_order.get(str(item.get("severity")), 3),
            _normalise(item.get("room_name")),
            _normalise(item.get("name")),
        )
    )

    apple_bridges = [
        bridge
        for bridge in inventory.get("bridges", [])
        if bridge.get("id") and _is_hue_bridge(bridge)
    ]
    unmatched_apple_bridges = [
        {
            "id": bridge.get("id"),
            "name": bridge.get("name"),
            "model": bridge.get("model"),
            "manufacturer": bridge.get("manufacturer"),
            "bridged_accessories": len(
                bridge.get("bridged_accessory_ids", [])
            ),
        }
        for bridge in apple_bridges
        if str(bridge.get("id")) in unused_bridge_ids
    ]

    return {
        "home": deepcopy(inventory.get("home") or {}),
        "inventory_received_at": inventory.get("received_at"),
        "bridges": bridge_rows,
        "unmatched_apple_hue_bridges": unmatched_apple_bridges,
        "summary": {
            "configured_hue_bridges": len(hue_trees),
            "matched_bridges": sum(
                row["status"] == "matched"
                for row in bridge_rows
            ),
            "apple_hue_accessories": len(accessories),
            "healthy": counts["ok"],
            "expected_offline": counts["expected_offline"],
            "unreachable": counts["unreachable"],
            "probable_migrations": (
                counts["migrated"]
                + counts["stale_after_migration"]
            ),
            "duplicates": sum(
                "duplicate" in item["flags"]
                for item in items
            ),
            "orphans": counts["orphan"],
            "ambiguous": counts["ambiguous"],
            "unresolved": counts["unresolved"],
            "unmapped_bridge": counts["unmapped_bridge"],
            "warnings": sum(
                item["severity"] == "warning"
                for item in items
            ),
        },
        "items": items,
    }
