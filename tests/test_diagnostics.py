from __future__ import annotations

from huemanager.diagnostics import (
    coexistence_report,
    diagnose_bridge,
    wifi_center_mhz,
    zigbee_center_mhz,
)


class FakeClient:
    def __init__(self, zigbee_channel: int = 25) -> None:
        self.zigbee_channel = zigbee_channel

    def v1_all(self) -> dict:
        return {
            "config": {
                "name": "Hue Bridge Pro",
                "bridgeid": "ABC",
                "modelid": "BSB003",
                "swversion": "2071524030",
                "apiversion": "1.78.0",
                "zigbeechannel": self.zigbee_channel,
            },
            "lights": {
                "1": {
                    "name": "Hue lamp",
                    "manufacturername": "Signify Netherlands B.V.",
                    "modelid": "LCA001",
                    "uniqueid": "00:11:22:33:44:55:66:77-0b",
                    "state": {"reachable": True},
                },
                "2": {
                    "name": "Third-party lamp",
                    "manufacturername": "Example vendor",
                    "modelid": "X1",
                    "uniqueid": "00:11:22:33:44:55:66:78-0b",
                    "state": {"reachable": False},
                },
            },
            "sensors": {},
            "groups": {},
            "scenes": {},
            "rules": {},
            "schedules": {},
            "resourcelinks": {},
        }

    def v2_resources(self) -> list[dict]:
        return [
            {
                "id": "device-1",
                "type": "device",
                "metadata": {"name": "Hue lamp"},
                "product_data": {
                    "manufacturer_name": "Signify Netherlands B.V.",
                    "model_id": "LCA001",
                },
                "services": [
                    {"rid": "zigbee-1", "rtype": "zigbee_connectivity"},
                ],
            },
            {
                "id": "zigbee-1",
                "type": "zigbee_connectivity",
                "status": "connected",
                "mac_address": "00:11:22:33:44:55:66:77",
                "owner": {"rid": "device-1", "rtype": "device"},
            },
            {
                "id": "device-2",
                "type": "device",
                "metadata": {"name": "Offline lamp"},
                "product_data": {
                    "manufacturer_name": "Signify Netherlands B.V.",
                    "model_id": "LCA002",
                },
                "services": [
                    {"rid": "zigbee-2", "rtype": "zigbee_connectivity"},
                ],
            },
            {
                "id": "zigbee-2",
                "type": "zigbee_connectivity",
                "status": "disconnected",
                "mac_address": "00:11:22:33:44:55:66:79",
                "owner": {"rid": "device-2", "rtype": "device"},
            },
            {
                "id": "room-1",
                "type": "room",
                "metadata": {"name": "Salon"},
                "children": [{"rid": "device-1", "rtype": "device"}],
            },
        ]


def test_channel_frequency_helpers() -> None:
    assert zigbee_center_mhz(11) == 2405.0
    assert zigbee_center_mhz(25) == 2475.0
    assert zigbee_center_mhz(29) is None
    assert wifi_center_mhz(1) == 2412.0
    assert wifi_center_mhz(3) == 2422.0


def test_coexistence_low_risk_for_wifi_3_and_zigbee_25() -> None:
    report = coexistence_report(25, 3, 20)
    assert report["risk"] == "low"
    assert report["guard_gap_mhz"] > 0


def test_non_standard_zigbee_channel_is_reported() -> None:
    report = coexistence_report(29, 3, 20)
    assert report["risk"] == "unknown"
    assert report["zigbee_standard_channel"] is False


def test_diagnose_bridge_reports_disconnects_and_unreachable_resources() -> None:
    result = diagnose_bridge(
        FakeClient(),
        wifi_channel=3,
        wifi_width_mhz=20,
        samples=1,
    )
    assert result["zigbee"]["channel"] == 25
    assert result["zigbee"]["connected"] == 1
    assert result["zigbee"]["disconnected"] == 1
    assert result["reachability"]["unreachable_count"] == 1
    assert result["third_party"]["count"] == 1
    assert result["wifi_coexistence"]["risk"] == "low"
    assert any(
        finding["code"] == "zigbee_disconnected"
        for finding in result["findings"]
    )


def test_diagnose_bridge_flags_channel_29() -> None:
    result = diagnose_bridge(
        FakeClient(zigbee_channel=29),
        wifi_channel=3,
        samples=1,
    )
    assert result["zigbee"]["standard_2_4ghz_channel"] is False
    assert any(
        finding["code"] == "non_standard_zigbee_channel"
        for finding in result["findings"]
    )
