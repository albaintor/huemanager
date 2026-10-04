from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any

from .client import HueBridgeClient
from .diagnostics import collect_monitor_sample


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
                except Exception as exc:
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
