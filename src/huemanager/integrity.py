from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import HueBridgeClient

V1_SECTIONS = (
    "lights",
    "sensors",
    "groups",
    "scenes",
    "rules",
    "schedules",
    "resourcelinks",
)
V1_REF_RE = re.compile(
    r"/(lights|sensors|groups|scenes|rules|schedules|resourcelinks)/([A-Za-z0-9_-]+)"
)

# Legacy Hue API v1 represented a multi-button remote as a single switch sensor,
# while API v2 exposes each physical button as its own button resource. Those
# button resources can therefore legitimately share one id_v1 (/sensors/N).
MULTI_SERVICE_ID_V1_TYPES = {"button", "bell_button", "relative_rotary"}

# Some ResourceIdentifier values intentionally point to Hue catalog/internal objects
# that are not enumerated by GET /clip/v2/resource. Treating them as dangling
# references creates false positives (notably scene metadata.image/public_image and
# behavior recipe references).
OPAQUE_V2_REFERENCE_TYPES = {"public_image", "recipe"}

_RUNTIME_FIELDS_BY_V2_TYPE: dict[str, set[str]] = {
    "zigbee_connectivity": {"status"},
    "device_software_update": {"status"},
    "light": {
        "on",
        "dimming",
        "dimming_delta",
        "color",
        "color_temperature",
        "color_temperature_delta",
        "dynamics",
        "effects",
        "timed_effects",
        "signaling",
        "gradient",
    },
    "grouped_light": {
        "on",
        "dimming",
        "dimming_delta",
        "color",
        "color_temperature",
        "color_temperature_delta",
        "dynamics",
        "effects",
        "timed_effects",
        "signaling",
        "gradient",
    },
    "button": {"button"},
    "relative_rotary": {"relative_rotary"},
    "motion": {"motion"},
    "temperature": {"temperature"},
    "light_level": {"light"},
    "contact": {"contact_report"},
    "tamper": {"tamper_reports"},
    "device_power": {"power_state"},
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    )


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _v1_path_exists(v1: dict[str, Any], path: str) -> bool:
    # /groups/0 is the implicit all-lights group. It is a valid id_v1 target for
    # bridge_home/grouped_light even when it is not materialized in v1["groups"].
    if path == "/groups/0":
        return True
    match = V1_REF_RE.fullmatch(path)
    if not match:
        return False
    section, resource_id = match.groups()
    return str(resource_id) in v1.get(section, {})


def _walk_v2_refs(value: Any, path: str = "") -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if isinstance(value, dict):
        rid = value.get("rid")
        rtype = value.get("rtype")
        if isinstance(rid, str) and isinstance(rtype, str):
            refs.append({"rid": rid, "rtype": rtype, "path": path or "$"})
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            refs.extend(_walk_v2_refs(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            refs.extend(_walk_v2_refs(child, f"{path}[{index}]"))
    return refs


def _normalize_v1_resource(section: str, resource: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(resource)
    if section == "lights":
        value.pop("state", None)
        value.pop("swupdate", None)
    elif section == "sensors":
        value.pop("state", None)
        config = value.get("config")
        if isinstance(config, dict):
            for key in ("battery", "reachable", "pending"):
                config.pop(key, None)
    elif section == "groups":
        value.pop("state", None)
        value.pop("action", None)
    return value


def _normalize_v2_resource(resource: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(resource)
    resource_type = str(value.get("type") or "")
    for key in _RUNTIME_FIELDS_BY_V2_TYPE.get(resource_type, set()):
        value.pop(key, None)
    return value


def _runtime_observations(resources: list[dict[str, Any]]) -> dict[str, Any]:
    zigbee = {}
    updates = {}
    homekit = {}
    matter = {}
    for resource in resources:
        resource_id = resource.get("id")
        if not resource_id:
            continue
        resource_type = resource.get("type")
        if resource_type == "zigbee_connectivity":
            zigbee[str(resource_id)] = {
                "owner": resource.get("owner"),
                "mac_address": resource.get("mac_address"),
                "status": resource.get("status"),
            }
        elif resource_type == "device_software_update":
            updates[str(resource_id)] = {
                "owner": resource.get("owner"),
                "status": resource.get("status"),
            }
        elif resource_type == "homekit":
            homekit[str(resource_id)] = {
                "status": resource.get("status"),
                "action": resource.get("action"),
            }
        elif resource_type in {"matter", "matter_fabric"}:
            matter[f"{resource_type}:{resource_id}"] = {
                key: resource.get(key)
                for key in ("status", "action", "fabric_data", "creation_time")
                if key in resource
            }
    return {
        "zigbee_connectivity": zigbee,
        "device_software_update": updates,
        "homekit": homekit,
        "matter": matter,
    }


def collect_configuration_snapshot(client: HueBridgeClient) -> dict[str, Any]:
    """Capture a read-only normalized configuration snapshot for crash correlation."""
    v1 = client.v1_all()
    resources = client.v2_resources()

    v1_normalized = {
        section: {
            str(resource_id): _normalize_v1_resource(section, resource)
            for resource_id, resource in v1.get(section, {}).items()
        }
        for section in V1_SECTIONS
    }
    v2_normalized = {
        f"{resource.get('type', 'unknown')}:{resource['id']}": _normalize_v2_resource(resource)
        for resource in resources
        if resource.get("id")
    }

    bridge_config = v1.get("config", {})
    return {
        "schema": 1,
        "captured_at": _utc_now(),
        "bridge": {
            key: bridge_config.get(key)
            for key in (
                "name",
                "bridgeid",
                "modelid",
                "swversion",
                "apiversion",
                "zigbeechannel",
                "mac",
            )
        },
        "counts": {
            "v1": {section: len(v1_normalized[section]) for section in V1_SECTIONS},
            "v2_total": len(v2_normalized),
            "v2_by_type": dict(
                sorted(
                    Counter(
                        str(resource.get("type") or "unknown")
                        for resource in resources
                    ).items()
                )
            ),
        },
        "v1": v1_normalized,
        "v2": v2_normalized,
        "runtime": _runtime_observations(resources),
        "configuration_hash": _canonical_hash(
            {"v1": v1_normalized, "v2": v2_normalized}
        ),
    }


def _field_differences(
    before: Any,
    after: Any,
    *,
    path: str = "$",
    limit: int = 40,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []

    def visit(left: Any, right: Any, current: str) -> None:
        if len(differences) >= limit:
            return
        if type(left) is not type(right):
            differences.append({"path": current, "before": left, "after": right})
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                if len(differences) >= limit:
                    return
                child_path = f"{current}.{key}"
                if key not in left:
                    differences.append(
                        {"path": child_path, "before": None, "after": right[key]}
                    )
                elif key not in right:
                    differences.append(
                        {"path": child_path, "before": left[key], "after": None}
                    )
                else:
                    visit(left[key], right[key], child_path)
            return
        if isinstance(left, list):
            if left != right:
                differences.append({"path": current, "before": left, "after": right})
            return
        if left != right:
            differences.append({"path": current, "before": left, "after": right})

    visit(before, after, path)
    return differences


def _flatten_v1(snapshot: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section, values in snapshot.get("v1", {}).items():
        for resource_id, resource in values.items():
            result[f"{section}:{resource_id}"] = resource
    return result


def compare_configuration_snapshots(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    before = {**_flatten_v1(baseline), **baseline.get("v2", {})}
    after = {**_flatten_v1(current), **current.get("v2", {})}

    added_keys = sorted(set(after) - set(before))
    removed_keys = sorted(set(before) - set(after))
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before) & set(after)):
        if _canonical_hash(before[key]) == _canonical_hash(after[key]):
            continue
        changed.append(
            {
                "key": key,
                "differences": _field_differences(before[key], after[key]),
            }
        )

    runtime_before = baseline.get("runtime", {})
    runtime_after = current.get("runtime", {})
    runtime_changes = _field_differences(
        runtime_before,
        runtime_after,
        path="$.runtime",
        limit=100,
    )

    return {
        "baseline_captured_at": baseline.get("captured_at"),
        "current_captured_at": current.get("captured_at"),
        "baseline_hash": baseline.get("configuration_hash"),
        "current_hash": current.get("configuration_hash"),
        "configuration_changed": bool(added_keys or removed_keys or changed),
        "added": added_keys,
        "removed": removed_keys,
        "changed": changed,
        "runtime_changes": runtime_changes,
        "summary": {
            "added": len(added_keys),
            "removed": len(removed_keys),
            "changed": len(changed),
            "runtime_changes": len(runtime_changes),
        },
    }


def deep_integrity_audit(client: HueBridgeClient) -> dict[str, Any]:
    """Perform a read-only structural integrity audit across Hue v1 and v2 resources."""
    v1 = client.v1_all()
    resources = client.v2_resources()
    by_id = {
        str(resource["id"]): resource
        for resource in resources
        if resource.get("id")
    }
    findings: list[dict[str, Any]] = []

    def add(
        severity: str,
        code: str,
        message: str,
        *,
        resource: str | None = None,
        details: Any = None,
        raw: Any = None,
    ) -> None:
        findings.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "resource": resource,
                "details": details,
                "raw": raw,
            }
        )

    # Resource payload sizes and high-cardinality structures.
    type_sizes: dict[str, list[int]] = {}
    type_counts = Counter()
    for resource in resources:
        resource_type = str(resource.get("type") or "unknown")
        type_counts[resource_type] += 1
        size = _json_size(resource)
        type_sizes.setdefault(resource_type, []).append(size)
        if size >= 65536:
            add(
                "high",
                "very_large_v2_resource",
                f"Resource payload is unusually large ({size} bytes).",
                resource=f"{resource_type}:{resource.get('id')}",
                details={"size_bytes": size},
                raw=resource,
            )
        elif size >= 32768:
            add(
                "medium",
                "large_v2_resource",
                f"Resource payload is large ({size} bytes).",
                resource=f"{resource_type}:{resource.get('id')}",
                details={"size_bytes": size},
                raw=resource,
            )

        if resource_type in {"scene", "smart_scene"}:
            actions = resource.get("actions")
            if isinstance(actions, list) and len(actions) >= 100:
                add(
                    "high",
                    "scene_many_actions",
                    f"Scene contains {len(actions)} actions.",
                    resource=f"{resource_type}:{resource.get('id')}",
                    details={"actions": len(actions)},
                    raw=resource,
                )
            elif isinstance(actions, list) and len(actions) >= 50:
                add(
                    "medium",
                    "scene_many_actions",
                    f"Scene contains {len(actions)} actions.",
                    resource=f"{resource_type}:{resource.get('id')}",
                    details={"actions": len(actions)},
                    raw=resource,
                )

        if resource_type == "behavior_instance":
            configuration = resource.get("configuration", {})
            config_size = _json_size(configuration)
            if config_size >= 32768:
                add(
                    "high",
                    "large_behavior_configuration",
                    f"Automation configuration is unusually large ({config_size} bytes).",
                    resource=f"behavior_instance:{resource.get('id')}",
                    details={"configuration_size_bytes": config_size},
                    raw=resource,
                )

    # Generic v2 references.
    for resource in resources:
        source_id = str(resource.get("id") or "")
        source_type = str(resource.get("type") or "unknown")
        for ref in _walk_v2_refs(resource):
            rid = ref["rid"]
            rtype = ref["rtype"]
            if rid == source_id:
                continue
            if rtype in OPAQUE_V2_REFERENCE_TYPES:
                continue
            target = by_id.get(rid)
            if target is None:
                add(
                    "high",
                    "missing_v2_reference",
                    f"{source_type} references a missing {rtype} resource.",
                    resource=f"{source_type}:{source_id}",
                    details=ref,
                    raw=resource,
                )
            elif target.get("type") != rtype:
                add(
                    "high",
                    "v2_reference_type_mismatch",
                    (
                        f"Reference declares rtype={rtype}, but target resource "
                        f"has type={target.get('type')}."
                    ),
                    resource=f"{source_type}:{source_id}",
                    details={**ref, "actual_type": target.get("type")},
                    raw=resource,
                )

    # Device/service ownership and room membership integrity.
    all_service_ids: set[str] = set()
    zigbee_macs: dict[str, list[str]] = {}
    for device in (
        resource
        for resource in resources
        if resource.get("type") == "device" and resource.get("id")
    ):
        device_id = str(device["id"])
        services = device.get("services", [])
        service_ids = [
            str(ref.get("rid"))
            for ref in services
            if isinstance(ref, dict) and ref.get("rid")
        ]
        if not service_ids:
            add(
                "high",
                "device_without_services",
                "Device has no services.",
                resource=f"device:{device_id}",
                raw=device,
            )
        duplicates = sorted(
            rid for rid, count in Counter(service_ids).items() if count > 1
        )
        if duplicates:
            add(
                "high",
                "duplicate_device_service_reference",
                "Device contains duplicate service references.",
                resource=f"device:{device_id}",
                details={"duplicate_service_ids": duplicates},
                raw=device,
            )

        zigbee_count = 0
        for service_ref in services:
            if not isinstance(service_ref, dict):
                continue
            rid = service_ref.get("rid")
            rtype = service_ref.get("rtype")
            if not isinstance(rid, str):
                continue
            all_service_ids.add(rid)
            service = by_id.get(rid)
            if service is None:
                add(
                    "critical",
                    "missing_device_service",
                    f"Device service {rtype}:{rid} does not exist.",
                    resource=f"device:{device_id}",
                    details={"rid": rid, "rtype": rtype},
                    raw=device,
                )
                continue
            owner = service.get("owner")
            if isinstance(owner, dict) and owner.get("rid") not in (None, device_id):
                add(
                    "high",
                    "service_owner_mismatch",
                    "Device references a service owned by another resource.",
                    resource=f"{service.get('type')}:{rid}",
                    details={
                        "expected_owner": device_id,
                        "actual_owner": owner,
                    },
                    raw=service,
                )
            if service.get("type") == "zigbee_connectivity":
                zigbee_count += 1
                mac = service.get("mac_address")
                if isinstance(mac, str) and mac:
                    zigbee_macs.setdefault(mac.casefold(), []).append(device_id)
        if zigbee_count > 1:
            add(
                "medium",
                "multiple_zigbee_connectivity_services",
                f"Device exposes {zigbee_count} Zigbee connectivity services.",
                resource=f"device:{device_id}",
                raw=device,
            )

    for mac, device_ids in sorted(zigbee_macs.items()):
        unique_devices = sorted(set(device_ids))
        if len(unique_devices) > 1:
            add(
                "critical",
                "duplicate_zigbee_mac",
                "The same Zigbee MAC address is associated with multiple devices.",
                details={"mac_address": mac, "device_ids": unique_devices},
            )

    for resource in resources:
        resource_id = resource.get("id")
        owner = resource.get("owner")
        if not resource_id or not isinstance(owner, dict):
            continue
        owner_id = owner.get("rid")
        owner_type = owner.get("rtype")
        if isinstance(owner_id, str) and owner_id not in by_id:
            add(
                "high",
                "missing_owner",
                f"Resource owner {owner_type}:{owner_id} does not exist.",
                resource=f"{resource.get('type')}:{resource_id}",
                details={"owner": owner},
                raw=resource,
            )

    for room in (
        resource
        for resource in resources
        if resource.get("type") in {"room", "zone"} and resource.get("id")
    ):
        room_id = str(room["id"])
        for child in room.get("children", []):
            if not isinstance(child, dict) or not child.get("rid"):
                continue
            child_id = str(child["rid"])
            expected_type = child.get("rtype")
            target = by_id.get(child_id)
            if target is None:
                add(
                    "critical",
                    "missing_room_child",
                    f"{room.get('type')} references a missing child resource.",
                    resource=f"{room.get('type')}:{room_id}",
                    details={"child": child},
                    raw=room,
                )
            elif expected_type and target.get("type") != expected_type:
                add(
                    "high",
                    "room_child_type_mismatch",
                    "Room/zone child reference type does not match the target resource.",
                    resource=f"{room.get('type')}:{room_id}",
                    details={
                        "child": child,
                        "actual_type": target.get("type"),
                    },
                    raw=room,
                )

    # Orphan service resources: service has an owner, but no device declares it.
    service_like_types = {
        "light",
        "button",
        "relative_rotary",
        "motion",
        "temperature",
        "light_level",
        "contact",
        "tamper",
        "device_power",
        "zigbee_connectivity",
        "device_software_update",
    }
    for resource in resources:
        resource_id = resource.get("id")
        if (
            not resource_id
            or resource.get("type") not in service_like_types
            or resource_id in all_service_ids
        ):
            continue
        owner = resource.get("owner")
        if isinstance(owner, dict) and owner.get("rtype") == "device":
            add(
                "medium",
                "orphan_device_service",
                "Service is owned by a device but is not declared in any device.services list.",
                resource=f"{resource.get('type')}:{resource_id}",
                details={"owner": owner},
                raw=resource,
            )

    # v1/v2 linkage. Sharing id_v1 across DIFFERENT v2 resource types is normal:
    # e.g. a device, light, zigbee_connectivity and entertainment service can all
    # map to /lights/N. Only duplicate id_v1 values within the SAME v2 type are
    # suspicious enough to report.
    id_v1_by_type: dict[tuple[str, str], list[str]] = {}
    for resource in resources:
        id_v1 = resource.get("id_v1")
        if not isinstance(id_v1, str) or not id_v1:
            continue
        resource_type = str(resource.get("type") or "unknown")
        key = f"{resource_type}:{resource.get('id')}"
        id_v1_by_type.setdefault((resource_type, id_v1), []).append(key)
        if not _v1_path_exists(v1, id_v1):
            add(
                "high",
                "missing_v1_counterpart",
                "v2 resource points to a missing v1 resource.",
                resource=key,
                details={"id_v1": id_v1},
                raw=resource,
            )

    for (resource_type, id_v1), resource_keys in sorted(id_v1_by_type.items()):
        if len(resource_keys) <= 1 or resource_type in MULTI_SERVICE_ID_V1_TYPES:
            continue
        add(
            "high",
            "duplicate_id_v1_same_type",
            (
                f"Multiple {resource_type} resources share the same id_v1. "
                "Sharing id_v1 is expected for multi-service switch resources "
                "such as button, bell_button and relative_rotary, which are excluded."
            ),
            details={
                "id_v1": id_v1,
                "resource_type": resource_type,
                "resources": resource_keys,
            },
        )

    v1_uniqueids: dict[str, list[str]] = {}
    for section in ("lights", "sensors"):
        for resource_id, resource in v1.get(section, {}).items():
            uniqueid = resource.get("uniqueid")
            if isinstance(uniqueid, str) and uniqueid:
                v1_uniqueids.setdefault(uniqueid.casefold(), []).append(
                    f"{section}:{resource_id}"
                )
    for uniqueid, resource_keys in sorted(v1_uniqueids.items()):
        if len(resource_keys) > 1:
            add(
                "high",
                "duplicate_v1_uniqueid",
                "Multiple v1 resources share the same uniqueid.",
                details={"uniqueid": uniqueid, "resources": resource_keys},
            )

    # Broken v1 references.
    existing_v1 = {
        f"/{section}/{resource_id}"
        for section in V1_SECTIONS
        for resource_id in v1.get(section, {})
    }
    existing_v1.add("/groups/0")
    for section in ("rules", "schedules", "resourcelinks"):
        for resource_id, resource in v1.get(section, {}).items():
            text = json.dumps(resource, ensure_ascii=False, default=str)
            refs = {
                f"/{ref_section}/{ref_id}"
                for ref_section, ref_id in V1_REF_RE.findall(text)
            }
            missing = sorted(ref for ref in refs if ref not in existing_v1)
            if missing:
                status = resource.get("status")
                if section == "resourcelinks":
                    severity = "medium"
                elif status == "disabled":
                    severity = "medium"
                else:
                    severity = "high"
                name = resource.get("name")
                prefix = (
                    f"{name} · " if isinstance(name, str) and name.strip() else ""
                )
                add(
                    severity,
                    "broken_v1_reference",
                    (
                        prefix
                        + f"{section[:-1].capitalize()} references missing v1 resources: "
                        + ", ".join(missing[:6])
                        + (" …" if len(missing) > 6 else "")
                    ),
                    resource=f"{section}:{resource_id}",
                    details={
                        "missing": missing,
                        "status": status,
                        "name": name,
                        "owner": resource.get("owner"),
                    },
                    raw=resource,
                )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    findings.sort(
        key=lambda item: (
            severity_order.get(str(item.get("severity")), 9),
            str(item.get("code")),
            str(item.get("resource") or ""),
        )
    )
    severity_counts = Counter(str(item["severity"]) for item in findings)

    payload_stats = {
        resource_type: {
            "count": len(sizes),
            "total_bytes": sum(sizes),
            "max_bytes": max(sizes) if sizes else 0,
        }
        for resource_type, sizes in sorted(type_sizes.items())
    }

    return {
        "captured_at": _utc_now(),
        "read_only": True,
        "summary": {
            "critical": severity_counts.get("critical", 0),
            "high": severity_counts.get("high", 0),
            "medium": severity_counts.get("medium", 0),
            "info": severity_counts.get("info", 0),
            "total_findings": len(findings),
            "suspicion_score": (
                severity_counts.get("critical", 0) * 100
                + severity_counts.get("high", 0) * 20
                + severity_counts.get("medium", 0) * 5
            ),
        },
        "counts": {
            "v1": {
                section: len(v1.get(section, {}))
                for section in V1_SECTIONS
            },
            "v2_total": len(resources),
            "v2_by_type": dict(sorted(type_counts.items())),
        },
        "payload_stats": payload_stats,
        "findings": findings,
    }


class CrashDiagnosticStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    @staticmethod
    def _safe_bridge_key(bridge_name: str) -> str:
        digest = hashlib.sha256(bridge_name.encode("utf-8")).hexdigest()[:12]
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", bridge_name).strip("._-") or "bridge"
        return f"{safe[:40]}-{digest}"

    def _bridge_dir(self, bridge_name: str) -> Path:
        path = self.root / self._safe_bridge_key(bridge_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _baseline_path(self, bridge_name: str) -> Path:
        return self._bridge_dir(bridge_name) / "baseline.json"

    def _reports_path(self, bridge_name: str) -> Path:
        return self._bridge_dir(bridge_name) / "post-crash-reports.json"

    def has_baseline(self, bridge_name: str) -> bool:
        return self._baseline_path(bridge_name).exists()

    def save_baseline(
        self,
        bridge_name: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        path = self._baseline_path(bridge_name)
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {
            "bridge": bridge_name,
            "captured_at": snapshot.get("captured_at"),
            "configuration_hash": snapshot.get("configuration_hash"),
            "counts": snapshot.get("counts"),
            "path": str(path),
        }

    def capture_baseline(
        self,
        bridge_name: str,
        client: HueBridgeClient,
    ) -> dict[str, Any]:
        return self.save_baseline(
            bridge_name,
            collect_configuration_snapshot(client),
        )

    def load_baseline(self, bridge_name: str) -> dict[str, Any] | None:
        path = self._baseline_path(bridge_name)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_reports(self, bridge_name: str) -> list[dict[str, Any]]:
        path = self._reports_path(bridge_name)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def reports(self, bridge_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._load_reports(bridge_name))

    def status(self, bridge_name: str) -> dict[str, Any]:
        baseline = self.load_baseline(bridge_name)
        reports = self.reports(bridge_name)
        return {
            "bridge": bridge_name,
            "baseline": (
                {
                    "captured_at": baseline.get("captured_at"),
                    "configuration_hash": baseline.get("configuration_hash"),
                    "counts": baseline.get("counts"),
                }
                if baseline
                else None
            ),
            "post_crash_enabled": baseline is not None,
            "reports": reports,
        }

    def capture_post_crash(
        self,
        bridge_name: str,
        client: HueBridgeClient,
        outage_event: dict[str, Any],
    ) -> dict[str, Any]:
        baseline = self.load_baseline(bridge_name)
        if baseline is None:
            return {
                "bridge": bridge_name,
                "status": "skipped",
                "reason": "no_baseline",
            }

        current = collect_configuration_snapshot(client)
        comparison = compare_configuration_snapshots(baseline, current)
        report = {
            "captured_at": _utc_now(),
            "outage": copy.deepcopy(outage_event),
            "comparison": comparison,
        }
        with self._lock:
            reports = self._load_reports(bridge_name)
            reports.append(report)
            reports = reports[-100:]
            self._reports_path(bridge_name).write_text(
                json.dumps(reports, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return report

    def schedule_post_crash(
        self,
        bridge_name: str,
        client_factory: Callable[[], HueBridgeClient],
        outage_event: dict[str, Any],
        *,
        delay_seconds: int = 20,
    ) -> bool:
        if not self.has_baseline(bridge_name):
            return False

        def worker() -> None:
            time.sleep(max(0, delay_seconds))
            try:
                self.capture_post_crash(
                    bridge_name,
                    client_factory(),
                    outage_event,
                )
            except (OSError, ValueError, KeyError, RuntimeError, TypeError):
                # Post-crash diagnostics must never interfere with the availability monitor.
                return

        thread = threading.Thread(
            target=worker,
            name=f"hue-post-crash-{self._safe_bridge_key(bridge_name)}",
            daemon=True,
        )
        thread.start()
        return True
