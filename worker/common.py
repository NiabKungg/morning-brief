#!/usr/bin/env python3
"""common.py — ตัวช่วยกลาง: โหลด config, HTTP แบบผ่านการตรวจ SSRF, และบันทึก JSON

safe_get() ป้องกัน SSRF สามชั้น:
  1) อนุญาตเฉพาะ https:// และ hostname ต้องอยู่ใน ALLOWED_HOSTS (allowlist ตายตัว)
  2) resolve hostname แล้วปฏิเสธ loopback/private/link-local/reserved IP
     (กันการแอบชี้ config ไปยิงเครือข่ายภายในหรือ cloud metadata)
  3) redirect ไม่เกิน 3 ชั้น และตรวจซ้ำทุกชั้น (กัน DNS rebinding ขั้นพื้นฐาน)
"""
import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse

import requests

UA = "MorningBrief-Agent/1.0 (Raspberry Pi; classroom project)"
MAX_REDIRECTS = 3
TIMEOUT = 25

# โดเมนต้นทางข้อมูลที่อนุมัติ — เพิ่มแหล่งใหม่ต้องเพิ่มที่นี่ก่อน
ALLOWED_HOSTS = frozenset({
    "www.blognone.com",
    "techcrunch.com",
    "www.theverge.com",
    "hnrss.org",
    "api.coingecko.com",
    "stooq.com",
    "api.github.com",
    "www.reddit.com",
})


def load_config(base: Path) -> dict:
    return json.loads((base / "sources.json").read_text(encoding="utf-8"))


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"only https allowed: {url}")
    host = parsed.hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host not in allowlist: {host}")
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    if not infos:
        raise ValueError(f"cannot resolve {host}")
    ip = ipaddress.ip_address(infos[0][4][0])
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise ValueError(f"blocked internal/reserved address: {ip} ({host})")


def safe_get(url: str, **kw) -> requests.Response:
    """GET พร้อมตรวจ allowlist + IP ใหม่ทุกครั้งที่ redirect (สูงสุด 3 ชั้น)"""
    kw.setdefault("headers", {"User-Agent": UA})
    kw.setdefault("timeout", TIMEOUT)
    kw["allow_redirects"] = False
    resp = None
    for _ in range(MAX_REDIRECTS + 1):
        _check_url(url)
        resp = requests.get(url, **kw)
        if 300 < resp.status_code < 400 and resp.headers.get("Location"):
            url = resp.headers["Location"]
            continue
        break
    resp.raise_for_status()
    return resp


def write_json(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)
