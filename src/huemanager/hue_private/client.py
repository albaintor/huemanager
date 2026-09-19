from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import grpc

from . import bridge_pb2, bridge_pb2_grpc

DEFAULT_ENDPOINT = "api.account.meethue.com:443"


class IrreversibleMigrationConfirmationRequired(RuntimeError):
    """Raised when a destructive migration RPC is attempted without confirmation."""


class HuePrivateBridgeClient:
    """Thin client for the private hue.accounts.v1.BridgeService API.

    The protobuf/service surface is reverse-engineered from Hue Android 5.57.0.
    Authentication uses the Hue account bearer token used by the app. The app
    also sends device/app/platform metadata; these values are accepted here
    without inventing defaults that may differ between app builds.
    """

    def __init__(
        self,
        access_token: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 30.0,
        device_id: str | None = None,
        app_name: str | None = None,
        app_version: str | None = None,
        app_build_number: str | None = None,
        app_platform: str | None = None,
        app_platform_version: str | None = None,
        extra_metadata: Iterable[tuple[str, str]] = (),
        channel: grpc.Channel | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token must not be empty")
        self._access_token = access_token
        self.endpoint = endpoint
        self.timeout = timeout
        recovered = (
            ("device-id", device_id),
            ("app-name", app_name),
            ("app-version", app_version),
            ("app-build-number", app_build_number),
            ("app-platform", app_platform),
            ("app-platform-version", app_platform_version),
        )
        self._extra_metadata = (
            *((key, value) for key, value in recovered if value is not None),
            *((key.lower(), value) for key, value in extra_metadata),
        )
        self._owns_channel = channel is None
        self._channel = channel or grpc.secure_channel(
            endpoint,
            grpc.ssl_channel_credentials(),
        )
        self._stub = bridge_pb2_grpc.BridgeServiceStub(self._channel)

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return (("authorization", f"Bearer {self._access_token}"), *self._extra_metadata)

    def _call(self, rpc: Any, request: Any) -> Any:
        return rpc(request, timeout=self.timeout, metadata=self._metadata())

    def get_migration_software_versions(
        self, source_bridge_id: str, destination_bridge_id: str
    ) -> bridge_pb2.GetMigrationSoftwareVersionsResponse:
        return self._call(
            self._stub.GetMigrationSoftwareVersions,
            bridge_pb2.GetMigrationSoftwareVersionsRequest(
                source_bridge_id=source_bridge_id,
                destination_bridge_id=destination_bridge_id,
            ),
        )

    def create_backup_job(
        self, bridge_id: str, bridge_resource_uuid: str
    ) -> bridge_pb2.BridgeBackupJob:
        return self._call(
            self._stub.CreateBridgeBackupJob,
            bridge_pb2.CreateBridgeBackupJobRequest(
                bridge_id=bridge_id,
                bridge_resource_uuid=bridge_resource_uuid,
            ),
        )

    def get_backup_job(self, bridge_id: str, job_id: str) -> bridge_pb2.BridgeBackupJob:
        return self._call(
            self._stub.GetBridgeBackupJob,
            bridge_pb2.GetBridgeBackupJobRequest(bridge_id=bridge_id, job_id=job_id),
        )

    def create_migrate_job(
        self, bridge_id: str, backup_job_id: str
    ) -> bridge_pb2.MigrateBridgeJob:
        return self._call(
            self._stub.CreateMigrateBridgeJob,
            bridge_pb2.CreateMigrateBridgeJobRequest(
                bridge_id=bridge_id,
                backup_job_id=backup_job_id,
            ),
        )

    def get_migrate_job(self, bridge_id: str, job_id: str) -> bridge_pb2.MigrateBridgeJob:
        return self._call(
            self._stub.GetMigrateBridgeJob,
            bridge_pb2.GetMigrateBridgeJobRequest(bridge_id=bridge_id, job_id=job_id),
        )

    def create_merge_job(
        self, bridge_id: str, backup_job_id: str
    ) -> bridge_pb2.BridgeMergeJob:
        return self._call(
            self._stub.CreateBridgeMergeJob,
            bridge_pb2.CreateBridgeMergeJobRequest(
                bridge_id=bridge_id,
                backup_job_id=backup_job_id,
            ),
        )

    def get_merge_job(self, bridge_id: str, job_id: str) -> bridge_pb2.BridgeMergeJob:
        return self._call(
            self._stub.GetBridgeMergeJob,
            bridge_pb2.GetBridgeMergeJobRequest(bridge_id=bridge_id, job_id=job_id),
        )

    def get_device_migration_status(
        self, bridge_id: str
    ) -> bridge_pb2.GetDeviceMigrationStatusResponse:
        return self._call(
            self._stub.GetDeviceMigrationStatus,
            bridge_pb2.GetDeviceMigrationStatusRequest(bridge_id=bridge_id),
        )

    def start_device_migration(
        self,
        bridge_id: str,
        *,
        migrate_job_id: str | None = None,
        merge_job_id: str | None = None,
        confirm_irreversible: bool = False,
    ) -> None:
        if not confirm_irreversible:
            raise IrreversibleMigrationConfirmationRequired(
                "StartDeviceMigration is potentially irreversible; pass "
                "confirm_irreversible=True only after validating the source/target bridges."
            )
        request = bridge_pb2.StartDeviceMigrationRequest(bridge_id=bridge_id)
        if migrate_job_id is not None:
            request.migrate_job_id = migrate_job_id
        if merge_job_id is not None:
            request.merge_job_id = merge_job_id
        self._call(self._stub.StartDeviceMigration, request)

    def stop_device_migration(self, bridge_id: str, *, confirm: bool = False) -> None:
        if not confirm:
            raise IrreversibleMigrationConfirmationRequired(
                "StopDeviceMigration changes an active migration; pass confirm=True explicitly."
            )
        self._call(
            self._stub.StopDeviceMigration,
            bridge_pb2.StopDeviceMigrationRequest(bridge_id=bridge_id),
        )

    def close(self) -> None:
        if self._owns_channel:
            self._channel.close()

    def __enter__(self) -> HuePrivateBridgeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
