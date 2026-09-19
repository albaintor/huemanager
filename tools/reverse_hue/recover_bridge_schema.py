#!/usr/bin/env python3
"""Recover Hue BridgeService migration protobuf evidence from Blutter output."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ADDERS = {
    "aOS": ("string", False),
    "aOB": ("bool", False),
    "aOM": ("message", False),
    "e": ("enum", False),
    "pPS": ("string", True),
    "pPM": ("message", True),
    "pc": ("message", True),
    "pPE": ("enum", True),
}

TARGET_MESSAGES = {
    "GetMigrationSoftwareVersionsResponse",
    "GetMigrationSoftwareVersionsRequest",
    "StopDeviceMigrationRequest",
    "GetDeviceMigrationStatusResponse",
    "GetDeviceMigrationStatusRequest",
    "StartDeviceMigrationRequest",
    "GetBridgeMergeJobRequest",
    "CreateBridgeMergeJobRequest",
    "BridgeMergeJob",
    "BridgeMergeJob_Error",
    "BridgeMergeJob_Success",
    "BridgeMergeJob_Pending",
    "GetMigrateBridgeJobRequest",
    "CreateMigrateBridgeJobRequest",
    "MigrateBridgeJob",
    "MigrateBridgeJob_Error",
    "MigrateBridgeJob_Success",
    "MigrateBridgeJob_Pending",
    "GetBridgeBackupJobRequest",
    "CreateBridgeBackupJobRequest",
    "BridgeBackupJob",
    "BridgeBackupJob_Error",
    "BridgeBackupJob_Success",
    "BridgeBackupJob_Pending",
}

TARGET_RPCS = {
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
}

TARGET_ENUMS = {
    "DeviceMigrationStatus",
    "BackupStage",
    "MigrationStage",
    "MergeStage",
}


def parse_message_file(path: Path) -> dict[str, dict]:
    lines = path.read_text(errors="replace").splitlines()
    classes: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"class (\w+) extends GeneratedMessage", line)
        if match:
            classes.append((index, match.group(1)))

    result: dict[str, dict] = {}
    for pos, (start, name) in enumerate(classes):
        if name not in TARGET_MESSAGES:
            continue
        end = classes[pos + 1][0] if pos + 1 < len(classes) else len(lines)
        ii = next(
            (i for i in range(start, end) if lines[i] == "  static BuilderInfo _i() {"),
            None,
        )
        if ii is None:
            continue

        fields = []
        oneof_tags: list[int] = []
        recent_tag = None
        recent_name = None
        recent_type = None

        for i in range(ii + 1, end):
            line = lines[i]
            if line == "  }":
                break

            tag_match = re.search(r"// 0x[0-9a-f]+: r\d+ = (\d+)\s*$", line)
            if tag_match:
                value = int(tag_match.group(1))
                if 1 <= value <= 536870911:
                    recent_tag = value

            name_match = re.search(
                r'// 0x[0-9a-f]+: r\d+ = "([A-Za-z_][A-Za-z0-9_]*)"',
                line,
            )
            if name_match:
                recent_name = name_match.group(1)

            type_match = re.search(r"r\d+ = <([^>]+)>", line)
            if type_match:
                recent_type = type_match.group(1)

            # Blutter shows Smi-encoded oneof tag arrays as field stores 8/10/12
            # for proto tags 4/5/6. Capture the common Hue job-state case.
            smi_match = re.search(r"r16 = (\d+)\s*$", line)
            if smi_match and "BridgeJob" in name:
                encoded = int(smi_match.group(1))
                if encoded in {8, 10, 12}:
                    oneof_tags.append(encoded // 2)

            adder_match = re.search(r"BuilderInfo::([A-Za-z0-9_]+)", line)
            if not adder_match:
                continue
            adder = adder_match.group(1)
            if adder == "oo":
                recent_name = None
                recent_type = None
                continue
            if adder not in ADDERS or recent_tag is None or recent_name is None:
                continue

            kind, repeated = ADDERS[adder]
            proto_type = recent_type if kind in {"message", "enum"} and recent_type else kind
            fields.append(
                {
                    "tag": recent_tag,
                    "name": recent_name,
                    "type": proto_type,
                    "repeated": repeated,
                    "adder": adder,
                }
            )
            recent_name = None
            recent_type = None

        result[name] = {
            "fields": sorted(fields, key=lambda field: field["tag"]),
            "oneof_tags": sorted(set(oneof_tags)),
            "source": str(path),
        }
    return result


def parse_service_file(path: Path) -> list[dict]:
    lines = path.read_text(errors="replace").splitlines()
    rpcs = []
    for i, line in enumerate(lines):
        match = re.search(r"r1 = <([^,>]+), ([^>]+)>", line)
        if not match:
            continue
        request, response = match.groups()
        for j in range(i + 1, min(i + 20, len(lines))):
            method_match = re.search(r'r0 = "([A-Z][A-Za-z0-9]+)"', lines[j])
            if not method_match:
                continue
            method = method_match.group(1)
            if method in TARGET_RPCS:
                entry = {"method": method, "request": request, "response": response}
                if entry not in rpcs:
                    rpcs.append(entry)
            break
    return rpcs


def extract_enum_evidence(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    lines = path.read_text(errors="replace").splitlines()
    result = {}
    starts = []
    for i, line in enumerate(lines):
        match = re.match(r"class (\w+) extends ProtobufEnum", line)
        if match:
            starts.append((i, match.group(1)))
    for pos, (start, name) in enumerate(starts):
        if name not in TARGET_ENUMS:
            continue
        end = starts[pos + 1][0] if pos + 1 < len(starts) else min(len(lines), start + 600)
        result[name] = lines[start:end]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("blutter_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    base = (
        args.blutter_root
        / "asm"
        / "account_api_client_dart"
        / "hue"
        / "accounts"
        / "v1"
    )
    pb = base / "bridge.pb.dart"
    grpc = base / "bridge.pbgrpc.dart"
    pbenum = base / "bridge.pbenum.dart"

    args.output.mkdir(parents=True, exist_ok=True)
    messages = parse_message_file(pb)
    rpcs = parse_service_file(grpc)
    enum_evidence = extract_enum_evidence(pbenum)

    evidence = {
        "package": "hue.accounts.v1",
        "service": "BridgeService",
        "messages": messages,
        "rpcs": rpcs,
        "enum_classes_found": sorted(enum_evidence),
    }
    (args.output / "bridge-migration-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )

    with (args.output / "bridge-enum-evidence.txt").open("w") as stream:
        if not pbenum.exists():
            stream.write(f"MISSING: {pbenum}\n")
        for name, block in enum_evidence.items():
            stream.write(f"===== {name} =====\n")
            stream.write("\n".join(block))
            stream.write("\n\n")

    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
