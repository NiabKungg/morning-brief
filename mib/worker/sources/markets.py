"""Crypto via CoinGecko's public API; stocks, indices and FX via Yahoo Finance's chart endpoint."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from mib.worker.http import Http

_LABELS = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^SET.BK": "SET Index",
           "^N225": "Nikkei 225", "THB=X": "USD/THB", "^VIX": "VIX"}


def _quote_item(*, symbol: str, name: str, price: float, currency: str | None, change_pct: float | None,
                url: str, asset: str) -> dict:
    return {
        "source": "markets",
        "source_name": "Markets",
        "kind": "quote",
        "title": f"{name} ({symbol})" if name != symbol else symbol,
        "url": url,
        "author": None,
        "published_at": None,
        "summary": "",
        "content": None,
        "metrics": {
            "symbol": symbol,
            "name": name,
            "price": price,
            "currency": currency,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "asset": asset,
        },
    }


async def _crypto(http: Http, ids: list[str]) -> list[dict]:
    url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&price_change_percentage=24h&ids="
           + ",".join(quote(i) for i in ids))
    data = await http.get_json(url)
    order = {cid: i for i, cid in enumerate(ids)}
    items = [
        _quote_item(symbol=c["symbol"].upper(), name=c["name"], price=c["current_price"], currency="USD",
                    change_pct=c.get("price_change_percentage_24h"),
                    url=f"https://www.coingecko.com/en/coins/{c['id']}", asset="crypto")
        for c in sorted(data, key=lambda c: order.get(c["id"], 99))
        if c.get("current_price") is not None
    ]
    return items


async def _yahoo(http: Http, symbol: str) -> dict:
    data = await http.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=1d&interval=1d")
    meta = data["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = (price - prev) / prev * 100 if prev else None
    name = _LABELS.get(symbol) or meta.get("shortName") or meta.get("longName") or symbol
    display = symbol.lstrip("^").removesuffix("=X")
    return _quote_item(symbol=display, name=name, price=price, currency=meta.get("currency"), change_pct=change,
                       url=f"https://finance.yahoo.com/quote/{quote(symbol)}", asset="fx" if symbol.endswith("=X") else "equity")


async def fetch(http: Http, *, crypto: list[str], symbols: list[str]) -> list[dict]:
    tasks = []
    if crypto:
        tasks.append(_crypto(http, crypto))
    results = await asyncio.gather(*tasks, *(_yahoo(http, s) for s in symbols), return_exceptions=True)
    items: list[dict] = []
    errors = []
    for res in results:
        if isinstance(res, Exception):
            errors.append(res)
        elif isinstance(res, list):
            items.extend(res)
        else:
            items.append(res)
    if errors and not items:
        raise errors[0]
    return items
