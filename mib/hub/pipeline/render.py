"""Turn the writer's JSON + exact data (quotes, agenda, repos) into the brief document and its renditions.

DOC is what the web UI renders; Markdown is for copy/Discord; Telegram gets HTML-mode messages.
"""

from __future__ import annotations

import html
from datetime import datetime

from mib.hub.pipeline.triage import CATEGORY_LABELS

TITLES = {"en": {"daily": "Morning Intelligence Brief", "web": "Web Digest"},
          "th": {"daily": "สรุปข่าวกรองยามเช้า", "web": "สรุปเว็บไซต์"}}
HEADINGS = {
    "en": {"tldr": "TL;DR", "connections": "Connections", "github": "GitHub Trending", "markets": "Markets",
           "agenda": "Today", "watch": "Watch today", "sources": "Sources", "no_events": "No events today"},
    "th": {"tldr": "สรุปสั้น", "connections": "ความเชื่อมโยง", "github": "GitHub ยอดนิยม", "markets": "ตลาด",
           "agenda": "วันนี้", "watch": "จับตาวันนี้", "sources": "แหล่งข้อมูล", "no_events": "ไม่มีนัดหมายวันนี้"},
}
ICONS = {"ai": "🤖", "dev": "🛠", "security": "🔐", "hardware": "🔌", "business": "💼", "science": "🔭",
         "crypto": "🪙", "policy": "⚖️", "thailand": "🇹🇭", "other": "📰", "tldr": "⚡", "connections": "🔗",
         "github": "⭐", "markets": "📈", "agenda": "📅", "watch": "👀"}
_TH_DAYS = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
_TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
              "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
TELEGRAM_LIMIT = 3900  # Bot API hard limit is 4096 characters; keep headroom for entities.


def date_label(now: datetime, language: str) -> str:
    if language == "th":
        return f"{_TH_DAYS[now.weekday()]}ที่ {now.day} {_TH_MONTHS[now.month - 1]} {now.year + 543}"
    return now.strftime("%A, %-d %B %Y")


class _Citations:
    """Renumbers cited sources 1..k in order of first citation; uncited sources are dropped."""

    def __init__(self, sources: list[dict]) -> None:
        self._sources = sources
        self._map: dict[int, int] = {}

    def __call__(self, cites) -> list[int]:
        out = []
        for c in cites or []:
            if isinstance(c, int) and 1 <= c <= len(self._sources):
                if c not in self._map:
                    self._map[c] = len(self._map) + 1
                if self._map[c] not in out:
                    out.append(self._map[c])
        return out

    def listing(self) -> list[dict]:
        ordered = sorted(self._map.items(), key=lambda kv: kv[1])
        return [{"n": new, "title": self._sources[old - 1]["title"], "url": self._sources[old - 1].get("url"),
                 "source_name": self._sources[old - 1]["source_name"]} for old, new in ordered]


def _text(value, limit: int = 600) -> str:
    # Constrained decoding occasionally starts a value with the key separator (": Ars Technica …").
    return " ".join(str(value or "").split()).lstrip(":;,-–—•* ")[:limit]


def build_doc(out: dict, *, kind: str, sources: list[dict], repos: list[dict], quotes: list[dict] | None,
              events: list[dict] | None, language: str, now: datetime) -> dict:
    labels = CATEGORY_LABELS.get(language, CATEGORY_LABELS["en"])
    cite = _Citations(sources)
    doc: dict = {"kind": kind, "title": TITLES.get(language, TITLES["en"])[kind], "date_label": date_label(now, language),
                 "headline": _text(out.get("headline"), 200)}
    doc["tldr"] = [{"text": _text(b.get("text")), "cites": cite(b.get("cites"))}
                   for b in out.get("tldr") or [] if _text(b.get("text"))]
    doc["connections"] = [{"title": _text(c.get("title"), 120), "text": _text(c.get("text")), "cites": cite(c.get("cites"))}
                          for c in out.get("connections") or [] if _text(c.get("text"))]
    sections: dict[str, dict] = {}
    if kind == "web":
        for page in out.get("pages") or []:
            n = page.get("n")
            if not isinstance(n, int) or not 1 <= n <= len(sources):
                continue
            bullets = [{"text": _text(p), "cites": cite([n])} for p in page.get("points") or [] if _text(p)]
            if bullets:
                sections[f"page-{n}"] = {"key": f"page-{n}", "label": sources[n - 1]["title"], "bullets": bullets}
    else:
        # The writer is told not to repeat TL;DR stories in sections; small models still do, so enforce it.
        # Stories already explained under Connections are not repeated either.
        seen = {c for b in [*(out.get("tldr") or []), *(out.get("connections") or [])] for c in b.get("cites") or []}
        for sec in out.get("sections") or []:
            key = sec.get("key") if sec.get("key") in labels else "other"
            bullets = []
            for b in sec.get("bullets") or []:
                raw = [c for c in b.get("cites") or [] if isinstance(c, int)]
                if not _text(b.get("text")) or (raw and set(raw) <= seen):
                    continue
                seen.update(raw)
                bullets.append({"text": _text(b.get("text")), "cites": cite(raw)})
            if bullets:  # the model may emit the same key twice: merge
                sections.setdefault(key, {"key": key, "label": labels[key], "bullets": []})["bullets"] += bullets
    doc["sections"] = list(sections.values())
    doc["github"] = [{"name": r["title"], "url": r.get("url"), "description": r.get("summary") or "",
                      "language": (r.get("metrics") or {}).get("language"),
                      "language_color": (r.get("metrics") or {}).get("language_color"),
                      "stars_today": (r.get("metrics") or {}).get("stars_today"),
                      "stars": (r.get("metrics") or {}).get("stars")} for r in repos]
    doc["markets"] = None if quotes is None else {
        "note": _text(out.get("market_note")),
        "quotes": [{k: q["metrics"].get(k) for k in ("symbol", "name", "price", "currency", "change_pct")}
                   for q in quotes]}
    doc["agenda"] = None if events is None else {
        "note": _text(out.get("agenda_note")),
        "events": [{"title": e["title"], "start": e["metrics"].get("start"), "end": e["metrics"].get("end"),
                    "location": e["metrics"].get("location"), "all_day": bool(e["metrics"].get("all_day"))}
                   for e in events]}
    doc["watch"] = [_text(w, 200) for w in out.get("watch") or [] if _text(w)]
    doc["sources"] = cite.listing()
    return doc


def _price(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def _when(event: dict) -> str:
    if event["all_day"]:
        return "all day"
    start = (event.get("start") or "")[11:16]
    end = (event.get("end") or "")[11:16]
    return f"{start}–{end}" if end else start


# ---- Markdown -------------------------------------------------------------------------------------
def to_markdown(doc: dict, language: str) -> str:
    h = HEADINGS.get(language, HEADINGS["en"])
    src = {s["n"]: s for s in doc["sources"]}

    def cites(ns: list[int]) -> str:
        return "".join(f" [{n}]({src[n]['url']})" if src.get(n, {}).get("url") else f" [{n}]" for n in ns)

    lines = [f"# {doc['title']} — {doc['date_label']}", "", f"**{doc['headline']}**", ""]
    if doc["tldr"]:
        lines += [f"## {h['tldr']}", *[f"- {b['text']}{cites(b['cites'])}" for b in doc["tldr"]], ""]
    if doc["connections"]:
        lines += [f"## {h['connections']}", *[f"- **{c['title']}** — {c['text']}{cites(c['cites'])}"
                                              for c in doc["connections"]], ""]
    for sec in doc["sections"]:
        lines += [f"## {sec['label']}", *[f"- {b['text']}{cites(b['cites'])}" for b in sec["bullets"]], ""]
    if doc["github"]:
        lines.append(f"## {h['github']}")
        for r in doc["github"]:
            extra = " · ".join(x for x in (f"+{r['stars_today']:,} ★ today" if r.get("stars_today") else "",
                                            r.get("language") or "") if x)
            lines.append(f"- [{r['name']}]({r['url']})" + (f" — {extra}" if extra else "")
                         + (f" — {r['description']}" if r["description"] else ""))
        lines.append("")
    if doc["markets"] and doc["markets"]["quotes"]:
        lines += [f"## {h['markets']}", "", "| Asset | Price | 24h |", "|---|---:|---:|"]
        for q in doc["markets"]["quotes"]:
            change = "—" if q.get("change_pct") is None else f"{q['change_pct']:+.2f}%"
            lines.append(f"| {q['name']} ({q['symbol']}) | {_price(q.get('price'))} {q.get('currency') or ''} | {change} |")
        lines += ([f"", doc["markets"]["note"]] if doc["markets"]["note"] else []) + [""]
    if doc["agenda"] is not None:
        lines.append(f"## {h['agenda']}")
        lines += [f"- {_when(e)} {e['title']}" + (f" ({e['location']})" if e.get("location") else "")
                  for e in doc["agenda"]["events"]] or [f"- {h['no_events']}"]
        lines += ([doc["agenda"]["note"]] if doc["agenda"]["note"] else []) + [""]
    if doc["watch"]:
        lines += [f"## {h['watch']}", *[f"- {w}" for w in doc["watch"]], ""]
    if doc["sources"]:
        lines += [f"## {h['sources']}", *[f"{s['n']}. [{s['title']}]({s['url']}) — {s['source_name']}"
                                          for s in doc["sources"]]]
    return "\n".join(lines).strip() + "\n"


# ---- Telegram (HTML parse mode) ---------------------------------------------------------------------
def _e(text: str) -> str:
    return html.escape(text or "", quote=False)


def _a(url: str | None, label: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return _e(label)
    return f'<a href="{html.escape(url, quote=True)}">{_e(label)}</a>'


def to_telegram(doc: dict, language: str) -> list[str]:
    h = HEADINGS.get(language, HEADINGS["en"])
    src = {s["n"]: s for s in doc["sources"]}

    def cites(ns: list[int]) -> str:
        return "".join(" " + _a(src.get(n, {}).get("url"), f"[{n}]") for n in ns)

    blocks = [f"☀️ <b>{_e(doc['title'])}</b>\n<i>{_e(doc['date_label'])}</i>\n\n<b>{_e(doc['headline'])}</b>"]
    if doc["tldr"]:
        blocks.append(f"{ICONS['tldr']} <b>{_e(h['tldr'])}</b>\n"
                      + "\n".join(f"• {_e(b['text'])}{cites(b['cites'])}" for b in doc["tldr"]))
    if doc["connections"]:
        blocks.append(f"{ICONS['connections']} <b>{_e(h['connections'])}</b>\n"
                      + "\n".join(f"▸ <b>{_e(c['title'])}</b> — {_e(c['text'])}{cites(c['cites'])}"
                                  for c in doc["connections"]))
    for sec in doc["sections"]:
        icon = ICONS.get(sec["key"], "📄")
        blocks.append(f"{icon} <b>{_e(sec['label'])}</b>\n"
                      + "\n".join(f"• {_e(b['text'])}{cites(b['cites'])}" for b in sec["bullets"]))
    if doc["github"]:
        rows = []
        for r in doc["github"][:5]:
            meta = " · ".join(x for x in (f"+{r['stars_today']:,}★" if r.get("stars_today") else "",
                                           r.get("language") or "") if x)
            rows.append(f"• {_a(r['url'], r['name'])}" + (f" <i>{_e(meta)}</i>" if meta else "")
                        + (f"\n   {_e(r['description'][:140])}" if r["description"] else ""))
        blocks.append(f"{ICONS['github']} <b>{_e(h['github'])}</b>\n" + "\n".join(rows))
    if doc["markets"] and doc["markets"]["quotes"]:
        width = max(len(q["symbol"]) for q in doc["markets"]["quotes"])
        rows = []
        for q in doc["markets"]["quotes"]:
            change = "" if q.get("change_pct") is None else f"{'▲' if q['change_pct'] >= 0 else '▼'}{abs(q['change_pct']):.2f}%"
            rows.append(f"{q['symbol']:<{width}}  {_price(q.get('price')):>12}  {change}")
        block = f"{ICONS['markets']} <b>{_e(h['markets'])}</b>\n<pre>{_e(chr(10).join(rows))}</pre>"
        if doc["markets"]["note"]:
            block += f"\n<i>{_e(doc['markets']['note'])}</i>"
        blocks.append(block)
    if doc["agenda"] is not None:
        rows = [f"• <b>{_e(_when(e))}</b> {_e(e['title'])}" + (f" ({_e(e['location'])})" if e.get("location") else "")
                for e in doc["agenda"]["events"]] or [f"• {_e(h['no_events'])}"]
        block = f"{ICONS['agenda']} <b>{_e(h['agenda'])}</b>\n" + "\n".join(rows)
        if doc["agenda"]["note"]:
            block += f"\n<i>{_e(doc['agenda']['note'])}</i>"
        blocks.append(block)
    if doc["watch"]:
        blocks.append(f"{ICONS['watch']} <b>{_e(h['watch'])}</b>\n" + "\n".join(f"• {_e(w)}" for w in doc["watch"]))
    return pack(blocks, TELEGRAM_LIMIT)


def pack(blocks: list[str], limit: int) -> list[str]:
    """Greedy packing of self-contained blocks into messages <= limit; oversized blocks split on lines."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        pieces = [block] if len(block) <= limit else _split_lines(block, limit)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    messages.append(current)
                current = piece
    if current:
        messages.append(current)
    return messages


def _split_lines(block: str, limit: int) -> list[str]:
    out, current = [], ""
    for line in block.split("\n"):
        line = line if len(line) <= limit else line[: limit - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            out.append(current)
            current = line
    if current:
        out.append(current)
    return out
