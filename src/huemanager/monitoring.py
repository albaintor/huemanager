from __future__ import annotations

import copy
import logging
import re
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any

from requests import exceptions as requests_exceptions

from .client import HueApiError, HueBridgeClient
from .diagnostics import collect_monitor_sample

LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _latency_summary(samples: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [
        float(sample[key]["ms"])
        for sample in samples
        if sample.get(key, {}).get("ms") is not None
    ]
    if not values:
        return {"samples": 0, "median_ms": None, "max_ms": None}
    return {
        "samples": len(values),
        "median_ms": round(median(values), 1),
        "max_ms": round(max(values), 1),
    }


def summarize_monitor_samples(
    samples: list[dict[str, Any]],
    ignored_device_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Summarize connectivity changes while excluding expected-off devices."""
    ignored = set(ignored_device_ids or set())
    if not samples:
        return {
            "baseline": {
                "devices": 0,
                "connected": 0,
                "disconnected": 0,
                "unknown": 0,
            },
            "tracked_devices": 0,
            "stable_tracked_devices": 0,
            "ignored_devices": [],
            "excluded_initially_disconnected": [],
            "flapping_devices": [],
            "transitions": 0,
            "api_latency": {
                "clip_v1_root": _latency_summary(samples, "clip_v1_root"),
                "clip_v2_resources": _latency_summary(samples, "clip_v2_resources"),
            },
        }

    baseline = samples[0]
    baseline_devices = {
        str(device["id"]): device
        for device in baseline.get("devices", [])
        if device.get("id")
    }
    baseline_counts = Counter(
        str(device.get("health") or "unknown")
        for device in baseline_devices.values()
    )

    ignored_devices = [
        baseline_devices[device_id]
        for device_id in sorted(ignored)
        if device_id in baseline_devices
    ]
    excluded_initially_disconnected = [
        device
        for device_id, device in baseline_devices.items()
        if device_id not in ignored and device.get("health") != "connected"
    ]
    tracked_ids = {
        device_id
        for device_id, device in baseline_devices.items()
        if device_id not in ignored and device.get("health") == "connected"
    }

    state: dict[str, dict[str, Any]] = {}
    for device_id in tracked_ids:
        device = baseline_devices[device_id]
        state[device_id] = {
            "id": device_id,
            "name": device.get("name"),
            "manufacturer": device.get("manufacturer"),
            "model": device.get("model"),
            "rooms": device.get("rooms", []),
            "initial_health": "connected",
            "current_health": "connected",
            "disconnects": 0,
            "reconnects": 0,
            "transitions": [],
            "_down_since": None,
            "_downtime": [],
        }

    for sample in samples[1:]:
        elapsed = float(sample.get("elapsed_seconds") or 0.0)
        devices = {
            str(device["id"]): device
            for device in sample.get("devices", [])
            if device.get("id")
        }
        for device_id in tracked_ids:
            item = state[device_id]
            health = str(devices.get(device_id, {}).get("health") or "unknown")
            previous = item["current_health"]
            if health == previous:
                continue

            item["transitions"].append(
                {
                    "elapsed_seconds": round(elapsed, 1),
                    "from": previous,
                    "to": health,
                }
            )
            if previous == "connected" and health != "connected":
                item["disconnects"] += 1
                item["_down_since"] = elapsed
            elif previous != "connected" and health == "connected":
                item["reconnects"] += 1
                if item["_down_since"] is not None:
                    item["_downtime"].append(max(0.0, elapsed - item["_down_since"]))
                    item["_down_since"] = None
            item["current_health"] = health

    final_elapsed = float(samples[-1].get("elapsed_seconds") or 0.0)
    flapping_devices: list[dict[str, Any]] = []
    transition_count = 0
    for item in state.values():
        if item["_down_since"] is not None:
            item["_downtime"].append(max(0.0, final_elapsed - item["_down_since"]))
        transition_count += len(item["transitions"])
        if item["transitions"]:
            downtimes = [float(value) for value in item["_downtime"]]
            flapping_devices.append(
                {
                    key: value
                    for key, value in item.items()
                    if not key.startswith("_")
                }
                | {
                    "total_disconnected_seconds": round(sum(downtimes), 1),
                    "longest_disconnected_seconds": (
                        round(max(downtimes), 1) if downtimes else 0.0
                    ),
                }
            )

    flapping_devices.sort(
        key=lambda item: (
            -int(item["disconnects"]),
            -len(item["transitions"]),
            str(item.get("name") or "").lower(),
        )
    )
    return {
        "baseline": {
            "devices": len(baseline_devices),
            "connected": baseline_counts.get("connected", 0),
            "disconnected": baseline_counts.get("disconnected", 0),
            "unknown": baseline_counts.get("unknown", 0),
        },
        "tracked_devices": len(tracked_ids),
        "stable_tracked_devices": len(tracked_ids) - len(flapping_devices),
        "ignored_devices": ignored_devices,
        "excluded_initially_disconnected": excluded_initially_disconnected,
        "flapping_devices": flapping_devices,
        "transitions": transition_count,
        "api_latency": {
            "clip_v1_root": _latency_summary(samples, "clip_v1_root"),
            "clip_v2_resources": _latency_summary(samples, "clip_v2_resources"),
        },
    }


@dataclass
class DiagnosticMonitor:
    bridge_name: str
    client: HueBridgeClient
    duration_seconds: int
    interval_seconds: int
    ignored_device_ids: set[str] = field(default_factory=set)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "starting"
    started_at: str | None = None
    finished_at: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"hue-monitor-{self.bridge_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        started_monotonic = time.monotonic()
        with self._lock:
            self.status = "running"
            self.started_at = _utc_now()

        try:
            while True:
                elapsed = time.monotonic() - started_monotonic
                if elapsed >= self.duration_seconds:
                    with self._lock:
                        self.status = "completed"
                        self.stop_reason = "duration_elapsed"
                    break
                if self._stop.is_set():
                    with self._lock:
                        self.status = "stopped"
                        self.stop_reason = "user"
                    break

                try:
                    sample = collect_monitor_sample(self.client)
                except (HueApiError, OSError, ValueError, KeyError, IndexError) as exc:
                    with self._lock:
                        self.error = str(exc)
                    if not self.samples:
                        with self._lock:
                            self.status = "failed"
                            self.stop_reason = "initial_sample_failed"
                        break
                else:
                    sample["captured_at"] = _utc_now()
                    sample["elapsed_seconds"] = round(
                        time.monotonic() - started_monotonic,
                        1,
                    )
                    with self._lock:
                        self.samples.append(sample)
                        self.error = None

                remaining = self.duration_seconds - (
                    time.monotonic() - started_monotonic
                )
                if remaining <= 0:
                    with self._lock:
                        self.status = "completed"
                        self.stop_reason = "duration_elapsed"
                    break
                if self._stop.wait(timeout=min(self.interval_seconds, remaining)):
                    with self._lock:
                        self.status = "stopped"
                        self.stop_reason = "user"
                    break
        finally:
            with self._lock:
                self.finished_at = _utc_now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            status = self.status
            started_at = self.started_at
            finished_at = self.finished_at
            stop_reason = self.stop_reason
            error = self.error
            samples = copy.deepcopy(self.samples)

        elapsed = float(samples[-1].get("elapsed_seconds") or 0.0) if samples else 0.0
        if status == "running" and started_at:
            elapsed = min(float(self.duration_seconds), elapsed + 0.0)
        return {
            "id": self.id,
            "bridge": self.bridge_name,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "stop_reason": stop_reason,
            "duration_seconds": self.duration_seconds,
            "interval_seconds": self.interval_seconds,
            "samples_collected": len(samples),
            "last_sample_elapsed_seconds": round(elapsed, 1),
            "error": error,
            "summary": summarize_monitor_samples(samples, self.ignored_device_ids),
            "samples": [
                {
                    "captured_at": sample.get("captured_at"),
                    "elapsed_seconds": sample.get("elapsed_seconds"),
                    "connected": sample.get("connected"),
                    "disconnected": sample.get("disconnected"),
                    "unknown": sample.get("unknown"),
                    "unreachable_count": sample.get("unreachable_count"),
                    "clip_v1_root_ms": sample.get("clip_v1_root", {}).get("ms"),
                    "clip_v2_resources_ms": sample.get("clip_v2_resources", {}).get("ms"),
                }
                for sample in samples
            ],
        }



def classify_service_failure(exc: Exception) -> dict[str, Any]:
    """Classify a failed Hue API probe by the layer that failed."""
    text = str(exc)
    lowered = text.casefold()

    def result(
        classification: str,
        layer: str,
        summary: str,
        *,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        return {
            "classification": classification,
            "layer": layer,
            "summary": summary,
            "http_status": http_status,
            "error": text,
        }

    if isinstance(exc, requests_exceptions.ConnectTimeout):
        return result(
            "CONNECT_TIMEOUT",
            "tcp",
            "Timed out while establishing the TCP connection to the Hue API service.",
        )
    if isinstance(exc, requests_exceptions.ReadTimeout):
        return result(
            "READ_TIMEOUT",
            "http",
            "The Hue API connection was established but no response arrived before timeout.",
        )
    if isinstance(exc, requests_exceptions.SSLError):
        return result(
            "TLS_ERROR",
            "tls",
            "TLS negotiation with the Hue API service failed.",
        )

    if "connection refused" in lowered or "errno 111" in lowered:
        return result(
            "CONNECTION_REFUSED",
            "tcp",
            "The Bridge host actively refused the HTTPS connection on port 443.",
        )
    if "connection reset by peer" in lowered or "connection reset" in lowered:
        return result(
            "CONNECTION_RESET",
            "tcp",
            "The TCP connection to the Hue API service was reset.",
        )
    if (
        "name or service not known" in lowered
        or "temporary failure in name resolution" in lowered
        or "nodename nor servname provided" in lowered
    ):
        return result(
            "DNS_ERROR",
            "dns",
            "The Hue Bridge hostname could not be resolved.",
        )
    if "network is unreachable" in lowered or "no route to host" in lowered:
        return result(
            "NETWORK_UNREACHABLE",
            "network",
            "No network route to the Hue Bridge was available.",
        )
    if isinstance(exc, requests_exceptions.ConnectionError):
        return result(
            "CONNECTION_ERROR",
            "tcp",
            "The HTTPS connection to the Hue API service failed.",
        )

    if isinstance(exc, HueApiError):
        match = re.search(r"Hue API\s+(\d{3})\b", text)
        status = int(match.group(1)) if match else None
        if status == 429:
            return result(
                "HTTP_429_RATE_LIMITED",
                "http",
                "The Hue API service is reachable but is rate limiting requests.",
                http_status=status,
            )
        if status is not None and 500 <= status <= 599:
            return result(
                "HTTP_5XX",
                "http",
                "The Hue HTTPS service is reachable but the Hue API returned a server error.",
                http_status=status,
            )
        if status is not None and 400 <= status <= 499:
            return result(
                "HTTP_4XX",
                "http",
                "The Hue HTTPS service is reachable but the Hue API rejected the request.",
                http_status=status,
            )
        if "no bridge resource" in lowered:
            return result(
                "API_EMPTY_RESPONSE",
                "api",
                "The Hue API responded but returned no bridge resource.",
            )
        if "unexpected clip" in lowered:
            return result(
                "API_INVALID_RESPONSE",
                "api",
                "The Hue API responded with an unexpected payload.",
            )
        return result(
            "API_ERROR",
            "api",
            "The Hue API service returned an application-level error.",
        )

    if isinstance(exc, TimeoutError):
        return result(
            "TIMEOUT",
            "network",
            "The Hue API probe timed out.",
        )
    if isinstance(exc, OSError):
        return result(
            "OS_NETWORK_ERROR",
            "network",
            "The operating system reported a network error while checking the Hue API.",
        )

    return result(
        "UNKNOWN_ERROR",
        "unknown",
        "An unexpected error occurred while checking the Hue API service.",
    )


@dataclass
class ServiceConnectivityMonitor:
    """Continuously check the authenticated Hue API service with a lightweight call.

    Only availability transitions are retained in the event log. Successful steady-state
    checks are counted but not stored, so long-running monitoring remains lightweight.
    """

    bridge_name: str
    client: HueBridgeClient
    interval_seconds: int = 10
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "starting"
    started_at: str | None = None
    finished_at: str | None = None
    stop_reason: str | None = None
    current_state: str = "unknown"
    last_check_at: str | None = None
    last_error: str | None = None
    last_failure_classification: str | None = None
    checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    _down_since_monotonic: float | None = field(default=None, repr=False)
    _outage_started_at: str | None = field(default=None, repr=False)
    _outage_failed_checks: int = field(default=0, repr=False)
    _outage_classifications: list[str] = field(default_factory=list, repr=False)
    _outage_last_error: str | None = field(default=None, repr=False)
    _started_monotonic: float | None = field(default=None, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    on_restored: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"hue-api-monitor-{self.bridge_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _endpoint(self) -> str:
        profile = getattr(self.client, "profile", None)
        host = getattr(profile, "host", None)
        return (
            f"https://{host}/clip/v2/resource/bridge"
            if host
            else "/clip/v2/resource/bridge"
        )

    def _probe(self) -> None:
        resources = self.client.v2_get("bridge")
        if not resources:
            raise HueApiError("Hue v2 API returned no bridge resource")

    def _record_probe(
        self,
        *,
        available: bool,
        checked_at: str,
        monotonic_now: float,
        error: str | None = None,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            previous = self.current_state
            self.checks += 1
            self.last_check_at = checked_at

            if available:
                self.successful_checks += 1
                if previous == "down":
                    down_since = self._down_since_monotonic
                    downtime = (
                        max(0.0, monotonic_now - down_since)
                        if down_since is not None
                        else None
                    )
                    event = {
                        "type": "restored",
                        "at": checked_at,
                        "outage_started_at": self._outage_started_at,
                        "downtime_seconds": (
                            round(downtime, 1) if downtime is not None else None
                        ),
                        "failed_checks": self._outage_failed_checks,
                        "classifications": list(self._outage_classifications),
                        "last_error": self._outage_last_error,
                        "endpoint": self._endpoint(),
                    }
                    self.events.append(event)
                    LOGGER.info(
                        "Hue API service RESTORED bridge=%s downtime_seconds=%s "
                        "failed_checks=%s classifications=%s endpoint=%s",
                        self.bridge_name,
                        event["downtime_seconds"],
                        event["failed_checks"],
                        ",".join(event["classifications"]) or "UNKNOWN",
                        event["endpoint"],
                    )
                self.current_state = "up"
                self.last_error = None
                self.last_failure_classification = None
                self._down_since_monotonic = None
                self._outage_started_at = None
                self._outage_failed_checks = 0
                self._outage_classifications = []
                self._outage_last_error = None
                return event if previous == "down" else None

            failure = failure or {
                "classification": "UNKNOWN_ERROR",
                "layer": "unknown",
                "summary": "The Hue API service probe failed.",
                "http_status": None,
                "error": error or "Hue API service unavailable",
            }
            classification = str(failure.get("classification") or "UNKNOWN_ERROR")
            self.failed_checks += 1
            self.last_error = error or str(failure.get("error") or "Hue API service unavailable")
            self.last_failure_classification = classification

            if previous != "down":
                self._down_since_monotonic = monotonic_now
                self._outage_started_at = checked_at
                self._outage_failed_checks = 1
                self._outage_classifications = [classification]
                self._outage_last_error = self.last_error
                event = {
                    "type": "down",
                    "at": checked_at,
                    "classification": classification,
                    "layer": failure.get("layer"),
                    "summary": failure.get("summary"),
                    "http_status": failure.get("http_status"),
                    "endpoint": self._endpoint(),
                    "error": self.last_error,
                }
                self.events.append(event)
                LOGGER.warning(
                    "Hue API service DOWN bridge=%s classification=%s layer=%s "
                    "endpoint=%s error=%s",
                    self.bridge_name,
                    classification,
                    failure.get("layer") or "unknown",
                    event["endpoint"],
                    self.last_error,
                )
            else:
                self._outage_failed_checks += 1
                self._outage_last_error = self.last_error
                if classification not in self._outage_classifications:
                    self._outage_classifications.append(classification)
            self.current_state = "down"
            return None

    def _run(self) -> None:
        self._started_monotonic = time.monotonic()
        with self._lock:
            self.status = "running"
            self.started_at = _utc_now()

        try:
            while not self._stop.is_set():
                checked_at = _utc_now()
                monotonic_now = time.monotonic()
                try:
                    self._probe()
                except (
                    HueApiError,
                    OSError,
                    ValueError,
                    KeyError,
                    IndexError,
                ) as exc:
                    failure = classify_service_failure(exc)
                    self._record_probe(
                        available=False,
                        checked_at=checked_at,
                        monotonic_now=monotonic_now,
                        error=str(exc),
                        failure=failure,
                    )
                else:
                    restored_event = self._record_probe(
                        available=True,
                        checked_at=checked_at,
                        monotonic_now=monotonic_now,
                    )
                    if restored_event is not None and self.on_restored is not None:
                        try:
                            self.on_restored(copy.deepcopy(restored_event))
                        except (OSError, ValueError, KeyError, RuntimeError):
                            LOGGER.exception(
                                "Hue API post-recovery callback failed bridge=%s",
                                self.bridge_name,
                            )

                if self._stop.wait(timeout=self.interval_seconds):
                    break
        finally:
            with self._lock:
                self.status = "stopped"
                self.stop_reason = "user" if self._stop.is_set() else "ended"
                self.finished_at = _utc_now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            started_at = self.started_at
            current_state = self.current_state
            status = self.status
            events = copy.deepcopy(self.events)
            last_check_at = self.last_check_at
            last_error = self.last_error
            last_failure_classification = self.last_failure_classification
            checks = self.checks
            successful_checks = self.successful_checks
            failed_checks = self.failed_checks
            finished_at = self.finished_at
            stop_reason = self.stop_reason

        elapsed_seconds = 0.0
        if self._started_monotonic is not None:
            elapsed_seconds = max(0.0, time.monotonic() - self._started_monotonic)

        return {
            "id": self.id,
            "bridge": self.bridge_name,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "stop_reason": stop_reason,
            "interval_seconds": self.interval_seconds,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "current_state": current_state,
            "last_check_at": last_check_at,
            "last_error": last_error,
            "last_failure_classification": last_failure_classification,
            "checks": checks,
            "successful_checks": successful_checks,
            "failed_checks": failed_checks,
            "events": events,
        }


class ServiceConnectivityMonitorManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ServiceConnectivityMonitor] = {}
        self._lock = threading.Lock()

    def start(
        self,
        bridge_name: str,
        client: HueBridgeClient,
        *,
        interval_seconds: int = 10,
        on_restored: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._jobs.get(bridge_name)
            if current and current.snapshot()["status"] in {"starting", "running"}:
                raise ValueError(
                    "An API connectivity monitor is already running for this Bridge"
                )
            monitor = ServiceConnectivityMonitor(
                bridge_name=bridge_name,
                client=client,
                interval_seconds=interval_seconds,
                on_restored=on_restored,
            )
            self._jobs[bridge_name] = monitor
            monitor.start()
        return monitor.snapshot()

    def get(self, bridge_name: str) -> dict[str, Any] | None:
        with self._lock:
            monitor = self._jobs.get(bridge_name)
        return monitor.snapshot() if monitor else None

    def stop(self, bridge_name: str) -> dict[str, Any]:
        with self._lock:
            monitor = self._jobs.get(bridge_name)
        if monitor is None:
            raise KeyError(f"No API connectivity monitor found for Bridge: {bridge_name}")
        monitor.stop()
        thread = monitor._thread
        if thread is not None:
            thread.join(timeout=2.0)
        return monitor.snapshot()


class DiagnosticMonitorManager:
    def __init__(self) -> None:
        self._jobs: dict[str, DiagnosticMonitor] = {}
        self._lock = threading.Lock()

    def start(
        self,
        bridge_name: str,
        client: HueBridgeClient,
        *,
        duration_seconds: int,
        interval_seconds: int,
        ignored_device_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._jobs.get(bridge_name)
            if current and current.snapshot()["status"] in {"starting", "running"}:
                raise ValueError("A diagnostic monitor is already running for this Bridge")
            monitor = DiagnosticMonitor(
                bridge_name=bridge_name,
                client=client,
                duration_seconds=duration_seconds,
                interval_seconds=interval_seconds,
                ignored_device_ids=set(ignored_device_ids or set()),
            )
            self._jobs[bridge_name] = monitor
            monitor.start()
        return monitor.snapshot()

    def get(self, bridge_name: str) -> dict[str, Any] | None:
        with self._lock:
            monitor = self._jobs.get(bridge_name)
        return monitor.snapshot() if monitor else None

    def stop(self, bridge_name: str) -> dict[str, Any]:
        with self._lock:
            monitor = self._jobs.get(bridge_name)
        if monitor is None:
            raise KeyError(f"No diagnostic monitor found for Bridge: {bridge_name}")
        monitor.stop()
        thread = monitor._thread
        if thread is not None:
            thread.join(timeout=2.0)
        return monitor.snapshot()
