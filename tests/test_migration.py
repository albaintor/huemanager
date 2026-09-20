from types import SimpleNamespace

import pytest

from huemanager.apple_home import build_apple_home_sync_plan
from huemanager.backup import backup_summary, create_bridge_backup
from huemanager.migration import (
    MigrationError,
    _create_entertainment_configurations,
    _create_schedules,
    _device_identifiers,
    _scene_body_with_pruning,
    audit_bridge,
    build_mapping_plan,
    delete_audit_issue,
    delete_audit_issues,
    delete_empty_room,
    rewrite_behavior_configuration,
    rewrite_rule,
    room_deletion_impact,
)
from huemanager.session import (
    load_migration_session,
    new_migration_session,
    record_plan,
    release_source_resources,
    save_migration_session,
    session_summary,
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
            {
                "group": {"rtype": "room", "rid": "room-source"},
                "recall": {"rtype": "scene", "rid": "scene-a"},
            },
            {
                "group": {"rtype": "room", "rid": "room-external"},
                "recall": {"rtype": "scene", "rid": "scene-b"},
            },
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


def test_entertainment_configuration_restore_remaps_services():
    class FakeClient:
        def __init__(self):
            self.created = None

        def v2_get(self, resource_type, resource_id=None):
            if resource_type != "entertainment_configuration":
                return []
            if resource_id:
                return [
                    {
                        "id": resource_id,
                        "type": "entertainment_configuration",
                        "metadata": {"name": "iLightShow"},
                    }
                ]
            return []

        def v2_post(self, resource_type, body):
            assert resource_type == "entertainment_configuration"
            self.created = body
            return [{"rid": "ent-dest", "rtype": "entertainment_configuration"}]

    client = FakeClient()
    snapshot = {
        "entertainment_configurations": [
            {
                "id": "ent-source",
                "type": "entertainment_configuration",
                "metadata": {"name": "iLightShow"},
                "configuration_type": "music",
                "locations": {
                    "service_locations": [
                        {
                            "service": {
                                "rid": "service-source",
                                "rtype": "entertainment",
                            },
                            "positions": [{"x": 0.0, "y": 0.0, "z": 0.0}],
                        }
                    ]
                },
            }
        ]
    }
    plan = SimpleNamespace(
        v2_map={
            "service-source": {
                "id": "service-dest",
                "type": "entertainment",
            }
        }
    )

    created, warnings = _create_entertainment_configurations(
        client,
        snapshot,
        plan,
    )

    assert created == 1
    assert not warnings
    assert (
        client.created["locations"]["service_locations"][0]["service"]["rid"]
        == "service-dest"
    )
    assert plan.v2_map["ent-source"]["id"] == "ent-dest"



def test_empty_room_deletion_reports_dependencies_and_requires_confirmation():
    class FakeClient:
        def __init__(self):
            self.deleted = None

        def v2_resources(self):
            return [
                {
                    "id": "room-empty",
                    "type": "room",
                    "id_v1": "/groups/7",
                    "metadata": {"name": "Ancienne pièce"},
                    "children": [],
                },
                {
                    "id": "scene-old",
                    "type": "scene",
                    "metadata": {"name": "Old scene"},
                    "group": {"rid": "room-empty", "rtype": "room"},
                },
                {
                    "id": "automation-old",
                    "type": "behavior_instance",
                    "metadata": {"name": "Old automation"},
                    "configuration": {
                        "where": [{"group": {"rid": "room-empty", "rtype": "room"}}]
                    },
                },
            ]

        def v1_all(self):
            return {
                "rules": {
                    "4": {
                        "name": "Old rule",
                        "conditions": [],
                        "actions": [
                            {
                                "address": "/groups/7/action",
                                "method": "PUT",
                                "body": {"on": False},
                            }
                        ],
                    }
                },
                "schedules": {},
                "resourcelinks": {},
            }

        def v2_delete(self, resource_type, resource_id):
            self.deleted = (resource_type, resource_id)
            return []

    client = FakeClient()
    impact = room_deletion_impact(client, "room-empty")

    assert impact["empty"]
    assert impact["has_dependencies"]
    assert impact["dependency_count"] == 3
    assert len(impact["dependencies"]["scenes"]) == 1
    assert len(impact["dependencies"]["rules"]) == 1
    assert len(impact["dependencies"]["automations_v2"]) == 1

    with pytest.raises(MigrationError, match="still referenced"):
        delete_empty_room(client, "room-empty")

    result = delete_empty_room(
        client,
        "room-empty",
        confirm_dependencies=True,
    )
    assert result["deleted"]
    assert client.deleted == ("room", "room-empty")


def test_room_deletion_refuses_room_with_devices():
    class FakeClient:
        def v2_resources(self):
            return [
                {
                    "id": "room-live",
                    "type": "room",
                    "metadata": {"name": "Salon"},
                    "children": [{"rid": "device-1", "rtype": "device"}],
                },
                {
                    "id": "device-1",
                    "type": "device",
                    "services": [],
                },
            ]

        def v1_all(self):
            return {"rules": {}, "schedules": {}, "resourcelinks": {}}

        def v2_delete(self, resource_type, resource_id):
            raise AssertionError("must not delete a non-empty room")

    impact = room_deletion_impact(FakeClient(), "room-live")
    assert not impact["empty"]
    assert impact["devices"] == 1



def test_bridge_audit_finds_safe_and_broken_cleanup_candidates():
    class FakeClient:
        def __init__(self):
            self.deleted = []

        def v2_resources(self):
            return [
                {
                    "id": "room-empty",
                    "type": "room",
                    "id_v1": "/groups/7",
                    "metadata": {"name": "Ancienne pièce"},
                    "children": [],
                },
                {
                    "id": "scene-empty",
                    "type": "scene",
                    "id_v1": "/scenes/9",
                    "metadata": {"name": "Scène vide"},
                    "group": {"rid": "room-empty", "rtype": "room"},
                    "actions": [],
                },
                {
                    "id": "automation-broken",
                    "type": "behavior_instance",
                    "metadata": {"name": "Broken automation"},
                    "script_id": "missing-script",
                    "configuration": {
                        "where": [
                            {"group": {"rid": "missing-room", "rtype": "room"}}
                        ]
                    },
                },
            ]

        def v1_all(self):
            return {
                "config": {"name": "Test bridge", "bridgeid": "ABC"},
                "lights": {},
                "sensors": {},
                "groups": {"7": {"name": "Ancienne pièce"}},
                "scenes": {"9": {"name": "Scène vide"}},
                "rules": {
                    "1": {
                        "name": "No-op",
                        "status": "enabled",
                        "conditions": [],
                        "actions": [],
                    },
                    "2": {
                        "name": "Broken",
                        "status": "enabled",
                        "conditions": [],
                        "actions": [
                            {
                                "address": "/lights/99/state",
                                "method": "PUT",
                                "body": {"on": True},
                            }
                        ],
                    },
                },
                "schedules": {},
                "resourcelinks": {},
            }

        def v1_delete(self, path):
            self.deleted.append(("v1", path))
            return [{"success": path}]

        def v2_delete(self, resource_type, resource_id):
            self.deleted.append(("v2", resource_type, resource_id))
            return []

    client = FakeClient()
    audit = audit_bridge(client)
    kinds = {issue["kind"] for issue in audit["issues"]}

    assert "empty_room" in kinds
    assert "rule_no_actions" in kinds
    assert "rule_broken_refs" in kinds
    assert "automation_broken_refs" in kinds
    assert audit["summary"]["safe_cleanup"] >= 1

    safe_rule = next(
        issue for issue in audit["issues"] if issue["kind"] == "rule_no_actions"
    )
    result = delete_audit_issue(client, safe_rule["id"])
    assert result["deleted"]
    assert ("v1", "/rules/1") in client.deleted

    broken_rule = next(
        issue for issue in audit["issues"] if issue["kind"] == "rule_broken_refs"
    )
    assert broken_rule["risk_reason"]

    batch_client = FakeClient()
    batch = delete_audit_issues(
        batch_client,
        [safe_rule["id"], broken_rule["id"]],
    )
    assert len(batch["deleted"]) == 1
    assert batch["deleted"][0]["id"] == safe_rule["id"]
    assert len(batch["skipped"]) == 1
    assert batch["skipped"][0]["id"] == broken_rule["id"]
    assert batch["skipped"][0]["risk_reason"]
    assert ("v1", "/rules/1") in batch_client.deleted

    forced_client = FakeClient()
    forced = delete_audit_issues(
        forced_client,
        [broken_rule["id"]],
        force_risky=True,
    )
    assert len(forced["deleted"]) == 1
    assert ("v1", "/rules/2") in forced_client.deleted



def test_scene_force_restore_prunes_only_unmapped_actions():
    scene = {
        "id": "scene-source",
        "metadata": {"name": "Mixed scene"},
        "actions": [
            {
                "target": {"rid": "light-present", "rtype": "light"},
                "action": {"on": {"on": True}},
            },
            {
                "target": {"rid": "light-missing", "rtype": "light"},
                "action": {"on": {"on": False}},
            },
        ],
    }
    destination_group = {"id": "room-dest", "type": "room"}
    plan = SimpleNamespace(
        v2_map={
            "light-present": {
                "id": "light-dest",
                "type": "light",
            }
        }
    )

    body, pruned = _scene_body_with_pruning(
        scene,
        destination_group,
        plan,
        prune_unmapped=True,
    )

    assert body is not None
    assert len(body["actions"]) == 1
    assert body["actions"][0]["target"]["rid"] == "light-dest"
    assert len(pruned) == 1
    assert pruned[0]["target"]["rid"] == "light-missing"


def test_scene_force_restore_skips_scene_when_all_actions_are_missing():
    scene = {
        "id": "scene-source",
        "metadata": {"name": "Unavailable scene"},
        "actions": [
            {
                "target": {"rid": "light-missing", "rtype": "light"},
                "action": {"on": {"on": True}},
            }
        ],
    }

    body, pruned = _scene_body_with_pruning(
        scene,
        {"id": "room-dest", "type": "room"},
        SimpleNamespace(v2_map={}),
        prune_unmapped=True,
    )

    assert body is None
    assert len(pruned) == 1


def test_release_source_resources_deletes_each_v2_device_once_and_is_idempotent():
    class FakeClient:
        def __init__(self):
            self.deleted = []

        def v2_resources(self):
            return [
                {"id": "device-present", "type": "device"},
                {"id": "unrelated", "type": "device"},
            ]

        def v2_delete(self, resource_type, resource_id):
            self.deleted.append((resource_type, resource_id))
            return []

    snapshot = {
        "devices": [
            {
                "id": "device-present",
                "metadata": {"name": "Motion"},
                "services_expanded": [
                    {"id_v1": "/sensors/1"},
                    {"id_v1": "/sensors/2"},
                    {"id_v1": "/sensors/3"},
                ],
            },
            {
                "id": "device-gone",
                "metadata": {"name": "Old lamp"},
                "services_expanded": [{"id_v1": "/lights/7"}],
            },
        ]
    }
    client = FakeClient()

    report = release_source_resources(snapshot, client)

    assert client.deleted == [("device", "device-present")]
    assert report["deleted"] == 1
    assert report["already_absent"] == 1
    assert report["failed"] == 0
    assert report["completed"]


def test_migration_session_survives_restart_and_keeps_partial_plan(tmp_path):
    path = tmp_path / "session.json"
    session = new_migration_session("old")
    session = record_plan(
        session,
        "pro",
        {
            "ready": False,
            "mapped": 3,
            "lights": 2,
            "sensors": 1,
            "devices": 3,
            "missing": [{"source": "/lights/9", "name": "Orphan"}],
            "unmapped_devices": [{"id": "device-9", "name": "Orphan"}],
        },
    )
    save_migration_session(session, path)

    loaded = load_migration_session(path)
    summary = session_summary(loaded)

    assert loaded["source_profile"] == "old"
    assert loaded["destination_profile"] == "pro"
    assert loaded["status"] == "waiting_for_devices"
    assert not summary["ready"]
    assert summary["missing"][0]["source"] == "/lights/9"
    assert summary["unmapped_devices"][0]["id"] == "device-9"



def test_apple_home_room_matching_uses_synonyms_and_partial_names():
    hue_tree = {
        "rooms": [
            {"id": "hue-salon", "name": "Salon", "devices": []},
            {"id": "hue-louis", "name": "Chambre Louis", "devices": []},
            {"id": "hue-bureau", "name": "Bureau", "devices": []},
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-sejour", "name": "Séjour"},
            {"id": "apple-louis", "name": "Louis"},
            {"id": "apple-office", "name": "Office"},
        ],
        "accessories": [],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    mapped = {row["hue_room_name"]: row for row in plan["rooms"]}
    assert mapped["Salon"]["apple_room_name"] == "Séjour"
    assert mapped["Salon"]["method"] == "heuristic"
    assert mapped["Chambre Louis"]["apple_room_name"] == "Louis"
    assert mapped["Bureau"]["apple_room_name"] == "Office"
    assert plan["summary"]["mapped_rooms"] == 3


def test_apple_home_room_matching_does_not_guess_when_ambiguous():
    hue_tree = {
        "rooms": [
            {"id": "hue-bedroom", "name": "Chambre", "devices": []},
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [
            {"id": "apple-1", "name": "Chambre 1"},
            {"id": "apple-2", "name": "Chambre 2"},
        ],
        "accessories": [],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    room = plan["rooms"][0]
    assert room["status"] == "unmapped"
    assert room["apple_room_id"] is None
    assert len(room["suggestions"]) == 2


def test_apple_home_accessory_matching_prefers_serial_then_fuzzy_name():
    hue_tree = {
        "rooms": [
            {
                "id": "hue-room",
                "name": "Salon",
                "devices": [
                    {
                        "id": "hue-device-1",
                        "name": "Lampe canapé",
                        "identifiers": {
                            "zigbee_macs": ["00:17:88:01:02:03:04:05"],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    },
                    {
                        "id": "hue-device-2",
                        "name": "Plafonnier salon",
                        "identifiers": {
                            "zigbee_macs": [],
                            "v1_uniqueids": [],
                            "pairing_fields": [],
                        },
                    },
                ],
            }
        ]
    }
    inventory = {
        "home": {"id": "home-1", "name": "Maison"},
        "rooms": [{"id": "apple-room", "name": "Séjour"}],
        "accessories": [
            {
                "id": "apple-1",
                "name": "Canapé",
                "serial_number": "0017880102030405",
                "room_id": "other",
                "room_name": "Autre",
            },
            {
                "id": "apple-2",
                "name": "Plafonnier du salon",
                "serial_number": None,
                "room_id": "other",
                "room_name": "Autre",
            },
            {
                "id": "apple-3",
                "name": "HomePod",
                "serial_number": None,
                "room_id": "apple-room",
                "room_name": "Séjour",
            },
        ],
    }

    plan = build_apple_home_sync_plan(hue_tree, inventory)

    methods = {row["hue_device_id"]: row["match_method"] for row in plan["devices"]}
    assert methods["hue-device-1"] == "serial"
    assert methods["hue-device-2"].startswith("heuristic:")
    assert plan["summary"]["moves"] == 2

    room = plan["rooms"][0]
    assert [item["name"] for item in room["hue_devices"]] == [
        "Lampe canapé",
        "Plafonnier salon",
    ]
    assert [item["name"] for item in room["apple_accessories"]] == ["HomePod"]
    assert room["impact"] == {
        "hue_device_count": 2,
        "apple_accessory_count": 1,
        "move_count": 2,
        "already_correct_count": 0,
    }
    assert {move["from_room_name"] for move in room["planned_moves"]} == {"Autre"}
    assert {move["to_room_name"] for move in room["planned_moves"]} == {"Séjour"}
