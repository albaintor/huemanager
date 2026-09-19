import pytest

from huemanager.hue_private import bridge_pb2
from huemanager.hue_private.client import (
    HuePrivateBridgeClient,
    IrreversibleMigrationConfirmationRequired,
)


class _FakeRpc:
    def __init__(self, response=None):
        self.calls = []
        self.response = response

    def __call__(self, request, *, timeout, metadata):
        self.calls.append((request, timeout, tuple(metadata)))
        return self.response


class _FakeChannel:
    def __init__(self):
        self.paths = {}
        self.closed = False

    def unary_unary(self, path, **kwargs):
        rpc = _FakeRpc()
        self.paths[path] = (rpc, kwargs)
        return rpc

    def close(self):
        self.closed = True


def test_start_device_migration_wire_layout():
    request = bridge_pb2.StartDeviceMigrationRequest(
        bridge_id="b",
        migrate_job_id="m",
        merge_job_id="x",
    )
    assert request.SerializeToString().hex() == "0a016212016d1a0178"


def test_job_state_fields_are_oneof():
    job = bridge_pb2.MigrateBridgeJob()
    job.pending.stage = bridge_pb2.MIGRATION_STAGE_MIGRATING_BRIDGE
    assert job.WhichOneof("state") == "pending"
    job.success.SetInParent()
    assert job.WhichOneof("state") == "success"
    assert not job.HasField("pending")


def test_recovered_enum_values():
    assert bridge_pb2.DEVICE_MIGRATION_STATUS_FAILED == 4
    assert bridge_pb2.MERGE_STAGE_UPLOADING_BACKUP_FILE_TO_BRIDGE == 1
    assert bridge_pb2.MERGE_STAGE_STARTING_DEVICE_IMPORT_ON_BRIDGE == 2
    assert bridge_pb2.MERGE_STAGE_IMPORTING_DEVICES_ON_BRIDGE == 3


def test_bridge_service_descriptor_matches_recovered_rpc_surface():
    service = bridge_pb2.DESCRIPTOR.services_by_name["BridgeService"]
    assert [method.name for method in service.methods] == [
        "CreateBridgeBackupJob",
        "GetBridgeBackupJob",
        "CreateMigrateBridgeJob",
        "GetMigrateBridgeJob",
        "StartDeviceMigration",
        "GetDeviceMigrationStatus",
        "StopDeviceMigration",
        "GetMigrationSoftwareVersions",
        "CreateBridgeMergeJob",
        "GetBridgeMergeJob",
    ]
    start = service.methods_by_name["StartDeviceMigration"]
    assert start.input_type.full_name == "hue.accounts.v1.StartDeviceMigrationRequest"
    assert start.output_type.full_name == "google.protobuf.Empty"


def test_client_uses_recovered_metadata_and_guards_start():
    channel = _FakeChannel()
    client = HuePrivateBridgeClient(
        "token",
        channel=channel,
        device_id="device",
        app_name="Hue",
        extra_metadata=(("X-Test", "value"),),
    )
    assert client._metadata() == (
        ("authorization", "Bearer token"),
        ("device-id", "device"),
        ("app-name", "Hue"),
        ("x-test", "value"),
    )

    with pytest.raises(IrreversibleMigrationConfirmationRequired):
        client.start_device_migration("bridge", migrate_job_id="job")

    client.start_device_migration(
        "bridge",
        migrate_job_id="job",
        confirm_irreversible=True,
    )
    path = "/hue.accounts.v1.BridgeService/StartDeviceMigration"
    rpc, _ = channel.paths[path]
    request, timeout, metadata = rpc.calls[-1]
    assert request.bridge_id == "bridge"
    assert request.migrate_job_id == "job"
    assert timeout == 30.0
    assert metadata[0] == ("authorization", "Bearer token")
