#!/usr/bin/env python3
"""fetch_reddit.py — โพสต์ยอดนิยมของวันจาก subreddit ที่ติดตาม (public JSON)"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import load_config, safe_get, write_json


def fetch_sub(sub: str, limit: int) -> list:
    url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={limit}"
    r = safe_get(url)
    data = r.json()
    posts = data.get("data", {}).get("children", [])
    out = []
    for p in posts:
        d = p.get("data", {})
        out.append({
            "sub": sub,
            "title": d.get("title", "")[:200],
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "link": "https://www.reddit.com" + d.get("permalink", ""),
            "external_url": d.get("url_overridden_by_dest", "") or d.get("url", ""),
        })
    return out


def main(out_path: Path) -> int:
    cfg = load_config(out_path)
    items = []
    for sub in cfg["reddit"]["subs"]:
        try:
            items.extend(fetch_sub(sub, cfg["reddit"]["limit"]))
            print(f"[reddit] r/{sub}: ok")
        except Exception as exc:
            print(f"[reddit] r/{sub}: FAILED {exc}", file=sys.stderr)
    payload = {"source": "reddit", "fetched_at": datetime.now(timezone.utc).isoformat(), "items": items}
    write_json(out_path, payload)
    print(f"[reddit] total {len(items)} posts")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
