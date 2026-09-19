#!/usr/bin/env python3
"""Extract Hue migration orchestration call-sites from a Blutter asm tree."""

from __future__ import annotations

import argparse
from pathlib import Path

TERMS = (
    "StartDeviceMigrationActionParams",
    "eligibleDevices",
    "startDeviceMigration",
    "StartDeviceMigrationRequest",
    "CreateMigrateBridgeJobRequest",
    "CreateBridgeMergeJobRequest",
    "BridgeMigrationService",
    "migrationJobId",
    "mergeJobId",
    "targetBridgeId",
    "sourceBridgeId",
)

FOCUSED = (
    "StartDeviceMigrationActionParams",
    "eligibleDevices",
    "BridgeMigrationService",
)


def contexts(path: Path, terms: tuple[str, ...], radius: int = 45):
    lines = path.read_text(errors="replace").splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(term in line for term in terms):
            lo = max(0, i - radius)
            hi = min(len(lines), i + radius + 1)
            hits.append((i, lo, hi))
    if not hits:
        return []
    merged = []
    for _, lo, hi in hits:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return [
        "\n".join(f"{n + 1:07d}: {lines[n]}" for n in range(lo, hi))
        for lo, hi in merged
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("asm_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    files = sorted(args.asm_root.rglob("*.dart"))
    index = []
    focused = []
    for path in files:
        rel = path.relative_to(args.asm_root)
        blocks = contexts(path, TERMS)
        if blocks:
            index.append(str(rel))
            with (args.output / "migration-call-sites.txt").open("a") as stream:
                for block in blocks:
                    stream.write(f"\n===== {rel} =====\n{block}\n")
        focused_blocks = contexts(path, FOCUSED, radius=100)
        if focused_blocks:
            focused.append(str(rel))
            with (args.output / "eligible-devices-focused.txt").open("a") as stream:
                for block in focused_blocks:
                    stream.write(f"\n===== {rel} =====\n{block}\n")

    (args.output / "matching-files.txt").write_text("\n".join(index) + "\n")
    (args.output / "focused-files.txt").write_text("\n".join(focused) + "\n")
    print(f"migration files: {len(index)}")
    print(f"focused eligibleDevices files: {len(focused)}")


if __name__ == "__main__":
    main()
