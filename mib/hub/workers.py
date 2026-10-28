"""Worker connections (Pi 4) and job dispatch over the WebSocket protocol in mib.common.protocol."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from mib import __version__
from mib.common.protocol import RELIABLE_TYPES, new_id
from mib.common.timeutil import iso
from mib.hub.bus import Bus
from mib.hub.db import DB

log = logging.getLogger(__name__)


class NoWorker(RuntimeError):
    pass


@dataclass
class WorkerConn:
    id: str
    ws: WebSocket | None
    host: str
    model: str
    version: str
    render: bool
    connected_at: str | None
    last_seen: str | None
    sys: dict | None = None
    busy: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def online(self) -> bool:
        return self.ws is not None

    def to_api(self) -> dict:
        return {"id": self.id, "online": self.online, "host": self.host, "model": self.model,
                "version": self.version, "connected_at": self.connected_at, "last_seen": self.last_seen,
                "render": self.render, "sys": self.sys, "busy": self.busy}

    async def send(self, msg: dict) -> None:
        if self.ws is None:
            raise NoWorker(f"worker {self.id} is offline")
        async with self.send_lock:
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))


Handler = Callable[..., Awaitable[None]]


@dataclass
class Job:
    id: str
    run_id: int
    kind: str
    worker_id: str
    done: asyncio.Future
    on_event: Handler | None = None
    on_items: Handler | None = None
    on_patch: Handler | None = None


class WorkerHub:
    def __init__(self, db: DB, bus: Bus) -> None:
        self._db = db
        self._bus = bus
        self.workers: dict[str, WorkerConn] = {}
        self.jobs: dict[str, Job] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()

    def snapshot(self) -> list[dict]:
        return [w.to_api() for w in self.workers.values()]

    def _publish(self, worker: WorkerConn) -> None:
        self._bus.publish({"type": "worker", "worker": worker.to_api()})

    async def serve(self, ws: WebSocket) -> None:
        """Owns one authenticated worker connection until it closes."""
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        if hello.get("type") != "hello" or not hello.get("worker_id"):
            await ws.close(code=4400)
            return
        wid = str(hello["worker_id"])
        previous = self.workers.get(wid)
        if previous and previous.ws is not None:
            try:
                await previous.ws.close(code=4409)
            except RuntimeError:
                pass
        worker = WorkerConn(id=wid, ws=ws, host=hello.get("host", wid), model=hello.get("model", ""),
                            version=hello.get("version", "?"), render=bool(hello.get("render")),
                            connected_at=iso(), last_seen=iso(), sys=previous.sys if previous else None,
                            busy=bool(hello.get("busy")))
        self.workers[wid] = worker
        await worker.send({"type": "welcome", "version": __version__})
        log.info("worker %s connected (%s)", wid, worker.model)
        self._publish(worker)
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                worker.last_seen = iso()
                await self._handle(worker, msg)
        except WebSocketDisconnect:
            pass
        finally:
            if self.workers.get(wid) is worker:
                worker.ws = None
                worker.busy = False
                self._publish(worker)
            log.info("worker %s disconnected", wid)

    async def _handle(self, worker: WorkerConn, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "heartbeat":
            worker.sys, worker.busy = msg.get("sys"), bool(msg.get("busy"))
            self._publish(worker)
            return
        job = self.jobs.get(msg.get("job_id", ""))
        if kind == "job.event":
            if job and job.on_event:
                await job.on_event(msg.get("event") or {})
            return
        if kind not in RELIABLE_TYPES:
            log.debug("ignoring %s from %s", kind, worker.id)
            return
        msg_id = msg.get("msg_id")
        if msg_id and msg_id not in self._seen:
            await self._reliable(job, msg)  # raises -> no ack, not marked seen: the worker replays it
            self._seen[msg_id] = None
            while len(self._seen) > 5000:
                self._seen.popitem(last=False)
        if msg_id:
            await worker.send({"type": "ack", "msg_id": msg_id})

    async def _reliable(self, job: Job | None, msg: dict) -> None:
        kind = msg["type"]
        if kind == "job.items":
            if job and job.on_items:
                await job.on_items(msg.get("items") or [])
            else:  # job no longer tracked (e.g. hub restarted): keep the data anyway
                self._db.upsert_items(msg.get("items") or [], msg.get("run_id"))
        elif kind == "job.patch":
            for patch in msg.get("patches") or []:
                self._db.apply_patch(patch["fingerprint"], patch.get("summary"), patch.get("content"))
            if job and job.on_patch:
                await job.on_patch(msg.get("patches") or [])
        elif kind == "job.done" and job and not job.done.done():
            job.done.set_result(msg)

    def pick(self) -> WorkerConn:
        online = [w for w in self.workers.values() if w.online]
        if not online:
            raise NoWorker("no worker is online — is mib-worker running on the Pi 4?")
        idle = [w for w in online if not w.busy]
        return (idle or online)[0]

    async def dispatch(self, run_id: int, kind: str, spec: dict, **handlers: Handler) -> Job:
        worker = self.pick()
        job = Job(id=new_id(), run_id=run_id, kind=kind, worker_id=worker.id,
                  done=asyncio.get_running_loop().create_future(), **handlers)
        self.jobs[job.id] = job
        await worker.send({"type": "job.start", "job_id": job.id, "run_id": run_id, "kind": kind, "spec": spec})
        return job

    async def cancel(self, job: Job) -> None:
        worker = self.workers.get(job.worker_id)
        if worker and worker.online:
            await worker.send({"type": "job.cancel", "job_id": job.id})

    def release(self, job: Job) -> None:
        self.jobs.pop(job.id, None)
