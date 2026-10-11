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
        entities=[
            {"entity_id": "light.parent", "device_id": "parent", "platform": "hue"},
            {"entity_id": "sensor.child", "device_id": "child", "platform": "hue"},
        ],
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


def test_inventory_contains_only_entities_from_the_hue_integration() -> None:
    inventory = normalize_home_assistant_inventory(
        config={},
        areas=[
            {"area_id": "living", "name": "Salon"},
            {"area_id": "other", "name": "Autre"},
        ],
        devices=[
            {"id": "hue-lamp", "name": "Lampadaire", "area_id": "living"},
            {"id": "other-lamp", "name": "Autre lampe", "area_id": "other",
             "manufacturer": "Signify Netherlands B.V."},
        ],
        entities=[
            {"entity_id": "light.lamp", "device_id": "hue-lamp",
             "platform": "hue", "config_entry_id": "hue-entry"},
            {"entity_id": "sensor.other_linked", "device_id": "hue-lamp", "platform": "template"},
            {"entity_id": "light.other", "device_id": "other-lamp", "platform": "mqtt"},
            {"entity_id": "sensor.hue_standalone", "area_id": "living",
             "platform": "hue", "config_entry_id": "hue-entry"},
            {"entity_id": "sensor.not_hue", "area_id": "other", "platform": "template"},
            {"entity_id": "light.disabled_hue", "area_id": "other",
             "platform": "hue", "disabled_by": "user"},
        ],
        hue_config_entries=[
            {"entry_id": "hue-entry", "domain": "hue"},
            {"entry_id": "other-entry", "domain": "mqtt"},
        ],
    )

    assert inventory["schema_version"] == 3
    assert {device["id"] for device in inventory["devices"]} == {
        "hue-lamp", "entity:sensor.hue_standalone"
    }
    assert inventory["devices"][0]["entity_ids"] == ["light.lamp"]
    assert [room["id"] for room in inventory["rooms"]] == ["living"]
    assert len(inventory["rooms"][0]["devices"]) == 2


def test_non_hue_entities_never_produce_apple_home_moves() -> None:
    inventory = normalize_home_assistant_inventory(
        config={},
        areas=[{"area_id": "living", "name": "Salon"}],
        devices=[
            {"id": "hue-lamp", "name": "Lampadaire", "model": "LCA001",
             "area_id": "living",
             "connections": [["mac", "AA:BB:CC:DD:EE:FF:00:01"]]},
            {"id": "foreign-sensor", "name": "Capteur bureau", "model": "SENSOR-1",
             "area_id": "living"},
        ],
        entities=[
            {"entity_id": "light.lampadaire", "device_id": "hue-lamp", "platform": "hue"},
            {"entity_id": "sensor.bureau", "device_id": "foreign-sensor", "platform": "mqtt"},
        ],
    )
    plan = build_home_assistant_apple_home_sync_plan(inventory, _apple_inventory())

    assert [device["source_device_id"] for device in plan["devices"]] == ["hue-lamp"]
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["accessory_id"] == "apple-lamp"


def test_inventory_without_any_hue_entities_has_no_source_rooms() -> None:
    inventory = normalize_home_assistant_inventory(
        config={},
        areas=[{"area_id": "living", "name": "Salon"}],
        devices=[{"id": "other", "name": "Lampe", "area_id": "living"}],
        entities=[{"entity_id": "light.other", "device_id": "other",
                   "platform": "mqtt"}],
    )
    assert inventory["devices"] == []
    assert inventory["rooms"] == []


def test_hue_filter_requires_both_platform_and_config_entry_and_tracks_status() -> None:
    inventory = normalize_home_assistant_inventory(
        config={},
        areas=[{"area_id": "salon", "name": "Salon"}],
        devices=[
            {"id": "real", "name": "Vraie lampe", "area_id": "salon",
             "config_entries": ["entry-hue"]},
            {"id": "foreign", "name": "Autre lampe", "area_id": "salon"},
            {"id": "mixed", "name": "Appareil partagé", "area_id": "salon",
             "config_entries": ["entry-other"]},
        ],
        entities=[
            {"entity_id": "light.real", "platform": "hue",
             "config_entry_id": "entry-hue", "device_id": "real"},
            {"entity_id": "sensor.foreign", "platform": "template",
             "config_entry_id": "entry-hue", "device_id": "foreign"},
            {"entity_id": "light.wrong_entry", "platform": "hue",
             "config_entry_id": "entry-other", "device_id": "foreign"},
            {"entity_id": "light.mismatched_device", "platform": "hue",
             "config_entry_id": "entry-hue", "device_id": "mixed"},
        ],
        hue_config_entries=[{"entry_id": "entry-hue", "domain": "hue"}],
        entity_states=[{"entity_id": "light.real", "state": "unavailable"}],
    )
    assert [device["id"] for device in inventory["devices"]] == ["real"]
    assert inventory["devices"][0]["availability"] == "offline"
    assert inventory["filter_diagnostics"]["hue_entities"] == 1
    assert inventory["filter_diagnostics"]["excluded_by_reason"] == {
        "other_platform": 1,
        "not_hue_config_entry": 1,
        "device_entry_mismatch": 1,
    }


def test_hue_platform_without_proven_config_entry_is_excluded() -> None:
    inventory = normalize_home_assistant_inventory(
        config={},
        areas=[{"area_id": "salon", "name": "Salon"}],
        devices=[{"id": "lamp", "area_id": "salon"}],
        entities=[{"entity_id": "light.lamp", "platform": "hue", "device_id": "lamp"}],
        hue_config_entries=[],
    )
    assert inventory["devices"] == []
    assert inventory["rooms"] == []
