from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class BridgeProfile:
    host: str
    app_key: str
    client_key: str | None = None
    verify_tls: bool = False


@dataclass(slots=True)
class HomeAssistantProfile:
    url: str
    token: str
    verify_tls: bool = False


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.environ.get("HUEMANAGER_CONFIG", "~/.config/huemanager/config.json")
        ).expanduser()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"bridges": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save_bridge(self, name: str, profile: BridgeProfile) -> None:
        data = self._read()
        data.setdefault("bridges", {})[name] = asdict(profile)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get_bridge(self, name: str) -> BridgeProfile:
        data = self._read().get("bridges", {})
        if name not in data:
            raise KeyError(f"Unknown bridge profile: {name}")
        return BridgeProfile(**data[name])

    def list_bridges(self) -> dict[str, BridgeProfile]:
        return {
            name: BridgeProfile(**value)
            for name, value in self._read().get("bridges", {}).items()
        }

    def save_home_assistant(self, profile: HomeAssistantProfile) -> None:
        data = self._read()
        data["home_assistant"] = asdict(profile)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get_home_assistant(self) -> HomeAssistantProfile:
        payload = self._read().get("home_assistant")
        if not payload:
            raise KeyError("Home Assistant is not configured")
        return HomeAssistantProfile(**payload)

    def home_assistant_status(self) -> dict:
        payload = self._read().get("home_assistant")
        if not payload:
            return {
                "configured": False,
                "url": None,
                "verify_tls": False,
                "has_token": False,
            }
        return {
            "configured": bool(payload.get("url") and payload.get("token")),
            "url": payload.get("url"),
            "verify_tls": bool(payload.get("verify_tls")),
            "has_token": bool(payload.get("token")),
        }

    def get_diagnostic_ignored_devices(self, bridge_name: str) -> set[str]:
        data = self._read()
        values = (
            data.get("diagnostics", {})
            .get("ignored_devices", {})
            .get(bridge_name, [])
        )
        return {
            str(value)
            for value in values
            if isinstance(value, str) and value
        }

    def save_diagnostic_ignored_devices(
        self,
        bridge_name: str,
        device_ids: set[str] | list[str],
    ) -> None:
        data = self._read()
        diagnostics = data.setdefault("diagnostics", {})
        ignored = diagnostics.setdefault("ignored_devices", {})
        ignored[bridge_name] = sorted(
            {
                str(value)
                for value in device_ids
                if isinstance(value, str) and value
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
