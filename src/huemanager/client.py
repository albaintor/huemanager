from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import requests
import urllib3

from .config import BridgeProfile

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_WRITE_JOURNAL_LOCK = threading.Lock()
_SENSITIVE_KEYS = {
    "app_key",
    "client_key",
    "username",
    "password",
    "token",
    "setup_code",
    "pairing_code",
    "manual_code",
    "install_code",
}


class HueApiError(RuntimeError):
    pass


class HueBridgeClient:
    def __init__(
        self,
        profile: BridgeProfile,
        timeout: float = 10.0,
        *,
        bridge_name: str | None = None,
        write_journal_path: Path | None = None,
    ) -> None:
        self.profile = profile
        self.timeout = timeout
        self.bridge_name = bridge_name
        self.write_journal_path = write_journal_path
        self.session = requests.Session()

    @staticmethod
    def _redact_journal_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "<redacted>"
                    if str(key).casefold() in _SENSITIVE_KEYS
                    else HueBridgeClient._redact_journal_value(child)
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [HueBridgeClient._redact_journal_value(child) for child in value]
        return value

    def _record_mutation(
        self,
        *,
        api: str,
        method: str,
        endpoint: str,
        body: dict | None,
        started: float,
        status_code: int | None,
        result: str,
        error: str | None = None,
    ) -> None:
        if method.upper() == "GET" or self.write_journal_path is None:
            return
        entry = {
            "at": datetime.now(UTC).isoformat(),
            "bridge": self.bridge_name or self.profile.host,
            "host": self.profile.host,
            "api": api,
            "method": method.upper(),
            "endpoint": endpoint,
            "status_code": status_code,
            "result": result,
            "duration_ms": round((perf_counter() - started) * 1000.0, 1),
            "body": self._redact_journal_value(body) if body is not None else None,
            "error": error,
        }
        path = self.write_journal_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _WRITE_JOURNAL_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    @staticmethod
    def discover(timeout: float = 8.0) -> list[dict]:
        response = requests.get("https://discovery.meethue.com/", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return [
            {"id": item.get("id"), "host": item.get("internalipaddress")}
            for item in payload
            if item.get("internalipaddress")
        ]

    @staticmethod
    def pair(host: str, device_type: str = "huemanager#web", verify_tls: bool = False) -> dict:
        response = requests.post(
            f"https://{host}/api",
            json={"devicetype": device_type, "generateclientkey": True},
            timeout=10,
            verify=verify_tls,
        )
        response.raise_for_status()
        payload = response.json()
        HueBridgeClient._raise_v1_errors(payload)
        if not payload or "success" not in payload[0]:
            raise HueApiError(f"Unexpected pairing response: {payload!r}")
        return payload[0]["success"]

    @staticmethod
    def _raise_v1_errors(payload: Any) -> None:
        if not isinstance(payload, list):
            return
        errors = [
            entry["error"]
            for entry in payload
            if isinstance(entry, dict) and "error" in entry
        ]
        if errors:
            descriptions = "; ".join(str(error.get("description", error)) for error in errors)
            raise HueApiError(descriptions)

    def _request_v1(self, method: str, path: str = "", json_body: dict | None = None) -> Any:
        url = f"https://{self.profile.host}/api/{self.profile.app_key}{path}"
        started = perf_counter()
        response: requests.Response | None = None
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                timeout=self.timeout,
                verify=self.profile.verify_tls,
            )
            response.raise_for_status()
            payload = response.json()
            self._raise_v1_errors(payload)
        except (requests.RequestException, HueApiError, ValueError) as exc:
            self._record_mutation(
                api="clip_v1",
                method=method,
                endpoint=path or "/",
                body=json_body,
                started=started,
                status_code=response.status_code if response is not None else None,
                result="error",
                error=str(exc),
            )
            raise

        self._record_mutation(
            api="clip_v1",
            method=method,
            endpoint=path or "/",
            body=json_body,
            started=started,
            status_code=response.status_code,
            result="success",
        )
        return payload

    def _request_v2(self, method: str, path: str = "", json_body: dict | None = None) -> Any:
        url = f"https://{self.profile.host}/clip/v2/resource{path}"
        started = perf_counter()
        response: requests.Response | None = None
        try:
            response = self.session.request(
                method,
                url,
                headers={"hue-application-key": self.profile.app_key},
                json=json_body,
                timeout=self.timeout,
                verify=self.profile.verify_tls,
            )

            payload: Any = None
            if response.content:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None

            if isinstance(payload, dict):
                errors = payload.get("errors") or []
                if errors:
                    descriptions = "; ".join(
                        str(error.get("description", error))
                        for error in errors
                    )
                    raise HueApiError(
                        f"Hue API {response.status_code} {method} {path}: {descriptions}"
                    )

            if not response.ok:
                detail = response.text.strip()
                if len(detail) > 500:
                    detail = detail[:500] + "…"
                raise HueApiError(
                    f"Hue API {response.status_code} {method} {path}"
                    + (f": {detail}" if detail else "")
                )

            if not response.content:
                result: Any = []
            elif not isinstance(payload, dict):
                raise HueApiError(
                    f"Unexpected CLIP v2 response for {method} {path}"
                )
            else:
                result = payload.get("data", [])
        except (requests.RequestException, HueApiError, ValueError) as exc:
            self._record_mutation(
                api="clip_v2",
                method=method,
                endpoint=path or "/",
                body=json_body,
                started=started,
                status_code=response.status_code if response is not None else None,
                result="error",
                error=str(exc),
            )
            raise

        self._record_mutation(
            api="clip_v2",
            method=method,
            endpoint=path or "/",
            body=json_body,
            started=started,
            status_code=response.status_code,
            result="success",
        )
        return result

    def v1_all(self) -> dict:
        payload = self._request_v1("GET")
        if not isinstance(payload, dict):
            raise HueApiError("Unexpected CLIP v1 root response")
        return payload

    def v1_get(self, path: str) -> Any:
        return self._request_v1("GET", path)

    def v1_post(self, path: str, body: dict | None = None) -> Any:
        return self._request_v1("POST", path, body or {})

    def v1_put(self, path: str, body: dict) -> Any:
        return self._request_v1("PUT", path, body)

    def v1_delete(self, path: str) -> Any:
        return self._request_v1("DELETE", path)

    def v2_resources(self) -> list[dict]:
        return self._request_v2("GET")

    def v2_get(self, resource_type: str, resource_id: str | None = None) -> list[dict]:
        suffix = f"/{resource_type}"
        if resource_id:
            suffix += f"/{resource_id}"
        return self._request_v2("GET", suffix)

    def v2_post(self, resource_type: str, body: dict) -> list[dict]:
        return self._request_v2("POST", f"/{resource_type}", body)

    def v2_put(self, resource_type: str, resource_id: str, body: dict) -> list[dict]:
        return self._request_v2("PUT", f"/{resource_type}/{resource_id}", body)

    def v2_delete(self, resource_type: str, resource_id: str) -> list[dict]:
        return self._request_v2("DELETE", f"/{resource_type}/{resource_id}")
