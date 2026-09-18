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
