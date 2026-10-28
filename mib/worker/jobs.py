"""Job execution on the worker: ``collect`` (all enabled sources + article enrichment) and ``crawl`` (URLs)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from mib.common.text import canonical_url, fingerprint, truncate
from mib.worker.config import WorkerConfig
from mib.worker.http import Http
from mib.worker.link import Link
from mib.worker.outbox import Store
from mib.worker.render import Renderer
from mib.worker.sources import build_tasks
from mib.worker.web import Robots, load, page_item, same_site

log = logging.getLogger(__name__)

SOURCE_TIMEOUT_S = 150  # rate-limited hosts (Reddit) are spaced and retried, which can take a while
ENRICH_CONCURRENCY = 4
CRAWL_CONCURRENCY = 3
BATCH = 40


def _error_text(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return truncate(f"{type(exc).__name__}: {text}" if type(exc).__name__ not in text else text, 200)


class JobContext:
    def __init__(self, link: Link, job_id: str, run_id: int) -> None:
        self.link = link
        self.job_id = job_id
        self.run_id = run_id

    async def event(self, **event) -> None:
        await self.link.send({"type": "job.event", "job_id": self.job_id, "run_id": self.run_id, "event": event})

    async def step(self, step: str, status: str, detail: str | None = None, progress: list[int] | None = None) -> None:
        await self.event(kind="step", step=step, status=status, detail=detail, progress=progress)

    async def log(self, msg: str, level: str = "info") -> None:
        log.log(logging.WARNING if level != "info" else logging.INFO, msg)
        await self.event(kind="log", level=level, msg=msg)

    async def items(self, items: list[dict]) -> None:
        for i in range(0, len(items), BATCH):
            await self.link.send_reliable({"type": "job.items", "job_id": self.job_id, "run_id": self.run_id,
                                           "items": items[i:i + BATCH]})

    async def patches(self, patches: list[dict]) -> None:
        if patches:
            await self.link.send_reliable({"type": "job.patch", "job_id": self.job_id, "run_id": self.run_id,
                                           "patches": patches})

    async def done(self, ok: bool, stats: dict | None = None, error: str | None = None) -> None:
        await self.link.send_reliable({"type": "job.done", "job_id": self.job_id, "run_id": self.run_id,
                                       "ok": ok, "stats": stats or {}, "error": error})

    async def page(self, page, *, depth: int, purpose: str) -> None:
        await self.event(kind="page", url=page.final_url or page.url, status=page.status, ms=page.ms,
                         chars=len(page.text), rendered=page.rendered, title=page.title, depth=depth,
                         error=page.error, purpose=purpose)


async def run_collect(ctx: JobContext, spec: dict, *, http: Http, renderer: Renderer, store: Store) -> dict:
    tz = ZoneInfo(spec.get("tz") or "UTC")
    tasks = build_tasks(spec.get("sources") or {}, tz)
    total = len(tasks)
    await ctx.step("collect", "active", f"0/{total} sources", [0, total])
    collected: list[dict] = []
    done = ok = 0

    async def run_task(task) -> None:
        nonlocal done, ok
        await ctx.event(kind="source", key=task.key, group=task.group, name=task.name, status="running",
                        count=0, ms=None, error=None)
        started = time.monotonic()
        items: list[dict] = []
        error = None
        try:
            items = await asyncio.wait_for(task.fetch(http), timeout=SOURCE_TIMEOUT_S)
            for item in items:
                item["fingerprint"] = fingerprint(item)
                item["source_key"] = task.key
            await ctx.items(items)
            collected.extend(items)
            ok += 1
        except Exception as exc:
            error = _error_text(exc)
            await ctx.log(f"{task.name}: {error}", "warn")
        done += 1
        await ctx.event(kind="source", key=task.key, group=task.group, name=task.name,
                        status="error" if error else "done", count=len(items),
                        ms=int((time.monotonic() - started) * 1000), error=error)
        await ctx.step("collect", "active", f"{done}/{total} sources · {len(collected)} items", [done, total])

    await asyncio.gather(*(run_task(t) for t in tasks))
    await ctx.step("collect", "done" if ok or not total else "error",
                   f"{len(collected)} items from {ok}/{total} sources", [total, total])

    enriched = await enrich(ctx, collected, limit=int(spec.get("enrich_limit", 30)), http=http, renderer=renderer,
                            store=store)
    return {"sources": total, "sources_ok": ok, "items": len(collected), "enriched": enriched}


def _enrich_target(item: dict) -> str | None:
    """Article URL worth fetching for a richer summary (feeds often carry a title only)."""
    if item["kind"] not in ("article", "post") or len(item.get("summary") or "") >= 280:
        return None
    url = (item.get("metrics") or {}).get("link") or item.get("url")
    host = urlsplit(url or "").netloc
    if not url or host.endswith(("reddit.com", "news.ycombinator.com", "youtube.com", "x.com", "twitter.com")):
        return None
    return url


async def enrich(ctx: JobContext, items: list[dict], *, limit: int, http: Http, renderer: Renderer, store: Store) -> int:
    candidates = [(it, url) for it in items if (url := _enrich_target(it))]
    skip = store.recently_enriched([it["fingerprint"] for it, _ in candidates])
    candidates = [(it, url) for it, url in candidates if it["fingerprint"] not in skip]
    candidates.sort(key=lambda pair: pair[0].get("published_at") or "", reverse=True)
    candidates = candidates[:max(0, limit)]
    total = len(candidates)
    if not total:
        await ctx.step("enrich", "skipped", "nothing new to enrich")
        return 0
    await ctx.step("enrich", "active", f"0/{total} articles", [0, total])
    robots = Robots(http)
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
    done = good = 0

    async def one(item: dict, url: str) -> None:
        nonlocal done, good
        async with sem:
            page = await load(http, renderer, robots, url, render="never", want_links=False)
        await ctx.page(page, depth=0, purpose="enrich")
        if page.text and not page.error:
            good += 1
            lead = page.description if len(page.description) > 160 else page.text
            await ctx.patches([{"fingerprint": item["fingerprint"], "summary": truncate(lead, 900),
                                "content": truncate(page.text, 6000)}])
        store.mark_enriched(item["fingerprint"])
        done += 1
        await ctx.step("enrich", "active", f"{done}/{total} articles · {good} extracted", [done, total])

    await asyncio.gather(*(one(it, url) for it, url in candidates))
    await ctx.step("enrich", "done", f"{good}/{total} articles extracted", [total, total])
    return good


async def run_crawl(ctx: JobContext, spec: dict, *, http: Http, renderer: Renderer) -> dict:
    urls = [u.strip() for u in spec.get("urls", []) if u.strip().startswith(("http://", "https://"))]
    max_depth = max(0, min(int(spec.get("depth", 0)), 2))
    max_pages = max(1, min(int(spec.get("max_pages", 8)), 20))
    render = spec.get("render", "auto")
    if render in ("auto", "always") and not renderer.available:
        await ctx.log("headless Chromium unavailable; crawling without JavaScript rendering", "warn")
        render = "never"
    await ctx.step("crawl", "active", f"0/{max_pages} pages", [0, max_pages])
    robots = Robots(http)
    queue: deque[tuple[str, int]] = deque((u, 0) for u in urls)
    seen = {canonical_url(u) for u in urls}
    fetched = extracted = 0
    while queue and fetched < max_pages:
        batch = [queue.popleft() for _ in range(min(CRAWL_CONCURRENCY, len(queue), max_pages - fetched))]
        pages = await asyncio.gather(*(load(http, renderer, robots, url, render=render, want_links=depth < max_depth)
                                       for url, depth in batch))
        for (url, depth), page in zip(batch, pages):
            fetched += 1
            await ctx.page(page, depth=depth, purpose="crawl")
            if page.text and not page.error:
                extracted += 1
                item = page_item(page, depth=depth)
                item["fingerprint"] = fingerprint(item)
                await ctx.items([item])
            for link in page.links:
                key = canonical_url(link)
                if key not in seen and same_site(link, url):
                    seen.add(key)
                    queue.append((link, depth + 1))
        await ctx.step("crawl", "active", f"{fetched}/{max_pages} pages · {extracted} extracted", [fetched, max_pages])
    await ctx.step("crawl", "done" if extracted else "error", f"{extracted}/{fetched} pages extracted",
                   [fetched, fetched])
    return {"pages": fetched, "extracted": extracted, "rendered": render != "never"}


class JobRunner:
    """Executes one job at a time; a job survives hub disconnects (its output waits in the outbox)."""

    def __init__(self, cfg: WorkerConfig, link: Link, store: Store) -> None:
        self.link = link
        self.store = store
        self.http = Http(cfg.http_concurrency)
        self.renderer = Renderer(cfg.chromium)
        self._task: asyncio.Task | None = None
        self._job_id: str | None = None

    @property
    def busy(self) -> bool:
        return self._job_id is not None

    async def start(self, msg: dict) -> None:
        if self.busy:
            await JobContext(self.link, msg["job_id"], msg.get("run_id")).done(
                False, error=f"worker busy with job {self._job_id}")
            return
        self._job_id = msg["job_id"]
        self._task = asyncio.create_task(self._run(msg))

    def cancel(self, job_id: str) -> None:
        if self.busy and self._job_id == job_id:
            self._task.cancel()

    async def _run(self, msg: dict) -> None:
        ctx = JobContext(self.link, msg["job_id"], msg.get("run_id"))
        kind, spec = msg.get("kind"), msg.get("spec") or {}
        log.info("job %s (%s) started", ctx.job_id, kind)
        ok, stats, error = False, {}, None
        try:
            if kind == "collect":
                stats = await run_collect(ctx, spec, http=self.http, renderer=self.renderer, store=self.store)
            elif kind == "crawl":
                stats = await run_crawl(ctx, spec, http=self.http, renderer=self.renderer)
            else:
                raise ValueError(f"unknown job kind {kind!r}")
            ok = True
        except asyncio.CancelledError:
            error = "cancelled"
        except Exception as exc:
            log.exception("job %s failed", ctx.job_id)
            error = _error_text(exc)
        finally:
            # Free Chromium and the busy flag *before* reporting: the hub may dispatch the next job at once.
            await self.renderer.close()
            self._job_id = None
        await ctx.done(ok, stats, error)
        log.info("job %s finished (%s)", ctx.job_id, "ok" if ok else error)

    async def shutdown(self) -> None:
        if self.busy:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.http.aclose()
