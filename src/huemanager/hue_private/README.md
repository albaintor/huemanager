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
