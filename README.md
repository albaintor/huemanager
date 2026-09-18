# HueManager

HueManager is a **non-destructive, selective Philips Hue migration CLI**. It is designed for the case where a Hue Bridge Pro is already populated and you want to move only selected rooms from another Hue Bridge without throwing away their configuration.

It combines the Hue local APIs:

- **CLIP v2** for rooms, devices and scenes;
- **CLIP v1** for stable Zigbee `uniqueid` matching and legacy rules (including many iConnectHue rules).

The source bridge is never modified by HueManager 0.1.0. Physical Zigbee migration/pairing stays explicit so a bad mapping cannot silently remove devices from the old bridge.

## What 0.1.0 migrates

For one selected room, HueManager snapshots:

- the room and its child devices;
- all v1 light/sensor resources belonging to those devices;
- all v2 scenes attached to the room, including actions and dynamic-scene palette data when exposed by the Bridge;
- v1 rules that reference the selected room, lights, sensors or scenes.

After the physical devices have been paired to the destination bridge, HueManager matches them by their Zigbee `uniqueid`, recreates or merges the room, recreates its scenes and remaps rule references.

Rules with references to resources that cannot be mapped are **skipped rather than guessed** and reported at the end.

## Install

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Pair HueManager with both bridges

Press the physical link button on the bridge, then run:

```bash
huemanager pair old 192.168.1.20
huemanager pair pro 192.168.1.21
```

Credentials are stored in `~/.config/huemanager/config.json` with restricted file permissions when supported by the OS.

By default TLS certificate verification is disabled because local Hue Bridge certificate validation depends on the local trust setup. Use `--verify-tls` if your environment is configured for it.

Check bridges and rooms:

```bash
huemanager bridges
huemanager rooms old
```

## Safe migration workflow

### 1. Snapshot the room while everything is still on the old bridge

```bash
huemanager snapshot old --room "Jardin" --output jardin.json
```

Keep this JSON until the migration is fully validated.

### 2. Move/pair the physical devices to the Bridge Pro

Use the Hue app, or start a light search with:

```bash
huemanager scan pro
```

Accessories may require their normal reset/pairing procedure. HueManager deliberately does not delete anything from the old bridge.

### 3. Check the mapping

```bash
huemanager plan jardin.json pro
```

`ready: true` means every snapshotted v1 light/sensor has been found on the destination by `uniqueid`. Exit code 2 means at least one physical resource is still missing.

### 4. Dry-run

```bash
huemanager apply jardin.json pro
```

No change is made without `--execute`.

### 5. Apply

```bash
huemanager apply jardin.json pro --execute
```

If a room with the same name already exists on the destination, HueManager merges the migrated devices into it. Existing scene names in that room are reused rather than overwritten.

To use another destination room name:

```bash
huemanager apply jardin.json pro --execute --room-name "Extérieur"
```

## Safety model

HueManager intentionally has no `delete-source` command in the first release. Validate the room, scenes, switches/motion sensors and rules on the Bridge Pro first, then clean up the old bridge using the Hue app.

A rule is recreated only when every Hue resource reference used by that rule can be remapped. Cross-room dependencies are surfaced instead of silently creating a broken automation.

## Current limitations

- Hue app **v2 `behavior_instance` automations** are not recreated yet. They are different from CLIP v1 rules and need a separate dependency-aware migrator.
- Entertainment areas, Matter bindings, HomeKit configuration and third-party cloud integrations are outside the scope of 0.1.0.
- A physical Zigbee device still has to leave the source Zigbee network and join the destination network.
- Rules created by third-party applications can depend on resources outside the selected room; HueManager skips them if those dependencies cannot be mapped.

## Development

```bash
pip install -e '.[dev]'
ruff check src tests
pytest -q
```
