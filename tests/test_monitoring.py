from __future__ import annotations

import pytest
from requests import exceptions as requests_exceptions

from huemanager.client import HueApiError
from huemanager.monitoring import (
    DiagnosticMonitor,
    ServiceConnectivityMonitor,
    _zigbee_sample_is_degraded,
    classify_service_failure,
    collect_zigbee_health,
    summarize_monitor_samples,
    summarize_outage_forensics,
)


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
        error="connection refused",
        failure={
            "classification": "CONNECTION_REFUSED",
            "layer": "tcp",
            "summary": "The Bridge host actively refused the HTTPS connection on port 443.",
            "http_status": None,
            "error": "connection refused",
        },
    )
    monitor._record_probe(
        available=False,
        checked_at="2026-10-04T18:00:20+00:00",
        monotonic_now=20.0,
        error="read timed out",
        failure={
            "classification": "READ_TIMEOUT",
            "layer": "http",
            "summary": "The Hue API connection was established but no response arrived before timeout.",
            "http_status": None,
            "error": "read timed out",
        },
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
    assert len(monitor.events) == 2
    assert monitor.events[0] == {
        "type": "down",
        "at": "2026-10-04T18:00:10+00:00",
        "classification": "CONNECTION_REFUSED",
        "layer": "tcp",
        "summary": "The Bridge host actively refused the HTTPS connection on port 443.",
        "http_status": None,
        "endpoint": "/clip/v2/resource/bridge",
        "error": "connection refused",
    }
    assert monitor.events[1] == {
        "type": "restored",
        "at": "2026-10-04T18:00:30+00:00",
        "outage_started_at": "2026-10-04T18:00:10+00:00",
        "downtime_seconds": 20.0,
        "failed_checks": 2,
        "classifications": ["CONNECTION_REFUSED", "READ_TIMEOUT"],
        "last_error": "read timed out",
        "endpoint": "/clip/v2/resource/bridge",
    }


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



@pytest.mark.parametrize(
    ("exc", "classification", "layer"),
    [
        (
            requests_exceptions.ConnectionError(
                "HTTPSConnectionPool(host='192.168.1.40', port=443): "
                "Failed to establish a new connection: [Errno 111] Connection refused"
            ),
            "CONNECTION_REFUSED",
            "tcp",
        ),
        (
            requests_exceptions.ConnectTimeout("connect timed out"),
            "CONNECT_TIMEOUT",
            "tcp",
        ),
        (
            requests_exceptions.ReadTimeout("read timed out"),
            "READ_TIMEOUT",
            "http",
        ),
        (
            requests_exceptions.SSLError("certificate verify failed"),
            "TLS_ERROR",
            "tls",
        ),
        (
            HueApiError("Hue API 500 GET /bridge: Internal Server Error"),
            "HTTP_5XX",
            "http",
        ),
        (
            HueApiError("Hue API 429 GET /bridge: Too Many Requests"),
            "HTTP_429_RATE_LIMITED",
            "http",
        ),
    ],
)
def test_classify_service_failure(
    exc: Exception,
    classification: str,
    layer: str,
) -> None:
    result = classify_service_failure(exc)

    assert result["classification"] == classification
    assert result["layer"] == layer


def test_classify_connection_refused_has_explanatory_summary() -> None:
    result = classify_service_failure(
        requests_exceptions.ConnectionError("[Errno 111] Connection refused")
    )

    assert result["classification"] == "CONNECTION_REFUSED"
    assert "actively refused" in result["summary"]


def test_outage_forensics_identifies_host_alive_https_service_down() -> None:
    result = summarize_outage_forensics(
        [
            {
                "status": "ok",
                "diagnosis": "HOST_RESPONDING_HTTPS_LISTENER_DOWN",
            },
            {
                "status": "ok",
                "diagnosis": "HOST_RESPONDING_HTTPS_LISTENER_DOWN",
            },
        ]
    )

    assert result["code"] == "HOST_ALIVE_HTTPS_SERVICE_DOWN"
    assert result["probe_count"] == 2
    assert "internal service/watchdog" in result["summary"]


def test_outage_forensics_keeps_full_reboot_or_path_loss_plausible() -> None:
    result = summarize_outage_forensics(
        [
            {
                "status": "ok",
                "diagnosis": "HOST_OR_NETWORK_PATH_UNRESPONSIVE",
            },
            {
                "status": "ok",
                "diagnosis": "HOST_OR_NETWORK_PATH_UNRESPONSIVE",
            },
        ]
    )

    assert result["code"] == "HOST_OR_PATH_DOWN"
    assert "full reboot" in result["summary"]


def test_zigbee_degradation_detects_broad_connected_loss() -> None:
    degraded, evidence = _zigbee_sample_is_degraded(
        {"connected": 60},
        {"connected": 100},
    )

    assert degraded is True
    assert evidence["connected_loss"] == 40
    assert evidence["loss_threshold"] == 25


def test_zigbee_degradation_ignores_small_variation() -> None:
    degraded, evidence = _zigbee_sample_is_degraded(
        {"connected": 96},
        {"connected": 100},
    )

    assert degraded is False
    assert evidence["connected_loss"] == 4


class _FakeZigbeeClient(_FakeServiceClient):
    def v2_get(self, resource_type: str) -> list[dict]:
        self.calls.append(resource_type)
        if resource_type == "zigbee_connectivity":
            return [
                {"id": "z1", "status": "connected", "owner": {"rid": "d1", "rtype": "device"}},
                {"id": "z2", "status": "connectivity_issue", "owner": {"rid": "d2", "rtype": "device"}},
            ]
        return super().v2_get(resource_type)


def test_collect_zigbee_health_summarizes_public_connectivity_resources() -> None:
    result = collect_zigbee_health(_FakeZigbeeClient())  # type: ignore[arg-type]

    assert result["total"] == 2
    assert result["connected"] == 1
    assert result["non_connected"] == 1
    assert result["counts"] == {
        "connected": 1,
        "connectivity_issue": 1,
    }
    assert len(result["issues_sample"]) == 1


def test_zigbee_forensics_are_attached_to_service_monitor() -> None:
    client = _FakeZigbeeClient()
    monitor = ServiceConnectivityMonitor(
        bridge_name="Bridge Pro",
        client=client,  # type: ignore[arg-type]
        interval_seconds=10,
    )

    monitor._maybe_probe_zigbee(0.0)

    assert monitor.zigbee_baseline is not None
    assert monitor.zigbee_health is not None
    assert monitor.zigbee_state == "normal"
    assert not hasattr(DiagnosticMonitor, "_maybe_probe_zigbee")
