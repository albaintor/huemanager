from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from huemanager import web


class FakeHueClient:
    def __init__(self, fabrics: list[dict]) -> None:
        self.fabrics = list(fabrics)
        self.deleted: list[tuple[str, str]] = []

    def v2_get(self, resource_type: str, resource_id: str | None = None) -> list[dict]:
        assert resource_type == "matter_fabric"
        if resource_id is not None:
            return [row for row in self.fabrics if row.get("id") == resource_id]
        return list(self.fabrics)

    def v2_delete(self, resource_type: str, resource_id: str) -> list[dict]:
        assert resource_type == "matter_fabric"
        self.deleted.append((resource_type, resource_id))
        self.fabrics = [row for row in self.fabrics if row.get("id") != resource_id]
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
    assert row["vendor_name"] == "Apple"
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


def test_delete_matter_fabric_only_deletes_requested_fabric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apple_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    client = FakeHueClient(
        [
            _fabric(fabric_id=apple_id, label="Maison", vendor_id=0x1349),
            _fabric(fabric_id=other_id, label="Google", vendor_id=6006),
        ]
    )
    monkeypatch.setattr(web, "_client", lambda _: client)

    result = web.delete_matter_fabric("Bridge Pro", apple_id)

    assert client.deleted == [("matter_fabric", apple_id)]
    assert result["deleted"]["is_apple"] is True
    assert result["remaining"] == 1
    assert client.fabrics[0]["id"] == other_id


def test_delete_matter_fabric_rejects_unknown_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeHueClient([])
    monkeypatch.setattr(web, "_client", lambda _: client)

    with pytest.raises(HTTPException) as exc_info:
        web.delete_matter_fabric("Bridge Pro", str(uuid.uuid4()))

    assert exc_info.value.status_code == 404
    assert client.deleted == []
