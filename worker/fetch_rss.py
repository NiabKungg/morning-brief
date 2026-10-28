#!/usr/bin/env python3
"""fetch_rss.py — ดึงข่าวจาก RSS feeds ตาม sources.json แล้วเขียนเป็น JSON"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from common import load_config, safe_get, write_json


def clean(html: str, limit: int = 280) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def main(out_path: Path) -> int:
    cfg = load_config(out_path.parents[1])
    items = []
    ok = 0
    for feed in cfg["rss"]["feeds"]:
        try:
            r = safe_get(feed["url"])
            parsed = feedparser.parse(r.text)
            for e in parsed.entries[: cfg["rss"]["max_per_feed"]]:
                items.append({
                    "feed": feed["name"],
                    "lang": feed.get("lang", "en"),
                    "title": e.get("title", "")[:200],
                    "link": e.get("link", ""),
                    "published": e.get("published", ""),
                    "summary": clean(e.get("summary", "")),
                })
            ok += 1
            print(f"[rss] {feed['name']}: ok")
        except Exception as exc:  # แหล่งไหนพังข้ามไปแหล่งอื่น
            print(f"[rss] {feed['name']}: FAILED {exc}", file=sys.stderr)
    payload = {"source": "rss", "fetched_at": datetime.now(timezone.utc).isoformat(), "items": items}
    write_json(out_path, payload)
    print(f"[rss] total {len(items)} items from {ok}/{len(cfg['rss']['feeds'])} feeds")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
