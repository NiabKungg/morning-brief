#!/usr/bin/env python3
"""fetch_github.py — repo ที่สร้างใหม่ยอดดาวสูงสุดวันนี้ ผ่าน GitHub Search API"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import load_config, safe_get, write_json

API = "https://api.github.com/search/repositories"


def main(out_path: Path) -> int:
    cfg = load_config(out_path.parents[1])
    since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    url = (f"{API}?q=created:>{since}&sort=stars&order=desc"
           f"&per_page={cfg['github']['per_page']}")
    r = safe_get(url)
    data = r.json()
    items = [{
        "repo": it["full_name"],
        "stars": it["stargazers_count"],
        "lang": it.get("language") or "",
        "description": (it.get("description") or "")[:200],
        "url": it["html_url"],
    } for it in data.get("items", [])]
    payload = {"source": "github", "fetched_at": datetime.now(timezone.utc).isoformat(), "items": items}
    write_json(out_path, payload)
    print(f"[github] total {len(items)} repos")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
