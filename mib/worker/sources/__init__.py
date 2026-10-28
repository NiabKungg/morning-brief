"""Source registry: turns the hub's ``sources`` settings into independent fetch tasks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Awaitable, Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from mib.worker.http import Http
from mib.worker.sources import calendar, github, markets, reddit, rss


@dataclass(frozen=True)
class SourceTask:
    key: str
    group: str
    name: str
    fetch: Callable[[Http], Awaitable[list[dict]]]


def build_tasks(spec: dict, tz: ZoneInfo) -> list[SourceTask]:
    tasks: list[SourceTask] = []

    cfg = spec.get("rss") or {}
    if cfg.get("enabled"):
        for feed in cfg.get("feeds", []):
            if feed.get("enabled", True) and feed.get("url"):
                name = feed.get("name") or urlsplit(feed["url"]).netloc
                tasks.append(SourceTask(f"rss:{name}", "rss", name,
                                        partial(rss.fetch, url=feed["url"], name=name, limit=int(cfg.get("per_feed", 12)))))

    cfg = spec.get("github") or {}
    if cfg.get("enabled"):
        for lang in cfg.get("languages") or [""]:
            name = "GitHub Trending" + (f" · {lang}" if lang else "")
            tasks.append(SourceTask(f"github:{lang or 'all'}", "github", name,
                                    partial(github.fetch, language=lang, since=cfg.get("since", "daily"),
                                            limit=int(cfg.get("limit", 12)))))

    cfg = spec.get("reddit") or {}
    if cfg.get("enabled"):
        for sub in cfg.get("subreddits", []):
            sub = sub.strip().removeprefix("r/").strip("/")
            if sub:
                tasks.append(SourceTask(f"reddit:{sub}", "reddit", f"r/{sub}",
                                        partial(reddit.fetch_subreddit, sub=sub, period=cfg.get("period", "day"),
                                                limit=int(cfg.get("per_sub", 8)))))
        for url in cfg.get("threads", []):
            if url.strip():
                tasks.append(SourceTask(f"reddit-thread:{url}", "reddit", reddit.thread_label(url),
                                        partial(reddit.fetch_thread, url=url.strip())))

    cfg = spec.get("markets") or {}
    if cfg.get("enabled") and (cfg.get("crypto") or cfg.get("symbols")):
        tasks.append(SourceTask("markets", "markets", "Markets",
                                partial(markets.fetch, crypto=cfg.get("crypto", []), symbols=cfg.get("symbols", []))))

    cfg = spec.get("calendar") or {}
    if cfg.get("enabled"):
        for i, url in enumerate(cfg.get("ics_urls", []), 1):
            name = "Calendar" if len(cfg.get("ics_urls", [])) == 1 else f"Calendar {i}"
            tasks.append(SourceTask(f"calendar:{i}", "calendar", name,
                                    partial(calendar.fetch, url=url, tz=tz, days=int(cfg.get("days", 1)))))
    return tasks
