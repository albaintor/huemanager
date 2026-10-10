"""Durable, single-use requests to the foreground HomeKit companion."""

import json
import time
import uuid
from pathlib import Path
from threading import RLock

LOCK = RLock()
TTL = 600


def read_request(path: Path) -> dict | None:
    if not path.exists():
        return None
    request = json.loads(path.read_text())
    if request["status"] == "pending" and time.time() > request["expires_at"]:
        request.update(status="expired", message="Request expired; submit again from the web.")
        write_request(path, request)
    elif request["status"] == "running" and time.time() > request["expires_at"]:
        request.update(
            status="failed",
            message="Companion did not report completion. Some moves may have occurred; refresh the inventory before submitting again.",
        )
        write_request(path, request)
    return request


def write_request(path: Path, request: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(request, ensure_ascii=False, indent=2))
    temporary.replace(path)


def enqueue(path: Path, home_id: str, scope: str, actions: list[dict]) -> dict:
    with LOCK:
        previous = read_request(path)
        if previous and previous["status"] in {"pending", "running"}:
            raise ValueError("A HomeKit request is already pending or running.")
        request = {
            "id": str(uuid.uuid4()),
            "home_id": home_id,
            "bridge_profile": scope,
            "actions": actions,
            "status": "pending",
            "expires_at": time.time() + TTL,
            "message": "Waiting for the matching foreground iOS companion.",
        }
        write_request(path, request)
        return request


def transition(
    path: Path, request_id: str, home_id: str, scope: str, status: str, message: str
) -> dict:
    with LOCK:
        request = read_request(path)
        if not request or (request["id"], request["home_id"], request["bridge_profile"]) != (
            request_id,
            home_id,
            scope,
        ):
            raise ValueError("Request or companion context does not match.")
        allowed = {"pending": {"running", "cancelled"}, "running": {"completed", "failed"}}
        if status not in allowed.get(request["status"], set()):
            raise ValueError("Request already claimed or no longer actionable.")
        request.update(status=status, message=message)
        if status == "running":
            request["expires_at"] = time.time() + 3600
        write_request(path, request)
        return request
