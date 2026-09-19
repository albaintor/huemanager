# Hue private API reverse engineering

This directory contains reproducible tooling used to recover the private Hue
Bridge Pro migration protobuf/gRPC surface from the Android app.

The workflow compares Hue 5.56.0 and 5.57.0 because 5.57.0 introduced
multi-Bridge migration to Bridge Pro. APKs are downloaded transiently and are
not stored as repository artifacts. Only textual Dart-AOT analysis is retained.

Current targets:

- StartDeviceMigrationRequest (Dart class ID 20888)
- CreateBridgeMergeJobRequest (Dart class ID 20890)
- CreateMigrateBridgeJobRequest (Dart class ID 20896)
- related class IDs 20884, 20885, 20887, 20889, 20895, 20901
- service/method strings under hue.accounts.v1.BridgeService

The extractor deliberately leaves protobuf field numbers unknown until they are
supported by DAE object-pool / annotated-disassembly evidence.
