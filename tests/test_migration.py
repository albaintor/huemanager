from huemanager.migration import build_mapping_plan, rewrite_rule


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
