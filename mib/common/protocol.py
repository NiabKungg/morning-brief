"""Hub <-> worker WebSocket protocol.

Every frame is a JSON object with a ``type``. The worker connects to ``/ws/worker`` with
``Authorization: Bearer <token>``.

worker -> hub
  hello       {worker_id, version, host, model, render}
  heartbeat   {sys}
  job.event   {job_id, run_id, event: {...}}            best effort (UI only)
  job.items   {msg_id, job_id, run_id, items: [ITEM]}   reliable (outbox, acked)
  job.patch   {msg_id, job_id, run_id, patches: [...]}  reliable
  job.done    {msg_id, job_id, run_id, ok, stats, error} reliable

hub -> worker
  welcome     {version}
  job.start   {job_id, run_id, kind: "collect"|"crawl", spec}
  job.cancel  {job_id}
  ack         {msg_id}

ITEM (raw, as produced by a source)
  {fingerprint, source, source_name, kind, title, url, author, published_at,
   summary, content, metrics}

job.event payloads (``event``)
  {kind: "step",   step: "collect"|"enrich"|"crawl", status, detail, progress: [done, total]|null}
  {kind: "source", key, group, name, status: "running"|"done"|"error", count, ms, error}
  {kind: "page",   url, status, ms, chars, rendered, title, depth, error, purpose: "enrich"|"crawl"}
  {kind: "log",    level, msg}
"""

from __future__ import annotations

import json
import uuid
from typing import Any

PROTOCOL_VERSION = 1

RELIABLE_TYPES = frozenset({"job.items", "job.patch", "job.done"})


def dumps(msg: dict[str, Any]) -> str:
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(raw: str | bytes) -> dict[str, Any]:
    msg = json.loads(raw)
    if not isinstance(msg, dict) or "type" not in msg:
        raise ValueError("frame must be a JSON object with a 'type'")
    return msg


def new_id() -> str:
    return uuid.uuid4().hex
