from __future__ import annotations

from huemanager.monitoring import summarize_monitor_samples


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
