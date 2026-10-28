"""HTTP surface of the hub: REST + Server-Sent Events for the UI, WebSocket for the worker, static UI."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mib import __version__
from mib.common.sysinfo import SysSampler, board_model, hostname
from mib.common.timeutil import iso, utcnow
from mib.hub.bus import Bus
from mib.hub.config import load
from mib.hub.db import DB
from mib.hub.llm import LLM
from mib.hub.runs import Busy, RunManager
from mib.hub.scheduler import Scheduler, upcoming
from mib.hub.settings import Settings, SettingsError
from mib.hub.telegram import TelegramBot
from mib.hub.workers import NoWorker, WorkerHub

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
MONITOR_S = 5


def create_app() -> FastAPI:
    cfg = load()
    db = DB(cfg.data_dir / "mib.sqlite3")
    bus = Bus(db)
    settings = Settings(db)
    workers = WorkerHub(db, bus)
    llm = LLM(cfg.llm_url, cfg.llm_model)
    runs = RunManager(cfg=cfg, db=db, bus=bus, settings=settings, workers=workers, llm=llm)
    telegram_bot = TelegramBot(settings=settings, bus=bus, runs=runs)
    scheduler = Scheduler(runs, settings, db, cfg.tz)
    sampler = SysSampler()
    hub_info = {"host": hostname(), "model": board_model(), "version": __version__, "sys": sampler.sample()}

    async def monitor() -> None:
        while True:
            try:
                await llm.refresh()
                hub_info["sys"] = sampler.sample()
                bus.publish({"type": "hub", "sys": hub_info["sys"], "llm": llm.state()})
            except Exception:
                log.exception("monitor loop failed")
            await asyncio.sleep(MONITOR_S)

    async def housekeeping() -> None:
        while True:
            try:
                db.prune(days=30)
            except Exception:
                log.exception("housekeeping loop failed")
            await asyncio.sleep(6 * 3600)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        tasks = [asyncio.create_task(t) for t in (scheduler.run_forever(), monitor(), housekeeping(),
                                                   telegram_bot.run())]
        log.info("hub ready on %s:%s (tz %s, llm %s)", cfg.bind, cfg.port, cfg.tz.key, cfg.llm_url)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await telegram_bot.aclose()
            await llm.aclose()

    app = FastAPI(title="Morning Intelligence Brief", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")

    def schedule_view() -> dict:
        sch = settings.data["schedule"]
        return {"enabled": sch["enabled"], "collect_times": sch["collect_times"], "brief_time": sch["brief_time"],
                "next": upcoming(sch, cfg.tz)}

    def state() -> dict:
        latest = db.list_briefs(1)
        return {
            "now": iso(), "tz": cfg.tz.key, "hub": hub_info, "workers": workers.snapshot(), "llm": llm.state(),
            "delivery": {"telegram": settings.telegram_ready, "discord": settings.discord_ready},
            "telegram": telegram_bot.state(),
            "schedule": schedule_view(),
            "active_run": runs.active.to_api() if runs.active else None,
            "latest_brief": latest[0] if latest else None,
            "stats": {"items_24h": db.count_items(iso(utcnow() - timedelta(hours=24))), "items_total": db.count_items(),
                      "briefs": db.count_briefs()},
        }

    # ---- REST ---------------------------------------------------------------------------------------
    @app.get("/api/state")
    async def get_state() -> dict:
        return state()

    @app.get("/api/runs")
    async def list_runs(limit: int = Query(20, ge=1, le=200)) -> dict:
        listed = db.list_runs(limit)
        if runs.active:  # the live object is fresher than the throttled row
            listed = [runs.active.to_api() if r["id"] == runs.active.id else r for r in listed]
        return {"runs": listed}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: int) -> dict:
        run = runs.active.to_api() if runs.active and runs.active.id == run_id else db.get_run(run_id)
        if not run:
            raise HTTPException(404, "run not found")
        return {"run": run, "events": db.run_events(run_id)}

    @app.post("/api/runs", status_code=202)
    async def start_run(body: dict = Body(...)) -> dict:
        try:
            run = await runs.start(str(body.get("kind")), body.get("params") or {}, trigger="manual")
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        return {"run": run.to_api()}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: int) -> dict:
        if not await runs.cancel(run_id):
            raise HTTPException(409, "that run is not active")
        return {"ok": True}

    @app.get("/api/items")
    async def list_items(hours: int = Query(24, ge=0, le=24 * 30), source: str | None = None,
                         status: str = Query("all", pattern="^(all|kept|dropped|untriaged)$"),
                         q: str | None = Query(None, max_length=200), limit: int = Query(200, ge=1, le=1000),
                         run_id: int | None = None) -> dict:
        since = iso(utcnow() - timedelta(hours=hours)) if hours else None
        items, total = db.list_items(since=since, source=source or None, status=status, q=q, limit=limit,
                                     run_id=run_id)
        return {"items": items, "total": total}

    @app.get("/api/briefs")
    async def list_briefs(limit: int = Query(30, ge=1, le=200), kind: str | None = None) -> dict:
        return {"briefs": db.list_briefs(limit, kind or None)}

    @app.get("/api/briefs/{brief_id}")
    async def get_brief(brief_id: int) -> dict:
        brief = db.get_brief(brief_id)
        if not brief:
            raise HTTPException(404, "brief not found")
        return {"brief": brief}

    @app.post("/api/briefs/{brief_id}/deliver")
    async def deliver_brief(brief_id: int) -> dict:
        if not (settings.telegram_ready or settings.discord_ready):
            raise HTTPException(409, "no delivery channel configured")
        try:
            return {"results": await runs.deliver_brief(brief_id)}
        except KeyError:
            raise HTTPException(404, "brief not found") from None

    @app.get("/api/settings")
    async def get_settings() -> dict:
        return settings.public()

    @app.put("/api/settings")
    async def put_settings(patch: dict = Body(...)) -> dict:
        try:
            public = settings.update(patch)
        except SettingsError as exc:
            raise HTTPException(422, str(exc)) from None
        bus.publish({"type": "settings", "settings": public})
        telegram_bot.wake()  # token/chat edits take effect now, not after the current poll/backoff
        return public

    @app.post("/api/delivery/test")
    async def test_delivery() -> dict:
        from mib.hub import delivery

        if not (settings.telegram_ready or settings.discord_ready):
            raise HTTPException(409, "no delivery channel configured")
        text = "✅ <b>Morning Intelligence Brief</b> is connected. Your brief arrives daily at " \
               f"{settings.data['schedule']['brief_time']}."
        results = await delivery.deliver(settings.data, telegram_html=[text],
                                         markdown=f"Morning Intelligence Brief is connected. Daily brief at "
                                                  f"{settings.data['schedule']['brief_time']}.")
        return {"results": [{"channel": r["channel"], "ok": r["ok"], "error": r["error"]} for r in results]}

    # ---- live events --------------------------------------------------------------------------------
    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue = bus.subscribe()

        async def stream():
            try:
                yield _sse({"type": "snapshot", "state": state(), "ts": iso()})
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield _sse(event)
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- worker link --------------------------------------------------------------------------------
    @app.websocket("/ws/worker")
    async def worker_socket(ws: WebSocket) -> None:
        header = ws.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not token or not hmac.compare_digest(token.encode(), cfg.token.encode()):
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            await workers.serve(ws)
        except (asyncio.TimeoutError, json.JSONDecodeError, NoWorker) as exc:
            log.warning("worker connection dropped: %s", exc)

    # ---- UI -----------------------------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.exception_handler(NoWorker)
    async def no_worker(_request: Request, exc: NoWorker) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    return app


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"
