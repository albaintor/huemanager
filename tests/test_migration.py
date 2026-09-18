from types import SimpleNamespace

from huemanager.backup import backup_summary, create_bridge_backup
from huemanager.migration import (
    _create_schedules,
    _device_identifiers,
    build_mapping_plan,
    rewrite_behavior_configuration,
    rewrite_rule,
)


def test_build_mapping_plan_matches_uniqueid_and_v2_service():
    snapshot = {
        "schema": 2,
        "rooms": [{"id": "room-source", "id_v1": "/groups/3"}],
        "devices": [
            {
                "id": "device-source",
                "services_expanded": [
                    {"id": "light-source", "type": "light", "id_v1": "/lights/7"}
                ],
            }
        ],
        "scenes": [],
        "v1": {
            "lights": {"7": {"name": "Patio", "uniqueid": "AA:BB-0b"}},
            "sensors": {},
            "virtual_sensors": {},
            "rules": {},
        },
    }
    dest_v1 = {
        "lights": {"42": {"name": "Patio", "uniqueid": "aa:bb-0B"}},
        "sensors": {},
    }
    dest_v2 = [
        {
            "id": "light-dest",
            "type": "light",
            "id_v1": "/lights/42",
            "owner": {"rid": "device-dest", "rtype": "device"},
        }
    ]

    plan = build_mapping_plan(snapshot, dest_v1, dest_v2)

    assert plan.complete
    assert plan.v1_map == {"/lights/7": "/lights/42"}
    assert plan.v2_map["light-source"]["id"] == "light-dest"


def test_rewrite_rule_prunes_only_external_action():
    rule = {
        "name": "Button controls two rooms",
        "conditions": [
            {"address": "/sensors/4/state/buttonevent", "operator": "eq", "value": "1002"}
        ],
        "actions": [
            {"address": "/groups/3/action", "method": "PUT", "body": {"on": True}},
            {"address": "/groups/9/action", "method": "PUT", "body": {"on": True}},
        ],
    }

    rewritten, unresolved, pruned = rewrite_rule(
        rule,
        {"/sensors/4": "/sensors/14", "/groups/3": "/groups/30"},
        prune_external=True,
    )

    assert not unresolved
    assert rewritten["conditions"][0]["address"] == "/sensors/14/state/buttonevent"
    assert len(rewritten["actions"]) == 1
    assert rewritten["actions"][0]["address"] == "/groups/30/action"
    assert pruned["actions"][0]["references"] == ["/groups/9"]


def test_rewrite_rule_keeps_cross_room_links_when_both_are_mapped():
    rule = {
        "name": "Button controls two rooms",
        "conditions": [
            {"address": "/sensors/4/state/buttonevent", "operator": "eq", "value": "1002"}
        ],
        "actions": [
            {"address": "/groups/3/action", "method": "PUT", "body": {"on": True}},
            {"address": "/groups/9/action", "method": "PUT", "body": {"on": True}},
        ],
    }

    rewritten, unresolved, pruned = rewrite_rule(
        rule,
        {
            "/sensors/4": "/sensors/14",
            "/groups/3": "/groups/30",
            "/groups/9": "/groups/90",
        },
        prune_external=True,
    )

    assert not unresolved
    assert not pruned["actions"]
    assert [a["address"] for a in rewritten["actions"]] == [
        "/groups/30/action",
        "/groups/90/action",
    ]


def test_rewrite_rule_reports_semantic_condition_pruning():
    rule = {
        "name": "Conditional button",
        "conditions": [
            {"address": "/sensors/4/state/buttonevent", "operator": "eq", "value": "1002"},
            {"address": "/sensors/99/state/presence", "operator": "eq", "value": "false"},
        ],
        "actions": [{"address": "/groups/3/action", "method": "PUT", "body": {"on": True}}],
    }

    rewritten, unresolved, pruned = rewrite_rule(
        rule,
        {"/sensors/4": "/sensors/14", "/groups/3": "/groups/30"},
        prune_external=True,
    )

    assert not unresolved
    assert len(rewritten["conditions"]) == 1
    assert pruned["conditions"][0]["references"] == ["/sensors/99"]


def test_rewrite_rule_without_pruning_blocks_external_reference():
    rule = {
        "name": "External dependency",
        "conditions": [
            {"address": "/sensors/99/state/flag", "operator": "eq", "value": "true"}
        ],
        "actions": [],
    }

    _, unresolved, _ = rewrite_rule(rule, {}, prune_external=False)

    assert "/sensors/99" in unresolved



def test_rewrite_behavior_graph_maps_uuid_keys_and_nested_resources():
    configuration = {
        "device": {"rtype": "device", "rid": "device-source"},
        "buttons": {
            "button-source": {
                "where": [{"group": {"rtype": "room", "rid": "room-source"}}],
                "on_short_release": {
                    "scene_cycle_extended": {
                        "slots": [
                            [
                                {
                                    "action": {
                                        "recall": {"rtype": "scene", "rid": "scene-source"}
                                    }
                                }
                            ]
                        ]
                    }
                },
            }
        },
    }
    mapping = {
        "device-source": {"id": "device-dest", "type": "device"},
        "button-source": {"id": "button-dest", "type": "button"},
        "room-source": {"id": "room-dest", "type": "room"},
        "scene-source": {"id": "scene-dest", "type": "scene"},
    }

    rewritten, unresolved, pruned = rewrite_behavior_configuration(
        configuration,
        mapping,
        set(mapping),
        prune_external=True,
    )

    assert not unresolved
    assert not pruned
    assert rewritten["device"]["rid"] == "device-dest"
    assert "button-dest" in rewritten["buttons"]
    assert rewritten["buttons"]["button-dest"]["where"][0]["group"]["rid"] == "room-dest"
    assert (
        rewritten["buttons"]["button-dest"]["on_short_release"]["scene_cycle_extended"]
        ["slots"][0][0]["action"]["recall"]["rid"]
        == "scene-dest"
    )


def test_rewrite_behavior_graph_prunes_only_external_scene_branch():
    configuration = {
        "where": [{"group": {"rtype": "room", "rid": "room-source"}}],
        "what": [
            {"group": {"rtype": "room", "rid": "room-source"}, "recall": {"rtype": "scene", "rid": "scene-a"}},
            {"group": {"rtype": "room", "rid": "room-external"}, "recall": {"rtype": "scene", "rid": "scene-b"}},
        ],
    }
    known = {"room-source", "room-external", "scene-a", "scene-b"}
    mapping = {
        "room-source": {"id": "room-dest", "type": "room"},
        "scene-a": {"id": "scene-a-dest", "type": "scene"},
    }

    rewritten, unresolved, pruned = rewrite_behavior_configuration(
        configuration,
        mapping,
        known,
        prune_external=True,
    )

    assert not unresolved
    assert rewritten is not None
    assert len(rewritten["what"]) == 1
    assert rewritten["what"][0]["group"]["rid"] == "room-dest"
    assert {item["rid"] for item in pruned} >= {"room-external"}


def test_rewrite_behavior_graph_strict_mode_reports_external_reference():
    configuration = {
        "where": [{"group": {"rtype": "room", "rid": "room-external"}}],
    }

    rewritten, unresolved, _ = rewrite_behavior_configuration(
        configuration,
        {},
        {"room-external"},
        prune_external=False,
    )

    assert rewritten is not None
    assert "room-external" in unresolved


def test_device_identifiers_exposes_mac_and_uniqueid_but_not_fake_serial():
    device = {
        "id": "device-source",
        "services_expanded": [
            {
                "id": "zigbee",
                "type": "zigbee_connectivity",
                "mac_address": "00:17:88:01:02:03:04:05",
            },
            {"id": "light", "type": "light", "id_v1": "/lights/7"},
        ],
    }
    v1 = {
        "lights": {
            "7": {
                "uniqueid": "00:17:88:01:02:03:04:05-0b",
            }
        }
    }

    identifiers = _device_identifiers(device, v1)

    assert identifiers["zigbee_macs"] == ["00:17:88:01:02:03:04:05"]
    assert identifiers["v1_uniqueids"] == ["00:17:88:01:02:03:04:05-0b"]
    assert identifiers["pairing_fields"] == []
    assert not identifiers["pairing_serial_available"]



def test_rewrite_behavior_graph_does_not_broaden_empty_items_scope():
    configuration = {
        "where": [
            {
                "group": {"rtype": "room", "rid": "room-source"},
                "items": [{"rtype": "light", "rid": "light-external"}],
            }
        ]
    }
    mapping = {"room-source": {"id": "room-dest", "type": "room"}}

    rewritten, unresolved, pruned = rewrite_behavior_configuration(
        configuration,
        mapping,
        {"room-source", "light-external"},
        prune_external=True,
    )

    assert not unresolved
    assert rewritten is None
    assert any(item["rid"] == "light-external" for item in pruned)



def test_full_backup_redacts_bridge_api_users():
    class FakeClient:
        def v1_all(self):
            return {
                "config": {
                    "name": "Old bridge",
                    "bridgeid": "ABC123",
                    "whitelist": {
                        "secret-api-user": {"name": "some app"}
                    },
                },
                "lights": {"1": {"name": "Lamp", "uniqueid": "aa-0b"}},
                "sensors": {},
                "rules": {
                    "3": {
                        "name": "Rule",
                        "owner": "secret-api-user",
                        "conditions": [],
                        "actions": [],
                    }
                },
                "schedules": {
                    "2": {
                        "name": "Timer",
                        "owner": "secret-api-user",
                        "command": {
                            "address": "/api/secret-api-user/lights/1/state",
                            "method": "PUT",
                            "body": {"on": False},
                        },
                    }
                },
                "resourcelinks": {},
            }

        def v2_resources(self):
            return [
                {"id": "auth-secret-id", "type": "auth_v1"},
                {"id": "bridge-resource", "type": "bridge"},
            ]

    backup = create_bridge_backup(FakeClient())

    archived_config = backup["raw"]["clip_v1"]["config"]
    assert "whitelist" not in archived_config
    assert archived_config["whitelist_redacted"]["count"] == 1
    assert backup["raw"]["clip_v1"]["rules"]["3"]["owner"] == "__REDACTED__"
    assert backup["raw"]["clip_v1"]["schedules"]["2"]["owner"] == "__REDACTED__"
    assert (
        backup["raw"]["clip_v1"]["schedules"]["2"]["command"]["address"]
        == "/api/__REDACTED__/lights/1/state"
    )
    assert (
        backup["logical_restore"]["v1"]["schedules"]["2"]["command"]["address"]
        == "/api/__REDACTED__/lights/1/state"
    )
    assert backup_summary(backup)["lights"] == 1
    assert backup["raw"]["auth_v1_redacted"]["count"] == 1
    assert all(
        resource.get("type") != "auth_v1"
        for resource in backup["raw"]["clip_v2_resources"]
    )
    assert backup["restore_scope"]["physical_pairing"] is False


def test_schedule_restore_rewrites_api_user_and_resource_ids():
    class FakeClient:
        def __init__(self):
            self.profile = SimpleNamespace(app_key="new-api-user")
            self.created = None

        def v1_all(self):
            return {"schedules": {}}

        def v1_post(self, path, body):
            assert path == "/schedules"
            self.created = body
            return [{"success": {"id": "8"}}]

    client = FakeClient()
    snapshot = {
        "v1": {
            "schedules": {
                "2": {
                    "name": "Night",
                    "localtime": "W127/T23:00:00",
                    "status": "enabled",
                    "command": {
                        "address": "/api/old-api-user/groups/3/action",
                        "method": "PUT",
                        "body": {"scene": "old-scene"},
                    },
                }
            }
        }
    }

    created, warnings, mapping = _create_schedules(
        client,
        snapshot,
        {
            "/groups/3": "/groups/30",
            "/scenes/old-scene": "/scenes/new-scene",
        },
    )

    assert created == 1
    assert not warnings
    assert mapping == {"/schedules/2": "/schedules/8"}
    assert client.created["command"]["address"] == "/api/new-api-user/groups/30/action"
    assert client.created["command"]["body"]["scene"] == "new-scene"
