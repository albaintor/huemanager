# Descriptor-backed bindings reconstructed from Hue Android 5.57.0.
from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import empty_pb2 as google_dot_protobuf_dot_empty__pb2  # noqa: F401
from google.protobuf import timestamp_pb2 as google_dot_protobuf_dot_timestamp__pb2  # noqa: F401
from google.protobuf.internal import builder as _builder

_fd = _descriptor_pb2.FileDescriptorProto(
    name="huemanager/hue_private/proto/bridge.proto",
    package="hue.accounts.v1",
    syntax="proto3",
)
_fd.dependency.extend(
    ["google/protobuf/empty.proto", "google/protobuf/timestamp.proto"]
)

_STRING = _descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_MESSAGE = _descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
_ENUM = _descriptor_pb2.FieldDescriptorProto.TYPE_ENUM
_OPTIONAL = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL


def _add_enum(name, values):
    enum = _fd.enum_type.add()
    enum.name = name
    for number, value_name in values:
        value = enum.value.add()
        value.name = value_name
        value.number = number


def _add_field(message, name, number, field_type, type_name=None, oneof=None):
    field = message.field.add()
    field.name = name
    field.number = number
    field.label = _OPTIONAL
    field.type = field_type
    if type_name:
        field.type_name = type_name
    if oneof is not None:
        field.oneof_index = oneof


def _add_message(name, fields=()):
    message = _fd.message_type.add()
    message.name = name
    for field in fields:
        _add_field(message, *field)
    return message


_add_enum(
    "DeviceMigrationStatus",
    [
        (0, "DEVICE_MIGRATION_STATUS_UNSPECIFIED"),
        (1, "DEVICE_MIGRATION_STATUS_IN_PROCESS"),
        (2, "DEVICE_MIGRATION_STATUS_COMPLETED"),
        (3, "DEVICE_MIGRATION_STATUS_STOPPED"),
        (4, "DEVICE_MIGRATION_STATUS_FAILED"),
    ],
)
_add_enum(
    "BackupStage",
    [
        (0, "BACKUP_STAGE_UNSPECIFIED"),
        (1, "BACKUP_STAGE_STARTING_BACKUP_ON_BRIDGE"),
        (2, "BACKUP_STAGE_CREATING_BACKUP_FILE"),
        (3, "BACKUP_STAGE_STORING_BACKUP_FILE"),
    ],
)
_add_enum(
    "MigrationStage",
    [
        (0, "MIGRATION_STAGE_UNSPECIFIED"),
        (1, "MIGRATION_STAGE_UPLOADING_BACKUP_FILE_TO_BRIDGE"),
        (2, "MIGRATION_STAGE_STARTING_MIGRATION_ON_BRIDGE"),
        (3, "MIGRATION_STAGE_MIGRATING_BRIDGE"),
    ],
)
_add_enum(
    "MergeStage",
    [
        (0, "MERGE_STAGE_UNSPECIFIED"),
        (1, "MERGE_STAGE_UPLOADING_BACKUP_FILE_TO_BRIDGE"),
        (2, "MERGE_STAGE_STARTING_DEVICE_IMPORT_ON_BRIDGE"),
        (3, "MERGE_STAGE_IMPORTING_DEVICES_ON_BRIDGE"),
    ],
)

_add_message(
    "CreateBridgeBackupJobRequest",
    [("bridge_id", 1, _STRING), ("bridge_resource_uuid", 2, _STRING)],
)
_add_message(
    "GetBridgeBackupJobRequest",
    [("bridge_id", 1, _STRING), ("job_id", 2, _STRING)],
)

backup = _add_message("BridgeBackupJob")
backup.oneof_decl.add().name = "state"
pending = backup.nested_type.add()
pending.name = "Pending"
_add_field(pending, "stage", 1, _ENUM, ".hue.accounts.v1.BackupStage")
success = backup.nested_type.add()
success.name = "Success"
_add_field(success, "backup_time", 1, _MESSAGE, ".google.protobuf.Timestamp")
error = backup.nested_type.add()
error.name = "Error"
_add_field(error, "error_message", 1, _STRING)
_add_field(backup, "job_id", 1, _STRING)
_add_field(backup, "bridge_id", 2, _STRING)
_add_field(backup, "create_time", 3, _MESSAGE, ".google.protobuf.Timestamp")
_add_field(backup, "pending", 4, _MESSAGE, ".hue.accounts.v1.BridgeBackupJob.Pending", 0)
_add_field(backup, "success", 5, _MESSAGE, ".hue.accounts.v1.BridgeBackupJob.Success", 0)
_add_field(backup, "error", 6, _MESSAGE, ".hue.accounts.v1.BridgeBackupJob.Error", 0)

_add_message(
    "CreateMigrateBridgeJobRequest",
    [("bridge_id", 1, _STRING), ("backup_job_id", 2, _STRING)],
)
_add_message(
    "GetMigrateBridgeJobRequest",
    [("bridge_id", 1, _STRING), ("job_id", 2, _STRING)],
)

migrate = _add_message("MigrateBridgeJob")
migrate.oneof_decl.add().name = "state"
pending = migrate.nested_type.add()
pending.name = "Pending"
_add_field(pending, "stage", 1, _ENUM, ".hue.accounts.v1.MigrationStage")
success = migrate.nested_type.add()
success.name = "Success"
_add_field(success, "migrate_time", 1, _MESSAGE, ".google.protobuf.Timestamp")
error = migrate.nested_type.add()
error.name = "Error"
_add_field(error, "error_message", 1, _STRING)
_add_field(migrate, "job_id", 1, _STRING)
_add_field(migrate, "bridge_id", 2, _STRING)
_add_field(migrate, "create_time", 3, _MESSAGE, ".google.protobuf.Timestamp")
_add_field(migrate, "pending", 4, _MESSAGE, ".hue.accounts.v1.MigrateBridgeJob.Pending", 0)
_add_field(migrate, "success", 5, _MESSAGE, ".hue.accounts.v1.MigrateBridgeJob.Success", 0)
_add_field(migrate, "error", 6, _MESSAGE, ".hue.accounts.v1.MigrateBridgeJob.Error", 0)
_add_field(migrate, "bridge_resource_uuid", 7, _STRING)

_add_message(
    "StartDeviceMigrationRequest",
    [
        ("bridge_id", 1, _STRING),
        ("migrate_job_id", 2, _STRING),
        ("merge_job_id", 3, _STRING),
    ],
)
_add_message("GetDeviceMigrationStatusRequest", [("bridge_id", 1, _STRING)])
_add_message(
    "GetDeviceMigrationStatusResponse",
    [("status", 1, _ENUM, ".hue.accounts.v1.DeviceMigrationStatus")],
)
_add_message("StopDeviceMigrationRequest", [("bridge_id", 1, _STRING)])
_add_message(
    "GetMigrationSoftwareVersionsRequest",
    [("source_bridge_id", 1, _STRING), ("destination_bridge_id", 2, _STRING)],
)
_add_message(
    "GetMigrationSoftwareVersionsResponse",
    [
        ("source_bridge_software_version", 1, _STRING),
        ("destination_bridge_software_version", 2, _STRING),
    ],
)
_add_message(
    "CreateBridgeMergeJobRequest",
    [("bridge_id", 1, _STRING), ("backup_job_id", 2, _STRING)],
)
_add_message(
    "GetBridgeMergeJobRequest",
    [("bridge_id", 1, _STRING), ("job_id", 2, _STRING)],
)

merge = _add_message("BridgeMergeJob")
merge.oneof_decl.add().name = "state"
pending = merge.nested_type.add()
pending.name = "Pending"
_add_field(pending, "stage", 1, _ENUM, ".hue.accounts.v1.MergeStage")
success = merge.nested_type.add()
success.name = "Success"
_add_field(success, "merge_time", 1, _MESSAGE, ".google.protobuf.Timestamp")
error = merge.nested_type.add()
error.name = "Error"
_add_field(error, "error_message", 1, _STRING)
_add_field(merge, "job_id", 1, _STRING)
_add_field(merge, "bridge_id", 2, _STRING)
_add_field(merge, "create_time", 3, _MESSAGE, ".google.protobuf.Timestamp")
_add_field(merge, "pending", 4, _MESSAGE, ".hue.accounts.v1.BridgeMergeJob.Pending", 0)
_add_field(merge, "success", 5, _MESSAGE, ".hue.accounts.v1.BridgeMergeJob.Success", 0)
_add_field(merge, "error", 6, _MESSAGE, ".hue.accounts.v1.BridgeMergeJob.Error", 0)

service = _fd.service.add()
service.name = "BridgeService"
for method_name, request_name, response_name in [
    ("CreateBridgeBackupJob", "CreateBridgeBackupJobRequest", "BridgeBackupJob"),
    ("GetBridgeBackupJob", "GetBridgeBackupJobRequest", "BridgeBackupJob"),
    ("CreateMigrateBridgeJob", "CreateMigrateBridgeJobRequest", "MigrateBridgeJob"),
    ("GetMigrateBridgeJob", "GetMigrateBridgeJobRequest", "MigrateBridgeJob"),
    ("StartDeviceMigration", "StartDeviceMigrationRequest", ".google.protobuf.Empty"),
    (
        "GetDeviceMigrationStatus",
        "GetDeviceMigrationStatusRequest",
        "GetDeviceMigrationStatusResponse",
    ),
    ("StopDeviceMigration", "StopDeviceMigrationRequest", ".google.protobuf.Empty"),
    (
        "GetMigrationSoftwareVersions",
        "GetMigrationSoftwareVersionsRequest",
        "GetMigrationSoftwareVersionsResponse",
    ),
    ("CreateBridgeMergeJob", "CreateBridgeMergeJobRequest", "BridgeMergeJob"),
    ("GetBridgeMergeJob", "GetBridgeMergeJobRequest", "BridgeMergeJob"),
]:
    method = service.method.add()
    method.name = method_name
    method.input_type = f".hue.accounts.v1.{request_name}"
    method.output_type = (
        response_name
        if response_name.startswith(".")
        else f".hue.accounts.v1.{response_name}"
    )

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_fd.SerializeToString())
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, __name__, globals())
