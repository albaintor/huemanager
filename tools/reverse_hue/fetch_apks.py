#!/usr/bin/env python3
"""Fetch the Philips Hue APKS bundle and verify its embedded base APK.

APK.Cafe exposes a stable download page but generates a short-lived CDN URL.
This resolver reads the current /go/?b=... link and decodes the signed target.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
import urllib.request
import zipfile

SPLITS = {
    "5.56.0": {
        "selector": "417659/3363490/philips-hue",
        "base_name": "Hue-5.56.0.apk",
        "base_size": 83300110,
        "base_md5": "759de34d3b65541269edbdafae9ee4ad",
        "bundle_size": 172840095,
    },
    "5.57.0": {
        "selector": "444517/3387201/philips-hue",
        "base_name": "Hue-5.57.0.apk",
        "base_size": 80512214,
        "base_md5": "41441ddf6e19be41d29c4dcd30135fa0",
        "bundle_size": 170117735,
    },
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36"


def request(url: str):
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def resolve_download(version: str) -> tuple[str, str]:
    selector = SPLITS[version]["selector"]
    page_url = f"https://apk.cafe/download?split={selector}"
    with urllib.request.urlopen(request(page_url), timeout=60) as response:
        body = response.read().decode("utf-8", errors="replace")

    candidates = re.findall(r'href=["\']([^"\']*(?:/go/\?)[^"\']+)["\']', body, flags=re.I)
    for candidate in candidates:
        go_url = urljoin(page_url, html.unescape(candidate))
        encoded = parse_qs(urlparse(go_url).query).get("b")
        if not encoded:
            continue
        raw = encoded[0] + "=" * (-len(encoded[0]) % 4)
        try:
            target = base64.urlsafe_b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if target.startswith("https://") and "/split/" in target and target.endswith(("premium_speed=0", "premium_speed=1")):
            return page_url, target

    raise RuntimeError(f"Could not resolve APKS download URL for Hue {version}")


def md5_stream(stream) -> tuple[int, str]:
    digest = hashlib.md5()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def verify_bundle(version: str, destination: Path) -> None:
    expected = SPLITS[version]
    if destination.stat().st_size != expected["bundle_size"]:
        raise RuntimeError(
            f"APKS size mismatch for {version}: "
            f"{destination.stat().st_size} != {expected['bundle_size']}"
        )

    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        print("Bundle members:")
        for name in names:
            print(f"  {name}")

        base_candidates = [
            name for name in names
            if Path(name).name == expected["base_name"]
        ]
        if len(base_candidates) != 1:
            raise RuntimeError(
                f"Expected exactly one {expected['base_name']} in bundle; got {base_candidates}"
            )

        split_candidates = [
            name for name in names
            if Path(name).name in {"config.arm64_v8a.apk", "config.arm64_v8a"}
        ]
        if len(split_candidates) != 1:
            raise RuntimeError(
                "Expected exactly one arm64 split; got "
                + repr(split_candidates)
            )

        with archive.open(base_candidates[0]) as stream:
            size, digest = md5_stream(stream)
        if size != expected["base_size"]:
            raise RuntimeError(
                f"Embedded base size mismatch for {version}: "
                f"{size} != {expected['base_size']}"
            )
        if digest != expected["base_md5"]:
            raise RuntimeError(
                f"Embedded base MD5 mismatch for {version}: "
                f"{digest} != {expected['base_md5']}"
            )
        print(
            f"Hue {version}: verified base {size} bytes md5={digest}; "
            f"arm64 split={split_candidates[0]}"
        )


def download(version: str, destination: Path) -> None:
    page_url, url = resolve_download(version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": page_url,
            "Accept": "application/zip,application/octet-stream,*/*",
        },
    )
    size = 0
    with urllib.request.urlopen(req, timeout=180) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    print(f"Downloaded Hue {version} APKS: {size} bytes")
    verify_bundle(version, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=sorted(SPLITS))
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    download(args.version, args.destination)


if __name__ == "__main__":
    main()
