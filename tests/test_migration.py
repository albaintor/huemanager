from huemanager.migration import build_mapping_plan, rewrite_rule


def test_build_mapping_plan_matches_uniqueid_and_v2_service():
    snapshot = {
        "room": {"id": "room-source", "id_v1": "/groups/3"},
        "devices": [
            {
                "id": "device-source",
                "services_expanded": [
                    {
                        "id": "light-source",
                        "type": "light",
                        "id_v1": "/lights/7",
                    }
                ],
            }
        ],
        "scenes": [],
        "v1": {
            "lights": {
                "7": {
                    "name": "Patio",
                    "uniqueid": "AA:BB-0b",
                }
            },
            "sensors": {},
        },
    }
    dest_v1 = {
        "lights": {
            "42": {
                "name": "Patio",
                "uniqueid": "aa:bb-0B",
            }
        },
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


def test_build_mapping_plan_reports_missing_resource():
    snapshot = {
        "room": {"id": "room-source", "id_v1": "/groups/3"},
        "devices": [],
        "scenes": [],
        "v1": {
            "lights": {
                "7": {
                    "name": "Patio",
                    "uniqueid": "aa",
                }
            },
            "sensors": {},
        },
    }

    plan = build_mapping_plan(
        snapshot,
        {"lights": {}, "sensors": {}},
        [],
    )

    assert not plan.complete
    assert plan.missing[0]["source"] == "/lights/7"


def test_rewrite_rule_maps_addresses_and_scene_body():
    rule = {
        "name": "Motion patio",
        "conditions": [
            {
                "address": "/sensors/4/state/presence",
                "operator": "eq",
                "value": "true",
            }
        ],
        "actions": [
            {
                "address": "/groups/3/action",
                "method": "PUT",
                "body": {"scene": "abc"},
            }
        ],
    }

    rewritten, unresolved = rewrite_rule(
        rule,
        {
            "/sensors/4": "/sensors/17",
            "/groups/3": "/groups/9",
            "/scenes/abc": "/scenes/xyz",
        },
    )

    assert not unresolved
    assert rewritten["conditions"][0]["address"] == "/sensors/17/state/presence"
    assert rewritten["actions"][0]["address"] == "/groups/9/action"
    assert rewritten["actions"][0]["body"]["scene"] == "xyz"


def test_rewrite_rule_blocks_external_hue_resource():
    rule = {
        "name": "External dependency",
        "conditions": [
            {
                "address": "/sensors/99/state/flag",
                "operator": "eq",
                "value": "true",
            }
        ],
        "actions": [],
    }

    _, unresolved = rewrite_rule(rule, {})

    assert "/sensors/99" in unresolved
