"""SQLite storage (WAL). One connection, used from the event-loop thread; every query is small."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

from mib.common.text import canonical_url
from mib.common.timeutil import iso, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    steps TEXT NOT NULL DEFAULT '[]',
    stats TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    brief_id INTEGER
);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_events_run ON run_events(run_id, id);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    canonical_url TEXT,
    author TEXT,
    published_at TEXT,
    summary TEXT NOT NULL DEFAULT '',
    content TEXT,
    metrics TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    first_run_id INTEGER,
    last_run_id INTEGER,
    triage_score INTEGER,
    triage_keep INTEGER,
    triage_category TEXT,
    triage_reason TEXT,
    triage_at TEXT
);
CREATE INDEX IF NOT EXISTS items_first_seen ON items(first_seen_at);
CREATE INDEX IF NOT EXISTS items_last_run ON items(last_run_id);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind);

CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    date TEXT NOT NULL,
    language TEXT NOT NULL,
    headline TEXT NOT NULL,
    doc TEXT NOT NULL,
    markdown TEXT NOT NULL,
    telegram TEXT NOT NULL,
    stats TEXT NOT NULL DEFAULT '{}',
    delivered_at TEXT,
    delivery TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS briefs_created ON briefs(created_at);
"""

_JSON_RUN = ("params", "steps", "stats")
_ITEM_COLS = ("id", "fingerprint", "source", "source_name", "kind", "title", "url", "author", "published_at",
              "summary", "metrics", "first_seen_at", "last_seen_at", "triage_score", "triage_keep",
              "triage_category", "triage_reason")


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class DB:
    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "foreign_keys=ON", "busy_timeout=5000"):
            self.conn.execute(f"PRAGMA {pragma}")
        self.conn.executescript(SCHEMA)
        # A hub restart cannot resume an in-flight run.
        self.conn.execute("UPDATE runs SET status='failed', error='hub restarted', finished_at=? "
                          "WHERE status IN ('queued','running')", (iso(),))

    # ---- settings -----------------------------------------------------------------------------
    def get_setting(self, key: str) -> Any:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _j(value)))

    # ---- runs ---------------------------------------------------------------------------------
    def create_run(self, kind: str, trigger: str, params: dict, steps: list[dict]) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(kind, trigger, status, created_at, params, steps) VALUES(?,?,?,?,?,?)",
            (kind, trigger, "queued", iso(), _j(params), _j(steps)))
        return int(cur.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        values = [_j(v) if k in _JSON_RUN else v for k, v in fields.items()]
        self.conn.execute(f"UPDATE runs SET {cols} WHERE id=?", (*values, run_id))

    @staticmethod
    def _run(row: sqlite3.Row) -> dict:
        run = dict(row)
        for key in _JSON_RUN:
            run[key] = json.loads(run[key])
        return run

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._run(row) if row else None

    def list_runs(self, limit: int) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return [self._run(r) for r in rows]

    def last_run(self, kind: str, trigger: str | None = None, since: str | None = None) -> dict | None:
        sql, args = "SELECT * FROM runs WHERE kind=?", [kind]
        if trigger:
            sql, args = sql + " AND trigger=?", [*args, trigger]
        if since:
            sql, args = sql + " AND created_at>=?", [*args, since]
        row = self.conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
        return self._run(row) if row else None

    def add_event(self, run_id: int, ts: str, type_: str, data: dict) -> None:
        self.conn.execute("INSERT INTO run_events(run_id, ts, type, data) VALUES(?,?,?,?)",
                          (run_id, ts, type_, _j(data)))

    def run_events(self, run_id: int, limit: int = 5000) -> list[dict]:
        rows = self.conn.execute("SELECT data FROM run_events WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit))
        return [json.loads(r["data"]) for r in rows]

    def prune(self, days: int = 30) -> None:
        cutoff = iso(utcnow() - timedelta(days=days))
        self.conn.execute("DELETE FROM runs WHERE created_at < ?", (cutoff,))
        self.conn.execute("DELETE FROM items WHERE last_seen_at < ?", (cutoff,))

    # ---- items --------------------------------------------------------------------------------
    def upsert_items(self, items: Iterable[dict], run_id: int | None) -> list[tuple[dict, bool]]:
        """Insert or refresh raw items. Returns (api_item, is_new) per input item."""
        now = iso()
        out = []
        with self.conn:
            for it in items:
                fp = it["fingerprint"]
                row = self.conn.execute("SELECT id FROM items WHERE fingerprint=?", (fp,)).fetchone()
                metrics = _j(it.get("metrics") or {})
                if row:
                    self.conn.execute(
                        """UPDATE items SET source_name=?, title=?, url=COALESCE(?, url), author=COALESCE(?, author),
                           published_at=COALESCE(published_at, ?),
                           summary=CASE WHEN length(?) > length(summary) THEN ? ELSE summary END,
                           content=COALESCE(?, content), metrics=?, last_seen_at=?, last_run_id=? WHERE id=?""",
                        (it["source_name"], it["title"], it.get("url"), it.get("author"), it.get("published_at"),
                         it.get("summary") or "", it.get("summary") or "", it.get("content"), metrics, now, run_id,
                         row["id"]))
                    item_id, is_new = row["id"], False
                else:
                    cur = self.conn.execute(
                        """INSERT INTO items(fingerprint, source, source_name, kind, title, url, canonical_url, author,
                           published_at, summary, content, metrics, first_seen_at, last_seen_at, first_run_id,
                           last_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (fp, it["source"], it["source_name"], it["kind"], it["title"], it.get("url"),
                         canonical_url(it.get("url")), it.get("author"), it.get("published_at"),
                         it.get("summary") or "", it.get("content"), metrics, now, now, run_id, run_id))
                    item_id, is_new = int(cur.lastrowid), True
                out.append(({"id": item_id, "source": it["source"], "source_name": it["source_name"],
                             "kind": it["kind"], "title": it["title"], "url": it.get("url"),
                             "metrics": it.get("metrics") or {}}, is_new))
        return out

    def apply_patch(self, fingerprint: str, summary: str | None, content: str | None) -> None:
        self.conn.execute(
            """UPDATE items SET summary=CASE WHEN length(COALESCE(?, '')) > length(summary) THEN ? ELSE summary END,
               content=COALESCE(?, content) WHERE fingerprint=?""",
            (summary, summary, content, fingerprint))

    @staticmethod
    def _item(row: sqlite3.Row, *, with_content: bool = False) -> dict:
        item = {k: row[k] for k in _ITEM_COLS if k in row.keys()}
        item["metrics"] = json.loads(item.get("metrics") or "{}")
        score = item.pop("triage_score", None)
        keep = item.pop("triage_keep", None)
        category = item.pop("triage_category", None)
        reason = item.pop("triage_reason", None)
        item["triage"] = None if keep is None else {"score": score, "keep": bool(keep), "category": category,
                                                   "reason": reason}
        if with_content:
            item["content"] = row["content"]
        return item

    def items_for_brief(self, since: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM items WHERE first_seen_at >= ? AND kind IN ('article','post','repo') "
            "ORDER BY first_seen_at DESC", (since,))
        return [self._item(r, with_content=True) for r in rows]

    def items_for_run(self, run_id: int, source: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM items WHERE last_run_id=?", [run_id]
        if source:
            sql, args = sql + " AND source=?", [*args, source]
        return [self._item(r, with_content=True) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def latest_of_kind(self, kind: str, since: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM items WHERE kind=? AND last_seen_at >= ? ORDER BY id", (kind, since))
        return [self._item(r) for r in rows]

    def set_triage(self, item_id: int, *, score: int | None, keep: bool, category: str | None, reason: str) -> None:
        self.conn.execute("UPDATE items SET triage_score=?, triage_keep=?, triage_category=?, triage_reason=?, "
                          "triage_at=? WHERE id=?", (score, int(keep), category, reason, iso(), item_id))

    def list_items(self, *, since: str | None, source: str | None, status: str, q: str | None, limit: int,
                   run_id: int | None) -> tuple[list[dict], int]:
        where, args = [], []
        if since:
            where.append("last_seen_at >= ?")
            args.append(since)
        if source:
            where.append("source = ?")
            args.append(source)
        if run_id:
            where.append("last_run_id = ?")
            args.append(run_id)
        if status == "kept":
            where.append("triage_keep = 1")
        elif status == "dropped":
            where.append("triage_keep = 0")
        elif status == "untriaged":
            where.append("triage_keep IS NULL")
        if q:
            where.append("(title LIKE ? OR summary LIKE ? OR source_name LIKE ?)")
            args += [f"%{q}%"] * 3
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.conn.execute(f"SELECT COUNT(*) FROM items{clause}", args).fetchone()[0]
        rows = self.conn.execute(f"SELECT * FROM items{clause} ORDER BY last_seen_at DESC, id DESC LIMIT ?",
                                 (*args, limit))
        return [self._item(r) for r in rows], int(total)

    def count_items(self, since: str | None = None) -> int:
        if since:
            return int(self.conn.execute("SELECT COUNT(*) FROM items WHERE first_seen_at >= ?", (since,)).fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    # ---- briefs -------------------------------------------------------------------------------
    def create_brief(self, *, run_id: int | None, kind: str, date: str, language: str, headline: str, doc: dict,
                     markdown: str, telegram: list[str], stats: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO briefs(run_id, kind, created_at, date, language, headline, doc, markdown, telegram, stats) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, kind, iso(), date, language, headline, _j(doc), markdown, _j(telegram), _j(stats)))
        return int(cur.lastrowid)

    @staticmethod
    def _brief(row: sqlite3.Row, *, full: bool) -> dict:
        brief = {k: row[k] for k in ("id", "kind", "created_at", "date", "language", "headline", "delivered_at")}
        brief["delivery"] = json.loads(row["delivery"])
        brief["stats"] = json.loads(row["stats"])
        brief["run_id"] = row["run_id"]
        if full:
            brief["doc"] = json.loads(row["doc"])
            brief["markdown"] = row["markdown"]
            brief["telegram_html"] = json.loads(row["telegram"])
        return brief

    def get_brief(self, brief_id: int, *, full: bool = True) -> dict | None:
        row = self.conn.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
        return self._brief(row, full=full) if row else None

    def list_briefs(self, limit: int, kind: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM briefs", []
        if kind:
            sql, args = sql + " WHERE kind=?", [kind]
        rows = self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        return [self._brief(r, full=False) for r in rows]

    def last_delivered_daily(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM briefs WHERE kind='daily' AND delivered_at IS NOT NULL "
                                "ORDER BY id DESC LIMIT 1").fetchone()
        return self._brief(row, full=False) if row else None

    def set_delivery(self, brief_id: int, delivery: dict, delivered_at: str | None) -> None:
        self.conn.execute("UPDATE briefs SET delivery=?, delivered_at=COALESCE(?, delivered_at) WHERE id=?",
                          (_j(delivery), delivered_at, brief_id))

    def count_briefs(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0])
