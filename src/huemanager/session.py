from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from .client import HueApiError, HueBridgeClient


SESSION_SCHEMA = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_migration_session(source_profile: str) -> dict:
    now = _now()
    return {
        "schema": SESSION_SCHEMA,
        "source_profile": source_profile,
        "destination_profile": None,
        "status": "snapshot_ready",
        "created_at": now,
        "updated_at": now,
        "source_release": None,
        "searches": [],
        "last_plan": None,
        "restore": None,
    }


def load_migration_session(path: Path, *, source_profile: str | None = None) -> dict:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SESSION_SCHEMA:
            raise ValueError(f"Unsupported migration session schema: {payload.get('schema')!r}")
        return payload
    return new_migration_session(source_profile or "")


def save_migration_session(session: dict, path: Path) -> None:
    payload = copy.deepcopy(session)
    payload["schema"] = SESSION_SCHEMA
    payload["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def session_summary(session: dict) -> dict:
    plan = session.get("last_plan") or {}
    release = session.get("source_release") or {}
    return {
        "source_profile": session.get("source_profile"),
        "destination_profile": session.get("destination_profile"),
        "status": session.get("status", "snapshot_ready"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "ready": bool(plan.get("ready")),
        "missing": plan.get("missing", []),
        "unmapped_devices": plan.get("unmapped_devices", []),
        "source_release": {
            "completed": bool(release.get("completed")),
            "deleted": release.get("deleted", 0),
            "already_absent": release.get("already_absent", 0),
            "failed": release.get("failed", 0),
        }
        if release
        else None,
        "restore": session.get("restore"),
    }


def record_search(session: dict, destination_profile: str, kind: str) -> dict:
    result = copy.deepcopy(session)
    result["destination_profile"] = destination_profile
    result.setdefault("searches", []).append(
        {
            "at": _now(),
            "kind": kind,
        }
    )
    if result.get("status") not in {"restored", "ready_to_restore"}:
        result["status"] = "waiting_for_devices"
    return result


def record_plan(session: dict, destination_profile: str, plan: dict) -> dict:
    result = copy.deepcopy(session)
    result["destination_profile"] = destination_profile
    result["last_plan"] = {
        "checked_at": _now(),
        "ready": bool(plan.get("ready")),
        "mapped": plan.get("mapped", 0),
        "lights": plan.get("lights", 0),
        "sensors": plan.get("sensors", 0),
        "devices": plan.get("devices", 0),
        "missing": copy.deepcopy(plan.get("missing", [])),
        "unmapped_devices": copy.deepcopy(plan.get("unmapped_devices", [])),
    }
    result["status"] = "ready_to_restore" if plan.get("ready") else "waiting_for_devices"
    return result


def record_restore(session: dict, destination_profile: str, report: dict) -> dict:
    result = copy.deepcopy(session)
    result["destination_profile"] = destination_profile
    result["status"] = "restored"
    result["restore"] = {
        "completed_at": _now(),
        "warnings": len(report.get("warnings", [])),
        "behavior_warnings": len(report.get("behavior_warnings", [])),
        "behavior_instances_skipped": len(report.get("behavior_instances_skipped", [])),
        "resourcelink_warnings": len(report.get("resourcelink_warnings", [])),
    }
    return result


def release_source_resources(snapshot: dict, client: HueBridgeClient) -> dict:
    """Remove selected physical devices from the source Bridge.

    The snapshot remains the source of truth. Deletion is performed once per
    CLIP v2 device instead of once per light/sensor service, which avoids
    partially deleting multi-service accessories. Re-running the operation is
    safe: devices that have already disappeared are reported as already absent.
    """
    current_ids = {
        resource.get("id")
        for resource in client.v2_resources()
        if resource.get("type") == "device" and resource.get("id")
    }
    results: list[dict] = []

    for device in snapshot.get("devices", []):
        device_id = device.get("id")
        if not device_id:
            continue
        product = device.get("product_data", {})
        v1_paths = [
            service.get("id_v1")
            for service in device.get("services_expanded", [])
            if service.get("id_v1")
        ]
        item = {
            "type": "device",
            "id": device_id,
            "name": device.get("metadata", {}).get("name")
            or product.get("product_name")
            or device_id,
            "product": product.get("product_name"),
            "model": product.get("model_id"),
            "v1_paths": v1_paths,
        }
        if device_id not in current_ids:
            item["status"] = "already_absent"
            results.append(item)
            continue
        try:
            client.v2_delete("device", device_id)
            item["status"] = "deleted"
        except (HueApiError, OSError, ValueError, KeyError, IndexError) as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
        results.append(item)

    deleted = sum(item["status"] == "deleted" for item in results)
    already_absent = sum(item["status"] == "already_absent" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    return {
        "attempted_at": _now(),
        "completed": failed == 0,
        "deleted": deleted,
        "already_absent": already_absent,
        "failed": failed,
        "resources": results,
    }


def record_source_release(session: dict, release: dict) -> dict:
    result = copy.deepcopy(session)
    result["source_release"] = copy.deepcopy(release)
    if result.get("status") != "restored":
        result["status"] = (
            "source_released" if release.get("completed") else "source_release_partial"
        )
    return result
