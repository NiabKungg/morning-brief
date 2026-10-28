#!/usr/bin/env python3
"""fetch_market.py — ราคาคริปโตจาก CoinGecko และหุ้นจาก Stooq CSV"""
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import load_config, safe_get, write_json


def coingecko(cfg) -> list:
    coins = ",".join(cfg["market"]["coingecko_coins"])
    url = (f"https://api.coingecko.com/api/v3/simple/price?ids={coins}"
           f"&vs_currencies={cfg['market']['coingecko_vs']}&include_24hr_change=true")
    r = safe_get(url)
    data = r.json()
    out = []
    for coin, v in data.items():
        out.append({
            "name": coin,
            "price_usd": v.get(cfg["market"]["coingecko_vs"]),
            "change_24h_pct": round(v.get(f"{cfg['market']['coingecko_vs']}_24h_change", 0), 2),
        })
    return out


def stooq(cfg) -> list:
    symbols = ",".join(cfg["market"]["stooq_symbols"])
    url = f"https://stooq.com/q/l/?s={symbols}&f=sd2t2ohlcv&h&e=csv"
    r = safe_get(url)
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        out.append({
            "symbol": row.get("Symbol", ""),
            "close": float(row["Close"]) if row.get("Close") else None,
            "open": float(row["Open"]) if row.get("Open") else None,
            "time": row.get("Time", ""),
        })
    return out


def main(out_path: Path) -> int:
    cfg = load_config(out_path.parents[1])
    payload = {"source": "market", "fetched_at": datetime.now(timezone.utc).isoformat()}
    errors = []
    try:
        payload["crypto"] = coingecko(cfg)
    except Exception as exc:
        errors.append(f"coingecko: {exc}")
    try:
        payload["stocks"] = stooq(cfg)
    except Exception as exc:
        errors.append(f"stooq: {exc}")
    write_json(out_path, payload)
    if errors:
        print("[market] partial: " + "; ".join(errors), file=sys.stderr)
    print(f"[market] crypto={len(payload.get('crypto', []))} stocks={len(payload.get('stocks', []) )}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
