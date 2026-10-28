"""Daily schedule: overnight collects, and the brief written ``prep_minutes`` ahead of ``brief_time``.

A brief missed while the hub was down is caught up if the hub is back within two hours of brief time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mib.common.timeutil import iso, utcnow
from mib.hub.db import DB
from mib.hub.runs import Busy, RunManager
from mib.hub.settings import Settings

log = logging.getLogger(__name__)
CATCH_UP = timedelta(hours=2)
BUSY_RETRY_S = 30
BUSY_GIVE_UP = timedelta(minutes=45)


def _at(day: datetime, hhmm: str, tz: ZoneInfo) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def plan(schedule: dict, tz: ZoneInfo, now: datetime, days: int = 2) -> list[tuple[datetime, str, datetime]]:
    """[(start_at, kind, deliver_at)] for today and the next day(s), sorted, in local time.

    For collects deliver_at == start_at. The brief starts prep_minutes before its delivery time.
    """
    local_now = now.astimezone(tz)
    out = []
    for offset in range(days):
        day = local_now + timedelta(days=offset)
        for hhmm in schedule["collect_times"]:
            at = _at(day, hhmm, tz)
            out.append((at, "collect", at))
        deliver = _at(day, schedule["brief_time"], tz)
        out.append((deliver - timedelta(minutes=schedule["prep_minutes"]), "brief", deliver))
    return sorted(out)


def upcoming(schedule: dict, tz: ZoneInfo, now: datetime | None = None) -> list[dict]:
    """Next occurrence of each job, for the UI (brief reported at its delivery time)."""
    now = now or utcnow()
    if not schedule["enabled"]:
        return []
    seen, out = set(), []
    for start, kind, deliver in plan(schedule, tz, now):
        if start > now and kind not in seen:
            seen.add(kind)
            out.append({"kind": kind, "at": iso(deliver if kind == "brief" else start)})
    return sorted(out, key=lambda e: e["at"])


class Scheduler:
    def __init__(self, runs: RunManager, settings: Settings, db: DB, tz: ZoneInfo) -> None:
        self._runs = runs
        self._settings = settings
        self._db = db
        self._tz = tz
        self._fired: set[tuple[str, str]] = set()
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self) -> None:
        await asyncio.sleep(3)
        await self._catch_up()
        while True:
            schedule = self._settings.data["schedule"]
            now = utcnow()
            if schedule["enabled"]:
                for start, kind, deliver in plan(schedule, self._tz, now - timedelta(minutes=2)):
                    key = (kind, iso(start))
                    if start <= now < start + timedelta(minutes=2) and key not in self._fired:
                        self._fired.add(key)
                        self._spawn(self._submit(kind, deliver))
            self._fired = {k for k in self._fired if k[1] >= iso(now - timedelta(days=1))}
            await asyncio.sleep(20)

    async def _submit(self, kind: str, deliver: datetime) -> None:
        params = {"deliver": True, "deliver_at": iso(deliver)} if kind == "brief" else {}
        deadline = utcnow() + BUSY_GIVE_UP
        while True:
            try:
                run = await self._runs.start(kind, params, trigger="schedule")
                log.info("scheduled %s started as run #%s", kind, run.id)
                return
            except Busy:
                if utcnow() > deadline:
                    log.warning("scheduled %s skipped: hub busy for %s", kind, BUSY_GIVE_UP)
                    return
                await asyncio.sleep(BUSY_RETRY_S)

    async def _catch_up(self) -> None:
        schedule = self._settings.data["schedule"]
        if not schedule["enabled"]:
            return
        now = utcnow()
        local_today = now.astimezone(self._tz)
        deliver = _at(local_today, schedule["brief_time"], self._tz)
        start = deliver - timedelta(minutes=schedule["prep_minutes"])
        if not (start <= now <= deliver + CATCH_UP):
            return
        last = self._db.last_run("brief", trigger="schedule", since=iso(start.astimezone(timezone.utc)))
        if last and last["status"] == "done":
            return  # a run killed by the restart is marked failed ("hub restarted") and must be redone
        log.info("catching up today's brief (hub was down at %s)", start.strftime("%H:%M"))
        self._fired.add(("brief", iso(start)))
        self._spawn(self._submit("brief", max(deliver, now)))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)  # keep a reference: the loop only holds tasks weakly
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
