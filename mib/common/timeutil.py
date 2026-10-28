"""Timestamps are stored as UTC ISO-8601 strings with an explicit offset (sortable as text)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_zone() -> ZoneInfo:
    """MIB_TZ, else the system zone (/etc/timezone or the /etc/localtime symlink), else UTC."""
    name = os.environ.get("MIB_TZ") or os.environ.get("TZ")
    if not name:
        tz_file = Path("/etc/timezone")
        if tz_file.exists():
            name = tz_file.read_text().strip()
    if not name:
        try:
            target = os.readlink("/etc/localtime")
            name = target.split("zoneinfo/", 1)[1]
        except (OSError, IndexError):
            name = "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
