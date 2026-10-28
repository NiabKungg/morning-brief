import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from mib.common.timeutil import iso
from mib.hub import scheduler
from mib.hub.db import DB
from mib.hub.scheduler import Scheduler, plan, upcoming
from mib.hub.settings import Settings

BKK = ZoneInfo("Asia/Bangkok")
SCHEDULE = {"enabled": True, "collect_times": ["00:30", "06:30"], "brief_time": "07:30", "prep_minutes": 25}


def test_brief_is_written_ahead_and_delivered_at_brief_time():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)  # 19:00 in Bangkok
    briefs = [(start, deliver) for start, kind, deliver in plan(SCHEDULE, BKK, now) if kind == "brief"]
    start, deliver = briefs[0]
    assert deliver.astimezone(BKK).strftime("%H:%M") == "07:30"
    assert start.astimezone(BKK).strftime("%H:%M") == "07:05"


def test_upcoming_reports_next_collect_and_brief_in_the_future():
    now = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)  # 00:00 Bangkok, 29 Oct
    assert upcoming(SCHEDULE, BKK, now) == [
        {"kind": "collect", "at": "2026-10-28T17:30:00+00:00"},
        {"kind": "brief", "at": "2026-10-29T00:30:00+00:00"},
    ]
    assert upcoming({**SCHEDULE, "enabled": False}, BKK, now) == []


def test_catch_up_redoes_a_scheduled_brief_killed_by_a_restart_but_not_a_finished_one(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.sqlite3")
    now = datetime(2026, 10, 29, 0, 10, tzinfo=timezone.utc)  # 07:10 Bangkok: brief started 07:05, due 07:30
    monkeypatch.setattr(scheduler, "utcnow", lambda: now)
    killed = db.create_run("brief", "schedule", {}, [])
    db.update_run(killed, created_at=iso(now), status="failed", error="hub restarted")
    started = []

    class Runs:
        async def start(self, kind, params, trigger):
            started.append((kind, params, trigger))
            return SimpleNamespace(id=99)

    async def catch_up() -> None:
        sched = Scheduler(Runs(), Settings(db), db, BKK)
        await sched._catch_up()
        await asyncio.gather(*sched._tasks)

    asyncio.run(catch_up())
    assert started == [("brief", {"deliver": True, "deliver_at": "2026-10-29T00:30:00+00:00"}, "schedule")]

    db.update_run(db.create_run("brief", "schedule", {}, []), created_at=iso(now), status="done")
    started.clear()
    asyncio.run(catch_up())
    assert started == []
