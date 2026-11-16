#!/usr/bin/env python3
"""Validate Markdown links, images, and GitHub heading anchors in README.md."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
USER_AGENT = "OpenTalos-README-Link-Checker/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    readme = args.readme.resolve()
    text = readme.read_text(encoding="utf-8")
    targets = tuple(dict.fromkeys(LINK_PATTERN.findall(text)))
    anchors = {github_slug(heading) for heading in HEADING_PATTERN.findall(text)}
    failures: list[tuple[str, str]] = []
    checked: set[str] = set()

    for raw_target in targets:
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if target in checked or target.startswith(("mailto:", "tel:")):
            continue
        checked.add(target)
        if target.startswith("#"):
            if target[1:] not in anchors:
                failures.append((target, "missing heading anchor"))
            continue
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme in {"http", "https"}:
            if args.offline:
                continue
            status, error = check_url(target, args.timeout)
            print(f"{status:>3} {target}")
            if error:
                failures.append((target, error))
            continue
        if parsed.scheme:
            failures.append((target, f"unsupported URL scheme: {parsed.scheme}"))
            continue
        local_path = (readme.parent / urllib.parse.unquote(parsed.path)).resolve()
        if local_path.exists():
            print(f" OK {target}")
        else:
            print(f"404 {target}")
            failures.append((target, f"missing local path: {local_path}"))

    if failures:
        print("\nInvalid links:", file=sys.stderr)
        for target, reason in failures:
            print(f"- {target}: {reason}", file=sys.stderr)
        return 1
    print(f"\nAll {len(checked)} links are valid.")
    return 0


def check_url(url: str, timeout: float) -> tuple[int | str, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/octet-stream,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, None
    except urllib.error.HTTPError as error:
        return error.code, f"HTTP {error.code}"
    except urllib.error.URLError as error:
        return "ERR", str(error.reason)


def github_slug(value: str) -> str:
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[`*_~]", "", plain).strip().lower()
    plain = re.sub(r"[^\w\s-]", "", plain)
    return re.sub(r"\s", "-", plain)


if __name__ == "__main__":
    raise SystemExit(main())
