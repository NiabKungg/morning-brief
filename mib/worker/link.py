"""The worker's side of the hub connection.

All frames go through one lock so ordering is preserved (items before their patches before job.done).
Reliable frames are persisted first and replayed in order after every reconnect until the hub acks them;
the hub treats replays idempotently.
"""

from __future__ import annotations

import asyncio
import logging

from websockets.exceptions import ConnectionClosed

from mib.common.protocol import dumps, new_id
from mib.worker.outbox import Store

log = logging.getLogger(__name__)


class Link:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._ws = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def attach(self, ws) -> None:
        async with self._lock:
            self._ws = ws
            pending = self._store.pending()
            if pending:
                log.info("replaying %d unacknowledged messages", len(pending))
            for payload in pending:
                if not await self._raw_send(payload):
                    return

    def detach(self) -> None:
        self._ws = None

    def ack(self, msg_id: str) -> None:
        self._store.ack(msg_id)

    async def _raw_send(self, payload: str) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(payload)
            return True
        except ConnectionClosed:
            self._ws = None
            return False

    async def send(self, msg: dict) -> None:
        """Best effort: dropped while disconnected (events, heartbeats)."""
        async with self._lock:
            await self._raw_send(dumps(msg))

    async def send_reliable(self, msg: dict) -> None:
        async with self._lock:
            msg["msg_id"] = new_id()
            payload = self._store.put(msg)
            await self._raw_send(payload)
