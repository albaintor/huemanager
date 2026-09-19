#!/usr/bin/env python3
"""Fetch exact Philips Hue APKs from APKBog without persisting signed CDN URLs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
import urllib.request

PAGE = "https://yota-devices-yotaphone.apkbog.com/en/apk/philips-hue/{version}"
EXPECTED = {
    "5.56.0": {"size": 83300110, "md5": "759de34d3b65541269edbdafae9ee4ad"},
    "5.57.0": {"size": 80512214, "md5": "41441ddf6e19be41d29c4dcd30135fa0"},
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def resolve_download(version: str) -> str:
    page_url = PAGE.format(version=version)
    body = _get(page_url).decode("utf-8", errors="replace")
    candidates = re.findall(r'href=["\']([^"\']*?/go/\?[^"\']+)["\']', body, flags=re.I)
    for candidate in candidates:
        go_url = urljoin(page_url, html.unescape(candidate))
        wrapped = parse_qs(urlparse(go_url).query).get("b")
        if not wrapped:
            continue
        raw = wrapped[0] + "=" * (-len(wrapped[0]) % 4)
        try:
            decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.startswith("https://") and f"Hue-{version}.apk" in decoded:
            return decoded
    raise RuntimeError(f"Could not resolve APKBog download URL for Hue {version}")


def download(version: str, destination: Path) -> None:
    expected = EXPECTED[version]
    url = resolve_download(version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": PAGE.format(version=version)},
    )
    digest = hashlib.md5()
    size = 0
    with urllib.request.urlopen(req, timeout=120) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)

    md5 = digest.hexdigest()
    print(f"Hue {version}: {size} bytes md5={md5}")
    if size != expected["size"]:
        raise RuntimeError(f"Size mismatch for {version}: {size} != {expected['size']}")
    if md5 != expected["md5"]:
        raise RuntimeError(f"MD5 mismatch for {version}: {md5} != {expected['md5']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=sorted(EXPECTED))
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    download(args.version, args.destination)


if __name__ == "__main__":
    main()
