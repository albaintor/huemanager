from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from huemanager import web


class FakeHueClient:
    def __init__(self, fabrics: list[dict], matters: list[dict] | None = None) -> None:
        self.fabrics = list(fabrics)
        self.matters = list(matters or [])
        self.deleted: list[tuple[str, str]] = []
        self.puts: list[tuple[str, str, dict]] = []

    def v2_get(self, resource_type: str, resource_id: str | None = None) -> list[dict]:
        rows = self.fabrics if resource_type == "matter_fabric" else self.matters
        if resource_type not in {"matter_fabric", "matter"}:
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
        assert resource_type == "matter"
        self.puts.append((resource_type, resource_id, body))
        if body == {"action": "matter_reset"}:
            self.fabrics = []
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
