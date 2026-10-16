#!/usr/bin/env python3
"""Validate playlist structure and flag expired signed URL tokens.

This deliberately does not fetch streams: broadcaster URLs may be geo-restricted,
require player-specific headers, or block automated checks.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

EXPIRY_NAMES = {"exp", "expires", "expiry", "expiration"}
SIGNED_TOKEN_NAMES = {"hdnea", "hdnts"}
TOKEN_EXPIRY = re.compile(r"(?:^|[~&])exp=(\d{10,13})(?:$|[~&])", re.IGNORECASE)


def _parse_expiry(value: str) -> Optional[datetime]:
    if not value.isdigit() or len(value) not in (10, 13):
        return None
    timestamp = int(value)
    if len(value) == 13:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _signed_url_expiry(url: str) -> Optional[datetime]:
    try:
        query = urlsplit(url).query
    except ValueError:
        return None

    candidates: List[str] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        key = key.lower()
        if key in EXPIRY_NAMES:
            candidates.append(value)
        elif key in SIGNED_TOKEN_NAMES:
            candidates.extend(match.group(1) for match in TOKEN_EXPIRY.finditer(value))

    expiries = [expiry for value in candidates if (expiry := _parse_expiry(value))]
    return min(expiries) if expiries else None


def validate_playlist_text(
    path: str,
    content: str,
    now: Optional[datetime] = None,
    expiry_warning_days: int = 30,
) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    """Return (errors, warnings), each as (line number, message)."""
    errors: List[Tuple[int, str]] = []
    warnings: List[Tuple[int, str]] = []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    lines = [
        (number, raw.strip().lstrip("\ufeff") if number == 1 else raw.strip())
        for number, raw in enumerate(content.splitlines(), start=1)
        if raw.strip()
    ]
    if not lines:
        return [(1, "playlist is empty")], warnings

    header_number, header = lines[0]
    if not header.startswith("#EXTM3U"):
        errors.append((header_number, "playlist must start with #EXTM3U"))

    seen_header = False
    pending: Optional[Tuple[str, int]] = None
    entry_count = 0

    for number, line in lines:
        if line.startswith("#EXTM3U"):
            if seen_header:
                errors.append((number, "duplicate #EXTM3U header"))
            seen_header = True
            continue

        if line.startswith("#EXTINF"):
            if not line.startswith("#EXTINF:"):
                errors.append((number, "malformed #EXTINF tag"))
                continue
            if pending is not None:
                errors.append((pending[1], f"channel {pending[0]!r} has no stream URL"))
            payload = line[len("#EXTINF:"):]
            if "," not in payload:
                errors.append((number, "#EXTINF tag is missing its channel name"))
                pending = ("", number)
                continue
            _, title = payload.split(",", 1)
            title = title.strip()
            if not title:
                errors.append((number, "#EXTINF tag has an empty channel name"))
            pending = (title, number)
            entry_count += 1
            continue

        if line.startswith("#"):
            # Player directives such as #EXTVLCOPT may appear between EXTINF and URL.
            continue

        if pending is None:
            errors.append((number, "stream URL has no preceding #EXTINF tag"))
            continue

        try:
            parsed = urlsplit(line)
            valid_url = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            errors.append((number, "stream URL must be an absolute HTTP(S) URL"))
        else:
            expiry = _signed_url_expiry(line)
            if expiry is not None and expiry <= now + timedelta(days=expiry_warning_days):
                title = pending[0] or "unnamed channel"
                state = "expired at" if expiry <= now else "expires at"
                warnings.append(
                    (number, f"signed URL for {title!r} {state} {expiry.isoformat()}")
                )
        pending = None

    if pending is not None:
        errors.append((pending[1], f"channel {pending[0]!r} has no stream URL"))
    if entry_count == 0:
        errors.append((header_number, "playlist contains no #EXTINF channel entries"))

    return errors, warnings


def _annotation(kind: str, path: Path, line: int, message: str) -> str:
    safe_path = str(path).replace("%", "%25").replace(",", "%2C").replace(":", "%3A")
    safe_message = (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )
    return f"::{kind} file={safe_path},line={line}::{safe_message}"


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Validate M3U playlists and signed URL expirations.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="return a failing exit code when a signed URL is expired or expires within 30 days",
    )
    parser.add_argument("files", nargs="*", type=Path)
    parsed = parser.parse_args(args)
    files = parsed.files or sorted(Path(".").glob("*.m3u"))
    if not files:
        print("No M3U files found.")
        return 1

    error_count = 0
    warning_count = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(_annotation("error", path, 1, f"cannot read playlist: {exc}"))
            error_count += 1
            continue

        errors, warnings = validate_playlist_text(str(path), content)
        for line, message in errors:
            print(_annotation("error", path, line, message))
        for line, message in warnings:
            print(_annotation("warning", path, line, message))
        error_count += len(errors)
        warning_count += len(warnings)

    print(f"Checked {len(files)} playlist file(s): {error_count} error(s), {warning_count} expiry warning(s).")
    if error_count:
        return 1
    if warning_count:
        print("Expiry warnings need manual review; stream reachability is not tested.")
        if parsed.fail_on_warning:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
