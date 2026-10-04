from __future__ import annotations

from huemanager.config import BridgeProfile, ConfigStore


def test_diagnostic_ignored_devices_are_persisted(tmp_path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    store.save_bridge(
        "Principal",
        BridgeProfile(host="192.0.2.1", app_key="key"),
    )

    store.save_diagnostic_ignored_devices(
        "Principal",
        {"device-b", "device-a", ""},
    )

    assert store.get_diagnostic_ignored_devices("Principal") == {
        "device-a",
        "device-b",
    }
    assert store.get_bridge("Principal").host == "192.0.2.1"
