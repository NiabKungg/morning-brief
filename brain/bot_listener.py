#!/usr/bin/env python3
"""bot_listener.py — รับคำสั่งจาก Telegram (long polling) แล้วทำงานตามคำสั่ง

คำสั่ง:
  /now    — สั่ง Pi 4 กวาดข้อมูลใหม่ทันที → สรุปด้วย AI → ส่งรายงานเข้าแชท
  /status — สถานะระบบ (Pi 4 กวาดล่าสุด, ส่งล่าสุด, โมเดล)
  /help   — วิธีใช้

ความปลอดภัย:
- ยอมรับเฉพาะข้อความจาก chat_id ที่ลงทะเบียนใน config.env เท่านั้น
- ทุก request ผ่าน check_url() อนุญาตแค่ api.telegram.org ผ่าน https
- คำสั่งที่รันเป็นไฟล์สคริปต์ path คงที่ในระบบ ไม่มีการประกอบจาก input ผู้ใช้
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = Path(__file__).resolve().parent
TELEGRAM_HOST = "api.telegram.org"
POLL_TIMEOUT_S = 25
NOW_TIMEOUT_S = 900
STATUS_TIMEOUT_S = 25


def check_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != "https" or (p.hostname or "") != TELEGRAM_HOST:
        raise ValueError(f"blocked URL: {url}")
    return url


def load_config() -> dict:
    cfg = {}
    env_path = BASE / "config.env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("'\"")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not cfg.get(k):
            print(f"[bot] missing {k}", file=sys.stderr)
            sys.exit(1)
    cfg.setdefault("MB_MODEL", "gemma4:e2b")
    return cfg


def tg(cfg: dict, method: str, payload: dict) -> dict:
    r = requests.post(
        check_url(f"https://{TELEGRAM_HOST}/bot{cfg['TELEGRAM_BOT_TOKEN']}/{method}"),
        json=payload, timeout=40)
    return r.json()


def reply(cfg: dict, chat_id: str, text: str) -> None:
    try:
        tg(cfg, "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    except Exception as exc:
        print(f"[bot] reply error: {exc}", file=sys.stderr)


def cmd_now(cfg: dict, chat_id: str) -> None:
    reply(cfg, chat_id, "⏳ สั่ง Pi 4 กวาดข้อมูลใหม่… (ใช้เวลา 1-3 นาที)")
    try:
        p = subprocess.run(
            ["/bin/bash", "/home/pi5/morning-brief/bot_pi4.sh", "sweep"],
            capture_output=True, text=True, timeout=NOW_TIMEOUT_S, shell=False, check=False)
        if p.returncode != 0:
            reply(cfg, chat_id, "❌ เก็บข้อมูลไม่สำเร็จ:\n" + (p.stdout[-250:] or p.stderr[-250:]))
            return
    except subprocess.TimeoutExpired:
        reply(cfg, chat_id, "❌ timeout — Pi 4 กวาดข้อมูลไม่เสร็จใน 15 นาที")
        return
    reply(cfg, chat_id, "🧠 ข้อมูลพร้อม — กำลังสรุปด้วย AI (อีก 1-4 นาที)…")
    env = dict(os.environ, MB_FORCE="1")  # /now = ส่งใหม่ทั้งที่วันนี้อาจส่งไปแล้ว
    try:
        s = subprocess.run(
            ["/home/pi5/morning-brief/.venv/bin/python", "/home/pi5/morning-brief/summarizer.py"],
            capture_output=True, text=True, timeout=1100, env=env, shell=False, check=False)
        if s.returncode == 0:
            reply(cfg, chat_id, "✅ ส่งรายงานใหม่แล้ว (อยู่ในข้อความด้านบน)")
        else:
            reply(cfg, chat_id, "❌ สรุปไม่สำเร็จ:\n" + (s.stdout[-250:] + s.stderr[-250:]))
    except subprocess.TimeoutExpired:
        reply(cfg, chat_id, "❌ AI ใช้เวลานานเกินไป — ลอง /now อีกครั้ง")


def cmd_status(cfg: dict, chat_id: str) -> None:
    lines = ["📊 Morning Brief Status", f"โมเดล: {cfg['MB_MODEL']}"]
    state = BASE / "state"
    sent = sorted(state.glob("sent-*"))[-1].name if state.exists() and any(state.glob("sent-*")) else "ยังไม่เคยส่ง"
    lines.append(f"ส่งล่าสุด: {sent}")
    try:
        p = subprocess.run(
            ["/bin/bash", "/home/pi5/morning-brief/bot_pi4.sh", "sweepstatus"],
            capture_output=True, text=True, timeout=STATUS_TIMEOUT_S, shell=False, check=False)
        lines.append("Pi 4 กวาดล่าสุด:\n" + (p.stdout.strip() or "(ไม่มีข้อมูล)"))
    except Exception:
        lines.append("Pi 4: เข้าถึงไม่ได้ตอนนี้")
    reply(cfg, chat_id, "\n".join(lines))


def cmd_help(cfg: dict, chat_id: str) -> None:
    reply(cfg, chat_id,
          "🤖 Morning Intelligence Brief\n"
          "/now — เก็บข้อมูลใหม่ + สรุป + ส่งทันที\n"
          "/status — ดูสถานะระบบ\n"
          "/help — วิธีใช้\n\n"
          "รายงานอัตโนมัติส่งทุกเช้า 07:30 น.")


def handle(cfg: dict, message: dict) -> None:
    chat_id = str(message.get("chat", {}).get("id", ""))
    if chat_id != str(cfg["TELEGRAM_CHAT_ID"]):  # แชทอื่น — ไม่ตอบ ไม่ทำงาน
        print(f"[bot] ignore chat {chat_id}", file=sys.stderr)
        return
    text = (message.get("text") or "").split("@")[0].strip().lower()
    print(f"[bot] cmd from {chat_id}: {text}")
    if text.startswith("/now"):
        cmd_now(cfg, chat_id)
    elif text.startswith("/status"):
        cmd_status(cfg, chat_id)
    elif text.startswith("/help") or text.startswith("/start"):
        cmd_help(cfg, chat_id)
    else:
        reply(cfg, chat_id, "ไม่รู้จักคำสั่ง — พิมพ์ /help")


def main() -> int:
    cfg = load_config()
    offset = 0
    print("[bot] listening…")
    while True:
        try:
            r = requests.post(
                check_url(f"https://{TELEGRAM_HOST}/bot{cfg['TELEGRAM_BOT_TOKEN']}/getUpdates"),
                json={"offset": offset, "timeout": POLL_TIMEOUT_S,
                      "allowed_updates": ["message"]},
                timeout=POLL_TIMEOUT_S + 15)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message")
                if msg and msg.get("text"):
                    try:
                        handle(cfg, msg)
                    except Exception as exc:
                        print(f"[bot] handle error: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"[bot] poll error: {exc} — retry in 5s", file=sys.stderr)
            time.sleep(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
