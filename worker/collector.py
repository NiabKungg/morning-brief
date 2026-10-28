#!/usr/bin/env python3
"""collector.py — ตัวคุมการกวาดข้อมูล: เรียก fetcher ทีละตัว คุมเวลาด้วย timeout

การกำหนดเวลา/ควบคุมการทำงาน (Scheduling & Supervision):
- รัน fetcher ทีละตัวเพื่อประหยัดแรมบน Pi 4 (2GB)
- แต่ละ fetcher มี timeout ต่อ request 25 วินาทีในตัว + ตัวคุมหลักกำหนด
  ไม่เกิน 150 วินาที/ตัว — ตัวไหนช้าหรือพังจะถูกข้าม แล้วรอบยังทำงานต่อ
"""
import importlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

FETCHERS = (
    ("fetch_rss", "fetch_rss.json"),
    ("fetch_market", "fetch_market.json"),
    ("fetch_github", "fetch_github.json"),
    ("fetch_reddit", "fetch_reddit.json"),
)
TIMEOUT_S = 150


def run_fetcher(mod_name: str, out_file: Path) -> int:
    mod = importlib.import_module(mod_name)
    return mod.main(out_file)


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = BASE / "data" / today
    failures = 0
    print(f"[collector] start {datetime.now().isoformat(timespec='seconds')}")
    with ThreadPoolExecutor(max_workers=1) as pool:  # ทีละตัว ประหยัดแรม
        for mod_name, out_name in FETCHERS:
            out_file = out_dir / out_name
            t0 = time.monotonic()
            fut = pool.submit(run_fetcher, mod_name, out_file)
            try:
                rc = fut.result(timeout=TIMEOUT_S)
                dt = time.monotonic() - t0
                if rc == 0:
                    print(f"[collector] {mod_name}: OK ({dt:.1f}s)")
                else:
                    failures += 1
                    print(f"[collector] {mod_name}: rc={rc} ({dt:.1f}s)")
            except FutTimeout:
                failures += 1
                print(f"[collector] {mod_name}: TIMEOUT >{TIMEOUT_S}s (ข้ามไปตัวถัดไป)")
    state = BASE / "state"
    state.mkdir(exist_ok=True)
    (state / "last_sweep.txt").write_text(
        datetime.now().isoformat(timespec="seconds") + f"\nfailures={failures}\n",
        encoding="utf-8")
    print(f"[collector] done, failures={failures}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
