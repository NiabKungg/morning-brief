"""In-process fan-out of live events to SSE clients, with optional persistence for run replay."""

from __future__ import annotations

import asyncio

from mib.common.timeutil import iso
from mib.hub.db import DB

QUEUE_SIZE = 2000


class Bus:
    def __init__(self, db: DB) -> None:
        self._db = db
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        self._subs.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subs.discard(queue)

    def publish(self, event: dict, *, persist: bool = False) -> dict:
        event.setdefault("ts", iso())
        if persist and event.get("run_id"):
            self._db.add_event(event["run_id"], event["ts"], event["type"], event)
        for queue in list(self._subs):
            if queue.full():  # slow client: drop its oldest event rather than block everyone
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
        return event
