from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from huemanager import web


class FakeHueClient:
    def __init__(
        self,
        fabrics: list[dict],
        matters: list[dict] | None = None,
        homekits: list[dict] | None = None,
    ) -> None:
        self.fabrics = list(fabrics)
        self.matters = list(matters or [])
        self.homekits = list(homekits or [])
        self.deleted: list[tuple[str, str]] = []
        self.puts: list[tuple[str, str, dict]] = []

    def v2_get(self, resource_type: str, resource_id: str | None = None) -> list[dict]:
        if resource_type == "matter_fabric":
            rows = self.fabrics
        elif resource_type == "matter":
            rows = self.matters
        elif resource_type == "homekit":
            rows = self.homekits
        else:
            raise AssertionError(resource_type)
        if resource_id is not None:
            return [row for row in rows if row.get("id") == resource_id]
        return list(rows)

    def v2_delete(self, resource_type: str, resource_id: str) -> list[dict]:
        assert resource_type == "matter_fabric"
        self.deleted.append((resource_type, resource_id))
        self.fabrics = [row for row in self.fabrics if row.get("id") != resource_id]
        return []

    def v2_put(self, resource_type: str, resource_id: str, body: dict) -> list[dict]:
        assert resource_type in {"matter", "homekit"}
        self.puts.append((resource_type, resource_id, body))
        if resource_type == "matter" and body == {"action": "matter_reset"}:
            self.fabrics = []
        if resource_type == "homekit" and body == {"action": "homekit_reset"}:
            for row in self.homekits:
                if row.get("id") == resource_id:
                    row["status"] = "unpaired"
                    row["action"] = "none"
        return []


def _fabric(
    *,
    fabric_id: str,
    label: str,
    vendor_id: int,
    status: str = "paired",
) -> dict:
    return {
        "id": fabric_id,
        "type": "matter_fabric",
        "status": status,
        "creation_time": "2026-10-04T18:00:00Z",
        "fabric_data": {
            "label": label,
            "vendor_id": vendor_id,
        },
    }


def test_matter_fabric_summary_identifies_apple() -> None:
    row = web._matter_fabric_summary(
        _fabric(
            fabric_id=str(uuid.uuid4()),
            label="Maison",
            vendor_id=0x1349,
        )
    )

    assert row["label"] == "Maison"
    assert row["vendor_id"] == 4937
    assert row["vendor_hex"] == "0x1349"
    assert row["vendor_name"] == "Apple Home"
    assert row["is_apple"] is True


def test_list_matter_fabrics_orders_apple_first(monkeypatch: pytest.MonkeyPatch) -> None:
    apple_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    client = FakeHueClient(
        [
            _fabric(fabric_id=other_id, label="Autre", vendor_id=1234),
            _fabric(fabric_id=apple_id, label="Maison", vendor_id=0x1349),
        ]
    )
    monkeypatch.setattr(web, "_client", lambda _: client)

    result = web.list_matter_fabrics("Bridge Pro")

    assert result["count"] == 2
    assert result["fabrics"][0]["id"] == apple_id
    assert result["fabrics"][0]["is_apple"] is True


def test_delete_matter_fabric_is_explicitly_unsupported() -> None:
    with pytest.raises(HTTPException) as exc_info:
        web.delete_matter_fabric("Bridge Pro", str(uuid.uuid4()))

    assert exc_info.value.status_code == 405
    assert "does not expose DELETE" in str(exc_info.value.detail)


def test_matter_fabric_summary_identifies_apple_keychain() -> None:
    row = web._matter_fabric_summary(
        _fabric(
            fabric_id=str(uuid.uuid4()),
            label="",
            vendor_id=0x1384,
        )
    )

    assert row["vendor_id"] == 4996
    assert row["vendor_name"] == "Apple Keychain"
    assert row["is_apple"] is True


def test_reset_matter_feature_uses_matter_reset_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matter_id = str(uuid.uuid4())
    client = FakeHueClient(
        [
            _fabric(
                fabric_id=str(uuid.uuid4()),
                label="Maison",
                vendor_id=0x1349,
            ),
            _fabric(
                fabric_id=str(uuid.uuid4()),
                label="",
                vendor_id=0x1384,
            ),
        ],
        matters=[
            {
                "id": matter_id,
                "type": "matter",
                "has_qr_code": True,
                "max_fabrics": 16,
            }
        ],
    )
    monkeypatch.setattr(web, "_client", lambda _: client)

    result = web.reset_matter_feature("Bridge Pro")

    assert client.puts == [
        ("matter", matter_id, {"action": "matter_reset"})
    ]
    assert result["removed_fabrics"] == 2
    assert client.fabrics == []



def test_get_homekit_state_reports_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    homekit_id = str(uuid.uuid4())
    client = FakeHueClient(
        [],
        homekits=[
            {
                "id": homekit_id,
                "type": "homekit",
                "status": "paired",
                "action": "none",
            }
        ],
    )
    monkeypatch.setattr(web, "_client", lambda _: client)

    result = web.get_homekit_state("Bridge Pro")

    assert result["count"] == 1
    assert result["resources"][0] == {
        "id": homekit_id,
        "type": "homekit",
        "status": "paired",
        "action": "none",
    }


def test_reset_homekit_feature_uses_homekit_reset_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    homekit_id = str(uuid.uuid4())
    client = FakeHueClient(
        [],
        homekits=[
            {
                "id": homekit_id,
                "type": "homekit",
                "status": "paired",
                "action": "none",
            }
        ],
    )
    monkeypatch.setattr(web, "_client", lambda _: client)

    result = web.reset_homekit_feature("Bridge Pro")

    assert client.puts == [
        ("homekit", homekit_id, {"action": "homekit_reset"})
    ]
    assert result["before"]["status"] == "paired"
    assert client.homekits[0]["status"] == "unpaired"

def test_homekit_503_is_unconfigured_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from huemanager.client import HueApiError

    class UnconfiguredClient:
        def v2_get(self, resource_type: str) -> list[dict]:
            raise HueApiError("Hue API 503 GET /homekit: Service Unavailable")

    monkeypatch.setattr(web, "_client", lambda _: UnconfiguredClient())

    assert web.get_homekit_state("Bridge Pro") == {
        "bridge": "Bridge Pro",
        "count": 0,
        "resources": [],
    }


def test_homekit_other_api_errors_are_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    from huemanager.client import HueApiError

    class FailingClient:
        def v2_get(self, resource_type: str) -> list[dict]:
            raise HueApiError("Hue API 401 GET /homekit: unauthorized")

    monkeypatch.setattr(web, "_client", lambda _: FailingClient())

    with pytest.raises(HTTPException) as exc_info:
        web.get_homekit_state("Bridge Pro")
    assert exc_info.value.status_code == 502
