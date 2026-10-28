"""Delivery channels: Telegram Bot API (HTML parse mode) and Discord webhooks."""

from __future__ import annotations

import asyncio

import httpx

from mib.common.timeutil import iso
from mib.hub.pipeline.render import pack

DISCORD_LIMIT = 1900


async def send_telegram(token: str, chat_id: str, messages: list[str]) -> None:
    async with httpx.AsyncClient(timeout=20) as http:
        for text in messages:
            for attempt in range(3):
                try:
                    resp = await http.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
                        "link_preview_options": {"is_disabled": True},
                    })
                except httpx.HTTPError as exc:
                    if attempt < 2:
                        await asyncio.sleep(2)
                        continue
                    raise RuntimeError(f"Telegram: {exc}") from exc
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 429 and attempt < 2:
                    await asyncio.sleep(float((body.get("parameters") or {}).get("retry_after", 3)))
                    continue
                if resp.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(2)
                    continue
                if not body.get("ok"):
                    raise RuntimeError(f"Telegram: {body.get('description') or f'HTTP {resp.status_code}'}")
                break


async def send_discord(webhook: str, markdown: str) -> None:
    async with httpx.AsyncClient(timeout=20) as http:
        for text in pack(markdown.split("\n\n"), DISCORD_LIMIT):
            resp = await http.post(webhook, json={"content": text, "flags": 4})  # 4 = SUPPRESS_EMBEDS
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.json().get("retry_after", 2)))
                resp = await http.post(webhook, json={"content": text, "flags": 4})
            if resp.status_code >= 300:
                raise RuntimeError(f"Discord: HTTP {resp.status_code} {resp.text[:200]}")


async def deliver(settings: dict, *, telegram_html: list[str], markdown: str,
                  channels: list[str] | None = None) -> list[dict]:
    """Send to every enabled+configured channel (or only those listed in ``channels``). Returns
    [{channel, ok, error, at}]."""
    results = []
    tg = settings["delivery"]["telegram"]
    if (channels is None or "telegram" in channels) and tg["enabled"] and tg["token"] and tg["chat_id"]:
        try:
            await send_telegram(tg["token"], tg["chat_id"], telegram_html)
            results.append({"channel": "telegram", "ok": True, "error": None, "at": iso()})
        except Exception as exc:
            error = str(exc).replace(tg["token"], "<token>")[:300]
            results.append({"channel": "telegram", "ok": False, "error": error, "at": iso()})
    dc = settings["delivery"]["discord"]
    if (channels is None or "discord" in channels) and dc["enabled"] and dc["webhook"]:
        try:
            await send_discord(dc["webhook"], markdown)
            results.append({"channel": "discord", "ok": True, "error": None, "at": iso()})
        except Exception as exc:
            error = str(exc).replace(dc["webhook"], "<webhook>")[:300]
            results.append({"channel": "discord", "ok": False, "error": error, "at": iso()})
    return results
