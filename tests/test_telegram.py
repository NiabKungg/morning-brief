import asyncio

from mib.hub.bus import Bus
from mib.hub.db import DB
from mib.hub.runs import Busy
from mib.hub.settings import Settings
from mib.hub.telegram import TelegramAPIError, TelegramBot


class FakeRun:
    """Stands in for mib.hub.runs.Run: just the attributes TelegramBot reads."""

    def __init__(self, id_, kind, params, trigger):
        self.id, self.kind, self.params, self.trigger = id_, kind, params, trigger
        self.status = "done"
        self.error = None
        self.stats = {"duration_s": 12}
        self.steps = [{"key": "collect", "label": "Collect", "status": "done", "detail": None}]


class FakeRunManager:
    def __init__(self):
        self.started = []  # [(kind, params, trigger)]
        self.busy = False
        self._next_id = 1

    async def start(self, kind, params, trigger="manual"):
        if self.busy:
            raise Busy("hub busy")
        self.started.append((kind, dict(params), trigger))
        run = FakeRun(self._next_id, kind, dict(params), trigger)
        self._next_id += 1
        return run


class FakeBotAPI:
    """Fake Bot API client: same async method surface as mib.hub.telegram.BotAPI, no network."""

    def __init__(self):
        self.sent = []    # [(token, chat_id, text)]
        self.edits = []   # [(token, chat_id, message_id, text)]
        self.me = {"id": 1, "username": "MyBot", "first_name": "MIB"}
        self.commands = None
        self.updates = []  # list of batches (list[dict]); one popped per get_updates call
        self._next_message_id = 100

    async def get_me(self, token):
        return self.me

    async def set_my_commands(self, token, commands):
        self.commands = commands

    async def get_chat(self, token, chat_id):
        return {"id": int(chat_id)}

    async def get_updates(self, token, offset, timeout):
        return self.updates.pop(0) if self.updates else []

    async def send_message(self, token, chat_id, text):
        self._next_message_id += 1
        self.sent.append((token, chat_id, text))
        return {"message_id": self._next_message_id}

    async def edit_message_text(self, token, chat_id, message_id, text):
        self.edits.append((token, chat_id, message_id, text))
        return {"ok": True}


def _env(tmp_path):
    db = DB(tmp_path / "t.sqlite3")
    return Settings(db), Bus(db)


def _msg(update_id, chat_id, text, **chat_extra):
    chat = {"id": chat_id, "type": "private", "first_name": "Ann", **chat_extra}
    return {"update_id": update_id, "message": {"message_id": update_id, "date": 0, "chat": chat, "text": text}}


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def test_first_start_links_unlinked_bot_and_publishes_settings(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1"}}})
        api = FakeBotAPI()
        bot = TelegramBot(settings=settings, bus=bus, runs=FakeRunManager(), api=api)
        queue = bus.subscribe()
        api.updates = [[_msg(1, 555, "/start")]]

        await bot.tick()

        assert settings.data["delivery"]["telegram"]["chat_id"] == "555"
        assert bot.state()["chat_id"] == "555"
        settings_events = [e for e in _drain(queue) if e["type"] == "settings"]
        assert settings_events and settings_events[-1]["settings"]["delivery"]["telegram"]["chat_id"] == "555"
        assert api.sent[-1][0:2] == ("tok-1", "555")
        assert settings.data["schedule"]["brief_time"] in api.sent[-1][2]  # /start + help mentions the daily time
    asyncio.run(scenario())


def test_another_chat_is_refused(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1", "chat_id": "555"}}})
        api = FakeBotAPI()
        bot = TelegramBot(settings=settings, bus=bus, runs=FakeRunManager(), api=api)
        api.updates = [[_msg(1, 999, "/start")]]

        await bot.tick()

        assert api.sent == [("tok-1", "999", "This bot is linked to another chat.")]
        assert settings.data["delivery"]["telegram"]["chat_id"] == "555"  # untouched
    asyncio.run(scenario())


def test_now_starts_a_pipeline_restricted_to_telegram(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1", "chat_id": "555"}}})
        api = FakeBotAPI()
        runs = FakeRunManager()
        bot = TelegramBot(settings=settings, bus=bus, runs=runs, api=api)
        api.updates = [[_msg(1, 555, "/now")]]

        await bot.tick()
        await bot.wait_for_now()

        assert runs.started == [("pipeline", {"deliver": True, "channels": ["telegram"]}, "telegram")]
        assert api.sent  # immediate status message
        assert api.edits and "Done" in api.edits[-1][3]  # edited to the final outcome
    asyncio.run(scenario())


def test_now_while_busy_queues_then_starts_when_idle(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1", "chat_id": "555"}}})
        api = FakeBotAPI()
        runs = FakeRunManager()
        runs.busy = True
        bot = TelegramBot(settings=settings, bus=bus, runs=runs, api=api)
        bot.now_retry_s = 0.01
        bot.now_give_up_s = 5
        api.updates = [[_msg(1, 555, "/now")]]

        await bot.tick()
        await asyncio.sleep(0.05)  # a few busy-retry cycles while the hub stays busy
        assert runs.started == []
        assert any("Queued" in e[3] for e in api.edits)

        runs.busy = False
        await bot.wait_for_now()

        assert len(runs.started) == 1
        assert runs.started[0] == ("pipeline", {"deliver": True, "channels": ["telegram"]}, "telegram")
    asyncio.run(scenario())


def test_second_now_while_one_is_pending_says_already_on_it(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1", "chat_id": "555"}}})
        api = FakeBotAPI()
        runs = FakeRunManager()
        runs.busy = True
        bot = TelegramBot(settings=settings, bus=bus, runs=runs, api=api)
        bot.now_retry_s = 0.01
        bot.now_give_up_s = 5
        api.updates = [[_msg(1, 555, "/now")]]
        await bot.tick()
        await asyncio.sleep(0.03)  # first /now is now pending behind the busy hub

        api.updates = [[_msg(2, 555, "/now")]]
        await bot.tick()

        assert api.sent[-1] == ("tok-1", "555", "Already on it ⏳")
        assert runs.started == []  # the pending one still hasn't started

        runs.busy = False
        await bot.wait_for_now()
    asyncio.run(scenario())


def test_now_with_bot_suffix_parses(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "tok-1", "chat_id": "555"}}})
        api = FakeBotAPI()
        runs = FakeRunManager()
        bot = TelegramBot(settings=settings, bus=bus, runs=runs, api=api)
        api.updates = [[_msg(1, 555, "/now@MyBot")]]

        await bot.tick()
        await bot.wait_for_now()

        assert runs.started and runs.started[0][0] == "pipeline"
        assert runs.started[0][2] == "telegram"
    asyncio.run(scenario())


def test_clearing_a_bad_token_in_the_web_ui_takes_effect_without_waiting_out_the_backoff(tmp_path):
    async def scenario():
        settings, bus = _env(tmp_path)
        settings.update({"delivery": {"telegram": {"enabled": True, "token": "bad-token"}}})
        api = FakeBotAPI()

        async def unauthorized(token):
            raise TelegramAPIError("Unauthorized", status_code=401)

        api.get_me = unauthorized
        bot = TelegramBot(settings=settings, bus=bus, runs=FakeRunManager(), api=api)
        bot.idle_poll_s = 0.01
        first = asyncio.create_task(bot.tick())  # handshake fails, then backs off (>= 1 s)
        await asyncio.sleep(0.05)
        assert bot.state()["error"] == "Invalid bot token"

        settings.update({"delivery": {"telegram": {"token": ""}}})  # what PUT /api/settings does…
        bot.wake()                                                   # …followed by this
        await asyncio.wait_for(first, timeout=0.5)
        await asyncio.wait_for(bot.tick(), timeout=0.5)
        assert bot.state()["token_set"] is False and bot.state()["error"] is None
    asyncio.run(scenario())
