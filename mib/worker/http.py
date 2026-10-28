"""Shared async HTTP client with a global concurrency cap, retries and a body-size guard (Pi 4 has 2 GB)."""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

USER_AGENT = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) MIB/1.0 (+morning-brief)"
MAX_BODY = 4 * 1024 * 1024


class FetchError(Exception):
    """Non-success HTTP status after retries."""


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    ms: int

    @property
    def is_html(self) -> bool:
        head = self.body[:300].lstrip().lower()
        return "html" in self.content_type or head.startswith((b"<!doctype html", b"<html"))

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


# Hosts that rate-limit unauthenticated clients hard: one request at a time, spaced out (seconds).
# Reddit's public RSS answers 429 to bursts from a home IP; overnight collects have time to spare.
_STRICT_HOSTS = {"www.reddit.com": 6.0, "reddit.com": 6.0, "api.coingecko.com": 1.0}


class Http:
    def __init__(self, concurrency: int) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._host_locks: dict[str, asyncio.Semaphore] = {}
        self._host_next: dict[str, float] = {}
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _host_gate(self, host: str) -> asyncio.Semaphore:
        if host not in self._host_locks:
            if len(self._host_locks) > 256:  # long-lived process: forget idle hosts so the maps stay small
                now = time.monotonic()
                for idle in [h for h, s in self._host_locks.items() if not s.locked() and self._host_next.get(h, 0) < now]:
                    del self._host_locks[idle]
                    self._host_next.pop(idle, None)
            self._host_locks[host] = asyncio.Semaphore(1 if host in _STRICT_HOSTS else 2)
        return self._host_locks[host]

    async def fetch(self, url: str, *, attempts: int = 3, max_body: int = MAX_BODY) -> Fetched:
        """GET with retries on transport errors, 429 (honouring Retry-After) and 5xx; at most two requests
        in flight per host (one, spaced, for strict hosts). Other statuses are returned as-is."""
        host = urlsplit(url).hostname or ""
        for attempt in range(attempts):
            last = attempt + 1 == attempts
            retry_after = None
            async with self._host_gate(host), self._sem:
                wait = self._host_next.get(host, 0) - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                started = time.monotonic()
                try:
                    async with self.client.stream("GET", url) as resp:
                        chunks, size = [], 0
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            if size > max_body:
                                break
                            chunks.append(chunk)
                        fetched = Fetched(
                            url=url,
                            final_url=str(resp.url),
                            status=resp.status_code,
                            content_type=resp.headers.get("content-type", "").lower(),
                            body=b"".join(chunks),
                            ms=int((time.monotonic() - started) * 1000),
                        )
                        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset")
                except httpx.HTTPError:
                    if last:
                        raise
                    fetched = None
                finally:
                    self._host_next[host] = time.monotonic() + _STRICT_HOSTS.get(host, 0.0)
            if fetched is not None and (last or not (fetched.status == 429 or fetched.status >= 500)):
                return fetched
            delay = (8.0 if host in _STRICT_HOSTS else 2.0) * (attempt + 1) + random.random()
            if retry_after and retry_after.replace(".", "", 1).isdigit():
                delay = min(float(retry_after), 30.0)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def get_ok(self, url: str, **kw) -> Fetched:
        fetched = await self.fetch(url, **kw)
        if fetched.status != 200:
            raise FetchError(f"HTTP {fetched.status}")
        return fetched

    async def get_json(self, url: str, **kw) -> object:
        return json.loads((await self.get_ok(url, **kw)).body)
