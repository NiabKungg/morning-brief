"""Reddit via its public RSS/Atom feeds (the unauthenticated JSON API answers 403)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

import feedparser

from mib.common.text import clean_line, html_to_text, truncate
from mib.worker.http import Http
from mib.worker.sources.rss import entry_html, entry_time

_LINK_RE = re.compile(r'<a href="([^"]+)">\s*\[link\]\s*</a>')
_MD_RE = re.compile(r'<div class="md">(.*?)</div>', re.S)


def _external_link(html: str) -> str | None:
    match = _LINK_RE.search(html)
    if not match:
        return None
    url = match.group(1).replace("&amp;", "&")
    host = urlsplit(url).netloc.lower()
    return None if host.endswith(("reddit.com", "redd.it")) else url


def parse_posts(body: bytes, *, sub: str, limit: int) -> list[dict]:
    items = []
    for entry in feedparser.parse(body).entries[:limit]:
        html = entry_html(entry)
        md = _MD_RE.search(html)
        selftext = html_to_text(md.group(1)) if md else ""
        title = clean_line(entry.get("title"))
        if not title or not entry.get("link"):
            continue
        metrics = {"subreddit": sub}
        link = _external_link(html)
        if link:
            metrics["link"] = link
        items.append(
            {
                "source": "reddit",
                "source_name": f"r/{sub}",
                "kind": "post",
                "title": title,
                "url": entry["link"],
                "author": clean_line(entry.get("author")).removeprefix("/u/") or None,
                "published_at": entry_time(entry),
                "summary": truncate(selftext, 1200),
                "content": None,
                "metrics": metrics,
            }
        )
    return items


async def fetch_subreddit(http: Http, *, sub: str, period: str, limit: int) -> list[dict]:
    fetched = await http.get_ok(f"https://www.reddit.com/r/{sub}/top/.rss?t={period}&limit={limit}")
    return await asyncio.to_thread(parse_posts, fetched.body, sub=sub, limit=limit)


def thread_label(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    slug = parts[4] if len(parts) > 4 else (parts[-1] if parts else url)
    return "Thread: " + slug.replace("_", " ")[:40]


def parse_thread(body: bytes, *, url: str) -> list[dict]:
    feed = feedparser.parse(body)
    if not feed.entries:
        return []
    post, comments = feed.entries[0], feed.entries[1:9]
    lines = []
    for c in comments:
        text = truncate(html_to_text(entry_html(c)), 280)
        if text:
            lines.append(f"{clean_line(c.get('author')).removeprefix('/u/')}: {text}")
    sub = next((p for p in urlsplit(url).path.split("/") if p and p != "r"), "reddit")
    return [
        {
            "source": "reddit",
            "source_name": thread_label(url),
            "kind": "post",
            "title": clean_line(feed.feed.get("title")) or clean_line(post.get("title")),
            "url": url,
            "author": None,
            "published_at": entry_time(comments[0]) if comments else entry_time(post),
            "summary": truncate("Latest comments:\n" + "\n".join(lines), 1600) if lines else "",
            "content": None,
            "metrics": {"subreddit": sub, "thread": True, "comments_seen": len(comments)},
        }
    ]


async def fetch_thread(http: Http, *, url: str) -> list[dict]:
    fetched = await http.get_ok(url.rstrip("/") + "/.rss?sort=new&limit=10")
    return await asyncio.to_thread(parse_thread, fetched.body, url=url)
