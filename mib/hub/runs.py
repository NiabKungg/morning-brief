"""Run orchestration. One run at a time (the Pi 5 has one LLM slot, the Pi 4 one crawler);
every step change is published live over SSE and persisted for replay."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import timedelta

from mib.common.timeutil import iso, parse_iso, utcnow
from mib.hub import delivery
from mib.hub.bus import Bus
from mib.hub.config import HubConfig
from mib.hub.db import DB
from mib.hub.llm import LLM
from mib.hub.pipeline import dedupe, render, synth, triage
from mib.hub.settings import Settings
from mib.hub.workers import NoWorker, WorkerHub

log = logging.getLogger(__name__)

STEP_LABELS = {"collect": "Collect", "enrich": "Enrich", "dedupe": "Dedupe", "triage": "Triage",
               "synthesize": "Synthesize", "deliver": "Deliver", "crawl": "Crawl", "summarize": "Summarize"}
KIND_STEPS = {
    "pipeline": ["collect", "enrich", "dedupe", "triage", "synthesize", "deliver"],
    "collect": ["collect", "enrich", "dedupe", "triage"],
    "brief": ["dedupe", "triage", "synthesize", "deliver"],
    "web": ["crawl", "summarize"],
}
JOB_TIMEOUT_S = 20 * 60
TOKEN_FLUSH_S = 0.08


class Busy(RuntimeError):
    pass


class StepFailed(RuntimeError):
    pass


class Run:
    def __init__(self, mgr: "RunManager", row: dict) -> None:
        self._mgr = mgr
        self.id: int = row["id"]
        self.kind: str = row["kind"]
        self.trigger: str = row["trigger"]
        self.params: dict = row["params"]
        self.status: str = row["status"]
        self.created_at: str = row["created_at"]
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.steps: list[dict] = row["steps"]
        self.stats: dict = {}
        self.error: str | None = None
        self.brief_id: int | None = None
        self.job = None
        self._persisted = 0.0

    def to_api(self) -> dict:
        return {"id": self.id, "kind": self.kind, "trigger": self.trigger, "status": self.status,
                "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
                "params": self.params, "steps": self.steps, "stats": self.stats, "error": self.error,
                "brief_id": self.brief_id}

    def publish(self, *, persist: bool = True) -> None:
        if persist or time.monotonic() - self._persisted > 2:
            self._mgr.db.update_run(self.id, status=self.status, started_at=self.started_at,
                                    finished_at=self.finished_at, steps=self.steps, stats=self.stats,
                                    error=self.error, brief_id=self.brief_id)
            self._persisted = time.monotonic()
        self._mgr.bus.publish({"type": "run", "run": self.to_api()})

    def step(self, key: str, status: str | None = None, detail: str | None = None,
             progress: list[int] | None = None) -> None:
        step = next((s for s in self.steps if s["key"] == key), None)
        if step is None:
            return
        changed = bool(status) and status != step["status"]
        if status:
            if status == "active" and not step["started_at"]:
                step["started_at"] = iso()
            if status in ("done", "error", "skipped") and not step["finished_at"]:
                step["finished_at"] = iso()
            step["status"] = status
        if detail is not None:
            step["detail"] = detail
        if progress is not None:
            step["progress"] = progress
        self.publish(persist=changed)

    def emit(self, event: dict, *, persist: bool = False) -> None:
        event["run_id"] = self.id
        self._mgr.bus.publish(event, persist=persist)

    def log(self, msg: str, level: str = "info", origin: str = "hub") -> None:
        self.emit({"type": "log", "level": level, "origin": origin, "msg": msg}, persist=True)


class _TokenPump:
    """Coalesces streamed tokens into ~12 SSE events per second."""

    def __init__(self, run: Run, phase: str) -> None:
        self._run, self._phase = run, phase
        self._buf: list[str] = []
        self._last = time.monotonic()

    async def push(self, piece: str) -> None:
        self._buf.append(piece)
        if time.monotonic() - self._last >= TOKEN_FLUSH_S:
            self.flush()

    def flush(self) -> None:
        if self._buf:
            self._run.emit({"type": "llm", "phase": self._phase, "event": "token", "text": "".join(self._buf)})
            self._buf.clear()
        self._last = time.monotonic()


def _validate_params(kind: str, params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    if kind in ("pipeline", "brief"):
        out = {"deliver": bool(params.get("deliver", True))}
        if params.get("deliver_at"):
            out["deliver_at"] = str(params["deliver_at"])
        channels = params.get("channels")
        if channels:
            seen = []
            for c in channels:
                if c in ("telegram", "discord") and c not in seen:
                    seen.append(c)
            if seen:
                out["channels"] = seen
        return out
    if kind == "web":
        raw = params.get("urls") or []
        urls = [str(u).strip() for u in (raw.replace(",", "\n").split() if isinstance(raw, str) else raw) if str(u).strip()]
        urls = [u if u.startswith(("http://", "https://")) else f"https://{u}" for u in urls][:5]
        if not urls:
            raise ValueError("give at least one URL to crawl")
        render = params.get("render", "auto")
        if render not in ("auto", "always", "never"):
            raise ValueError("render must be auto, always or never")
        return {"urls": urls, "depth": max(0, min(int(params.get("depth", 0)), 2)),
                "max_pages": max(1, min(int(params.get("max_pages", 6)), 20)), "render": render}
    return {}


class RunManager:
    def __init__(self, *, cfg: HubConfig, db: DB, bus: Bus, settings: Settings, workers: WorkerHub, llm: LLM) -> None:
        self.cfg, self.db, self.bus, self.settings, self.workers, self.llm = cfg, db, bus, settings, workers, llm
        self.active: Run | None = None
        self._task: asyncio.Task | None = None

    # ---- lifecycle --------------------------------------------------------------------------------
    async def start(self, kind: str, params: dict | None = None, trigger: str = "manual") -> Run:
        if kind not in KIND_STEPS:
            raise ValueError(f"unknown run kind {kind!r}")
        if self.active:
            raise Busy(f"run #{self.active.id} ({self.active.kind}) is still in progress")
        params = _validate_params(kind, params or {})
        steps = [{"key": k, "label": STEP_LABELS[k], "status": "pending", "detail": None, "progress": None,
                  "started_at": None, "finished_at": None} for k in KIND_STEPS[kind]]
        run = Run(self, self.db.get_run(self.db.create_run(kind, trigger, params, steps)))
        self.active = run
        self._task = asyncio.create_task(self._execute(run))
        return run

    async def cancel(self, run_id: int) -> bool:
        run = self.active
        if not run or run.id != run_id or not self._task:
            return False
        if run.job:
            try:
                await self.workers.cancel(run.job)
            except Exception:
                log.warning("could not forward cancel to the worker", exc_info=True)
        self._task.cancel()
        return True

    async def _execute(self, run: Run) -> None:
        run.status, run.started_at = "running", iso()
        run.publish()
        run.log(f"{run.kind} run started ({run.trigger})")
        started = time.monotonic()
        try:
            if run.kind in ("collect", "pipeline"):
                await self._collect(run)
            if run.kind == "collect":
                await self._dedupe_and_triage(run)
            elif run.kind in ("pipeline", "brief"):
                await self._brief(run)
            elif run.kind == "web":
                await self._web(run)
            run.status = "done"
        except asyncio.CancelledError:
            run.status, run.error = "cancelled", "cancelled"
        except (StepFailed, NoWorker) as exc:
            run.status, run.error = "failed", str(exc)
        except Exception as exc:
            log.exception("run %s failed", run.id)
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            for step in run.steps:
                if step["status"] == "active":
                    step["status"] = "done" if run.status == "done" else "error"
                    step["finished_at"] = iso()
                elif step["status"] == "pending":
                    step["status"] = "skipped"
            run.finished_at = iso()
            run.stats["duration_s"] = round(time.monotonic() - started, 1)
            self.active = None
            self._task = None
            run.log(f"run {run.status}" + (f": {run.error}" if run.error else "") + f" in {run.stats['duration_s']}s",
                    "info" if run.status == "done" else "error")
            run.publish()

    # ---- helpers ----------------------------------------------------------------------------------
    def _completer(self, run: Run, phase: str, label: str):
        async def complete(messages: list[dict], *, grammar: str | None = None, max_tokens: int = 1024):
            run.emit({"type": "llm", "phase": phase, "label": label, "event": "start"})
            pump = _TokenPump(run, phase)
            try:
                completion = await self.llm.complete(messages, grammar=grammar, max_tokens=max_tokens, phase=phase,
                                                     on_text=pump.push)
            finally:
                pump.flush()
            run.emit({"type": "llm", "phase": phase, "label": label, "event": "end", "stats": completion.stats},
                     persist=True)
            if completion.finish_reason == "length":
                run.log(f"{label}: output reached the {max_tokens}-token limit", "warn", "llm")
            return completion
        return complete

    async def _worker_job(self, run: Run, kind: str, spec: dict) -> dict:
        new_by_key: Counter = Counter()

        async def on_items(items: list[dict]) -> None:
            fresh = 0
            for (lite, is_new), raw in zip(self.db.upsert_items(items, run.id), items):
                fresh += is_new
                new_by_key[raw.get("source_key")] += is_new
                run.emit({"type": "item", "new": is_new, "item": lite})
            run.stats["items"] = run.stats.get("items", 0) + len(items)
            run.stats["new_items"] = run.stats.get("new_items", 0) + fresh

        async def on_event(ev: dict) -> None:
            kind_ = ev.get("kind")
            if kind_ == "step":
                run.step(ev.get("step", ""), ev.get("status"), ev.get("detail"), ev.get("progress"))
            elif kind_ == "source":
                final = ev.get("status") != "running"
                run.emit({"type": "source", "key": ev.get("key"), "group": ev.get("group"), "name": ev.get("name"),
                          "status": ev.get("status"), "count": ev.get("count", 0), "new": new_by_key[ev.get("key")],
                          "ms": ev.get("ms"), "error": ev.get("error")}, persist=final)
            elif kind_ == "page":
                run.emit({"type": "page", **{k: ev.get(k) for k in ("url", "status", "ms", "chars", "rendered",
                                                                     "title", "depth", "error", "purpose")}},
                         persist=True)
            elif kind_ == "log":
                run.log(str(ev.get("msg", "")), ev.get("level", "info"), "worker")

        first = KIND_STEPS[run.kind][0]
        run.step(first, "active", "dispatching to the worker…")
        job = await self.workers.dispatch(run.id, kind, spec, on_event=on_event, on_items=on_items)
        run.job = job
        run.log(f"{kind} job sent to worker {job.worker_id}")
        try:
            done = await asyncio.wait_for(job.done, timeout=JOB_TIMEOUT_S)
        except asyncio.TimeoutError:
            await self.workers.cancel(job)
            raise StepFailed(f"worker did not finish within {JOB_TIMEOUT_S // 60} minutes") from None
        finally:
            self.workers.release(job)
            run.job = None
        if not done.get("ok"):
            raise StepFailed(done.get("error") or "worker job failed")
        return done.get("stats") or {}

    # ---- stages -----------------------------------------------------------------------------------
    async def _collect(self, run: Run) -> None:
        s = self.settings.data
        spec = {"sources": s["sources"], "enrich_limit": s["pipeline"]["enrich_limit"], "tz": self.cfg.tz.key}
        run.stats["collect"] = await self._worker_job(run, "collect", spec)

    async def _dedupe_and_triage(self, run: Run) -> tuple[list[dict], dict]:
        s = self.settings.data
        hours = s["pipeline"]["window_hours"]
        threshold = s["pipeline"]["triage_threshold"]
        items = self.db.items_for_brief(iso(utcnow() - timedelta(hours=hours)))
        news = [it for it in items if it["kind"] != "repo"]
        run.step("dedupe", "active", f"{len(news)} stories from the last {hours}h")
        result = dedupe.dedupe(news)
        drops = []
        for item, reason in result.dropped:
            if (item.get("triage") or {}).get("reason") != reason:
                self.db.set_triage(item["id"], score=None, keep=False, category=None, reason=reason)
            item["triage"] = {"score": None, "keep": False, "category": None, "reason": reason}
            drops.append({"item_id": item["id"], "score": None, "keep": False, "category": None, "reason": reason})
        if drops:
            run.emit({"type": "triage", "results": drops}, persist=True)
        rules = sum(1 for _, r in result.dropped if r.startswith("rule"))
        run.step("dedupe", "done", f"{len(news)} → {len(result.candidates)} unique · {rules} junk by rules · "
                                   f"{len(result.dropped) - rules} duplicates")
        run.stats["candidates"] = len(result.candidates)

        todo = [c for c in result.candidates if (c.get("triage") or {}).get("reason") not in ("llm", "llm:junk")]
        if not todo:
            run.step("triage", "skipped", "nothing new to triage — every story was scored earlier")
            return result.candidates, result.coverage
        batches = [todo[i:i + triage.BATCH] for i in range(0, len(todo), triage.BATCH)]
        by_id = {it["id"]: it for it in todo}
        done = kept = 0
        run.step("triage", "active", f"0/{len(todo)} stories", [0, len(todo)])
        interests = s["profile"]["interests"]
        for n, batch in enumerate(batches, 1):
            label = f"Triage batch {n}/{len(batches)}"
            results = await triage.triage(batch, result.coverage, interests,
                                          complete=self._completer(run, "triage", label))
            rows = []
            for r in results:
                keep, reason = triage.verdict(r, threshold)
                kept += keep
                self.db.set_triage(r["item_id"], score=r["score"], keep=keep, category=r["category"], reason=reason)
                by_id[r["item_id"]]["triage"] = {"score": r["score"], "keep": keep, "category": r["category"],
                                                 "reason": reason}
                rows.append({"item_id": r["item_id"], "score": r["score"], "keep": keep, "category": r["category"],
                             "reason": reason, "why": r["why"]})
            run.emit({"type": "triage", "results": rows}, persist=True)
            done += len(batch)
            run.step("triage", "active", f"{done}/{len(todo)} stories · {kept} kept", [done, len(todo)])
        run.step("triage", "done", f"{kept}/{len(todo)} new stories kept (score ≥ {threshold})")
        run.stats["kept"] = kept
        return result.candidates, result.coverage

    async def _brief(self, run: Run) -> None:
        s = self.settings.data
        candidates, coverage = await self._dedupe_and_triage(run)
        chosen = triage.select(candidates, coverage, threshold=s["pipeline"]["triage_threshold"],
                               limit=s["pipeline"]["max_brief_items"])
        if not chosen:
            raise StepFailed("no stories to write about — run a collect first")
        since = iso(utcnow() - timedelta(hours=s["pipeline"]["window_hours"]))
        repos = sorted((it for it in self.db.items_for_brief(since) if it["kind"] == "repo"),
                       key=lambda r: (r["metrics"].get("stars_today") or 0), reverse=True)[:5]
        recent = iso(utcnow() - timedelta(hours=12))
        quotes = self.db.latest_of_kind("quote", recent) if s["sources"]["markets"]["enabled"] else None
        events = None
        deliver_at = parse_iso(run.params.get("deliver_at"))
        now_local = (deliver_at or utcnow()).astimezone(self.cfg.tz)
        if s["sources"]["calendar"]["enabled"]:
            today = now_local.date().isoformat()
            events = [e for e in self.db.latest_of_kind("event", recent) if (e["metrics"].get("start") or "")[:10] == today]
        language = s["profile"]["language"]
        label = render.date_label(now_local, language)
        sources = chosen + repos
        groups = synth.numbered_groups(sources, dedupe.related(sources))
        connections = []
        for n, group in enumerate(groups, 1):
            run.step("synthesize", "active", f"checking possible connection {n}/{len(groups)}…")
            found = await synth.find_connection(group, sources, s["profile"],
                                                complete=self._completer(run, "connect", f"Connection check {n}/{len(groups)}"))
            if found:
                connections.append(found)
        run.step("synthesize", "active", f"LFM3 is writing from {len(chosen)} stories and {len(repos)} repos…")
        out, stats = await synth.write_brief(sources=sources, quotes=quotes or [], events=events,
                                             profile=s["profile"], date_label=label, tz=self.cfg.tz.key,
                                             complete=self._completer(run, "synth", "Writing brief"))
        out["connections"] = connections
        doc = render.build_doc(out, kind="daily", sources=sources, repos=repos, quotes=quotes, events=events,
                               language=language, now=now_local)
        brief_stats = {"items_considered": run.stats.get("candidates", 0), "items_kept": run.stats.get("kept", 0),
                       "items_used": len(doc["sources"]), "gen_tps": stats.get("gen_tps"),
                       "duration_s": round(stats.get("ms", 0) / 1000, 1)}
        run.brief_id = self.db.create_brief(run_id=run.id, kind="daily", date=now_local.date().isoformat(),
                                            language=language, headline=doc["headline"], doc=doc,
                                            markdown=render.to_markdown(doc, language),
                                            telegram=render.to_telegram(doc, language), stats=brief_stats)
        run.emit({"type": "brief", "brief": self.db.get_brief(run.brief_id, full=False)})
        run.step("synthesize", "done", f"{len(doc['sources'])} sources cited · {stats.get('gen_tps')} tok/s")
        await self._deliver_step(run)

    async def _deliver_step(self, run: Run) -> None:
        if not run.params.get("deliver", True):
            run.step("deliver", "skipped", "delivery is off for this run")
            return
        if not (self.settings.telegram_ready or self.settings.discord_ready):
            run.step("deliver", "skipped", "no channel configured — add a Telegram bot in Settings")
            return
        deliver_at = parse_iso(run.params.get("deliver_at"))
        if deliver_at and deliver_at > utcnow():
            run.step("deliver", "active", f"holding until {deliver_at.astimezone(self.cfg.tz):%H:%M}")
            await asyncio.sleep((deliver_at - utcnow()).total_seconds())
        run.step("deliver", "active", "sending…")
        results = await self.deliver_brief(run.brief_id, channels=run.params.get("channels"))
        ok = any(r["ok"] for r in results)
        run.step("deliver", "done" if ok else "error",
                 " · ".join(f"{r['channel']}: {'sent' if r['ok'] else r['error']}" for r in results))
        if not ok:
            raise StepFailed("delivery failed")

    async def deliver_brief(self, brief_id: int, channels: list[str] | None = None) -> list[dict]:
        brief = self.db.get_brief(brief_id)
        if brief is None:
            raise KeyError(brief_id)
        results = await delivery.deliver(self.settings.data, telegram_html=brief["telegram_html"],
                                         markdown=brief["markdown"], channels=channels)
        state = {**brief["delivery"], **{r["channel"]: {"ok": r["ok"], "error": r["error"], "at": r["at"]}
                                         for r in results}}
        self.db.set_delivery(brief_id, state, iso() if any(r["ok"] for r in results) else None)
        public = [{"channel": r["channel"], "ok": r["ok"], "error": r["error"]} for r in results]
        self.bus.publish({"type": "delivery", "brief_id": brief_id, "results": public})
        return public

    async def _web(self, run: Run) -> None:
        stats = await self._worker_job(run, "crawl", dict(run.params))
        run.stats["crawl"] = stats
        pages = self.db.items_for_run(run.id, source="web")
        if not pages:
            raise StepFailed("no readable pages were crawled")
        pages = sorted(pages, key=lambda p: len(p.get("content") or ""), reverse=True)[:8]
        pages.sort(key=lambda p: p["id"])
        s = self.settings.data
        language = s["profile"]["language"]
        now_local = utcnow().astimezone(self.cfg.tz)
        run.step("summarize", "active", f"LFM3 is reading {len(pages)} pages…")
        out, llm_stats = await synth.write_web_digest(pages=pages, profile=s["profile"],
                                                      complete=self._completer(run, "web", "Web digest"))
        doc = render.build_doc(out, kind="web", sources=pages, repos=[], quotes=None, events=None,
                               language=language, now=now_local)
        run.brief_id = self.db.create_brief(
            run_id=run.id, kind="web", date=now_local.date().isoformat(), language=language,
            headline=doc["headline"], doc=doc, markdown=render.to_markdown(doc, language),
            telegram=render.to_telegram(doc, language),
            stats={"items_considered": stats.get("pages", 0), "items_kept": stats.get("extracted", 0),
                   "items_used": len(doc["sources"]), "gen_tps": llm_stats.get("gen_tps"),
                   "duration_s": round(llm_stats.get("ms", 0) / 1000, 1)})
        run.emit({"type": "brief", "brief": self.db.get_brief(run.brief_id, full=False)})
        run.step("summarize", "done", f"digest of {len(pages)} pages · {llm_stats.get('gen_tps')} tok/s")
