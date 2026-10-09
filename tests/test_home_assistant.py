from __future__ import annotations

from huemanager.home_assistant import (
    build_home_assistant_apple_home_sync_plan,
    normalize_home_assistant_inventory,
)


def _apple_inventory() -> dict:
    return {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-living", "name": "Salon"},
            {"id": "apple-office", "name": "Bureau"},
        ],
        "bridges": [
            {"id": "bridge-1", "name": "Hue Bridge"},
        ],
        "accessories": [
            {
                "id": "bridge-1",
                "name": "Hue Bridge",
                "room_id": "apple-living",
                "room_name": "Salon",
                "manufacturer": "Signify Netherlands B.V.",
                "model": "BSB003",
            },
            {
                "id": "apple-lamp",
                "name": "Lampadaire",
                "room_id": "apple-office",
                "room_name": "Bureau",
                "manufacturer": "Signify Netherlands B.V.",
                "model": "LCA001",
                "serial_number": "AA:BB:CC:DD:EE:FF:00:01",
            },
            {
                "id": "apple-sensor",
                "name": "Capteur bureau",
                "room_id": "apple-office",
                "room_name": "Bureau",
                "manufacturer": "Acme",
                "model": "SENSOR-1",
                "serial_number": "SN-1234-Z",
            },
        ],
        "received_at": "2026-10-09T12:00:00+00:00",
    }


def test_normalize_home_assistant_inventory_uses_area_and_parent_area() -> None:
    inventory = normalize_home_assistant_inventory(
        config={
            "location_name": "Home",
            "version": "2026.10.0",
            "time_zone": "Europe/Paris",
        },
        areas=[
            {"area_id": "living", "name": "Salon"},
            {"area_id": "office", "name": "Bureau"},
        ],
        devices=[
            {
                "id": "parent",
                "area_id": "living",
                "name": "Parent",
                "identifiers": [["hue", "parent-id"]],
            },
            {
                "id": "child",
                "parent_device_id": "parent",
                "area_id": None,
                "name": "Child",
                "identifiers": [["demo", "child-id"]],
            },
            {
                "id": "service-room",
                "entry_type": "service",
                "area_id": "office",
                "name": "Service room",
            },
        ],
        entities=[],
    )

    devices = {item["id"]: item for item in inventory["devices"]}
    assert devices["parent"]["area_id"] == "living"
    assert devices["child"]["area_id"] == "living"
    assert devices["child"]["area_source"] == "parent_device"
    assert "service-room" not in devices


def test_plan_matches_home_assistant_mac_to_apple_serial() -> None:
    ha_inventory = {
        "captured_at": "2026-10-09T12:00:00+00:00",
        "rooms": [
            {
                "id": "living",
                "name": "Salon",
                "devices": [
                    {
                        "id": "ha-lamp",
                        "name": "Lampadaire",
                        "manufacturer": "Signify Netherlands B.V.",
                        "model": "LCA001",
                        "serial_number": None,
                        "identifiers": [
                            "hue-device-v2-uuid",
                            "AA:BB:CC:DD:EE:FF:00:01",
                        ],
                    }
                ],
            }
        ],
    }

    plan = build_home_assistant_apple_home_sync_plan(
        ha_inventory,
        _apple_inventory(),
    )

    assert plan["source_kind"] == "home_assistant"
    assert plan["rooms"][0]["apple_room_id"] == "apple-living"
    row = plan["devices"][0]
    assert row["apple_accessory_id"] == "apple-lamp"
    assert row["match_method"] == "serial"
    assert row["status"] == "move"
    assert plan["actions"][0]["to_room_id"] == "apple-living"


def test_plan_requires_model_for_name_based_automatic_match() -> None:
    ha_inventory = {
        "rooms": [
            {
                "id": "office",
                "name": "Bureau",
                "devices": [
                    {
                        "id": "ha-sensor",
                        "name": "Capteur bureau",
                        "manufacturer": "Acme",
                        "model": None,
                        "serial_number": None,
                        "identifiers": [],
                    }
                ],
            }
        ],
    }

    plan = build_home_assistant_apple_home_sync_plan(
        ha_inventory,
        _apple_inventory(),
    )

    row = plan["devices"][0]
    assert row["status"] == "unmatched_accessory"
    assert row["match_method"] is None


def test_plan_matches_unique_exact_name_and_model() -> None:
    ha_inventory = {
        "rooms": [
            {
                "id": "office",
                "name": "Bureau",
                "devices": [
                    {
                        "id": "ha-sensor",
                        "name": "Capteur bureau",
                        "manufacturer": "Acme",
                        "model": "SENSOR-1",
                        "serial_number": None,
                        "identifiers": [],
                    }
                ],
            }
        ],
    }

    plan = build_home_assistant_apple_home_sync_plan(
        ha_inventory,
        _apple_inventory(),
    )

    row = plan["devices"][0]
    assert row["apple_accessory_id"] == "apple-sensor"
    assert row["match_method"] == "name_model"
    assert row["status"] == "already_correct"


def test_plan_supports_manual_accessory_mapping() -> None:
    ha_inventory = {
        "rooms": [
            {
                "id": "living",
                "name": "Salon",
                "devices": [
                    {
                        "id": "ha-sensor",
                        "name": "Completely different",
                        "model": None,
                        "serial_number": None,
                        "identifiers": [],
                    }
                ],
            }
        ],
    }

    plan = build_home_assistant_apple_home_sync_plan(
        ha_inventory,
        _apple_inventory(),
        accessory_map={"ha-sensor": "apple-sensor"},
    )

    row = plan["devices"][0]
    assert row["apple_accessory_id"] == "apple-sensor"
    assert row["match_method"] == "manual_accessory"
    assert row["status"] == "move"
