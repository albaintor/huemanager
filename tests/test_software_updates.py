from __future__ import annotations

import pytest

from huemanager.client import HueApiError
from huemanager.updates import (
    request_software_update_check,
    request_software_update_install,
    software_update_status,
)


class FakeHueClient:
    def __init__(
        self,
        update=None,
        *,
        v2_error=False,
        bridge_v2_software_version="6.2.2071537020",
    ):
        self.update = update
        self.v2_error = v2_error
        self.bridge_v2_software_version = bridge_v2_software_version
        self.writes = []

    def v1_get(self, path):
        assert path == "/config"
        config = {
            "name": "Principal",
            "bridgeid": "ABC123",
            "modelid": "BSB003",
            "swversion": "2071537020",
            "apiversion": "1.72.0",
            "internetservices": {"internet": "connected", "swupdate": "connected"},
            "whitelist": {"secret-api-key": {"name": "Do not return"}},
        }
        if self.update is not None:
            config["swupdate2"] = self.update
        return config

    def v2_get(self, resource_type):
        if self.v2_error:
            raise HueApiError("Unsupported v2 resource")
        if resource_type == "device":
            return [
                {
                    "id": "bridge-device-1",
                    "type": "device",
                    "product_data": {
                        "model_id": "BSB003",
                        "product_archetype": "bridge_v2",
                        "software_version": self.bridge_v2_software_version,
                    },
                    "services": [{"rid": "bridge-service-1", "rtype": "bridge"}],
                }
            ]
        assert resource_type == "device_software_update"
        return [{"id": "device-update-1", "state": "no_update",
                 "owner": {"rid": "device-1", "rtype": "device"}}]

    def v1_put(self, path, body):
        self.writes.append((path, body))
        return [{"success": {"/config/swupdate2": body["swupdate2"]}}]


def test_status_sanitizes_config_and_shows_schedule():
    client = FakeHueClient({
        "state": "noupdates",
        "bridge": {"state": "noupdates", "lastinstall": "2026-10-01T02:00:00"},
        "autoinstall": {"on": False, "updatetime": "T13:35:00"},
        "lastchange": "2026-10-09T12:00:00",
    })
    info = software_update_status(client)
    assert info["bridge"]["software_version"] == "6.2.2071537020"
    assert info["bridge"]["software_build"] == "2071537020"
    assert info["updates"]["automatic_install"] is False
    assert info["updates"]["automatic_install_time"] == "T13:35:00"
    assert info["updates"]["ready_to_install"] is False
    assert len(info["devices"]["items"]) == 1
    assert "whitelist" not in repr(info)
    assert "secret-api-key" not in repr(info)


def test_check_uses_config_swupdate2_and_does_not_install():
    client = FakeHueClient({
        "state": "noupdates",
        "checkforupdate": False,
        "bridge": {"state": "noupdates"},
    })
    assert request_software_update_check(client)["requested"]
    assert client.writes == [
        ("/config", {"swupdate2": {"checkforupdate": True}})
    ]


def test_check_in_progress_is_not_retriggered():
    client = FakeHueClient({"checkforupdate": True})
    with pytest.raises(HueApiError, match="already in progress"):
        request_software_update_check(client)
    assert client.writes == []


def test_install_requires_ready_state():
    client = FakeHueClient({"state": "noupdates", "bridge": {"state": "noupdates"}})
    with pytest.raises(HueApiError, match="No update"):
        request_software_update_install(client)
    assert client.writes == []


@pytest.mark.parametrize("state", ["anyreadytoinstall", "allreadytoinstall"])
def test_install_ready_firmware(state):
    client = FakeHueClient({"state": state, "bridge": {"state": "noupdates"}})
    assert request_software_update_install(client)["action"] == "install"
    assert client.writes == [("/config", {"swupdate2": {"install": True}})]


def test_unsupported_v2_resource_does_not_disable_bridge_status():
    client = FakeHueClient({"state": "noupdates"}, v2_error=True)
    status = software_update_status(client)
    assert status["updates"]["supported"] is True
    assert status["devices"]["supported"] is False


def test_unsupported_v1_blocks_writes():
    client = FakeHueClient(None)
    assert software_update_status(client)["updates"]["supported"] is False
    with pytest.raises(HueApiError, match="swupdate2"):
        request_software_update_check(client)
    assert client.writes == []


def test_status_falls_back_to_v1_build_when_bridge_device_v2_unavailable():
    client = FakeHueClient(
        {"state": "noupdates"},
        v2_error=True,
    )
    status = software_update_status(client)
    assert status["bridge"]["software_version"] == "2071537020"
    assert status["bridge"]["software_build"] == "2071537020"
