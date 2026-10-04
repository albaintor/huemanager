from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

APPLE_HOME_STATE_SCHEMA = 1

ROOM_WORD_ALIASES = {
    "living": "salon",
    "livingroom": "salon",
    "sejour": "salon",
    "séjour": "salon",
    "lounge": "salon",
    "kitchen": "cuisine",
    "bedroom": "chambre",
    "office": "bureau",
    "study": "bureau",
    "bathroom": "sdb",
    "bath": "sdb",
    "salledebain": "sdb",
    "salledebains": "sdb",
    "toilet": "wc",
    "toilets": "wc",
    "restroom": "wc",
    "hall": "entree",
    "hallway": "entree",
    "entry": "entree",
    "entrance": "entree",
    "dining": "sam",
    "diningroom": "sam",
    "salleamanger": "sam",
    "garage": "garage",
    "garden": "jardin",
    "outdoor": "exterieur",
    "outside": "exterieur",
    "terrace": "terrasse",
    "patio": "terrasse",
    "parents": "parent",
    "parentale": "parent",
    "master": "parent",
}

GENERIC_DEVICE_WORDS = {
    "hue",
    "philips",
    "signify",
    "device",
    "appareil",
}

HUE_ACCESSORY_HINTS = ("hue", "philips", "signify")
FUZZY_MATCHABLE_HUE_SERVICE_TYPES = {
    "light",
    "motion",
    "temperature",
    "light_level",
    "contact",
}


def _words(value: str | None) -> list[str]:
    if not value:
        return []
    ascii_value = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in ascii_value if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", ascii_value.lower())


def _canonical_room_tokens(value: str | None) -> list[str]:
    words = _words(value)
    compact = "".join(words)
    phrase_alias = ROOM_WORD_ALIASES.get(compact)
    if phrase_alias:
        return [phrase_alias]
    return [ROOM_WORD_ALIASES.get(word, word) for word in words]


def _similarity(
    left: str | None,
    right: str | None,
    *,
    room: bool = False,
    ignore_generic_device_words: bool = False,
) -> float:
    if _normalise(left) == _normalise(right) and _normalise(left):
        return 1.0

    left_words = _canonical_room_tokens(left) if room else _words(left)
    right_words = _canonical_room_tokens(right) if room else _words(right)
    if ignore_generic_device_words:
        left_words = [word for word in left_words if word not in GENERIC_DEVICE_WORDS]
        right_words = [word for word in right_words if word not in GENERIC_DEVICE_WORDS]

    if not left_words or not right_words:
        return 0.0

    left_set = set(left_words)
    right_set = set(right_words)
    if left_set == right_set:
        return 0.98
    intersection = left_set & right_set
    union = left_set | right_set
    jaccard = len(intersection) / len(union) if union else 0.0
    containment = len(intersection) / min(len(left_set), len(right_set))
    sequence = SequenceMatcher(
        None,
        " ".join(left_words),
        " ".join(right_words),
    ).ratio()

    score = max(sequence, 0.55 * jaccard + 0.45 * containment)
    if containment == 1.0 and intersection:
        score = max(score, 0.90)
    return min(score, 1.0)


def _best_fuzzy_match(
    source_name: str,
    candidates: list[dict],
    *,
    field: str = "name",
    room: bool = False,
    threshold: float,
    ambiguity_gap: float,
    ignore_generic_device_words: bool = False,
) -> tuple[dict | None, float, list[dict]]:
    scored = [
        (
            _similarity(
                source_name,
                candidate.get(field),
                room=room,
                ignore_generic_device_words=ignore_generic_device_words,
            ),
            candidate,
        )
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    suggestions = [
        {
            "id": item.get("id"),
            "name": item.get(field),
            "score": round(score, 3),
        }
        for score, item in scored[:3]
        if score > 0
    ]
    if not scored or scored[0][0] < threshold:
        return None, scored[0][0] if scored else 0.0, suggestions
    top_score, top = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if second_score >= threshold and top_score - second_score < ambiguity_gap:
        return None, top_score, suggestions
    return top, top_score, suggestions


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalise(value: str | None) -> str:
    if not value:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in ascii_value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _normalise_identifier(value: str | None) -> str:
    return re.sub(r"[^a-f0-9]+", "", (value or "").lower())


def _hue_identifier_candidates(device: dict) -> set[str]:
    identifiers = device.get("identifiers", {})
    candidates: set[str] = set()

    for value in identifiers.get("zigbee_macs", []):
        normalised = _normalise_identifier(value)
        if normalised:
            candidates.add(normalised)

    for value in identifiers.get("v1_uniqueids", []):
        normalised = _normalise_identifier(value)
        if normalised:
            candidates.add(normalised)
        # Hue v1 uniqueids commonly append an endpoint such as "-0b" to the EUI-64.
        match = re.match(r"^(.*)-[0-9a-fA-F]{2}$", str(value))
        if match:
            base = _normalise_identifier(match.group(1))
            if base:
                candidates.add(base)

    for field in identifiers.get("pairing_fields", []):
        normalised = _normalise_identifier(str(field.get("value") or ""))
        if normalised:
            candidates.add(normalised)

    return candidates


def _hue_device_allows_fuzzy_match(device: dict) -> bool:
    services = device.get("services")
    if services is None:
        # Preserve compatibility with older/incomplete inventory payloads that
        # predate explicit service metadata.
        return True
    service_types = {
        str(service.get("type") or "")
        for service in services
        if service.get("type")
    }
    return bool(service_types & FUZZY_MATCHABLE_HUE_SERVICE_TYPES)


def _apple_accessories_for_hue_bridge(
    hue_tree: dict,
    accessories: list[dict],
) -> list[dict]:
    """Return Apple accessories that belong to the Hue bridge currently analysed.

    Prefer the bridge model (BSB003, BSB002, ...), then bridge name. Only fall
    back to generic Hue-origin classification when the inventory does not expose
    enough bridge metadata. This prevents devices from two Hue bridges from being
    mixed into the same synchronization plan.
    """
    bridge = hue_tree.get("bridge") or {}
    model_key = _normalise(bridge.get("modelid"))
    name_key = _normalise(bridge.get("name"))

    hue_like = [
        accessory
        for accessory in accessories
        if _apple_accessory_origin(accessory) == "hue"
    ]

    if model_key:
        by_model = [
            accessory
            for accessory in hue_like
            if _normalise(accessory.get("bridge_model")) == model_key
        ]
        if by_model:
            return by_model

    if name_key:
        by_name = [
            accessory
            for accessory in hue_like
            if _normalise(accessory.get("bridge_name")) == name_key
        ]
        if by_name:
            return by_name

    if hue_like:
        return hue_like

    return [
        accessory
        for accessory in accessories
        if _apple_accessory_origin(accessory) == "unknown"
    ]


def _apple_accessory_origin(accessory: dict) -> str:
    """Classify an Apple Home accessory for Hue-focused previews.

    "hue" means the HomeKit metadata clearly identifies Philips/Signify/Hue.
    "other" means a different manufacturer is explicitly reported.
    "unknown" keeps accessories whose origin cannot be established safely.
    """
    manufacturer = str(accessory.get("manufacturer") or "").strip()
    model = str(accessory.get("model") or "").strip()
    name = str(accessory.get("name") or "").strip()
    bridge_name = str(accessory.get("bridge_name") or "").strip()
    bridge_manufacturer = str(accessory.get("bridge_manufacturer") or "").strip()
    bridge_model = str(accessory.get("bridge_model") or "").strip()

    own_haystack = f"{manufacturer} {model} {name}".lower()
    bridge_haystack = f"{bridge_manufacturer} {bridge_model} {bridge_name}".lower()

    # The strongest signal for third-party Hue-compatible devices is that
    # HomeKit explicitly exposes them behind a Hue bridge.
    if any(hint in bridge_haystack for hint in HUE_ACCESSORY_HINTS):
        return "hue"

    if any(hint in own_haystack for hint in HUE_ACCESSORY_HINTS):
        if "bridge" in own_haystack:
            return "hue_bridge"
        return "hue"

    # A bridged accessory behind a clearly non-Hue bridge is outside this
    # Hue-focused synchronization scope, regardless of its own manufacturer.
    if accessory.get("is_bridged") and bridge_manufacturer:
        return "other"
    if manufacturer:
        return "other"
    return "unknown"


def load_apple_home_state(path: Path) -> dict:
    if not path.exists():
        return {
            "schema": APPLE_HOME_STATE_SCHEMA,
            "updated_at": None,
            "inventory": None,
            "room_maps": {},
            "room_selections": {},
            "accessory_maps": {},
            "last_sync": None,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != APPLE_HOME_STATE_SCHEMA:
        raise ValueError(
            f"Unsupported Apple Home state schema: {payload.get('schema')!r}"
        )
    payload.setdefault("inventory", None)
    payload.setdefault("room_maps", {})
    payload.setdefault("room_selections", {})
    payload.setdefault("accessory_maps", {})
    payload.setdefault("last_sync", None)
    return payload


def save_apple_home_state(state: dict, path: Path) -> None:
    payload = copy.deepcopy(state)
    payload["schema"] = APPLE_HOME_STATE_SCHEMA
    payload["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def store_inventory(state: dict, inventory: dict) -> dict:
    result = copy.deepcopy(state)
    payload = copy.deepcopy(inventory)
    payload["received_at"] = _now()
    result["inventory"] = payload
    return result


def store_room_map(
    state: dict,
    bridge_profile: str,
    home_id: str,
    room_map: dict[str, str],
) -> dict:
    result = copy.deepcopy(state)
    result.setdefault("room_maps", {}).setdefault(bridge_profile, {})[home_id] = {
        str(hue_room_id): str(apple_room_id or "")
        for hue_room_id, apple_room_id in room_map.items()
        if hue_room_id
    }
    return result


def get_room_map(state: dict, bridge_profile: str, home_id: str) -> dict[str, str]:
    return copy.deepcopy(
        state.get("room_maps", {}).get(bridge_profile, {}).get(home_id, {})
    )


def store_room_selection(
    state: dict,
    bridge_profile: str,
    home_id: str,
    hue_room_ids: list[str],
) -> dict:
    result = copy.deepcopy(state)
    result.setdefault("room_selections", {}).setdefault(bridge_profile, {})[home_id] = sorted(
        {
            str(room_id)
            for room_id in hue_room_ids
            if str(room_id)
        }
    )
    return result


def get_room_selection(
    state: dict,
    bridge_profile: str,
    home_id: str,
) -> list[str] | None:
    bridge = state.get("room_selections", {}).get(bridge_profile, {})
    if home_id not in bridge:
        return None
    return [
        str(room_id)
        for room_id in copy.deepcopy(bridge.get(home_id, []))
        if str(room_id)
    ]


def store_accessory_map(
    state: dict,
    bridge_profile: str,
    home_id: str,
    accessory_map: dict[str, str],
) -> dict:
    result = copy.deepcopy(state)
    result.setdefault("accessory_maps", {}).setdefault(bridge_profile, {})[home_id] = {
        str(hue_device_id): str(apple_accessory_id)
        for hue_device_id, apple_accessory_id in accessory_map.items()
        if str(hue_device_id) and str(apple_accessory_id)
    }
    return result


def get_accessory_map(
    state: dict,
    bridge_profile: str,
    home_id: str,
) -> dict[str, str]:
    return copy.deepcopy(
        state.get("accessory_maps", {}).get(bridge_profile, {}).get(home_id, {})
    )


def record_sync_result(state: dict, result: dict) -> dict:
    updated = copy.deepcopy(state)
    updated["last_sync"] = {
        "at": _now(),
        **copy.deepcopy(result),
    }
    return updated


def _unique_index(items: list[dict], key_getter) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        key = key_getter(item)
        if key:
            buckets.setdefault(key, []).append(item)
    return {key: values[0] for key, values in buckets.items() if len(values) == 1}




def build_apple_home_identity_diagnostics(
    hue_tree: dict,
    inventory: dict,
    *,
    room_map: dict[str, str] | None = None,
    accessory_map: dict[str, str] | None = None,
) -> dict:
    """Compare every public Apple/Hue identity surface without using it to move devices."""
    room_map = room_map or {}
    accessory_map = accessory_map or {}
    plan = build_apple_home_sync_plan(
        hue_tree,
        inventory,
        room_map=room_map,
        accessory_map=accessory_map,
    )

    hue_devices: dict[str, dict] = {}
    for room in hue_tree.get("rooms", []):
        for device in room.get("devices", []):
            device_id = str(device.get("id") or "")
            if not device_id:
                continue
            hue_devices[device_id] = {
                **copy.deepcopy(device),
                "_room_id": str(room.get("id") or ""),
                "_room_name": room.get("name"),
            }

    apple_accessories = [
        accessory
        for accessory in inventory.get("accessories", [])
        if accessory.get("id")
    ]
    apple_by_id = {
        str(accessory["id"]): accessory
        for accessory in apple_accessories
    }
    hue_apple_accessories = _apple_accessories_for_hue_bridge(
        hue_tree,
        apple_accessories,
    )

    room_plan_by_hue_id = {
        str(room.get("hue_room_id")): room
        for room in plan.get("rooms", [])
        if room.get("hue_room_id")
    }

    anchors: list[dict] = []
    anchored_hue_ids: set[str] = set()
    anchored_apple_ids: set[str] = set()

    def add_anchor(
        hue_device: dict,
        apple_accessory: dict,
        source: str,
        confidence: float,
    ) -> None:
        hue_device_id = str(hue_device.get("id") or "")
        apple_accessory_id = str(apple_accessory.get("id") or "")
        if (
            not hue_device_id
            or not apple_accessory_id
            or hue_device_id in anchored_hue_ids
            or apple_accessory_id in anchored_apple_ids
        ):
            return

        identifiers = hue_device.get("identifiers", {})
        hue_identifier_values = _hue_identifier_candidates(hue_device)
        apple_serial = _normalise_identifier(
            apple_accessory.get("serial_number")
        )
        apple_uuid = _normalise_identifier(apple_accessory_id)
        apple_legacy_uuid = _normalise_identifier(
            apple_accessory.get("legacy_identifier")
        )
        hap_instance_id = apple_accessory.get("hap_instance_id")
        v1_numeric_ids = [
            int(value)
            for value in identifiers.get("v1_numeric_ids", [])
            if isinstance(value, int) or str(value).isdigit()
        ]

        comparisons = {
            "serial_equals_hue_identifier": bool(
                apple_serial and apple_serial in hue_identifier_values
            ),
            "apple_uuid_equals_hue_identifier": bool(
                apple_uuid and apple_uuid in hue_identifier_values
            ),
            "apple_legacy_uuid_equals_hue_identifier": bool(
                apple_legacy_uuid
                and apple_legacy_uuid in hue_identifier_values
            ),
            "hap_aid_equals_v1_numeric_id": bool(
                hap_instance_id is not None
                and int(hap_instance_id) in v1_numeric_ids
            ),
        }

        offsets = []
        if hap_instance_id is not None:
            for numeric_id in v1_numeric_ids:
                offsets.append(int(hap_instance_id) - int(numeric_id))

        anchors.append(
            {
                "source": source,
                "confidence": confidence,
                "hue": {
                    "id_v2": hue_device_id,
                    "name": hue_device.get("name"),
                    "room_id": hue_device.get("_room_id"),
                    "room_name": hue_device.get("_room_name"),
                    "model": hue_device.get("model"),
                    "identifiers": copy.deepcopy(identifiers),
                },
                "apple": {
                    "id": apple_accessory_id,
                    "name": apple_accessory.get("name"),
                    "room_id": apple_accessory.get("room_id"),
                    "room_name": apple_accessory.get("room_name"),
                    "model": apple_accessory.get("model"),
                    "serial_number": apple_accessory.get("serial_number"),
                    "legacy_identifier": apple_accessory.get("legacy_identifier"),
                    "hap_instance_id": hap_instance_id,
                    "vendor_accessory": apple_accessory.get("vendor_accessory"),
                    "bridge_id": apple_accessory.get("bridge_id"),
                    "bridge_name": apple_accessory.get("bridge_name"),
                    "bridge_child_index": apple_accessory.get("bridge_child_index"),
                    "bridge_reported_identifier_index": apple_accessory.get(
                        "bridge_reported_identifier_index"
                    ),
                    "bridge_legacy_identifier_index": apple_accessory.get(
                        "bridge_legacy_identifier_index"
                    ),
                },
                "comparisons": comparisons,
                "hap_minus_v1_offsets": offsets,
            }
        )
        anchored_hue_ids.add(hue_device_id)
        anchored_apple_ids.add(apple_accessory_id)

    # Ground truth first: explicit user mappings and real exact identifier matches.
    for device_row in plan.get("devices", []):
        hue_device_id = str(device_row.get("hue_device_id") or "")
        apple_accessory_id = str(device_row.get("apple_accessory_id") or "")
        method = str(device_row.get("match_method") or "")
        if (
            hue_device_id in hue_devices
            and apple_accessory_id in apple_by_id
            and method in {"manual_accessory", "serial"}
        ):
            add_anchor(
                hue_devices[hue_device_id],
                apple_by_id[apple_accessory_id],
                method,
                1.0,
            )

    # Diagnostic-only anchors: unique exact name + exact model in the room already
    # mapped Hue -> Apple. These anchors never drive a HomeKit move.
    for hue_device_id, hue_device in hue_devices.items():
        if hue_device_id in anchored_hue_ids:
            continue
        room_plan = room_plan_by_hue_id.get(str(hue_device.get("_room_id") or ""))
        if not room_plan or not room_plan.get("apple_room_id"):
            continue
        name_key = _normalise(hue_device.get("name"))
        model_key = _normalise(hue_device.get("model"))
        candidates = []
        for accessory in hue_apple_accessories:
            accessory_id = str(accessory.get("id") or "")
            if accessory_id in anchored_apple_ids:
                continue
            if str(accessory.get("room_id") or "") != str(
                room_plan.get("apple_room_id") or ""
            ):
                continue
            if _normalise(accessory.get("name")) != name_key:
                continue
            apple_model_key = _normalise(accessory.get("model"))
            if model_key and apple_model_key and model_key != apple_model_key:
                continue
            candidates.append(accessory)
        if len(candidates) == 1:
            add_anchor(hue_device, candidates[0], "diagnostic_name_room_model", 0.8)

    offset_counter: Counter[int] = Counter()
    for anchor in anchors:
        if len(anchor.get("hap_minus_v1_offsets", [])) == 1:
            offset_counter[anchor["hap_minus_v1_offsets"][0]] += 1

    common_offsets = [
        {"offset": offset, "anchors": count}
        for offset, count in offset_counter.most_common(10)
    ]

    bridge_rows = inventory.get("bridges", [])
    bridge_identifier_checks = []
    for bridge in bridge_rows:
        actual = {
            _normalise_identifier(value)
            for value in bridge.get("bridged_accessory_ids", [])
            if value
        }
        actual_legacy = {
            _normalise_identifier(value)
            for value in bridge.get("bridged_accessory_legacy_ids", [])
            if value
        }
        reported = {
            _normalise_identifier(value)
            for value in bridge.get(
                "unique_identifiers_for_bridged_accessories", []
            )
            if value
        }
        legacy_reported = {
            _normalise_identifier(value)
            for value in bridge.get(
                "identifiers_for_bridged_accessories", []
            )
            if value
        }
        bridge_identifier_checks.append(
            {
                "id": bridge.get("id"),
                "name": bridge.get("name"),
                "manufacturer": bridge.get("manufacturer"),
                "model": bridge.get("model"),
                "hap_instance_id": bridge.get("hap_instance_id"),
                "vendor_accessory": bridge.get("vendor_accessory"),
                "bridged_accessories": len(actual),
                "reported_bridged_identifiers": len(reported),
                "reported_ids_equal_child_uuids": (
                    bool(actual) and actual == reported
                ),
                "overlap": len(actual & reported),
                "legacy_bridged_accessories": len(actual_legacy),
                "legacy_reported_bridged_identifiers": len(legacy_reported),
                "legacy_reported_ids_equal_child_ids": (
                    bool(actual_legacy) and actual_legacy == legacy_reported
                ),
                "legacy_overlap": len(actual_legacy & legacy_reported),
                "legacy_equals_unique_identifiers": (
                    bool(actual)
                    and bool(actual_legacy)
                    and actual == actual_legacy
                ),
            }
        )

    hue_with_identifiers = sum(
        bool(_hue_identifier_candidates(device))
        for device in hue_devices.values()
    )
    apple_with_serial = sum(
        bool(accessory.get("serial_number"))
        for accessory in hue_apple_accessories
    )
    apple_with_hap_aid = sum(
        accessory.get("hap_instance_id") is not None
        for accessory in hue_apple_accessories
    )
    apple_with_vendor_access = sum(
        accessory.get("vendor_accessory") is True
        for accessory in hue_apple_accessories
    )
    serial_exact = sum(
        anchor["comparisons"]["serial_equals_hue_identifier"]
        for anchor in anchors
    )
    hap_equals_v1 = sum(
        anchor["comparisons"]["hap_aid_equals_v1_numeric_id"]
        for anchor in anchors
    )

    legacy_exact = sum(
        anchor["comparisons"]["apple_legacy_uuid_equals_hue_identifier"]
        for anchor in anchors
    )

    findings = []
    if hue_apple_accessories and apple_with_serial and serial_exact == 0:
        findings.append(
            {
                "code": "homekit_serial_not_hue_identifier",
                "severity": "info",
                "message": (
                    "HomeKit exposes serial numbers on Hue accessories, but none "
                    "of the diagnostic anchors matches a Hue Zigbee/v1 identifier."
                ),
            }
        )
    if hue_apple_accessories and apple_with_hap_aid == 0:
        findings.append(
            {
                "code": "hap_aid_unavailable",
                "severity": "warning",
                "message": (
                    "No HAP Accessory Instance ID is exposed to this app. On recent "
                    "iOS versions this property requires vendor-level HomeKit access; "
                    "a standard HomeKit entitlement can therefore return no AID."
                ),
            }
        )
    if hap_equals_v1:
        findings.append(
            {
                "code": "hap_aid_matches_hue_v1_id",
                "severity": "info",
                "message": (
                    f"{hap_equals_v1} diagnostic anchor(s) have a HAP AID equal "
                    "to one Hue v1 numeric resource id."
                ),
            }
        )
    if common_offsets and common_offsets[0]["anchors"] >= 3:
        findings.append(
            {
                "code": "candidate_hap_v1_offset",
                "severity": "info",
                "message": (
                    "A repeated HAP-AID minus Hue-v1-ID offset was detected on "
                    f"{common_offsets[0]['anchors']} anchors: "
                    f"{common_offsets[0]['offset']}."
                ),
            }
        )

    selected_bridge = hue_tree.get("bridge") or {}
    serial_samples = [
        {
            "id": accessory.get("id"),
            "legacy_identifier": accessory.get("legacy_identifier"),
            "name": accessory.get("name"),
            "room_name": accessory.get("room_name"),
            "model": accessory.get("model"),
            "serial_number": accessory.get("serial_number"),
            "bridge_id": accessory.get("bridge_id"),
            "bridge_name": accessory.get("bridge_name"),
            "bridge_model": accessory.get("bridge_model"),
        }
        for accessory in hue_apple_accessories
        if accessory.get("serial_number")
    ][:100]

    return {
        "inventory_received_at": inventory.get("received_at"),
        "selected_hue_bridge": copy.deepcopy(selected_bridge),
        "summary": {
            "hue_devices": len(hue_devices),
            "hue_devices_with_identifiers": hue_with_identifiers,
            "apple_accessories_total": len(apple_accessories),
            "apple_hue_accessories": len(hue_apple_accessories),
            "apple_hue_with_serial": apple_with_serial,
            "apple_hue_with_hap_aid": apple_with_hap_aid,
            "apple_hue_with_vendor_access": apple_with_vendor_access,
            "anchors": len(anchors),
            "exact_serial_matches_on_anchors": serial_exact,
            "legacy_uuid_matches_on_anchors": legacy_exact,
            "hap_aid_equals_v1_on_anchors": hap_equals_v1,
            "manual_mappings": len(accessory_map),
        },
        "bridge_identity": bridge_identifier_checks,
        "apple_selected_bridge_serial_samples": serial_samples,
        "candidate_hap_v1_offsets": common_offsets,
        "anchors": anchors[:100],
        "findings": findings,
        "limitations": [
            (
                "HMAccessory.uniqueIdentifier is a HomeKit identifier and is not "
                "documented as the Zigbee EUI-64."
            ),
            (
                "The Hue local REST API does not expose the native Hue Bridge "
                "HomeKit AID mapping table."
            ),
            (
                "Diagnostic name/room/model anchors are observational only and "
                "are never used to move an Apple Home accessory."
            ),
        ],
    }


def build_apple_home_sync_plan(
    hue_tree: dict,
    inventory: dict,
    *,
    room_map: dict[str, str] | None = None,
    accessory_map: dict[str, str] | None = None,
) -> dict:
    room_map = room_map or {}
    accessory_map = accessory_map or {}
    home = inventory.get("home") or {}
    home_id = str(home.get("id") or "")
    if not home_id:
        raise ValueError("Apple Home inventory has no home id")

    apple_rooms = [room for room in inventory.get("rooms", []) if room.get("id")]
    apple_rooms_by_id = {str(room["id"]): room for room in apple_rooms}
    apple_rooms_by_name = _unique_index(
        apple_rooms,
        lambda room: _normalise(room.get("name")),
    )

    accessories = [
        accessory for accessory in inventory.get("accessories", []) if accessory.get("id")
    ]
    accessories_by_id = {
        str(accessory["id"]): accessory
        for accessory in accessories
    }
    candidate_accessories = _apple_accessories_for_hue_bridge(
        hue_tree,
        accessories,
    )

    accessories_by_serial: dict[str, list[dict]] = {}
    for accessory in candidate_accessories:
        serial = _normalise_identifier(accessory.get("serial_number"))
        if serial:
            accessories_by_serial.setdefault(serial, []).append(accessory)

    accessories_by_name: dict[str, list[dict]] = {}
    for accessory in candidate_accessories:
        key = _normalise(accessory.get("name"))
        if key:
            accessories_by_name.setdefault(key, []).append(accessory)

    room_rows: list[dict] = []
    desired_room_by_hue_id: dict[str, dict] = {}
    room_match_meta_by_hue_id: dict[str, dict] = {}
    for room in hue_tree.get("rooms", []):
        hue_room_id = str(room.get("id") or "")
        if not hue_room_id:
            continue
        hue_name = room.get("name") or hue_room_id

        has_explicit_mapping = hue_room_id in room_map
        explicit_id = room_map.get(hue_room_id)
        confidence = None
        suggestions: list[dict] = []
        if has_explicit_mapping:
            desired = apple_rooms_by_id.get(str(explicit_id)) if explicit_id else None
            method = "manual"
            confidence = 1.0
        else:
            desired = apple_rooms_by_name.get(_normalise(hue_name))
            if desired:
                method = "name"
                confidence = 1.0
            else:
                desired, confidence, suggestions = _best_fuzzy_match(
                    hue_name,
                    apple_rooms,
                    room=True,
                    threshold=0.72,
                    ambiguity_gap=0.08,
                )
                method = "heuristic" if desired else None

        row = {
            "hue_room_id": hue_room_id,
            "hue_room_name": hue_name,
            "apple_room_id": str(desired.get("id")) if desired else None,
            "apple_room_name": desired.get("name") if desired else None,
            "method": method,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "suggestions": suggestions,
            "status": "mapped" if desired else "unmapped",
        }
        room_rows.append(row)
        if desired:
            desired_room_by_hue_id[hue_room_id] = desired
            room_match_meta_by_hue_id[hue_room_id] = {
                "method": method,
                "confidence": round(confidence, 3) if confidence is not None else None,
            }

    hue_room_by_apple_room_id = {
        str(apple_room.get("id")): hue_room_id
        for hue_room_id, apple_room in desired_room_by_hue_id.items()
        if apple_room.get("id")
    }

    moves: list[dict] = []
    device_rows: list[dict] = []
    matched_apple_ids: set[str] = set()

    for room in hue_tree.get("rooms", []):
        hue_room_id = str(room.get("id") or "")
        desired_room = desired_room_by_hue_id.get(hue_room_id)
        for device in room.get("devices", []):
            device_id = str(device.get("id") or "")
            device_name = device.get("name") or device_id
            candidates: list[dict] = []
            match_method = None
            hue_identifiers = _hue_identifier_candidates(device)
            manual_accessory_id = str(accessory_map.get(device_id) or "")

            serial_matches: dict[str, dict] = {}
            if manual_accessory_id:
                manual_accessory = accessories_by_id.get(manual_accessory_id)
                if manual_accessory is None:
                    match_method = "manual_missing"
                elif manual_accessory_id in matched_apple_ids:
                    match_method = "manual_conflict"
                else:
                    candidates = [manual_accessory]
                    match_method = "manual_accessory"
            else:
                for identifier in hue_identifiers:
                    for accessory in accessories_by_serial.get(identifier, []):
                        accessory_id = str(accessory["id"])
                        if accessory_id not in matched_apple_ids:
                            serial_matches[accessory_id] = accessory

            if manual_accessory_id:
                pass
            elif len(serial_matches) == 1:
                candidates = list(serial_matches.values())
                match_method = "serial"
            elif not serial_matches and hue_identifiers:
                # A real Hue identifier exists but Apple Home did not expose a
                # matching serial number. Do not guess by name: renamed or
                # similarly named accessories can otherwise be moved incorrectly.
                candidates = []
                match_method = "identifier_unmatched"
            elif not serial_matches:
                name_matches = []
                for accessory in accessories_by_name.get(_normalise(device_name), []):
                    accessory_id = str(accessory.get("id"))
                    if accessory_id in matched_apple_ids:
                        continue
                    current_apple_room_id = str(accessory.get("room_id") or "")
                    owner_hue_room_id = hue_room_by_apple_room_id.get(
                        current_apple_room_id
                    )
                    if owner_hue_room_id and owner_hue_room_id != hue_room_id:
                        continue
                    name_matches.append(accessory)
                if len(name_matches) == 1:
                    candidates = name_matches
                    match_method = "name"
                elif len(name_matches) > 1:
                    candidates = name_matches
                    match_method = "name_ambiguous"
                elif _hue_device_allows_fuzzy_match(device):
                    fuzzy_candidates = []
                    for accessory in candidate_accessories:
                        accessory_id = str(accessory.get("id"))
                        if accessory_id in matched_apple_ids:
                            continue
                        current_apple_room_id = str(accessory.get("room_id") or "")
                        owner_hue_room_id = hue_room_by_apple_room_id.get(current_apple_room_id)
                        if owner_hue_room_id and owner_hue_room_id != hue_room_id:
                            # A fuzzy fallback must never steal an accessory from
                            # another Apple room that already maps to a different
                            # Hue room. Exact serial/name matching may still move it.
                            continue
                        fuzzy_candidates.append(accessory)

                    fuzzy, fuzzy_score, fuzzy_suggestions = _best_fuzzy_match(
                        device_name,
                        fuzzy_candidates,
                        threshold=0.90,
                        ambiguity_gap=0.12,
                        ignore_generic_device_words=True,
                    )
                    if fuzzy:
                        candidates = [fuzzy]
                        match_method = f"heuristic:{fuzzy_score:.2f}"
                    elif fuzzy_suggestions:
                        candidates = []
                        match_method = "heuristic_unmatched"
                else:
                    candidates = []
                    match_method = "unsupported_fuzzy_match"
            else:
                candidates = list(serial_matches.values())
                match_method = "serial_ambiguous"

            if len(candidates) != 1:
                status = "ambiguous_accessory" if candidates else "unmatched_accessory"
                device_rows.append(
                    {
                        "hue_device_id": device_id,
                        "hue_device_name": device_name,
                        "hue_room_id": hue_room_id,
                        "hue_room_name": room.get("name"),
                        "status": status,
                        "match_method": match_method,
                        "hue_identifiers": sorted(hue_identifiers),
                        "candidates": [
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "room_id": item.get("room_id"),
                                "room_name": item.get("room_name"),
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
                        "hue_device_id": device_id,
                        "hue_device_name": device_name,
                        "hue_room_id": hue_room_id,
                        "hue_room_name": room.get("name"),
                        "match_method": match_method,
                        "room_match_method": room_match_meta_by_hue_id.get(
                            hue_room_id, {}
                        ).get("method"),
                        "room_match_confidence": room_match_meta_by_hue_id.get(
                            hue_room_id, {}
                        ).get("confidence"),
                    }
                )

            device_rows.append(
                {
                    "hue_device_id": device_id,
                    "hue_device_name": device_name,
                    "hue_room_id": hue_room_id,
                    "hue_room_name": room.get("name"),
                    "apple_accessory_id": accessory_id,
                    "apple_accessory_name": accessory.get("name"),
                    "apple_room_id": current_room_id,
                    "apple_room_name": accessory.get("room_name"),
                    "desired_apple_room_id": (
                        str(desired_room["id"]) if desired_room else None
                    ),
                    "desired_apple_room_name": (
                        desired_room.get("name") if desired_room else None
                    ),
                    "status": status,
                    "match_method": match_method,
                    "hue_identifiers": sorted(hue_identifiers),
                    "apple_serial_number": accessory.get("serial_number"),
                }
            )

    unmatched_apple = [
        {
            "id": accessory.get("id"),
            "name": accessory.get("name"),
            "room_id": accessory.get("room_id"),
            "room_name": accessory.get("room_name"),
            "manufacturer": accessory.get("manufacturer"),
            "model": accessory.get("model"),
            "serial_number": accessory.get("serial_number"),
            "is_bridged": bool(accessory.get("is_bridged")),
            "bridge_id": accessory.get("bridge_id"),
            "bridge_name": accessory.get("bridge_name"),
            "bridge_manufacturer": accessory.get("bridge_manufacturer"),
            "bridge_model": accessory.get("bridge_model"),
            "origin": _apple_accessory_origin(accessory),
        }
        for accessory in accessories
        if str(accessory.get("id")) not in matched_apple_ids
    ]

    status_counts: dict[str, int] = {}
    for row in device_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    # Aggregate the plan per Hue ↔ Apple room pair so clients can preview the
    # concrete impact of a room association before applying any HomeKit move.
    device_rows_by_hue_room: dict[str, list[dict]] = {}
    for device_row in device_rows:
        device_rows_by_hue_room.setdefault(
            str(device_row.get("hue_room_id") or ""), []
        ).append(device_row)

    accessories_by_room: dict[str, list[dict]] = {}
    for accessory in accessories:
        room_id = str(accessory.get("room_id") or "")
        accessories_by_room.setdefault(room_id, []).append(accessory)

    matched_device_by_apple_id = {
        str(device_row["apple_accessory_id"]): device_row
        for device_row in device_rows
        if device_row.get("apple_accessory_id")
    }

    moves_by_hue_room: dict[str, list[dict]] = {}
    for move in moves:
        moves_by_hue_room.setdefault(str(move.get("hue_room_id") or ""), []).append(move)

    for room_row in room_rows:
        hue_room_id = str(room_row.get("hue_room_id") or "")
        target_room_id = str(room_row.get("apple_room_id") or "")
        hue_device_rows = device_rows_by_hue_room.get(hue_room_id, [])

        room_row["hue_devices"] = [
            {
                "id": device_row.get("hue_device_id"),
                "name": device_row.get("hue_device_name"),
                "status": device_row.get("status"),
                "match_method": device_row.get("match_method"),
                "hue_identifiers": device_row.get("hue_identifiers", []),
                "apple_serial_number": device_row.get("apple_serial_number"),
                "apple_accessory_id": device_row.get("apple_accessory_id"),
                "apple_accessory_name": device_row.get("apple_accessory_name"),
                "apple_current_room_id": device_row.get("apple_room_id"),
                "apple_current_room_name": device_row.get("apple_room_name"),
            }
            for device_row in hue_device_rows
        ]

        target_accessories = (
            accessories_by_room.get(target_room_id, []) if target_room_id else []
        )
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
                "origin": (
                    "hue"
                    if str(accessory.get("id") or "") in matched_device_by_apple_id
                    else _apple_accessory_origin(accessory)
                ),
                "matched_hue_device_id": matched_device_by_apple_id.get(
                    str(accessory.get("id") or ""), {}
                ).get("hue_device_id"),
                "matched_hue_device_name": matched_device_by_apple_id.get(
                    str(accessory.get("id") or ""), {}
                ).get("hue_device_name"),
            }
            for accessory in target_accessories
        ]

        room_row["planned_moves"] = copy.deepcopy(
            moves_by_hue_room.get(hue_room_id, [])
        )
        room_row["impact"] = {
            "hue_device_count": len(hue_device_rows),
            "apple_accessory_count": len(target_accessories),
            "move_count": len(room_row["planned_moves"]),
            "already_correct_count": sum(
                device_row.get("status") == "already_correct"
                for device_row in hue_device_rows
            ),
        }

    return {
        "home": copy.deepcopy(home),
        "inventory_received_at": inventory.get("received_at"),
        "rooms": room_rows,
        "devices": device_rows,
        "actions": moves,
        "accessory_map": copy.deepcopy(accessory_map),
        "unmatched_apple_accessories": unmatched_apple,
        "summary": {
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
