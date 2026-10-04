from __future__ import annotations

from huemanager.apple_home import (
    build_apple_home_sync_plan,
    get_accessory_map,
    get_room_selection,
    store_accessory_map,
    store_room_selection,
)


def test_room_selection_is_persisted_per_bridge_and_home() -> None:
    state = {
        "schema": 1,
        "inventory": None,
        "room_maps": {},
        "room_selections": {},
        "last_sync": None,
    }

    updated = store_room_selection(
        state,
        "Bridge Pro",
        "home-1",
        ["room-b", "room-a", "room-a"],
    )

    assert get_room_selection(updated, "Bridge Pro", "home-1") == [
        "room-a",
        "room-b",
    ]
    assert get_room_selection(updated, "Bridge ancien", "home-1") is None


def test_control_only_hue_device_is_not_fuzzy_matched_to_another_room() -> None:
    hue_tree = {
        "rooms": [
            {
                "id": "hue-buanderie",
                "name": "Sous-sol buanderie",
                "devices": [
                    {
                        "id": "switch-1",
                        "name": "Sous-sol détecteur",
                        "services": [
                            {"type": "button"},
                            {"type": "relative_rotary"},
                        ],
                        "identifiers": {
                            "zigbee_macs": [],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    }
                ],
            },
            {
                "id": "hue-descente",
                "name": "Sous-sol descente",
                "devices": [],
            },
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-buanderie", "name": "Sous-sol buanderie"},
            {"id": "apple-descente", "name": "Sous-sol descente"},
        ],
        "accessories": [
            {
                "id": "motion-1",
                "name": "Sous-sol détecteur",
                "room_id": "apple-descente",
                "room_name": "Sous-sol descente",
                "manufacturer": "Signify Netherlands B.V.",
                "model": "SML001",
                "serial_number": None,
                "is_bridged": True,
                "bridge_name": "Philips Hue",
                "bridge_manufacturer": "Signify",
                "bridge_model": "BSB003",
            }
        ],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    assert plan["actions"] == []
    device = plan["devices"][0]
    assert device["hue_device_id"] == "switch-1"
    assert device["status"] == "unmatched_accessory"
    assert device["match_method"] == "unsupported_fuzzy_match"


def test_fuzzy_match_does_not_steal_accessory_from_other_mapped_room() -> None:
    hue_tree = {
        "rooms": [
            {
                "id": "hue-a",
                "name": "Pièce A",
                "devices": [
                    {
                        "id": "light-a",
                        "name": "Lampe bureau",
                        "services": [{"type": "light"}],
                        "identifiers": {
                            "zigbee_macs": [],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    }
                ],
            },
            {
                "id": "hue-b",
                "name": "Pièce B",
                "devices": [],
            },
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-a", "name": "Pièce A"},
            {"id": "apple-b", "name": "Pièce B"},
        ],
        "accessories": [
            {
                "id": "apple-light-b",
                "name": "Lampe bureau 2",
                "room_id": "apple-b",
                "room_name": "Pièce B",
                "manufacturer": "Signify",
                "model": "LCT001",
                "serial_number": None,
                "is_bridged": True,
                "bridge_name": "Philips Hue",
                "bridge_manufacturer": "Signify",
                "bridge_model": "BSB003",
            }
        ],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    assert plan["actions"] == []
    assert plan["devices"][0]["status"] == "unmatched_accessory"


def test_identifier_bearing_device_never_falls_back_to_similar_name() -> None:
    hue_tree = {
        "rooms": [
            {
                "id": "hue-buanderie",
                "name": "Sous-sol Buanderie",
                "devices": [
                    {
                        "id": "new-light",
                        "name": "Sous-sol buanderie",
                        "services": [{"type": "light"}],
                        "identifiers": {
                            "zigbee_macs": ["00:17:88:01:02:03:04:05"],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    }
                ],
            }
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [{"id": "apple-buanderie", "name": "Sous-sol Buanderie"}],
        "accessories": [
            {
                "id": "motion",
                "name": "Sous-sol buanderie détecteur",
                "serial_number": None,
                "room_id": "apple-buanderie",
                "room_name": "Sous-sol Buanderie",
                "manufacturer": "Signify Netherlands B.V.",
                "model": "SML001",
                "is_bridged": True,
                "bridge_name": "Hue Bridge Pro",
                "bridge_manufacturer": "Signify Netherlands B.V.",
                "bridge_model": "BSB003",
            }
        ],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    device = plan["devices"][0]
    assert device["status"] == "unmatched_accessory"
    assert device["match_method"] == "identifier_unmatched"
    assert device["hue_identifiers"] == ["0017880102030405"]
    assert plan["actions"] == []


def test_accessory_map_is_persisted_per_bridge_and_home() -> None:
    state = {
        "schema": 1,
        "inventory": None,
        "room_maps": {},
        "room_selections": {},
        "accessory_maps": {},
        "last_sync": None,
    }

    updated = store_accessory_map(
        state,
        "Bridge Pro",
        "home-1",
        {"hue-device": "apple-accessory"},
    )

    assert get_accessory_map(updated, "Bridge Pro", "home-1") == {
        "hue-device": "apple-accessory"
    }
    assert get_accessory_map(updated, "Bridge ancien", "home-1") == {}


def test_manual_accessory_map_overrides_missing_common_identifier() -> None:
    hue_tree = {
        "rooms": [
            {
                "id": "hue-room",
                "name": "Salon",
                "devices": [
                    {
                        "id": "hue-light",
                        "name": "Nouvelle lumière",
                        "services": [{"type": "light"}],
                        "identifiers": {
                            "zigbee_macs": ["00:17:88:01:02:03:04:05"],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    }
                ],
            }
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-room", "name": "Salon"},
            {"id": "other-room", "name": "Bureau"},
        ],
        "accessories": [
            {
                "id": "apple-light",
                "name": "Lampe Apple",
                "serial_number": "SERIAL-NOT-EUI64",
                "room_id": "other-room",
                "room_name": "Bureau",
                "manufacturer": "Signify Netherlands B.V.",
                "model": "LCA001",
                "is_bridged": True,
                "bridge_name": "Hue Bridge Pro",
                "bridge_manufacturer": "Signify Netherlands B.V.",
                "bridge_model": "BSB003",
            }
        ],
    }

    no_manual = build_apple_home_sync_plan(hue_tree, inventory)
    assert no_manual["devices"][0]["match_method"] == "identifier_unmatched"
    assert no_manual["actions"] == []

    manual = build_apple_home_sync_plan(
        hue_tree,
        inventory,
        accessory_map={"hue-light": "apple-light"},
    )
    device = manual["devices"][0]
    assert device["match_method"] == "manual_accessory"
    assert device["apple_accessory_id"] == "apple-light"
    assert device["status"] == "move"
    assert manual["actions"][0]["from_room_name"] == "Bureau"
    assert manual["actions"][0]["to_room_name"] == "Salon"
