from __future__ import annotations

import asyncio
import calendar as _calendar
from datetime import datetime, timezone

import feedparser

from mib.common.text import clean_line, html_to_text, truncate
from mib.worker.http import Http

_EMPTY_SUMMARIES = {"comments", "article url comments url"}


def entry_time(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(_calendar.timegm(value), tz=timezone.utc).isoformat(timespec="seconds")
    return None


def entry_html(entry) -> str:
    candidates = [entry.get("summary") or ""]
    candidates += [c.get("value", "") for c in entry.get("content") or []]
    return max(candidates, key=len)


def parse(body: bytes, *, name: str, limit: int) -> list[dict]:
    parsed = feedparser.parse(body)
    items = []
    for entry in parsed.entries[:limit]:
        title = clean_line(entry.get("title"))
        link = entry.get("link")
        if not title or not link:
            continue
        summary = html_to_text(entry_html(entry))
        if summary.strip().lower() in _EMPTY_SUMMARIES:
            summary = ""
        metrics = {}
        if entry.get("comments"):
            metrics["comments_url"] = entry["comments"]
        items.append(
            {
                "source": "rss",
                "source_name": name,
                "kind": "article",
                "title": title,
                "url": link,
                "author": clean_line(entry.get("author")) or None,
                "published_at": entry_time(entry),
                "summary": truncate(summary, 1200),
                "content": None,
                "metrics": metrics,
            }
        )
    return items


async def fetch(http: Http, *, url: str, name: str, limit: int) -> list[dict]:
    fetched = await http.get_ok(url)
    return await asyncio.to_thread(parse, fetched.body, name=name, limit=limit)
