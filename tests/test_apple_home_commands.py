import pytest
from fastapi import HTTPException

from huemanager import apple_home_commands as commands
from huemanager import web


@pytest.fixture
def command_path(tmp_path, monkeypatch):
    path = tmp_path / "commands.json"
    monkeypatch.setattr(web, "_apply_request_path", lambda: path)
    monkeypatch.setattr(web, "_load_apple_home", lambda: {"inventory": {"home": {"id": "home"}}})
    plan = {
        "selected_hue_room_ids": ["selected"],
        "actions": [
            {"accessory_id": "lamp", "to_room_id": "bedroom", "hue_room_id": "selected"},
            {"accessory_id": "other", "to_room_id": "kitchen", "hue_room_id": "excluded"},
        ],
    }
    monkeypatch.setattr(web, "apple_home_plan", lambda scope: plan)
    monkeypatch.setattr(web, "home_assistant_apple_home_plan", lambda: plan)
    return path


def submit(scope="bridge", home="home", actions=None):
    return web.request_apple_home_apply(
        web.AppleHomeApplyRequest(
            home_id=home,
            bridge_profile=scope,
            actions=actions
            if actions is not None
            else [{"accessory_id": "lamp", "to_room_id": "bedroom"}],
        )
    )["request"]


@pytest.mark.parametrize("scope", ["bridge", "__home_assistant__"])
def test_request_is_durable_and_claimed_only_once(command_path, scope):
    request = submit(scope)
    assert commands.read_request(command_path) == request
    assert request["status"] == "pending"
    assert len(request["actions"]) == 1
    with pytest.raises(HTTPException):
        submit(scope)
    with pytest.raises(ValueError):
        commands.transition(command_path, request["id"], "home", "other-bridge", "running", "")
    commands.transition(command_path, request["id"], "home", scope, "running", "")
    with pytest.raises(ValueError):
        commands.transition(command_path, request["id"], "home", scope, "running", "")
    commands.transition(command_path, request["id"], "home", scope, "completed", "1 moved")
    assert web.get_apple_home_apply_request()["request"]["status"] == "completed"
    assert submit(scope)["id"] != request["id"]


@pytest.mark.parametrize(
    "actions",
    [
        [{"accessory_id": "other", "to_room_id": "kitchen"}],
        [{"accessory_id": "lamp", "to_room_id": "wrong-room"}],
        [{"accessory_id": "lamp", "to_room_id": "bedroom"}] * 2,
    ],
)
def test_changed_or_excluded_moves_are_rejected(command_path, actions):
    with pytest.raises(HTTPException) as error:
        submit(actions=actions)
    assert error.value.status_code == 409
    assert not command_path.exists()


def test_different_home_rejected(command_path):
    with pytest.raises(HTTPException):
        submit(home="different-home")
    assert not command_path.exists()


def test_expired_request_never_claimed(command_path, monkeypatch):
    request = submit()
    monkeypatch.setattr(commands.time, "time", lambda: request["expires_at"] + 1)
    assert commands.read_request(command_path)["status"] == "expired"
    with pytest.raises(ValueError):
        commands.transition(command_path, request["id"], "home", "bridge", "running", "")
    assert submit()["id"] != request["id"]


def test_completion_requires_a_claim(command_path):
    request = submit()
    with pytest.raises(ValueError):
        commands.transition(command_path, request["id"], "home", "bridge", "completed", "")
    commands.transition(command_path, request["id"], "home", "bridge", "cancelled", "")
    assert submit()["status"] == "pending"


def test_interrupted_claim_is_not_replayed(command_path, monkeypatch):
    request = submit()
    running = commands.transition(command_path, request["id"], "home", "bridge", "running", "")
    monkeypatch.setattr(commands.time, "time", lambda: running["expires_at"] + 1)
    assert commands.read_request(command_path)["status"] == "failed"
    with pytest.raises(ValueError):
        commands.transition(command_path, request["id"], "home", "bridge", "running", "")
