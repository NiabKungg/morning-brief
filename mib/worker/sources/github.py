"""GitHub Trending (no official API): parse the server-rendered HTML."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import lxml.html

from mib.common.text import clean_line, truncate
from mib.worker.http import Http

_NUM_RE = re.compile(r"[\d,]+")
_COLOR_RE = re.compile(r"background-color:\s*(#[0-9a-fA-F]{3,8})")


def _num(text: str) -> int | None:
    match = _NUM_RE.search(text or "")
    return int(match.group(0).replace(",", "")) if match else None


def parse(html: str, *, since: str, language: str, limit: int) -> list[dict]:
    doc = lxml.html.fromstring(html)
    label = "GitHub Trending" + (f" · {language}" if language else "")
    items = []
    for rank, row in enumerate(doc.xpath('//article[contains(concat(" ", normalize-space(@class), " "), " Box-row ")]'), 1):
        anchors = row.xpath(".//h2//a[@href]")
        if not anchors:
            continue
        name = anchors[0].get("href").strip("/")
        if name.count("/") != 1:
            continue
        desc = clean_line(" ".join(row.xpath(".//p//text()")))
        lang = clean_line(" ".join(row.xpath('.//*[@itemprop="programmingLanguage"]//text()')))
        color_el = row.xpath('.//*[contains(@class, "repo-language-color")]/@style')
        color = _COLOR_RE.search(color_el[0]).group(1) if color_el and _COLOR_RE.search(color_el[0]) else None
        stars = _num(" ".join(row.xpath('.//a[contains(@href, "/stargazers")]//text()')))
        forks = _num(" ".join(row.xpath('.//a[contains(@href, "/forks")]//text()')))
        today_text = " ".join(row.xpath('.//*[contains(@class, "float-sm-right")]//text()'))
        items.append(
            {
                "source": "github",
                "source_name": label,
                "kind": "repo",
                "title": name,
                "url": f"https://github.com/{name}",
                "author": name.split("/")[0],
                "published_at": None,
                "summary": truncate(desc, 600),
                "content": None,
                "metrics": {
                    "rank": rank,
                    "stars": stars,
                    "forks": forks,
                    "stars_today": _num(today_text),
                    "period": since,
                    "language": lang or None,
                    "language_color": color,
                },
            }
        )
        if len(items) >= limit:
            break
    return items


async def fetch(http: Http, *, language: str, since: str, limit: int) -> list[dict]:
    path = f"/{quote(language.lower())}" if language else ""
    fetched = await http.get_ok(f"https://github.com/trending{path}?since={since}")
    return await asyncio.to_thread(parse, fetched.text(), since=since, language=language, limit=limit)
