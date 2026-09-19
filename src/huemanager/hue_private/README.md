# Hue private BridgeService

Experimental client for the private `hue.accounts.v1.BridgeService` API recovered
from Philips Hue Android 5.57.0 (Flutter/Dart AOT).

The recovered production endpoint is `api.account.meethue.com:443` over TLS.
The app supplies a Hue account bearer token and also builds these metadata keys:
`device-id`, `app-name`, `app-version`, `app-build-number`, `app-platform`,
and `app-platform-version`. The client accepts them but deliberately does not
invent values.

`StartDeviceMigrationRequest` contains only `bridge_id`, `migrate_job_id`,
and `merge_job_id`. It contains no light/device selector. The app computes an
`eligibleDevices` collection locally, but that collection is not passed to
`BridgeMigrationService.startDeviceMigration` or the gRPC request.

For that reason `HuePrivateBridgeClient.start_device_migration()` exposes no
`device_ids` parameter and requires `confirm_irreversible=True`. Unit tests
never make a live migration call.

## Recovered migration data flow

The Android app uses two distinct notions of "backup":

1. The migration backup is a server-side `BridgeBackupJob`. The app calls
   `CreateBridgeBackupJob(bridgeId, bridgeResourceUuid)`, polls
   `GetBridgeBackupJob`, and later passes only the resulting `backupJobId`
   into `CreateMigrateBridgeJob` / `CreateBridgeMergeJob`. No backup bytes
   are downloaded, uploaded, parsed, or modified by the Flutter application.

2. During bridge merge the app also dispatches a local
   `BackupSourceBridgeDataAction`. This is an application-state snapshot used
   for post-migration CLIP reconstruction. Recovered fields include source and
   target bridge identifiers, device hardware addresses, device enabled states,
   devices, bridge devices, rooms, lights, zones, scenes, scene palettes,
   entertainment resources, smart scenes, motion/service resources, behaviors,
   and legacy accessory configuration. This is not the firmware migration
   backup referenced by `backupJobId`.

The recovered sequence is therefore:

```text
source bridge
  -> CreateBridgeBackupJob(bridgeId, bridgeResourceUuid)
  -> BridgeBackupJobId
  -> CreateMigrateBridgeJob / CreateBridgeMergeJob(bridgeId, backupJobId)
  -> migrationJobId / mergeJobId
  -> StartDeviceMigration(bridgeId, migrationJobId, mergeJobId)
```

`eligibleDevices` is retained separately in application state. After
`StartDeviceMigration` succeeds it is copied into
`DeviceMigrationStartedAction` / `BridgeMergeDeviceMigrationStartedAction`
and into `BridgeMergeState.eligibleForDeviceMigration`. This supports UI,
progress accounting, and post-migration reconstruction, but changing that Set
alone cannot change the wire request because no device list is serialized into
the recovered gRPC calls.
