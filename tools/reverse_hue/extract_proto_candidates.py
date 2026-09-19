#!/usr/bin/env python3
"""Mine DAE dumps for Hue private protobuf/gRPC descriptor evidence.

The extractor deliberately does not guess protobuf field numbers. It emits
object-pool, class, function and annotated-disassembly neighborhoods so every
recovered tag/type can be tied to binary evidence.
"""

from __future__ import annotations

import argparse
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

TARGET_CLASSES = [
    "StartDeviceMigrationRequest",
    "CreateBridgeMergeJobRequest",
    "CreateMigrateBridgeJobRequest",
]
RELATED_CIDS = {20884, 20885, 20887, 20888, 20889, 20890, 20895, 20896, 20901}
TERMS = [
    *TARGET_CLASSES,
    "StartDeviceMigration",
    "GetDeviceMigrationStatus",
    "StopDeviceMigration",
    "CreateBridgeBackupJob",
    "CreateBridgeMergeJob",
    "CreateMigrateBridgeJob",
    "BridgeService",
    "hue.accounts.v1",
    "api.account.meethue.com",
    "BuilderInfo",
    "FieldInfo",
    "PbFieldType",
    "bridgeId",
    "targetBridgeId",
    "homeId",
    "jobId",
    "migrateJobId",
    "mergeJobId",
    "deviceIds",
    "extended_pan_id",
    "ClipReconstruction",
]


@dataclass
class Hit:
    file: str
    line: int
    term: str
    context: str


def text_files(root: Path) -> list[Path]:
    preferred = {
        "classes.txt",
        "functions.txt",
        "objs.txt",
        "pp.txt",
        "strings.txt",
        "arrays.txt",
        "maps.txt",
        "libs.txt",
    }
    files = [p for p in root.rglob("*") if p.is_file() and p.name in preferred]
    files.extend(p for p in root.rglob("*.dart") if p.is_file())
    return sorted(set(files))


def scan_file(path: Path, root: Path, context_lines: int = 16) -> list[Hit]:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    lowered = [line.lower() for line in lines]
    hits: list[Hit] = []
    for term in TERMS:
        needle = term.lower()
        indexes = [i for i, line in enumerate(lowered) if needle in line]
        if term in {"BuilderInfo", "FieldInfo", "PbFieldType"}:
            indexes = indexes[:200]
        for i in indexes:
            lo = max(0, i - context_lines)
            hi = min(len(lines), i + context_lines + 1)
            block = "\n".join(f"{n + 1:07d}: {lines[n]}" for n in range(lo, hi))
            hits.append(Hit(str(path.relative_to(root)), i + 1, term, block))
    return hits


def class_cid_lines(root: Path) -> list[str]:
    result: list[str] = []
    for path in root.rglob("classes.txt"):
        for line in path.read_text(errors="replace").splitlines():
            if any(name in line for name in TARGET_CLASSES):
                result.append(line)
                continue
            nums = {int(x) for x in re.findall(r"\b\d{4,6}\b", line)}
            if nums & RELATED_CIDS:
                result.append(line)
    return result


def render_hits(root: Path, output: Path) -> tuple[int, dict[str, int]]:
    counts: dict[str, int] = {}
    total = 0
    with output.open("w") as stream:
        for path in text_files(root):
            for hit in scan_file(path, root):
                total += 1
                counts[hit.term] = counts.get(hit.term, 0) + 1
                stream.write(f"\n===== {hit.file}:{hit.line} [{hit.term}] =====\n")
                stream.write(hit.context)
                stream.write("\n")
    return total, counts


def interesting_lines(root: Path) -> list[str]:
    result: list[str] = []
    needles = [
        term.lower()
        for term in TERMS
        if term not in {"BuilderInfo", "FieldInfo", "PbFieldType"}
    ]
    for path in text_files(root):
        if path.suffix == ".dart":
            continue
        for line in path.read_text(errors="replace").splitlines():
            if any(needle in line.lower() for needle in needles):
                result.append(f"{path.relative_to(root)}: {line}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    old_hits, old_counts = render_hits(
        args.old, args.output / "5.56.0-neighborhoods.txt"
    )
    new_hits, new_counts = render_hits(
        args.new, args.output / "5.57.0-neighborhoods.txt"
    )

    old_cids = class_cid_lines(args.old)
    new_cids = class_cid_lines(args.new)
    (args.output / "5.56.0-class-cids.txt").write_text("\n".join(old_cids) + "\n")
    (args.output / "5.57.0-class-cids.txt").write_text("\n".join(new_cids) + "\n")

    old_lines = interesting_lines(args.old)
    new_lines = interesting_lines(args.new)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="5.56.0",
        tofile="5.57.0",
        lineterm="",
    )
    (args.output / "migration-string-diff.txt").write_text("\n".join(diff) + "\n")

    summary = [
        "# Hue protobuf reverse-engineering summary",
        "",
        "No protobuf tag is asserted unless it is visible in the DAE evidence.",
        "",
        "## Target generated-message classes",
        "",
        *[f"- {name}" for name in TARGET_CLASSES],
        "",
        "## Known/related Dart class IDs",
        "",
        "- " + ", ".join(map(str, sorted(RELATED_CIDS))),
        "",
        "## Class inventory: 5.56.0",
        *(old_cids or ["(no matching class inventory lines)"]),
        "",
        "## Class inventory: 5.57.0",
        *(new_cids or ["(no matching class inventory lines)"]),
        "",
        "## Evidence hits",
        f"- 5.56.0: {old_hits}",
        f"- 5.57.0: {new_hits}",
        "",
        "### 5.57.0 term counts",
        *[f"- {term}: {new_counts.get(term, 0)}" for term in TERMS],
        "",
        "See the neighborhood files for BuilderInfo/FieldInfo/object-pool and "
        "annotated-assembly context.",
    ]
    (args.output / "summary.md").write_text("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
