"""Durable worker state: unacknowledged hub messages and a cache of already-enriched articles."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS enriched (
    fingerprint TEXT PRIMARY KEY,
    at REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self.prune()

    def put(self, msg: dict) -> str:
        payload = json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=str)
        self._db.execute("INSERT OR REPLACE INTO outbox (msg_id, payload, created_at) VALUES (?, ?, ?)",
                         (msg["msg_id"], payload, time.time()))
        return payload

    def ack(self, msg_id: str) -> None:
        self._db.execute("DELETE FROM outbox WHERE msg_id = ?", (msg_id,))

    def pending(self) -> list[str]:
        return [row[0] for row in self._db.execute("SELECT payload FROM outbox ORDER BY seq")]

    def recently_enriched(self, fingerprints: list[str], days: float = 3) -> set[str]:
        if not fingerprints:
            return set()
        cutoff = time.time() - days * 86400
        marks = ",".join("?" * len(fingerprints))
        rows = self._db.execute(f"SELECT fingerprint FROM enriched WHERE at > ? AND fingerprint IN ({marks})",
                                (cutoff, *fingerprints))
        return {row[0] for row in rows}

    def mark_enriched(self, fingerprint: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO enriched (fingerprint, at) VALUES (?, ?)", (fingerprint, time.time()))

    def prune(self) -> None:
        week = time.time() - 7 * 86400
        self._db.execute("DELETE FROM outbox WHERE created_at < ?", (week,))
        self._db.execute("DELETE FROM enriched WHERE at < ?", (week,))
