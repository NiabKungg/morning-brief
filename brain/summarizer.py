#!/usr/bin/env python3
"""summarizer.py — รวมข้อมูลที่ Pi 4 กวาดมาส่งให้ แล้วสรุปด้วย Ollama (gemma4:e2b)
ส่งรายงานเข้า Telegram พร้อมลิงก์อ้างอิงจริง (โค้ดแนบลิงก์เอง ไม่ให้ LLM เดา URL)

ความปลอดภัย: ทุก HTTP request ผ่าน check_url() ก่อน — อนุญาตเฉพาะ
host ที่กำหนดชัดเจน 2 แห่ง คือ Ollama บน loopback ของเครื่องตัวเอง
และ api.telegram.org ผ่าน https เท่านั้น

ทำงานแบบ idempotent: วันหนึ่งส่งครั้งเดียว (ตรวจจาก state/sent-<วันที่>)
ถ้า LLM ล้มหรือช้าเกิน จะส่ง digest ดิบพร้อมหมายเหตุแทนการเงียบ
"""
import html
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = Path(__file__).resolve().parent
INCOMING = BASE / "incoming"
STATE = BASE / "state"
ARCHIVE = BASE / "archive"

OLLAMA_HOST = "127.0.0.1"
OLLAMA_URL = f"http://{OLLAMA_HOST}:11434/api/generate"
TELEGRAM_HOST = "api.telegram.org"
LLM_TIMEOUT_S = 900


def check_url(url: str, allowed_host: str, allow_http: bool = False) -> str:
    """ยืนยันว่า URL ชี้ไปที่ host ที่อนุมัติไว้เท่านั้น ก่อนยิงทุกครั้ง"""
    p = urlparse(url)
    ok_scheme = p.scheme == "https" or (allow_http and p.scheme == "http")
    if not ok_scheme or (p.hostname or "") != allowed_host:
        raise ValueError(f"blocked URL (ไม่ตรง host ที่อนุมัติ): {url}")
    return url


def load_config() -> dict:
    cfg = {}
    env_path = BASE / "config.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'\"")
    # environment variable มีลำดับความสำคัญสูงกว่าไฟล์ (ตามหลักอ่าน credential จาก env)
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MB_MODEL"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not cfg.get(k):
            print(f"[summarizer] missing {k}", file=sys.stderr)
            sys.exit(1)
    cfg.setdefault("MB_MODEL", "gemma4:e2b")
    return cfg


def collect_recent(max_age_hours: int = 12) -> dict:
    """รวมไฟล์ JSON ที่อัปเดตภายใน 12 ชม. ล่าสุด (ไม่ยึดชื่อโฟลเดอร์วันที่)"""
    cutoff = time.time() - max_age_hours * 3600
    sources = {"rss": [], "market": {}, "github": [], "reddit": []}
    for f in sorted(INCOMING.rglob("*.json")):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[summarizer] skip {f.name}: {exc}", file=sys.stderr)
            continue
        src = data.get("source")
        if src == "rss":
            sources["rss"].extend(data.get("items", []))
        elif src == "market":
            sources["market"] = data
        elif src == "github":
            sources["github"].extend(data.get("items", []))
        elif src == "reddit":
            sources["reddit"].extend(data.get("items", []))
    # ตัดซ้ำด้วยลิงก์
    for key in ("rss", "github", "reddit"):
        seen, uniq = set(), []
        for it in sources[key]:
            u = it.get("link") or it.get("url") or it.get("repo", "")
            if u and u not in seen:
                seen.add(u)
                uniq.append(it)
        sources[key] = uniq
    return sources


def build_prompt(sources: dict, today: str) -> str:
    lines = [f"ข้อมูลข่าวสารที่เก็บได้เช้าวันที่ {today}:"]

    lines.append("\n[ข่าวเทคโนโลยีจาก RSS]")
    for it in sources["rss"][:18]:
        lines.append(f"- ({it.get('feed','')}) {it.get('title','')} :: {it.get('summary','')[:180]}")

    m = sources.get("market", {})
    if m.get("crypto"):
        lines.append("\n[ราคาคริปโต]")
        for c in m["crypto"]:
            lines.append(f"- {c['name']}: ${c.get('price_usd')} ({c.get('change_24h_pct', 0):+.2f}% 24h)")
    if m.get("stocks"):
        lines.append("\n[ราคาหุ้น]")
        for s in m["stocks"]:
            lines.append(f"- {s.get('symbol','')}: close ${s.get('close')}")

    lines.append("\n[GitHub ที่กำลังมาแรง]")
    for it in sources["github"][:8]:
        lines.append(f"- {it.get('repo','')} (★{it.get('stars',0)}) {it.get('lang','')} :: {it.get('description','')[:120]}")

    lines.append("\n[Reddit ยอดนิยม]")
    for it in sources["reddit"][:10]:
        lines.append(f"- (r/{it.get('sub','')}, 👍{it.get('score',0)}) {it.get('title','')}")

    lines.append(
        "\nหน้าที่ของคุณ: เป็นนักวิเคราะห์ข่าว คัดกรองข่าวที่สำคัญ/น่าสนใจจริง ตัดขยะออก "
        "แล้วเขียน Executive Summary ภาษาไทยกระชับ ใช้รูปแบบนี้เท่านั้น (ห้ามแต่งลิงก์เอง ห้ามเขียนสิ่งที่ไม่มีในข้อมูล):\n"
        "🔧 ข่าวเทคโนโลยี (3-5 ข้อ สั้น ๆ พร้อมเหตุผลว่าทำไมน่าสนใจ)\n"
        "📈 ตลาด (สรุปการเคลื่อนไหว 1-2 บรรทัด)\n"
        "⭐ GitHub น่าลอง (2-3 ข้อ)\n"
        "💬 จากชุมชน (2-3 ข้อ)\n"
        "🎯 ประเด็นที่ควรจับตาวันนี้ (1-2 ข้อ)"
    )
    return "\n".join(lines)


def ask_ollama(prompt: str, model: str) -> str:
    r = requests.post(check_url(OLLAMA_URL, OLLAMA_HOST, allow_http=True), json={
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "15m",
        "options": {"num_predict": 900, "temperature": 0.4},
    }, timeout=LLM_TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def telegram_send(cfg: dict, text: str) -> bool:
    ok = True
    for i in range(0, len(text), 3800):  # Telegram จำกัด 4096 ตัวอักษร/ข้อความ
        chunk = text[i:i + 3800]
        url = check_url(
            f"https://{TELEGRAM_HOST}/bot{cfg['TELEGRAM_BOT_TOKEN']}/sendMessage",
            TELEGRAM_HOST)
        try:
            r = requests.post(url, json={
                "chat_id": cfg["TELEGRAM_CHAT_ID"],
                "text": chunk,
                "disable_web_page_preview": True,
            }, timeout=30)
            ok = ok and r.ok
        except Exception as exc:
            print(f"[summarizer] telegram send error: {exc}", file=sys.stderr)
            ok = False
    return ok


def build_fallback(sources: dict) -> str:
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"☀️ Morning Intelligence Brief — {today}", "⚠️ (AI สรุปไม่สำเร็จ — ส่งข่าวดิบแทน)", ""]
    for it in sources["rss"][:10]:
        lines.append(f"• {it.get('title','')}")
    for it in sources["github"][:5]:
        lines.append(f"• ⭐ {it.get('repo','')} — {it.get('description','')[:100]}")
    for it in sources["reddit"][:5]:
        lines.append(f"• (r/{it.get('sub','')}) {it.get('title','')}")
    return "\n".join(lines)


def build_links(sources: dict) -> str:
    lines = ["", "🔗 แหล่งข่าวอ้างอิง:"]
    n = 0
    for it in sources["rss"][:8]:
        n += 1
        lines.append(f"{n}. {html.escape(it.get('title','')[:80])} — {it.get('link','')}")
    for it in sources["github"][:3]:
        n += 1
        lines.append(f"{n}. {it.get('repo','')} — {it.get('url','')}")
    for it in sources["reddit"][:3]:
        n += 1
        lines.append(f"{n}. (r/{it.get('sub','')}) {html.escape(it.get('title','')[:70])} — https://www.reddit.com{it.get('link','')}")
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    today = datetime.now().strftime("%Y-%m-%d")
    STATE.mkdir(exist_ok=True)
    marker = STATE / f"sent-{today}"
    if marker.exists() and not os.environ.get("MB_FORCE"):
        print(f"[summarizer] วันนี้ ({today}) ส่งไปแล้ว — จบ ไม่ส่งซ้ำ (ใช้ MB_FORCE=1 เพื่อบังคับส่งใหม่)")
        return 0

    sources = collect_recent()
    total = len(sources["rss"]) + len(sources["github"]) + len(sources["reddit"])
    if total == 0:
        print("[summarizer] ไม่มีข้อมูลใหม่ — ไม่ส่ง (อาจยังไม่มีการกวาด)")
        return 1

    sent = False
    body = ""
    try:
        prompt = build_prompt(sources, today)
        print(f"[summarizer] asking {cfg['MB_MODEL']} ({len(prompt)} chars prompt)…")
        t0 = time.monotonic()
        body = ask_ollama(prompt, cfg["MB_MODEL"])
        print(f"[summarizer] LLM done in {time.monotonic()-t0:.0f}s, {len(body)} chars")
    except Exception as exc:
        print(f"[summarizer] LLM failed: {exc}", file=sys.stderr)

    if body:
        text = f"☀️ Morning Intelligence Brief — {datetime.now().strftime('%d/%m/%Y')}\n\n{body}\n{build_links(sources)}"
        sent = telegram_send(cfg, text)
    if not sent:
        sent = telegram_send(cfg, build_fallback(sources) + "\n" + build_links(sources))

    if sent:
        marker.write_text(datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8")
        ARCHIVE.mkdir(exist_ok=True)
        (ARCHIVE / f"brief-{today}.txt").write_text(body or build_fallback(sources), encoding="utf-8")
        print("[summarizer] sent ✓")
        return 0
    print("[summarizer] ส่งไม่สำเร็จ (จะลองใหม่ในรอบ timer ถัดไป)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
