#!/usr/bin/env python3
"""fetch_market.py — ราคาคริปโตจาก CoinGecko และหุ้นจาก Yahoo Finance chart API"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import load_config, safe_get, write_json


def coingecko(cfg) -> list:
    coins = ",".join(cfg["market"]["coingecko_coins"])
    vs = cfg["market"]["coingecko_vs"]
    url = (f"https://api.coingecko.com/api/v3/simple/price?ids={coins}"
           f"&vs_currencies={vs}&include_24hr_change=true")
    r = safe_get(url)
    data = r.json()
    out = []
    for coin, v in data.items():
        out.append({
            "name": coin,
            "price_usd": v.get(vs),
            "change_24h_pct": round(v.get(f"{vs}_24h_change", 0), 2),
        })
    return out


def yahoo(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
    r = safe_get(url)
    meta = r.json()["chart"]["result"][0]["meta"]
    return {
        "symbol": meta.get("symbol", symbol),
        "price": meta.get("regularMarketPrice"),
        "prev_close": meta.get("chartPreviousClose"),
        "currency": meta.get("currency", "USD"),
    }


def main(out_path: Path) -> int:
    cfg = load_config(out_path)
    payload = {"source": "market", "fetched_at": datetime.now(timezone.utc).isoformat()}
    errors = []
    try:
        payload["crypto"] = coingecko(cfg)
    except Exception as exc:
        errors.append(f"coingecko: {exc}")
    payload["stocks"] = []
    for sym in cfg["market"]["yahoo_symbols"]:
        try:
            payload["stocks"].append(yahoo(sym))
        except Exception as exc:
            errors.append(f"{sym}: {exc}")
    write_json(out_path, payload)
    if errors:
        print("[market] partial: " + "; ".join(errors), file=sys.stderr)
    print(f"[market] crypto={len(payload.get('crypto', []))} stocks={len(payload.get('stocks', []))}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
