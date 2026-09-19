from __future__ import annotations

import grpc
from google.protobuf import empty_pb2 as google_dot_protobuf_dot_empty__pb2

from . import bridge_pb2 as bridge__pb2


class BridgeServiceStub:
    def __init__(self, channel: grpc.Channel) -> None:
        self.CreateBridgeBackupJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/CreateBridgeBackupJob",
            request_serializer=bridge__pb2.CreateBridgeBackupJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.BridgeBackupJob.FromString,
        )
        self.GetBridgeBackupJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/GetBridgeBackupJob",
            request_serializer=bridge__pb2.GetBridgeBackupJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.BridgeBackupJob.FromString,
        )
        self.CreateMigrateBridgeJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/CreateMigrateBridgeJob",
            request_serializer=bridge__pb2.CreateMigrateBridgeJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.MigrateBridgeJob.FromString,
        )
        self.GetMigrateBridgeJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/GetMigrateBridgeJob",
            request_serializer=bridge__pb2.GetMigrateBridgeJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.MigrateBridgeJob.FromString,
        )
        self.StartDeviceMigration = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/StartDeviceMigration",
            request_serializer=bridge__pb2.StartDeviceMigrationRequest.SerializeToString,
            response_deserializer=google_dot_protobuf_dot_empty__pb2.Empty.FromString,
        )
        self.GetDeviceMigrationStatus = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/GetDeviceMigrationStatus",
            request_serializer=bridge__pb2.GetDeviceMigrationStatusRequest.SerializeToString,
            response_deserializer=bridge__pb2.GetDeviceMigrationStatusResponse.FromString,
        )
        self.StopDeviceMigration = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/StopDeviceMigration",
            request_serializer=bridge__pb2.StopDeviceMigrationRequest.SerializeToString,
            response_deserializer=google_dot_protobuf_dot_empty__pb2.Empty.FromString,
        )
        self.GetMigrationSoftwareVersions = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/GetMigrationSoftwareVersions",
            request_serializer=bridge__pb2.GetMigrationSoftwareVersionsRequest.SerializeToString,
            response_deserializer=bridge__pb2.GetMigrationSoftwareVersionsResponse.FromString,
        )
        self.CreateBridgeMergeJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/CreateBridgeMergeJob",
            request_serializer=bridge__pb2.CreateBridgeMergeJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.BridgeMergeJob.FromString,
        )
        self.GetBridgeMergeJob = channel.unary_unary(
            "/hue.accounts.v1.BridgeService/GetBridgeMergeJob",
            request_serializer=bridge__pb2.GetBridgeMergeJobRequest.SerializeToString,
            response_deserializer=bridge__pb2.BridgeMergeJob.FromString,
        )
