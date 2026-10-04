from __future__ import annotations

import pytest

from huemanager.client import HueApiError
from huemanager.monitoring import ServiceConnectivityMonitor, summarize_monitor_samples


def _sample(
    elapsed: float,
    states: dict[str, str],
    *,
    v1_ms: float = 100.0,
    v2_ms: float = 120.0,
) -> dict:
    return {
        "elapsed_seconds": elapsed,
        "devices": [
            {
                "id": device_id,
                "name": device_id,
                "manufacturer": "Signify",
                "model": "test",
                "rooms": ["Test"],
                "health": health,
            }
            for device_id, health in states.items()
        ],
        "clip_v1_root": {"ms": v1_ms},
        "clip_v2_resources": {"ms": v2_ms},
    }


def test_monitor_excludes_initially_off_and_manually_ignored_devices() -> None:
    samples = [
        _sample(0, {"stable": "connected", "flap": "connected", "off": "disconnected", "ignored": "connected"}),
        _sample(10, {"stable": "connected", "flap": "disconnected", "off": "disconnected", "ignored": "disconnected"}),
        _sample(20, {"stable": "connected", "flap": "connected", "off": "connected", "ignored": "connected"}),
    ]

    result = summarize_monitor_samples(samples, {"ignored"})

    assert result["tracked_devices"] == 2
    assert result["stable_tracked_devices"] == 1
    assert [item["id"] for item in result["ignored_devices"]] == ["ignored"]
    assert [item["id"] for item in result["excluded_initially_disconnected"]] == ["off"]
    assert result["transitions"] == 2

    flapping = result["flapping_devices"]
    assert len(flapping) == 1
    assert flapping[0]["id"] == "flap"
    assert flapping[0]["disconnects"] == 1
    assert flapping[0]["reconnects"] == 1
    assert flapping[0]["total_disconnected_seconds"] == 10.0
    assert flapping[0]["longest_disconnected_seconds"] == 10.0


def test_monitor_reports_api_latency_across_samples() -> None:
    samples = [
        _sample(0, {"lamp": "connected"}, v1_ms=100, v2_ms=200),
        _sample(10, {"lamp": "connected"}, v1_ms=300, v2_ms=400),
        _sample(20, {"lamp": "connected"}, v1_ms=200, v2_ms=300),
    ]

    result = summarize_monitor_samples(samples)

    assert result["api_latency"]["clip_v1_root"]["median_ms"] == 200.0
    assert result["api_latency"]["clip_v1_root"]["max_ms"] == 300.0
    assert result["api_latency"]["clip_v2_resources"]["median_ms"] == 300.0
    assert result["api_latency"]["clip_v2_resources"]["max_ms"] == 400.0
    assert result["flapping_devices"] == []



class _FakeServiceClient:
    def __init__(self, resources: list[dict] | None = None) -> None:
        self.resources = resources if resources is not None else [{"id": "bridge"}]
        self.calls: list[str] = []

    def v2_get(self, resource_type: str) -> list[dict]:
        self.calls.append(resource_type)
        return list(self.resources)


def test_service_monitor_logs_only_outage_and_restoration_transitions() -> None:
    monitor = ServiceConnectivityMonitor(
        bridge_name="Bridge Pro",
        client=_FakeServiceClient(),  # type: ignore[arg-type]
        interval_seconds=10,
    )

    monitor._record_probe(
        available=True,
        checked_at="2026-10-04T18:00:00+00:00",
        monotonic_now=0.0,
    )
    monitor._record_probe(
        available=False,
        checked_at="2026-10-04T18:00:10+00:00",
        monotonic_now=10.0,
        error="timeout",
    )
    monitor._record_probe(
        available=False,
        checked_at="2026-10-04T18:00:20+00:00",
        monotonic_now=20.0,
        error="still unavailable",
    )
    monitor._record_probe(
        available=True,
        checked_at="2026-10-04T18:00:30+00:00",
        monotonic_now=30.0,
    )

    assert monitor.checks == 4
    assert monitor.successful_checks == 2
    assert monitor.failed_checks == 2
    assert monitor.current_state == "up"
    assert monitor.events == [
        {
            "type": "down",
            "at": "2026-10-04T18:00:10+00:00",
            "error": "timeout",
        },
        {
            "type": "restored",
            "at": "2026-10-04T18:00:30+00:00",
            "downtime_seconds": 20.0,
        },
    ]


def test_service_monitor_probe_uses_lightweight_authenticated_bridge_resource() -> None:
    client = _FakeServiceClient()
    monitor = ServiceConnectivityMonitor(
        bridge_name="Bridge Pro",
        client=client,  # type: ignore[arg-type]
        interval_seconds=10,
    )

    monitor._probe()

    assert client.calls == ["bridge"]


def test_service_monitor_probe_rejects_empty_bridge_resource() -> None:
    monitor = ServiceConnectivityMonitor(
        bridge_name="Bridge Pro",
        client=_FakeServiceClient([]),  # type: ignore[arg-type]
        interval_seconds=10,
    )

    with pytest.raises(HueApiError, match="no bridge resource"):
        monitor._probe()
