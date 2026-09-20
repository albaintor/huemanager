#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET_NAME = "HueManagerHomeSync"


def matching_brace(text: str, opening: int) -> int:
    if text[opening] != "{":
        raise ValueError("opening position is not a brace")
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced PBX braces")


def find_native_target_uuid(text: str) -> str:
    pattern = re.compile(
        rf"(?m)^\s*([A-F0-9]{{24}}) /\* {re.escape(TARGET_NAME)} \*/ = \{{\s*"
        rf"\n\s*isa = PBXNativeTarget;"
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Could not find PBXNativeTarget {TARGET_NAME!r}")
    return match.group(1)


def target_attributes_block(text: str, target_uuid: str) -> tuple[int, int, str]:
    marker = "TargetAttributes = {"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise SystemExit("Could not find PBXProject TargetAttributes")

    target_attributes_open = text.find("{", marker_index)
    target_attributes_close = matching_brace(text, target_attributes_open)

    target_pattern = re.compile(
        rf"(?m)^(?P<indent>\s*){re.escape(target_uuid)} = \{{"
    )
    match = target_pattern.search(
        text, target_attributes_open, target_attributes_close
    )
    if not match:
        raise SystemExit(
            f"Target UUID {target_uuid} is missing from PBXProject TargetAttributes"
        )

    opening = text.find("{", match.start(), match.end())
    closing = matching_brace(text, opening)
    if closing > target_attributes_close:
        raise SystemExit("TargetAttributes block parsing escaped its parent dictionary")

    return opening, closing, match.group("indent")


def has_valid_homekit(block: str) -> bool:
    return bool(
        re.search(
            r"SystemCapabilities\s*=\s*\{"
            r".*?com\.apple\.HomeKit\s*=\s*\{"
            r".*?enabled\s*=\s*1\s*;",
            block,
            re.S,
        )
    )


def patch_target_block(block: str, entry_indent: str) -> str:
    if has_valid_homekit(block):
        return block

    # Remove the malformed nested-dictionary representation emitted by
    # XcodeGen 2.45/2.46, but only inside the target's TargetAttributes block.
    block = re.sub(
        r"(?m)^\s*SystemCapabilities\s*=\s*"
        r'"\[.*?com\.apple\.HomeKit.*?\]";\s*\n?',
        "",
        block,
        count=1,
    )

    # If a real SystemCapabilities dictionary exists for another capability,
    # add HomeKit to it instead of creating a second dictionary.
    system_match = re.search(r"SystemCapabilities\s*=\s*\{", block)
    if system_match:
        opening = block.find("{", system_match.start())
        closing = matching_brace(block, opening)
        system_indent_match = re.search(
            r"(?m)^(\s*)SystemCapabilities\s*=", block[: system_match.end()]
        )
        system_indent = (
            system_indent_match.group(1)
            if system_indent_match
            else entry_indent + "\t"
        )
        capability = (
            f"\n{system_indent}\tcom.apple.HomeKit = {{"
            f"\n{system_indent}\t\tenabled = 1;"
            f"\n{system_indent}\t}};"
        )
        return block[:closing] + capability + block[closing:]

    capability = (
        f"\n{entry_indent}\tSystemCapabilities = {{"
        f"\n{entry_indent}\t\tcom.apple.HomeKit = {{"
        f"\n{entry_indent}\t\t\tenabled = 1;"
        f"\n{entry_indent}\t\t}};"
        f"\n{entry_indent}\t}};"
    )
    return block[:-1] + capability + "\n" + entry_indent + "}"


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit(
            "usage: fix_homekit_capability.py <project.pbxproj> [--check]"
        )

    check_only = len(sys.argv) == 3 and sys.argv[2] == "--check"
    if len(sys.argv) == 3 and not check_only:
        raise SystemExit("only optional argument supported is --check")

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    target_uuid = find_native_target_uuid(text)
    opening, closing, indent = target_attributes_block(text, target_uuid)
    block = text[opening : closing + 1]

    if check_only:
        if not has_valid_homekit(block):
            raise SystemExit(
                f"HomeKit capability is missing from TargetAttributes for "
                f"{TARGET_NAME} ({target_uuid})"
            )
        print(
            f"HomeKit capability verified for {TARGET_NAME} "
            f"target {target_uuid}"
        )
        return

    patched = patch_target_block(block, indent)
    text = text[:opening] + patched + text[closing + 1 :]

    # Reparse the final project, so a successful exit guarantees the capability
    # is under the exact target Xcode will display in Signing & Capabilities.
    final_open, final_close, _ = target_attributes_block(text, target_uuid)
    final_block = text[final_open : final_close + 1]
    if not has_valid_homekit(final_block):
        raise SystemExit("HomeKit injection failed validation")

    path.write_text(text, encoding="utf-8")
    print(
        f"HomeKit capability installed in TargetAttributes for "
        f"{TARGET_NAME} target {target_uuid}"
    )


if __name__ == "__main__":
    main()
