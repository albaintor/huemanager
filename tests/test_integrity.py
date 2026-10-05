from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from huemanager.client import HueBridgeClient
from huemanager.config import BridgeProfile
from huemanager.integrity import (
    CrashDiagnosticStore,
    collect_configuration_snapshot,
    compare_configuration_snapshots,
    deep_integrity_audit,
)


class FakeHueClient:
    def __init__(self, v1: dict, resources: list[dict]) -> None:
        self._v1 = v1
        self._resources = resources

    def v1_all(self) -> dict:
        return self._v1

    def v2_resources(self) -> list[dict]:
        return self._resources


def _healthy_v1() -> dict:
    return {
        "config": {
            "name": "Bridge Pro",
            "bridgeid": "001788FFFE000001",
            "modelid": "BSB003",
            "swversion": "6.2.2071537020",
            "apiversion": "1.70.0",
            "zigbeechannel": 25,
            "mac": "00:11:22:33:44:55",
        },
        "lights": {
            "1": {
                "name": "Lamp",
                "uniqueid": "aa:bb:cc:dd:ee:ff:00:01-0b",
                "state": {"on": True, "reachable": True},
            }
        },
        "sensors": {},
        "groups": {},
        "scenes": {},
        "rules": {},
        "schedules": {},
        "resourcelinks": {},
    }


def _healthy_resources() -> list[dict]:
    return [
        {
            "id": "device-1",
            "type": "device",
            "metadata": {"name": "Lamp"},
            "services": [
                {"rid": "light-1", "rtype": "light"},
                {"rid": "zigbee-1", "rtype": "zigbee_connectivity"},
            ],
        },
        {
            "id": "light-1",
            "type": "light",
            "id_v1": "/lights/1",
            "owner": {"rid": "device-1", "rtype": "device"},
            "on": {"on": True},
            "dimming": {"brightness": 50.0},
        },
        {
            "id": "zigbee-1",
            "type": "zigbee_connectivity",
            "owner": {"rid": "device-1", "rtype": "device"},
            "mac_address": "aa:bb:cc:dd:ee:ff:00:01",
            "status": "connected",
        },
        {
            "id": "room-1",
            "type": "room",
            "metadata": {"name": "Room"},
            "children": [{"rid": "device-1", "rtype": "device"}],
        },
    ]


def test_deep_integrity_audit_detects_missing_device_service() -> None:
    resources = _healthy_resources()
    resources[0]["services"].append({"rid": "missing", "rtype": "button"})

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    codes = [item["code"] for item in result["findings"]]
    assert "missing_device_service" in codes
    assert result["summary"]["critical"] >= 1
    assert result["read_only"] is True


def test_deep_integrity_audit_detects_duplicate_zigbee_mac() -> None:
    resources = _healthy_resources()
    resources.extend(
        [
            {
                "id": "device-2",
                "type": "device",
                "services": [{"rid": "zigbee-2", "rtype": "zigbee_connectivity"}],
            },
            {
                "id": "zigbee-2",
                "type": "zigbee_connectivity",
                "owner": {"rid": "device-2", "rtype": "device"},
                "mac_address": "AA:BB:CC:DD:EE:FF:00:01",
                "status": "connected",
            },
        ]
    )

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert any(item["code"] == "duplicate_zigbee_mac" for item in result["findings"])


def test_shared_id_v1_across_different_v2_types_is_normal() -> None:
    resources = _healthy_resources()
    resources[0]["id_v1"] = "/lights/1"
    resources[2]["id_v1"] = "/lights/1"

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert not any(
        item["code"] in {"duplicate_id_v1", "duplicate_id_v1_same_type"}
        for item in result["findings"]
    )


def test_duplicate_id_v1_within_same_v2_type_is_reported() -> None:
    resources = _healthy_resources()
    resources.append(
        {
            "id": "light-2",
            "type": "light",
            "id_v1": "/lights/1",
            "owner": {"rid": "device-1", "rtype": "device"},
        }
    )

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert any(
        item["code"] == "duplicate_id_v1_same_type"
        for item in result["findings"]
    )


def test_groups_zero_is_valid_v1_counterpart_for_bridge_home_services() -> None:
    resources = _healthy_resources()
    resources.extend(
        [
            {
                "id": "bridge-home-1",
                "type": "bridge_home",
                "id_v1": "/groups/0",
                "services": [
                    {"rid": "grouped-all-1", "rtype": "grouped_light"},
                ],
            },
            {
                "id": "grouped-all-1",
                "type": "grouped_light",
                "id_v1": "/groups/0",
                "owner": {"rid": "bridge-home-1", "rtype": "bridge_home"},
            },
        ]
    )

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert not any(
        item["code"] == "missing_v1_counterpart"
        and item.get("details", {}).get("id_v1") == "/groups/0"
        for item in result["findings"]
    )


def test_opaque_public_image_and_recipe_references_are_not_dangling() -> None:
    resources = _healthy_resources()
    resources.extend(
        [
            {
                "id": "scene-1",
                "type": "scene",
                "metadata": {
                    "name": "Scene",
                    "image": {"rid": "catalog-image-1", "rtype": "public_image"},
                },
                "group": {"rid": "room-1", "rtype": "room"},
                "actions": [],
            },
            {
                "id": "behavior-1",
                "type": "behavior_instance",
                "configuration": {
                    "recipe": {"rid": "recipe-1", "rtype": "recipe"},
                },
            },
        ]
    )

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert not any(
        item["code"] == "missing_v2_reference"
        and item.get("details", {}).get("rtype") in {"public_image", "recipe"}
        for item in result["findings"]
    )


def test_real_missing_local_v2_reference_is_still_reported() -> None:
    resources = _healthy_resources()
    resources.append(
        {
            "id": "scene-1",
            "type": "scene",
            "group": {"rid": "missing-room", "rtype": "room"},
            "actions": [],
        }
    )

    result = deep_integrity_audit(FakeHueClient(_healthy_v1(), resources))  # type: ignore[arg-type]

    assert any(
        item["code"] == "missing_v2_reference"
        and item.get("details", {}).get("rtype") == "room"
        for item in result["findings"]
    )


def test_multiple_button_resources_can_share_one_v1_sensor() -> None:
    resources = _healthy_resources()
    resources[0]["services"].extend(
        [
            {"rid": "button-1", "rtype": "button"},
            {"rid": "button-2", "rtype": "button"},
        ]
    )
    resources.extend(
        [
            {
                "id": "button-1",
                "type": "button",
                "id_v1": "/sensors/16",
                "owner": {"rid": "device-1", "rtype": "device"},
                "metadata": {"control_id": 1},
            },
            {
                "id": "button-2",
                "type": "button",
                "id_v1": "/sensors/16",
                "owner": {"rid": "device-1", "rtype": "device"},
                "metadata": {"control_id": 2},
            },
        ]
    )
    v1 = _healthy_v1()
    v1["sensors"]["16"] = {
        "name": "Dimmer switch",
        "type": "ZLLSwitch",
        "uniqueid": "aa:bb:cc:dd:ee:ff:00:02-02-fc00",
    }

    result = deep_integrity_audit(FakeHueClient(v1, resources))  # type: ignore[arg-type]

    assert not any(
        item["code"] == "duplicate_id_v1_same_type"
        and item.get("details", {}).get("resource_type") == "button"
        for item in result["findings"]
    )


def test_v1_reference_regex_does_not_include_json_punctuation() -> None:
    v1 = _healthy_v1()
    v1["resourcelinks"]["18501"] = {
        "name": "Example",
        "links": [
            "/groups/13",
            "/scenes/6ToIyA5eT2FzZU6",
        ],
    }

    result = deep_integrity_audit(FakeHueClient(v1, _healthy_resources()))  # type: ignore[arg-type]

    finding = next(
        item
        for item in result["findings"]
        if item["code"] == "broken_v1_reference"
        and item["resource"] == "resourcelinks:18501"
    )
    assert finding["details"]["missing"] == [
        "/groups/13",
        "/scenes/6ToIyA5eT2FzZU6",
    ]
    assert not any(
        any(char in path for char in ['"', ",", "]", "}"])
        for path in finding["details"]["missing"]
    )
    assert finding["severity"] == "medium"


def test_disabled_schedule_with_missing_reference_is_medium() -> None:
    v1 = _healthy_v1()
    v1["schedules"]["1"] = {
        "name": "Old schedule",
        "status": "disabled",
        "command": {
            "address": "/api/key/sensors/106/state",
            "method": "PUT",
            "body": {"status": 1},
        },
    }

    result = deep_integrity_audit(FakeHueClient(v1, _healthy_resources()))  # type: ignore[arg-type]

    finding = next(
        item
        for item in result["findings"]
        if item["code"] == "broken_v1_reference"
        and item["resource"] == "schedules:1"
    )
    assert finding["severity"] == "medium"
    assert finding["details"]["missing"] == ["/sensors/106"]
    assert finding["details"]["name"] == "Old schedule"


def test_configuration_snapshot_ignores_normal_light_state_changes() -> None:
    before_client = FakeHueClient(_healthy_v1(), _healthy_resources())

    after_v1 = _healthy_v1()
    after_v1["lights"]["1"]["state"]["on"] = False
    after_resources = _healthy_resources()
    after_resources[1]["on"] = {"on": False}
    after_resources[1]["dimming"] = {"brightness": 10.0}
    after_client = FakeHueClient(after_v1, after_resources)

    before = collect_configuration_snapshot(before_client)  # type: ignore[arg-type]
    after = collect_configuration_snapshot(after_client)  # type: ignore[arg-type]
    comparison = compare_configuration_snapshots(before, after)

    assert comparison["configuration_changed"] is False
    assert comparison["summary"]["changed"] == 0


def test_configuration_snapshot_keeps_zigbee_runtime_changes_separate() -> None:
    before = collect_configuration_snapshot(  # type: ignore[arg-type]
        FakeHueClient(_healthy_v1(), _healthy_resources())
    )
    after_resources = _healthy_resources()
    after_resources[2]["status"] = "connectivity_issue"
    after = collect_configuration_snapshot(  # type: ignore[arg-type]
        FakeHueClient(_healthy_v1(), after_resources)
    )

    comparison = compare_configuration_snapshots(before, after)

    assert comparison["configuration_changed"] is False
    assert comparison["summary"]["runtime_changes"] >= 1


def test_crash_store_persists_baseline_and_report(tmp_path: Path) -> None:
    store = CrashDiagnosticStore(tmp_path)
    healthy = FakeHueClient(_healthy_v1(), _healthy_resources())
    store.capture_baseline("Bridge Pro", healthy)  # type: ignore[arg-type]

    changed_resources = _healthy_resources()
    changed_resources[3]["metadata"]["name"] = "Renamed room"
    report = store.capture_post_crash(
        "Bridge Pro",
        FakeHueClient(_healthy_v1(), changed_resources),  # type: ignore[arg-type]
        {
            "type": "restored",
            "downtime_seconds": 50.0,
            "classifications": ["CONNECTION_REFUSED"],
        },
    )

    assert report["comparison"]["configuration_changed"] is True
    status = store.status("Bridge Pro")
    assert status["post_crash_enabled"] is True
    assert len(status["reports"]) == 1


def test_write_journal_records_only_mutations_and_redacts_secrets(tmp_path: Path) -> None:
    journal = tmp_path / "writes.jsonl"
    client = HueBridgeClient(
        BridgeProfile(host="192.168.1.40", app_key="secret"),
        bridge_name="Bridge Pro",
        write_journal_path=journal,
    )

    client._record_mutation(
        api="clip_v2",
        method="GET",
        endpoint="/bridge",
        body=None,
        started=perf_counter(),
        status_code=200,
        result="success",
    )
    assert not journal.exists()

    client._record_mutation(
        api="clip_v2",
        method="PUT",
        endpoint="/matter/id",
        body={"action": "matter_reset", "token": "do-not-store"},
        started=perf_counter(),
        status_code=500,
        result="error",
        error="Internal Server Error",
    )

    entry = json.loads(journal.read_text(encoding="utf-8").strip())
    assert entry["bridge"] == "Bridge Pro"
    assert entry["method"] == "PUT"
    assert entry["body"]["action"] == "matter_reset"
    assert entry["body"]["token"] == "<redacted>"
    assert entry["status_code"] == 500
