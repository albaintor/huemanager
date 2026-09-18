from __future__ import annotations

from typing import Any

import requests
import urllib3

from .config import BridgeProfile

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HueApiError(RuntimeError):
    pass


class HueBridgeClient:
    def __init__(self, profile: BridgeProfile, timeout: float = 10.0) -> None:
        self.profile = profile
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def pair(host: str, device_type: str = "huemanager#cli", verify_tls: bool = False) -> dict:
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
        errors = [entry["error"] for entry in payload if isinstance(entry, dict) and "error" in entry]
        if errors:
            descriptions = "; ".join(str(error.get("description", error)) for error in errors)
            raise HueApiError(descriptions)

    def _request_v1(self, method: str, path: str = "", json_body: dict | None = None) -> Any:
        url = f"https://{self.profile.host}/api/{self.profile.app_key}{path}"
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
        return payload

    def _request_v2(self, method: str, path: str = "", json_body: dict | None = None) -> Any:
        url = f"https://{self.profile.host}/clip/v2/resource{path}"
        response = self.session.request(
            method,
            url,
            headers={"hue-application-key": self.profile.app_key},
            json=json_body,
            timeout=self.timeout,
            verify=self.profile.verify_tls,
        )
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or []
        if errors:
            raise HueApiError("; ".join(str(e.get("description", e)) for e in errors))
        return payload.get("data", [])

    def v1_all(self) -> dict:
        payload = self._request_v1("GET")
        if not isinstance(payload, dict):
            raise HueApiError("Unexpected CLIP v1 root response")
        return payload

    def v1_post(self, path: str, body: dict | None = None) -> Any:
        return self._request_v1("POST", path, body or {})

    def v1_put(self, path: str, body: dict) -> Any:
        return self._request_v1("PUT", path, body)

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
