#!/usr/bin/env python3
"""boot_notify.py — แจ้งเตือน Telegram เมื่อเครื่องเพิ่งบูทและออนไลน์พร้อมทำงาน

รันอัตโนมัติตอนบูทผ่าน systemd (mb-boot-notify.service):
รออินเทอร์เน็ตสูงสุด 5 นาที → ยิงข้อความ "🟢 <ชื่อเครื่อง> พร้อมทำงาน" พร้อม IP
"""
import socket
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ALLOWED_HOST = "api.telegram.org"
WAIT_MAX_S = 300
ROLES = {
    "pi4": "Worker — กวาดข้อมูล",
    "raspberrypi": "Brain — AI สรุป + ส่งรายงาน",
}


def check_url(url: str) -> str:
    host = url.split("/")[2] if len(url.split("/")) > 2 else ""
    if not url.startswith("https://") or host != ALLOWED_HOST:
        raise ValueError(f"blocked URL: {url}")
    return url


def load_cfg() -> dict:
    cfg = {}
    env_path = BASE / "config.env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("'\"")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not cfg.get(k):
            print(f"[boot-notify] missing {k}", file=sys.stderr)
            sys.exit(1)
    return cfg


def wait_internet() -> bool:
    t0 = time.time()
    while time.time() - t0 < WAIT_MAX_S:
        try:
            requests.get("https://api.telegram.org/", timeout=6)
            return True
        except requests.RequestException:
            time.sleep(5)
    return False


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "ไม่ทราบ IP"
    finally:
        s.close()


def main() -> int:
    cfg = load_cfg()
    host = socket.gethostname()
    role = ROLES.get(host, "")
    online = wait_internet()
    ip = local_ip()
    up = int(float(open("/proc/uptime").read().split()[0]))
    text = (f"🟢 {host} ({role}) พร้อมทำงาน\n"
            f"IP: {ip}\n"
            f"ออนไลน์: {'✓' if online else '✗ (ยังไม่มีเน็ต)'}\n"
            f"บูทมาแล้ว: {up // 60} นาที")
    try:
        r = requests.post(
            check_url(f"https://{ALLOWED_HOST}/bot{cfg['TELEGRAM_BOT_TOKEN']}/sendMessage"),
            json={"chat_id": cfg["TELEGRAM_CHAT_ID"], "text": text,
                  "disable_web_page_preview": True},
            timeout=20)
        print(f"[boot-notify] sent: {text.splitlines()[0]} (rc={r.status_code})")
        return 0 if r.ok else 1
    except Exception as exc:
        print(f"[boot-notify] failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
