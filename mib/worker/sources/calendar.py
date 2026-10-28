"""Google Calendar through its secret iCal address (Settings → Integrate calendar → Secret address in iCal format)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from mib.common.text import clean_line, truncate
from mib.worker.http import Http


def _iso(value, tz: ZoneInfo) -> tuple[str, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(tz).isoformat(timespec="minutes"), False
    if isinstance(value, date):
        return value.isoformat(), True
    return str(value), False


def parse(body: bytes, *, tz: ZoneInfo, days: int) -> list[dict]:
    cal = icalendar.Calendar.from_ical(body)
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=max(1, days))
    items = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        begin, all_day = _iso(ev.decoded("DTSTART"), tz)
        finish = _iso(ev.decoded("DTEND"), tz)[0] if ev.get("DTEND") else None
        title = clean_line(str(ev.get("SUMMARY", ""))) or "(untitled event)"
        items.append(
            {
                "source": "calendar",
                "source_name": "Calendar",
                "kind": "event",
                "title": title,
                "url": None,
                "author": None,
                "published_at": None,
                "summary": truncate(clean_line(str(ev.get("DESCRIPTION", ""))), 400),
                "content": None,
                "metrics": {
                    "uid": str(ev.get("UID", "")),
                    "start": begin,
                    "end": finish,
                    "all_day": all_day,
                    "location": clean_line(str(ev.get("LOCATION", ""))) or None,
                },
            }
        )
    items.sort(key=lambda it: (not it["metrics"]["all_day"], it["metrics"]["start"]))
    return items


async def fetch(http: Http, *, url: str, tz: ZoneInfo, days: int) -> list[dict]:
    fetched = await http.get_ok(url)
    return await asyncio.to_thread(parse, fetched.body, tz=tz, days=days)
