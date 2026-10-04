from __future__ import annotations

from huemanager.apple_audit import build_apple_home_multi_bridge_audit


def _base_accessory(
    accessory_id: str,
    bridge_id: str,
    bridge_name: str,
    bridge_model: str,
    *,
    reachable: bool = True,
) -> dict:
    return {
        "id": accessory_id,
        "name": "Salon lampe",
        "model": "LCA001",
        "room_id": "apple-room",
        "room_name": "Salon",
        "manufacturer": "Signify",
        "is_bridged": True,
        "bridge_id": bridge_id,
        "bridge_name": bridge_name,
        "bridge_manufacturer": "Signify",
        "bridge_model": bridge_model,
        "reachable": reachable,
    }


def test_multi_bridge_audit_detects_stale_entry_after_migration() -> None:
    hue_trees = {
        "Ancien": {
            "bridge": {"name": "Jardin", "modelid": "BSB002"},
            "rooms": [],
        },
        "Principal": {
            "bridge": {"name": "Principal", "modelid": "BSB003"},
            "rooms": [
                {
                    "id": "new-room",
                    "name": "Salon",
                    "devices": [
                        {
                            "id": "new-light",
                            "name": "Salon lampe",
                            "model": "LCA001",
                        }
                    ],
                }
            ],
        },
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "received_at": "2026-10-04T12:00:00+00:00",
        "bridges": [
            {
                "id": "apple-old",
                "name": "Jardin",
                "manufacturer": "Signify",
                "model": "BSB002",
                "bridged_accessory_ids": ["old-copy"],
            },
            {
                "id": "apple-pro",
                "name": "Hue Bridge Pro",
                "manufacturer": "Signify",
                "model": "BSB003",
                "bridged_accessory_ids": ["new-copy"],
            },
        ],
        "accessories": [
            _base_accessory(
                "old-copy",
                "apple-old",
                "Jardin",
                "BSB002",
                reachable=False,
            ),
            _base_accessory(
                "new-copy",
                "apple-pro",
                "Hue Bridge Pro",
                "BSB003",
            ),
        ],
    }

    report = build_apple_home_multi_bridge_audit(hue_trees, inventory)

    by_id = {
        item["apple_accessory_id"]: item
        for item in report["items"]
    }
    assert by_id["old-copy"]["status"] == "stale_after_migration"
    assert by_id["old-copy"]["expected_bridge_profile"] == "Principal"
    assert by_id["new-copy"]["apple_bridge_profile"] == "Principal"
    assert report["summary"]["probable_migrations"] == 1
    assert report["summary"]["duplicates"] == 2


def test_multi_bridge_audit_marks_known_power_off_as_expected() -> None:
    hue_trees = {
        "Principal": {
            "bridge": {"name": "Principal", "modelid": "BSB003"},
            "rooms": [
                {
                    "id": "room",
                    "name": "Salon",
                    "devices": [
                        {
                            "id": "light-1",
                            "name": "Salon lampe",
                            "model": "LCA001",
                        }
                    ],
                }
            ],
        }
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "bridges": [
            {
                "id": "apple-pro",
                "name": "Hue Bridge Pro",
                "manufacturer": "Signify",
                "model": "BSB003",
                "bridged_accessory_ids": ["apple-light"],
            }
        ],
        "accessories": [
            _base_accessory(
                "apple-light",
                "apple-pro",
                "Hue Bridge Pro",
                "BSB003",
                reachable=False,
            )
        ],
    }

    report = build_apple_home_multi_bridge_audit(
        hue_trees,
        inventory,
        accessory_maps_by_bridge={
            "Principal": {"light-1": "apple-light"}
        },
        ignored_devices_by_bridge={"Principal": {"light-1"}},
    )

    item = report["items"][0]
    assert item["status"] == "expected_offline"
    assert item["ignored_power_off"] is True
    assert item["match_source"] == "persistent"


def test_multi_bridge_audit_keeps_unknown_model_unresolved() -> None:
    hue_trees = {
        "Principal": {
            "bridge": {"name": "Principal", "modelid": "BSB003"},
            "rooms": [],
        }
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "bridges": [
            {
                "id": "apple-pro",
                "name": "Hue Bridge Pro",
                "manufacturer": "Signify",
                "model": "BSB003",
                "bridged_accessory_ids": ["apple-light"],
            }
        ],
        "accessories": [
            {
                **_base_accessory(
                    "apple-light",
                    "apple-pro",
                    "Hue Bridge Pro",
                    "BSB003",
                ),
                "model": "Unknown",
            }
        ],
    }

    report = build_apple_home_multi_bridge_audit(hue_trees, inventory)

    assert report["items"][0]["status"] == "unresolved"
    assert report["summary"]["orphans"] == 0
