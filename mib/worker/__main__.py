"""python -m mib.worker — connect to the hub and execute crawl jobs until stopped."""

from __future__ import annotations

import asyncio
import logging
import signal

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from mib import __version__
from mib.common.protocol import dumps, loads
from mib.common.sysinfo import SysSampler, board_model, hostname
from mib.worker.config import WorkerConfig, load
from mib.worker.jobs import JobRunner
from mib.worker.link import Link
from mib.worker.outbox import Store

log = logging.getLogger("mib.worker")
HEARTBEAT_S = 5


async def heartbeat(link: Link, runner: JobRunner, sampler: SysSampler) -> None:
    while True:
        await link.send({"type": "heartbeat", "sys": sampler.sample(), "busy": runner.busy})
        await asyncio.sleep(HEARTBEAT_S)


async def session(cfg: WorkerConfig, link: Link, runner: JobRunner, sampler: SysSampler) -> None:
    async with connect(cfg.hub_ws, additional_headers={"Authorization": f"Bearer {cfg.token}"},
                       open_timeout=15, ping_interval=20, ping_timeout=30, close_timeout=5,
                       max_size=8 * 1024 * 1024) as ws:
        log.info("connected to %s", cfg.hub_ws)
        await ws.send(dumps({
            "type": "hello", "worker_id": cfg.worker_id, "version": __version__, "host": hostname(),
            "model": board_model(), "render": runner.renderer.available, "busy": runner.busy,
        }))
        await link.attach(ws)
        beat = asyncio.create_task(heartbeat(link, runner, sampler))
        try:
            async for raw in ws:
                msg = loads(raw)
                kind = msg["type"]
                if kind == "ack":
                    link.ack(msg["msg_id"])
                elif kind == "job.start":
                    await runner.start(msg)
                elif kind == "job.cancel":
                    runner.cancel(msg["job_id"])
        finally:
            beat.cancel()
            link.detach()


async def amain() -> None:
    cfg = load()
    store = Store(cfg.data_dir / "worker.sqlite3")
    link = Link(store)
    runner = JobRunner(cfg, link, store)
    sampler = SysSampler()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def forever() -> None:
        backoff = 1
        while True:
            try:
                await session(cfg, link, runner, sampler)
                backoff = 1
            except InvalidStatus as exc:
                log.error("hub rejected the connection: HTTP %s", exc.response.status_code)
                backoff = 30
            except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
                log.warning("hub connection lost: %s", exc)
            except Exception:  # never let the reconnect loop die silently (e.g. outbox I/O error, bad frame)
                log.exception("hub session crashed; reconnecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    conn = asyncio.create_task(forever())
    log.info("worker %s (render=%s) starting", cfg.worker_id, runner.renderer.available)
    await stop.wait()
    conn.cancel()
    await runner.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(amain())


if __name__ == "__main__":
    main()
