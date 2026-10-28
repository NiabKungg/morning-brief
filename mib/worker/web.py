"""Fetch a page (static first, Chromium when needed), extract the readable text and outgoing links."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import lxml.html
import trafilatura
from lxml import etree

from mib.common.text import canonical_url, clean_line, truncate
from mib.worker.http import USER_AGENT, Http
from mib.worker.render import Renderer

MIN_TEXT = 400
_SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".gz", ".mp4", ".mp3",
             ".mov", ".avi", ".dmg", ".exe", ".apk", ".css", ".js", ".xml", ".rss", ".ico", ".woff2")


@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int | None = None
    ms: int = 0
    rendered: bool = False
    title: str | None = None
    text: str = ""
    description: str = ""
    published: str | None = None
    author: str | None = None
    site: str | None = None
    links: list[str] = field(default_factory=list)
    error: str | None = None


def _links(doc, base: str) -> list[str]:
    doc.make_links_absolute(base, resolve_base_href=True)
    seen, links = set(), []
    for el, attr, link, _pos in doc.iterlinks():
        if el.tag != "a" or attr != "href":
            continue
        link = link.split("#", 1)[0]
        if not link.startswith(("http://", "https://")) or urlsplit(link).path.lower().endswith(_SKIP_EXT):
            continue
        key = canonical_url(link)
        if key and key not in seen:
            seen.add(key)
            links.append(link)
    return links


def extract(html: str, url: str, *, want_links: bool) -> dict:
    """trafilatura for the main text; lxml fallback for non-article pages; links for crawling."""
    out: dict = {"links": [], "text": "", "description": ""}
    raw = trafilatura.extract(html, url=url, output_format="json", with_metadata=True, favor_precision=True,
                              include_comments=False, include_tables=False)
    if raw:
        data = json.loads(raw)
        out.update(title=data.get("title"), text=data.get("text") or "", description=data.get("description") or "",
                   published=data.get("date"), author=data.get("author"), site=data.get("sitename"))
    try:
        doc = lxml.html.fromstring(html)
    except (etree.ParserError, ValueError):
        return out
    if want_links:
        out["links"] = _links(doc, url)
    if not out.get("title"):
        out["title"] = clean_line(" ".join(doc.xpath("//title//text()"))) or None
    if not out["description"]:
        meta = doc.xpath('//meta[@name="description" or @property="og:description"]/@content')
        out["description"] = clean_line(meta[0]) if meta else ""
    if len(out["text"]) < 200:
        for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//form"):
            bad.drop_tree()
        body = doc.xpath("//body")
        fallback = clean_line(body[0].text_content()) if body else ""
        if len(fallback) > len(out["text"]):
            out["text"] = fallback
    return out


class Robots:
    """robots.txt per host, cached for the lifetime of one job. Unreachable robots.txt = allowed."""

    def __init__(self, http: Http) -> None:
        self._http = http
        self._cache: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        async with self._locks.setdefault(host, asyncio.Lock()):
            if host not in self._cache:
                parser: RobotFileParser | None = None
                try:
                    fetched = await self._http.fetch(host + "/robots.txt", attempts=1, max_body=512 * 1024)
                    if fetched.status == 200:
                        parser = RobotFileParser()
                        parser.parse(fetched.text().splitlines())
                except Exception:
                    parser = None
                self._cache[host] = parser
        parser = self._cache[host]
        return parser is None or parser.can_fetch(USER_AGENT, url)


async def load(http: Http, renderer: Renderer, robots: Robots, url: str, *, render: str, want_links: bool) -> Page:
    """render: "never" (static only), "auto" (Chromium when static text is thin or bot-blocked), "always"."""
    page = Page(url=url)
    started = time.monotonic()
    try:
        if not await robots.allowed(url):
            page.error = "blocked by robots.txt"
            return page
        data = None
        if render != "always":
            fetched = await http.fetch(url)
            page.status, page.final_url = fetched.status, fetched.final_url
            if fetched.status >= 400:
                page.error = f"HTTP {fetched.status}"
            elif not fetched.is_html:
                page.error = f"not HTML ({fetched.content_type or 'unknown type'})"
            else:
                data = await asyncio.to_thread(extract, fetched.text(), fetched.final_url, want_links=want_links)
        thin = data is None or len(data["text"]) < MIN_TEXT
        blocked = page.status in (401, 403, 429)
        not_html = bool(page.error and page.error.startswith("not HTML"))
        if render == "always" or (render == "auto" and renderer.available and not not_html and (thin or blocked)):
            status, html, final_url = await renderer.render(url)
            page.status, page.final_url, page.rendered = status, final_url, True
            page.error = f"HTTP {status}" if status and status >= 400 else None
            rendered = await asyncio.to_thread(extract, html, final_url, want_links=want_links)
            if data is None or len(rendered["text"]) >= len(data["text"]):
                data = rendered
        if data:
            page.title = data.get("title")
            page.text = data["text"]
            page.description = data["description"]
            page.published = data.get("published")
            page.author = data.get("author")
            page.site = data.get("site")
            page.links = data["links"]
        if not page.error and not page.text:
            page.error = "no readable text"
    except Exception as exc:  # network, parser or browser failure: reported per page, never fatal
        page.error = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        page.ms = int((time.monotonic() - started) * 1000)
        page.final_url = page.final_url or url
    return page


def page_item(page: Page, *, depth: int) -> dict:
    host = urlsplit(page.final_url).netloc.removeprefix("www.")
    lead = page.description if len(page.description) > 80 else page.text
    return {
        "source": "web",
        "source_name": page.site or host,
        "kind": "page",
        "title": clean_line(page.title) or host,
        "url": page.final_url,
        "author": page.author,
        "published_at": page.published,
        "summary": truncate(lead, 700),
        "content": truncate(page.text, 12000),
        "metrics": {"depth": depth, "rendered": page.rendered, "chars": len(page.text), "status": page.status},
    }


def same_site(a: str, b: str) -> bool:
    return (urlsplit(a).hostname or "").removeprefix("www.") == (urlsplit(b).hostname or "").removeprefix("www.")
