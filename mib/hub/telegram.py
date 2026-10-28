"""Telegram bot: long-polls the Bot API (``getUpdates``, no public webhook needed) for /start, /help and /now.

Shares ``settings.data['delivery']['telegram']`` (token + chat_id) with the normal brief-delivery channel
(``mib.hub.delivery``), so once a chat is linked here the scheduled 07:30 brief, any run started with
``deliver: true`` and the web UI's "send to Telegram" button all land in that same chat.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from mib.hub.bus import Bus
from mib.hub.runs import Busy, RunManager
from mib.hub.settings import Settings

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_S = 50                 # getUpdates long-poll timeout
HTTP_TIMEOUT_S = POLL_TIMEOUT_S + 15  # client timeout must exceed the long-poll timeout
IDLE_POLL_S = 2                     # how often to re-check settings while disabled / no token
BACKOFF_START_S = 1
BACKOFF_CAP_S = 60
EDIT_INTERVAL_S = 4                 # minimum gap between editMessageText calls for one /now
NOW_RETRY_S = 5                     # how often a queued /now re-attempts runs.start()
NOW_GIVE_UP_S = 45 * 60

CONFLICT_MSG = ("Another program is polling this bot token (e.g. an old bot service) — stop it or create a "
                "new bot")
OTHER_CHAT_MSG = "This bot is linked to another chat."
COMMANDS = [
    {"command": "now", "description": "Fresh brief right now"},
    {"command": "help", "description": "Show help"},
]
STATUS_ICON = {"pending": "▫️", "active": "▶️", "done": "✅", "error": "❌", "skipped": "⏭️"}

TEXT = {
    "en": {
        "linked": "Linked ✓ — your brief arrives here every day at {time}. Send /now for one right away.",
        "status": "Your brief arrives here every day at {time}.",
        "help": "/now — fetch a fresh brief right now\n/help — show this help",
        "hint": "Unknown command. Send /help to see what I can do.",
        "already": "Already on it ⏳",
        "starting": "🚀 Starting your brief…",
        "queued": "📥 Queued — I'll start as soon as the hub is free…",
        "give_up": "⌛ Still busy after {minutes} minutes. Send /now again later.",
        "progress_header": "⏳ Working on your brief…",
        "done": "✅ Done in {duration}",
        "failed": "❌ Failed: {reason}",
    },
    "th": {
        "linked": "เชื่อมต่อแล้ว ✓ — สรุปข่าวจะส่งมาที่นี่ทุกวันเวลา {time} น. พิมพ์ /now เพื่อขอสรุปตอนนี้เลย",
        "status": "สรุปข่าวจะส่งมาที่นี่ทุกวันเวลา {time} น.",
        "help": "/now — ขอสรุปข่าวตอนนี้เลย\n/help — แสดงวิธีใช้งาน",
        "hint": "ไม่รู้จักคำสั่งนี้ พิมพ์ /help เพื่อดูวิธีใช้งาน",
        "already": "กำลังทำอยู่ ⏳",
        "starting": "🚀 กำลังเริ่มทำสรุปข่าว…",
        "queued": "📥 เข้าคิวไว้แล้ว — จะเริ่มทันทีที่ระบบว่าง…",
        "give_up": "⌛ ระบบไม่ว่างนานกว่า {minutes} นาที พิมพ์ /now อีกครั้งภายหลัง",
        "progress_header": "⏳ กำลังจัดทำสรุปข่าว…",
        "done": "✅ เสร็จแล้วใน {duration}",
        "failed": "❌ ล้มเหลว: {reason}",
    },
}


class TelegramAPIError(RuntimeError):
    def __init__(self, description: str, *, status_code: int | None = None) -> None:
        super().__init__(description)
        self.status_code = status_code


class BotAPI:
    """Thin async wrapper over the Telegram Bot API. ``base_url`` is overridable so tests/verification
    can point it at a fake server instead of ``https://api.telegram.org``."""

    def __init__(self, base_url: str, *, timeout: float = HTTP_TIMEOUT_S) -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, token: str, method: str, params: dict | None = None) -> dict | None:
        resp = await self._http.post(f"{self._base}/bot{token}/{method}", json=params or {})
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not body.get("ok"):
            raise TelegramAPIError(body.get("description") or f"HTTP {resp.status_code}",
                                   status_code=body.get("error_code", resp.status_code))
        return body.get("result")

    async def get_me(self, token: str) -> dict:
        return await self._call(token, "getMe")

    async def set_my_commands(self, token: str, commands: list[dict]) -> None:
        await self._call(token, "setMyCommands", {"commands": commands})

    async def get_updates(self, token: str, offset: int | None, timeout: int) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return await self._call(token, "getUpdates", params) or []

    async def get_chat(self, token: str, chat_id: str) -> dict:
        return await self._call(token, "getChat", {"chat_id": chat_id})

    async def send_message(self, token: str, chat_id: str, text: str) -> dict:
        return await self._call(token, "sendMessage", {"chat_id": chat_id, "text": text,
                                                        "link_preview_options": {"is_disabled": True}})

    async def edit_message_text(self, token: str, chat_id: str, message_id, text: str) -> dict | None:
        return await self._call(token, "editMessageText",
                                {"chat_id": chat_id, "message_id": message_id, "text": text})


def _command(text: str) -> str:
    """``/now@MyBot extra args`` -> ``/now``; '' if ``text`` isn't a command."""
    if not text.startswith("/"):
        return ""
    return text.split()[0].split("@", 1)[0].lower()


def _display_name(chat: dict) -> str | None:
    title = chat.get("title")
    if title:
        return str(title)
    name = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p)
    if name:
        return name
    username = chat.get("username")
    return f"@{username}" if username else None


def _safe(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def _step_line(step: dict) -> str:
    line = f"{STATUS_ICON.get(step.get('status'), '•')} {step.get('label') or step.get('key', '')}"
    if step.get("status") == "active" and step.get("detail"):
        line += f" — {step['detail']}"
    return line


def _progress_text(run, language: str) -> str:
    return "\n".join([TEXT[language]["progress_header"], *(_step_line(s) for s in run.steps)])


def _fmt_duration(seconds) -> str:
    try:
        seconds = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}m {rest}s" if rest else f"{minutes}m"


def _final_text(run, language: str) -> str:
    t = TEXT[language]
    if run.status == "done":
        stats = getattr(run, "stats", None) or {}
        duration = stats.get("duration_s") if isinstance(stats, dict) else None
        header = t["done"].format(duration=_fmt_duration(duration))
    else:
        header = t["failed"].format(reason=getattr(run, "error", None) or run.status)
    return "\n".join([header, *(_step_line(s) for s in run.steps)])


class _Editor:
    """Edits one Telegram message, throttled to ``interval_s`` and only when the text actually changed."""

    def __init__(self, api: BotAPI, token: str, chat_id: str, message_id, interval_s: float) -> None:
        self._api, self._token, self._chat_id, self._message_id = api, token, chat_id, message_id
        self._interval = interval_s
        self._last_text: str | None = None
        self._last_at = 0.0

    async def update(self, text: str) -> None:
        if text == self._last_text or (time.monotonic() - self._last_at) < self._interval:
            return
        await self._push(text)

    async def flush(self, text: str) -> None:
        """Send the final text immediately, bypassing the interval throttle."""
        if text == self._last_text:
            return
        await self._push(text)

    async def _push(self, text: str) -> None:
        self._last_text, self._last_at = text, time.monotonic()
        if self._message_id is None:
            return
        try:
            await self._api.edit_message_text(self._token, self._chat_id, self._message_id, text)
        except (TelegramAPIError, httpx.HTTPError):
            log.warning("telegram: failed to edit status message", exc_info=True)


class TelegramBot:
    def __init__(self, *, settings: Settings, bus: Bus, runs: RunManager, api: BotAPI | None = None,
                base_url: str | None = None) -> None:
        self._settings = settings
        self._bus = bus
        self._runs = runs
        self._owns_api = api is None
        self._api = api or BotAPI(base_url or os.environ.get("MIB_TELEGRAM_API", DEFAULT_API_BASE))
        self._state: dict = {"enabled": False, "token_set": False, "bot_username": None, "polling": False,
                             "chat_id": None, "chat_title": None, "error": None, "link_url": None}
        self._offset: int | None = None
        self._last_token: str | None = None
        self._last_chat_id: str | None = None
        self._backoff = BACKOFF_START_S
        self._now_task: asyncio.Task | None = None
        self._wake = asyncio.Event()  # set by wake(): settings changed, re-read them now
        # testability knobs (sane production defaults; tests may lower them)
        self.idle_poll_s = IDLE_POLL_S
        self.edit_interval_s = EDIT_INTERVAL_S
        self.now_retry_s = NOW_RETRY_S
        self.now_give_up_s = NOW_GIVE_UP_S

    def state(self) -> dict:
        return dict(self._state)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad update must not stop the bot for the process lifetime
                log.exception("telegram: poll cycle crashed")
                await self._sleep_backoff()

    async def aclose(self) -> None:
        if self._now_task and not self._now_task.done():
            self._now_task.cancel()
        if self._owns_api:
            await self._api.aclose()

    async def wait_for_now(self) -> None:
        """Await the in-flight /now (if any). Mainly for tests/graceful draining."""
        if self._now_task:
            await self._now_task

    # ---- state -------------------------------------------------------------------------------------
    def _set(self, **patch) -> None:
        changed = False
        for key, value in patch.items():
            if self._state.get(key) != value:
                self._state[key] = value
                changed = True
        if changed:
            self._bus.publish({"type": "telegram", "telegram": self.state()})

    def _mirror_settings(self, cfg: dict) -> None:
        chat_id = cfg["chat_id"] or None
        patch = {"enabled": bool(cfg["enabled"]), "token_set": bool(cfg["token"]), "chat_id": chat_id}
        if chat_id is None:
            patch["chat_title"] = None
        self._set(**patch)

    def _brief_time(self) -> str:
        return self._settings.data["schedule"]["brief_time"]

    # ---- poll loop -----------------------------------------------------------------------------------
    async def tick(self) -> None:
        """One polling cycle: re-read settings, (re)handshake/sync as needed, one getUpdates round-trip."""
        cfg = self._settings.data["delivery"]["telegram"]
        token, chat_id, enabled = cfg["token"], cfg["chat_id"], cfg["enabled"]
        self._mirror_settings(cfg)
        if not enabled or not token:
            self._set(polling=False, error=None)
            if not token:
                self._set(bot_username=None, link_url=None)
            self._last_token, self._last_chat_id = token, chat_id
            await self._nap(self.idle_poll_s)
            return

        if token != self._last_token:
            self._offset = None
            ok = await self._handshake(token)
            self._last_token = token
            if not ok:
                await self._sleep_backoff()
                return
            self._backoff = BACKOFF_START_S

        if chat_id != self._last_chat_id:
            await self._sync_chat(token, chat_id)
            self._last_chat_id = chat_id

        try:
            updates = await self._poll(token)
            if updates is None:
                return  # settings changed mid-poll: re-read them on the next tick
        except TelegramAPIError as exc:
            await self._on_api_error(exc)
            return
        except httpx.HTTPError as exc:
            self._set(polling=False, error=f"Telegram unreachable: {_safe(str(exc), token)}")
            await self._sleep_backoff()
            return

        self._backoff = BACKOFF_START_S
        self._set(polling=True, error=None)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = update_id + 1
            message = update.get("message")
            if not message:
                continue
            try:
                await self._handle_message(token, message)
            except (TelegramAPIError, httpx.HTTPError):
                log.warning("telegram: failed to handle an update", exc_info=True)

    def wake(self) -> None:
        """Called when settings change so a token/chat edit in the web UI takes effect immediately."""
        self._backoff = BACKOFF_START_S
        self._wake.set()

    async def _nap(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def _poll(self, token: str) -> list | None:
        """getUpdates long-poll that a wake() interrupts (cancelling it consumes no updates)."""
        poll = asyncio.create_task(self._api.get_updates(token, self._offset, POLL_TIMEOUT_S))
        woken = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait({poll, woken}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            woken.cancel()
        if poll.done():
            return poll.result()
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        self._wake.clear()
        return None

    async def _sleep_backoff(self) -> None:
        await self._nap(self._backoff)
        self._backoff = min(self._backoff * 2, BACKOFF_CAP_S)

    async def _on_api_error(self, exc: TelegramAPIError) -> None:
        if exc.status_code == 409:
            self._set(polling=False, error=CONFLICT_MSG)
        elif exc.status_code == 401:
            self._set(polling=False, error="Invalid bot token", bot_username=None, link_url=None)
        else:
            self._set(polling=False, error=f"Telegram unreachable: {exc}")
        await self._sleep_backoff()

    async def _handshake(self, token: str) -> bool:
        try:
            me = await self._api.get_me(token)
        except TelegramAPIError as exc:
            if exc.status_code == 401:
                self._set(error="Invalid bot token", bot_username=None, link_url=None, polling=False)
            else:
                self._set(error=f"Telegram unreachable: {exc}", polling=False)
            return False
        except httpx.HTTPError as exc:
            self._set(error=f"Telegram unreachable: {_safe(str(exc), token)}", polling=False)
            return False
        username = (me or {}).get("username")
        self._set(bot_username=username, link_url=f"https://t.me/{username}" if username else None, error=None)
        try:
            await self._api.set_my_commands(token, COMMANDS)
        except (TelegramAPIError, httpx.HTTPError):
            log.warning("telegram: setMyCommands failed", exc_info=True)
        return True

    async def _sync_chat(self, token: str, chat_id: str) -> None:
        if not chat_id:
            self._set(chat_id=None, chat_title=None)
            return
        try:
            chat = await self._api.get_chat(token, chat_id)
            self._set(chat_id=str(chat_id), chat_title=_display_name(chat or {}))
        except (TelegramAPIError, httpx.HTTPError):
            log.warning("telegram: getChat failed", exc_info=True)
            self._set(chat_id=str(chat_id))

    def _link(self, chat: dict) -> None:
        chat_id = str(chat["id"])
        public = self._settings.update({"delivery": {"telegram": {"chat_id": chat_id}}})
        self._bus.publish({"type": "settings", "settings": public})
        self._last_chat_id = chat_id  # already in sync: no redundant getChat next tick
        self._set(chat_id=chat_id, chat_title=_display_name(chat))

    # ---- messages ------------------------------------------------------------------------------------
    async def _handle_message(self, token: str, msg: dict) -> None:
        chat = msg.get("chat") or {}
        if chat.get("id") is None:
            return
        chat_id_in = str(chat["id"])
        cfg = self._settings.data["delivery"]["telegram"]
        linked = cfg["chat_id"]
        language = self._settings.data["profile"]["language"]
        t = TEXT.get(language, TEXT["en"])
        cmd = _command((msg.get("text") or "").strip())

        if linked and chat_id_in != linked:
            await self._api.send_message(token, chat_id_in, OTHER_CHAT_MSG)
            return

        if not linked:
            if cmd != "/start":
                await self._api.send_message(token, chat_id_in, t["hint"])
                return
            self._link(chat)
            greeting = t["linked"].format(time=self._brief_time()) + "\n\n" + t["help"]
            await self._api.send_message(token, chat_id_in, greeting)
            return

        self._set(chat_title=_display_name(chat))  # keep the title fresh from the linked chat's own messages
        if cmd in ("/start", "/help"):
            reply = t["status"].format(time=self._brief_time()) + "\n\n" + t["help"]
            await self._api.send_message(token, chat_id_in, reply)
        elif cmd == "/now":
            await self._cmd_now(token, chat_id_in, language)
        else:
            await self._api.send_message(token, chat_id_in, t["hint"])

    # ---- /now ----------------------------------------------------------------------------------------
    async def _cmd_now(self, token: str, chat_id: str, language: str) -> None:
        if self._now_task and not self._now_task.done():
            await self._api.send_message(token, chat_id, TEXT[language]["already"])
            return
        sent = await self._api.send_message(token, chat_id, TEXT[language]["starting"])
        message_id = (sent or {}).get("message_id")
        self._now_task = asyncio.create_task(self._run_now(token, chat_id, message_id, language))

    async def _run_now(self, token: str, chat_id: str, message_id, language: str) -> None:
        t = TEXT[language]
        editor = _Editor(self._api, token, chat_id, message_id, self.edit_interval_s)
        deadline = time.monotonic() + self.now_give_up_s
        run = None
        try:
            while run is None:
                try:
                    run = await self._runs.start("pipeline", {"deliver": True, "channels": ["telegram"]},
                                                 trigger="telegram")
                except Busy:
                    if time.monotonic() > deadline:
                        minutes = max(1, round(self.now_give_up_s / 60))
                        await editor.flush(t["give_up"].format(minutes=minutes))
                        return
                    await editor.update(t["queued"])
                    await asyncio.sleep(self.now_retry_s)
            while run.status in ("queued", "running"):
                await editor.update(_progress_text(run, language))
                await asyncio.sleep(1)
            await editor.flush(_final_text(run, language))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # report instead of leaving the status message stuck on "Working…"
            log.exception("telegram: /now failed")
            await editor.flush(t["failed"].format(reason=_safe(str(exc), token)[:200]))
