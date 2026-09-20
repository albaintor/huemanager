#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_homekit_capability.py <project.pbxproj>")

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

# XcodeGen 2.45/2.46 currently serializes nested target attributes such as
# SystemCapabilities as a quoted Swift-dictionary description, e.g.:
#
#   SystemCapabilities = "[\"com.apple.HomeKit\": [\"enabled\": 1]]";
#
# Xcode expects a real PBX dictionary. Replace only the known malformed
# HomeKit representation so this workaround fails loudly once XcodeGen fixes
# the upstream issue instead of silently rewriting unrelated data.
patterns = [
    r'(?P<indent>\s*)SystemCapabilities = "\[\\\"com\.apple\.HomeKit\\\": \[\\\"enabled\\\": 1\]\]";',
    r'(?P<indent>\s*)SystemCapabilities = "\[\\"com\.apple\.HomeKit\\": \[\\"enabled\\": 1\]\]";',
]

replacement_template = """{indent}SystemCapabilities = {{
{indent}\tcom.apple.HomeKit = {{
{indent}\t\tenabled = 1;
{indent}\t}};
{indent}}};"""

for pattern in patterns:
    match = re.search(pattern, text)
    if match:
        indent = match.group("indent")
        replacement = replacement_template.format(indent=indent)
        text = text[: match.start()] + replacement + text[match.end() :]
        path.write_text(text, encoding="utf-8")
        print("Fixed HomeKit SystemCapabilities in", path)
        break
else:
    valid = re.search(
        r"SystemCapabilities\s*=\s*\{[^}]*com\.apple\.HomeKit\s*=\s*\{[^}]*enabled\s*=\s*1;",
        text,
        re.S,
    )
    if valid:
        print("HomeKit SystemCapabilities already valid")
    else:
        raise SystemExit(
            "Could not find malformed or valid HomeKit SystemCapabilities. "
            "Inspect the generated project before updating this workaround."
        )
