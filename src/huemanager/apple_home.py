from __future__ import annotations

import copy
import json
import re
import unicodedata
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
    "light",
    "lamp",
    "lampe",
    "bulb",
    "ampoule",
    "spot",
    "plafonnier",
    "ceiling",
    "device",
    "appareil",
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


def load_apple_home_state(path: Path) -> dict:
    if not path.exists():
        return {
            "schema": APPLE_HOME_STATE_SCHEMA,
            "updated_at": None,
            "inventory": None,
            "room_maps": {},
            "last_sync": None,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != APPLE_HOME_STATE_SCHEMA:
        raise ValueError(
            f"Unsupported Apple Home state schema: {payload.get('schema')!r}"
        )
    payload.setdefault("inventory", None)
    payload.setdefault("room_maps", {})
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
        str(hue_room_id): str(apple_room_id)
        for hue_room_id, apple_room_id in room_map.items()
        if hue_room_id and apple_room_id
    }
    return result


def get_room_map(state: dict, bridge_profile: str, home_id: str) -> dict[str, str]:
    return copy.deepcopy(
        state.get("room_maps", {}).get(bridge_profile, {}).get(home_id, {})
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


def build_apple_home_sync_plan(
    hue_tree: dict,
    inventory: dict,
    *,
    room_map: dict[str, str] | None = None,
) -> dict:
    room_map = room_map or {}
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
    accessories_by_serial: dict[str, list[dict]] = {}
    for accessory in accessories:
        serial = _normalise_identifier(accessory.get("serial_number"))
        if serial:
            accessories_by_serial.setdefault(serial, []).append(accessory)

    accessories_by_name: dict[str, list[dict]] = {}
    for accessory in accessories:
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

        explicit_id = room_map.get(hue_room_id)
        confidence = None
        suggestions: list[dict] = []
        if explicit_id and explicit_id in apple_rooms_by_id:
            desired = apple_rooms_by_id[explicit_id]
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

            serial_matches: dict[str, dict] = {}
            for identifier in _hue_identifier_candidates(device):
                for accessory in accessories_by_serial.get(identifier, []):
                    serial_matches[str(accessory["id"])] = accessory
            if len(serial_matches) == 1:
                candidates = list(serial_matches.values())
                match_method = "serial"
            elif not serial_matches:
                name_matches = accessories_by_name.get(_normalise(device_name), [])
                if len(name_matches) == 1:
                    candidates = name_matches
                    match_method = "name"
                elif len(name_matches) > 1:
                    candidates = name_matches
                    match_method = "name_ambiguous"
                else:
                    fuzzy, fuzzy_score, fuzzy_suggestions = _best_fuzzy_match(
                        device_name,
                        [
                            accessory
                            for accessory in accessories
                            if str(accessory.get("id")) not in matched_apple_ids
                        ],
                        threshold=0.84,
                        ambiguity_gap=0.10,
                        ignore_generic_device_words=True,
                    )
                    if fuzzy:
                        candidates = [fuzzy]
                        match_method = f"heuristic:{fuzzy_score:.2f}"
                    elif fuzzy_suggestions:
                        candidates = []
                        match_method = "heuristic_unmatched"
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
        }
        for accessory in accessories
        if str(accessory.get("id")) not in matched_apple_ids
    ]

    status_counts: dict[str, int] = {}
    for row in device_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    return {
        "home": copy.deepcopy(home),
        "inventory_received_at": inventory.get("received_at"),
        "rooms": room_rows,
        "devices": device_rows,
        "actions": moves,
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
