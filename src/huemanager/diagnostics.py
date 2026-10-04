from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from statistics import median
from time import perf_counter
from typing import Any

from .client import HueBridgeClient

ZIGBEE_MIN_CHANNEL = 11
ZIGBEE_MAX_CHANNEL = 26
VALID_WIFI_CHANNELS = range(1, 14)
VALID_WIFI_WIDTHS = {20, 40}


def zigbee_center_mhz(channel: int) -> float | None:
    """Return the IEEE 802.15.4 2.4 GHz center frequency for channel 11..26."""
    if channel < ZIGBEE_MIN_CHANNEL or channel > ZIGBEE_MAX_CHANNEL:
        return None
    return 2405.0 + (channel - 11) * 5.0


def wifi_center_mhz(channel: int) -> float | None:
    """Return the 2.4 GHz Wi-Fi center frequency for channels 1..13."""
    if channel not in VALID_WIFI_CHANNELS:
        return None
    return 2407.0 + channel * 5.0


def coexistence_report(
    zigbee_channel: int | None,
    wifi_channel: int | None,
    wifi_width_mhz: int = 20,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "zigbee_channel": zigbee_channel,
        "wifi_channel": wifi_channel,
        "wifi_width_mhz": wifi_width_mhz,
        "risk": "unknown",
    }

    if zigbee_channel is None or wifi_channel is None:
        report["reason"] = "Both Zigbee and Wi-Fi channels are required"
        return report

    zigbee_center = zigbee_center_mhz(int(zigbee_channel))
    wifi_center = wifi_center_mhz(int(wifi_channel))
    if zigbee_center is None:
        report["reason"] = (
            "The Bridge value is outside IEEE 802.15.4 2.4 GHz channels 11..26"
        )
        report["zigbee_standard_channel"] = False
        return report
    report["zigbee_standard_channel"] = True

    if wifi_center is None:
        report["reason"] = "Wi-Fi channel must be between 1 and 13"
        return report
    if wifi_width_mhz not in VALID_WIFI_WIDTHS:
        report["reason"] = "Wi-Fi width must be 20 or 40 MHz"
        return report

    # Approximate occupied spectra. Zigbee uses a narrow ~2 MHz channel. Wi-Fi
    # spectral masks are wider than the nominal bandwidth, so this is a guide,
    # not an RF spectrum measurement.
    zigbee_low = zigbee_center - 1.0
    zigbee_high = zigbee_center + 1.0
    wifi_half = wifi_width_mhz / 2.0
    wifi_low = wifi_center - wifi_half
    wifi_high = wifi_center + wifi_half

    overlap = max(0.0, min(zigbee_high, wifi_high) - max(zigbee_low, wifi_low))
    if overlap > 0:
        gap = 0.0
        risk = "high"
    else:
        gap = max(wifi_low - zigbee_high, zigbee_low - wifi_high, 0.0)
        risk = "medium" if gap < 5.0 else "low"

    report.update(
        {
            "zigbee_center_mhz": zigbee_center,
            "wifi_center_mhz": wifi_center,
            "zigbee_approx_range_mhz": [zigbee_low, zigbee_high],
            "wifi_approx_range_mhz": [wifi_low, wifi_high],
            "overlap_mhz": round(overlap, 1),
            "guard_gap_mhz": round(gap, 1),
            "risk": risk,
            "reason": {
                "high": "Approximate occupied spectra overlap",
                "medium": "No direct overlap but little guard band remains",
                "low": "No direct overlap and a useful guard band remains",
            }[risk],
        }
    )
    return report


def _timed_samples(call: Callable[[], Any], samples: int) -> tuple[Any, dict[str, Any]]:
    timings: list[float] = []
    payload: Any = None
    for _ in range(samples):
        started = perf_counter()
        payload = call()
        timings.append((perf_counter() - started) * 1000.0)
    ordered = sorted(timings)
    return payload, {
        "samples": samples,
        "median_ms": round(median(timings), 1),
        "min_ms": round(ordered[0], 1),
        "max_ms": round(ordered[-1], 1),
        "all_ms": [round(value, 1) for value in timings],
    }


def _is_first_party(manufacturer: str | None) -> bool:
    value = (manufacturer or "").strip().lower()
    return "philips" in value or "signify" in value


def diagnose_bridge(
    client: HueBridgeClient,
    *,
    wifi_channel: int | None = None,
    wifi_width_mhz: int = 20,
    samples: int = 3,
) -> dict[str, Any]:
    """Collect read-only Hue Bridge diagnostics exposed by the public local APIs."""
    samples = max(1, min(int(samples), 5))

    v1, v1_latency = _timed_samples(client.v1_all, samples)
    resources, v2_latency = _timed_samples(client.v2_resources, samples)
    by_id = {
        resource["id"]: resource
        for resource in resources
        if resource.get("id")
    }
    resource_counts = Counter(
        str(resource.get("type") or "unknown")
        for resource in resources
    )

    config = v1.get("config", {})
    zigbee_channel_raw = config.get("zigbeechannel")
    try:
        zigbee_channel = int(zigbee_channel_raw) if zigbee_channel_raw is not None else None
    except (TypeError, ValueError):
        zigbee_channel = None

    room_names_by_device: dict[str, list[str]] = {}
    for room in (item for item in resources if item.get("type") == "room"):
        room_name = room.get("metadata", {}).get("name") or room.get("id") or "?"
        for child in room.get("children", []):
            if child.get("rtype") == "device" and child.get("rid"):
                room_names_by_device.setdefault(child["rid"], []).append(room_name)

    zigbee_devices: list[dict[str, Any]] = []
    for device in (
        item for item in resources
        if item.get("type") == "device" and item.get("id")
    ):
        connectivity = [
            by_id.get(service.get("rid"), {})
            for service in device.get("services", [])
            if service.get("rid")
            and by_id.get(service.get("rid"), {}).get("type") == "zigbee_connectivity"
        ]
        if not connectivity:
            continue

        product = device.get("product_data", {})
        statuses = [
            {
                "id": service.get("id"),
                "status": service.get("status"),
                "mac_address": service.get("mac_address"),
            }
            for service in connectivity
        ]
        status_values = [entry.get("status") for entry in statuses]
        if any(value not in (None, "connected") for value in status_values):
            health = "disconnected"
        elif any(value == "connected" for value in status_values):
            health = "connected"
        else:
            health = "unknown"

        zigbee_devices.append(
            {
                "id": device.get("id"),
                "name": (
                    device.get("metadata", {}).get("name")
                    or product.get("product_name")
                    or device.get("id")
                ),
                "manufacturer": product.get("manufacturer_name"),
                "model": product.get("model_id"),
                "rooms": sorted(room_names_by_device.get(device["id"], [])),
                "health": health,
                "connectivity": statuses,
            }
        )

    zigbee_health_counts = Counter(item["health"] for item in zigbee_devices)
    disconnected_devices = [
        item for item in zigbee_devices if item["health"] == "disconnected"
    ]

    unreachable: list[dict[str, Any]] = []
    for light_id, light in v1.get("lights", {}).items():
        if light.get("state", {}).get("reachable") is False:
            unreachable.append(
                {
                    "kind": "light",
                    "id": str(light_id),
                    "name": light.get("name"),
                    "manufacturer": light.get("manufacturername"),
                    "model": light.get("modelid"),
                    "uniqueid": light.get("uniqueid"),
                }
            )
    for sensor_id, sensor in v1.get("sensors", {}).items():
        if sensor.get("config", {}).get("reachable") is False:
            unreachable.append(
                {
                    "kind": "sensor",
                    "id": str(sensor_id),
                    "name": sensor.get("name"),
                    "manufacturer": sensor.get("manufacturername"),
                    "model": sensor.get("modelid"),
                    "uniqueid": sensor.get("uniqueid"),
                }
            )

    third_party: list[dict[str, Any]] = []
    for section, kind in (("lights", "light"), ("sensors", "sensor")):
        for resource_id, item in v1.get(section, {}).items():
            manufacturer = item.get("manufacturername")
            if manufacturer and not _is_first_party(str(manufacturer)):
                third_party.append(
                    {
                        "kind": kind,
                        "id": str(resource_id),
                        "name": item.get("name"),
                        "manufacturer": manufacturer,
                        "model": item.get("modelid"),
                    }
                )

    software_update_status = Counter()
    for update in (
        resource for resource in resources
        if resource.get("type") == "device_software_update"
    ):
        software_update_status[str(update.get("status") or "unknown")] += 1

    coexistence = coexistence_report(
        zigbee_channel,
        wifi_channel,
        wifi_width_mhz,
    )

    findings: list[dict[str, str]] = []
    if zigbee_channel is not None and zigbee_center_mhz(zigbee_channel) is None:
        findings.append(
            {
                "severity": "warning",
                "code": "non_standard_zigbee_channel",
                "message": (
                    f"Bridge reports Zigbee channel {zigbee_channel}, outside standard "
                    "2.4 GHz Zigbee channels 11..26. Verify the raw Bridge value before "
                    "drawing RF conclusions."
                ),
            }
        )
    if disconnected_devices:
        findings.append(
            {
                "severity": "warning",
                "code": "zigbee_disconnected",
                "message": (
                    f"{len(disconnected_devices)} Zigbee device(s) are reported disconnected."
                ),
            }
        )
    if unreachable:
        findings.append(
            {
                "severity": "warning",
                "code": "v1_unreachable",
                "message": (
                    f"{len(unreachable)} v1 light/sensor resource(s) are explicitly unreachable."
                ),
            }
        )
    if coexistence.get("risk") == "high":
        findings.append(
            {
                "severity": "warning",
                "code": "wifi_zigbee_overlap",
                "message": (
                    "The supplied 2.4 GHz Wi-Fi channel approximately overlaps the Zigbee channel."
                ),
            }
        )
    elif coexistence.get("risk") == "medium":
        findings.append(
            {
                "severity": "info",
                "code": "wifi_zigbee_small_guard",
                "message": (
                    "Wi-Fi and Zigbee do not directly overlap in the approximation, "
                    "but the guard band is small."
                ),
            }
        )
    if max(v1_latency["max_ms"], v2_latency["max_ms"]) >= 1000:
        findings.append(
            {
                "severity": "warning",
                "code": "slow_bridge_api",
                "message": (
                    "At least one local Bridge API read took 1 second or more. "
                    "This is IP/API latency, not a direct Zigbee radio measurement."
                ),
            }
        )
    if third_party:
        findings.append(
            {
                "severity": "info",
                "code": "third_party_zigbee",
                "message": (
                    f"{len(third_party)} third-party v1 light/sensor resource(s) detected. "
                    "Presence alone does not prove a mesh problem."
                ),
            }
        )
    if not findings:
        findings.append(
            {
                "severity": "info",
                "code": "no_public_api_fault",
                "message": (
                    "No obvious fault is visible through the public Hue APIs. "
                    "This does not exclude RF retries, congestion, weak routes or packet loss."
                ),
            }
        )

    return {
        "bridge": {
            key: config.get(key)
            for key in (
                "name",
                "bridgeid",
                "modelid",
                "swversion",
                "apiversion",
                "zigbeechannel",
                "ipaddress",
                "mac",
            )
        },
        "api_latency": {
            "clip_v1_root": v1_latency,
            "clip_v2_resources": v2_latency,
        },
        "counts": {
            "v1": {
                section: len(v1.get(section, {}))
                for section in (
                    "lights",
                    "sensors",
                    "groups",
                    "scenes",
                    "rules",
                    "schedules",
                    "resourcelinks",
                )
            },
            "v2_total": len(resources),
            "v2_by_type": dict(sorted(resource_counts.items())),
        },
        "zigbee": {
            "channel": zigbee_channel,
            "standard_2_4ghz_channel": (
                zigbee_channel is not None
                and zigbee_center_mhz(zigbee_channel) is not None
            ),
            "center_mhz": (
                zigbee_center_mhz(zigbee_channel)
                if zigbee_channel is not None
                else None
            ),
            "devices": len(zigbee_devices),
            "connected": zigbee_health_counts.get("connected", 0),
            "disconnected": zigbee_health_counts.get("disconnected", 0),
            "unknown": zigbee_health_counts.get("unknown", 0),
            "disconnected_devices": disconnected_devices,
        },
        "reachability": {
            "unreachable_count": len(unreachable),
            "unreachable": unreachable,
        },
        "third_party": {
            "count": len(third_party),
            "resources": third_party,
        },
        "software_updates": dict(sorted(software_update_status.items())),
        "wifi_coexistence": coexistence,
        "findings": findings,
        "limitations": [
            "Hue public local APIs do not expose a Zigbee neighbour table.",
            "Per-link RSSI/LQI, retry counters, packet loss and channel utilization are not exposed.",
            "Wi-Fi coexistence is an RF approximation based on the channel supplied by the user.",
        ],
    }
