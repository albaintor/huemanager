from __future__ import annotations

from typing import Any

from .client import HueApiError, HueBridgeClient

# CLIP v1 swupdate2 reports these states when a manually installable update exists.
_READY_STATES = frozenset({"anyreadytoinstall", "allreadytoinstall", "readytoinstall"})


def _update_info(config: dict[str, Any]) -> dict[str, Any]:
    update = config.get("swupdate2")
    if not isinstance(update, dict):
        return {
            "supported": False,
            "reason": "CLIP v1 swupdate2 is not exposed by this Bridge.",
        }

    bridge = update.get("bridge")
    bridge = bridge if isinstance(bridge, dict) else {}
    autoinstall = update.get("autoinstall")
    autoinstall = autoinstall if isinstance(autoinstall, dict) else {}
    state = str(update.get("state") or "unknown")
    bridge_state = str(bridge.get("state") or "unknown")
    return {
        "supported": True,
        "state": state,
        "bridge_state": bridge_state,
        "check_in_progress": bool(update.get("checkforupdate")),
        "ready_to_install": state.lower() in _READY_STATES
        or bridge_state.lower() in _READY_STATES,
        "last_change": update.get("lastchange"),
        "last_install": bridge.get("lastinstall"),
        "automatic_install": autoinstall.get("on"),
        "automatic_install_time": autoinstall.get("updatetime"),
    }


def software_update_status(client: HueBridgeClient) -> dict[str, Any]:
    """Read the Bridge update state without fetching or installing new firmware.

    Only return selected configuration fields; never expose the CLIP v1 whitelist.
    Firmware eligibility (stable/beta) is decided outside the local Hue API.
    """
    config = client.v1_get("/config")
    if not isinstance(config, dict):
        raise HueApiError("Unexpected Hue /config response")

    services = config.get("internetservices")
    services = services if isinstance(services, dict) else {}

    # Bridge Pro CLIP v1 may expose only the numeric firmware build in
    # config.swversion (for example 2071537020), while the v2 bridge device
    # product_data carries the complete semantic Hue version
    # (for example 6.2.2071537020). Prefer v2 when available, but retain the
    # raw v1 build for diagnostics and for older firmware compatibility.
    v1_software_version = config.get("swversion")
    full_software_version = v1_software_version
    try:
        devices = client.v2_get("device")
        if isinstance(devices, list):
            bridge_device = next(
                (
                    item
                    for item in devices
                    if isinstance(item, dict)
                    and (
                        any(
                            isinstance(service, dict)
                            and service.get("rtype") == "bridge"
                            for service in item.get("services", [])
                        )
                        or (
                            str((item.get("product_data") or {}).get("model_id") or "")
                            == str(config.get("modelid") or "")
                            and str(
                                (item.get("product_data") or {}).get(
                                    "product_archetype"
                                )
                                or ""
                            ).startswith("bridge")
                        )
                    )
                ),
                None,
            )
            if bridge_device:
                product_data = bridge_device.get("product_data") or {}
                candidate = product_data.get("software_version")
                if candidate:
                    full_software_version = candidate
    except (HueApiError, OSError, ValueError):
        pass

    info: dict[str, Any] = {
        "bridge": {
            "name": config.get("name"),
            "model_id": config.get("modelid"),
            "bridge_id": config.get("bridgeid"),
            "software_version": full_software_version,
            "software_build": v1_software_version,
            "api_version": config.get("apiversion"),
        },
        "updates": _update_info(config),
        "internet": {
            "internet": services.get("internet"),
            "software_update": services.get("swupdate"),
        },
        "devices": {"supported": False, "items": []},
    }

    # Some Hue firmware versions expose device_software_update in CLIP v2.
    # Absence/denial must never prevent the Bridge update controls from working.
    try:
        items = client.v2_get("device_software_update")
        if isinstance(items, list):
            info["devices"] = {
                "supported": True,
                "items": [
                    {
                        "id": item.get("id"),
                        "owner": item.get("owner"),
                        "state": item.get("state"),
                        "software_version": item.get("software_version"),
                    }
                    for item in items
                    if isinstance(item, dict)
                ],
            }
    except (HueApiError, OSError, ValueError):
        pass

    return info


def request_software_update_check(client: HueBridgeClient) -> dict[str, Any]:
    """Ask the Bridge to check Signify's update service, without installing."""
    status = software_update_status(client)
    if not status["updates"]["supported"]:
        raise HueApiError("The Bridge does not expose swupdate2")
    if status["updates"]["check_in_progress"]:
        raise HueApiError("A Hue software update check is already in progress")
    result = client.v1_put("/config", {"swupdate2": {"checkforupdate": True}})
    return {"requested": True, "action": "check", "bridge_response": result}


def request_software_update_install(client: HueBridgeClient) -> dict[str, Any]:
    """Install only a firmware that the Bridge reports as ready.

    Prevent blind install requests, especially on beta firmware.
    """
    status = software_update_status(client)
    if not status["updates"]["supported"]:
        raise HueApiError("The Bridge does not expose swupdate2")
    if not status["updates"]["ready_to_install"]:
        raise HueApiError(
            "No update is marked ready to install by the Bridge; run a check first"
        )
    result = client.v1_put("/config", {"swupdate2": {"install": True}})
    return {"requested": True, "action": "install", "bridge_response": result}
