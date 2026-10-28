"""The writer: LFM3 turns the selected sources into the executive brief (grammar-constrained JSON).

Small-model techniques that made the difference in testing on LFM3-1.7B:
- pointer first: every bullet names ONE source number *before* its sentence, so the sentence stays about
  that source (free-form bullets citing several sources became run-on lists of unrelated stories);
- grounded connections: code finds groups of same-topic sources (TF-IDF) and a short, focused call per group
  decides whether they really share a story and explains the link;
- exact facts (prices, % changes, calendar times, star counts) are rendered by code, never by the model.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from mib.common.text import truncate
from mib.hub.grammar import compact_json_grammar
from mib.hub.pipeline.triage import CATEGORIES

LANGUAGE_RULE = {
    "en": "Write in clear, concise English.",
    "th": "Write every text value in Thai (ภาษาไทย). Keep names of products, companies and people as they are.",
}

SYSTEM = """You are the reader's chief of staff. You write their morning executive brief from numbered sources.
Rules:
- Use ONLY the sources given. Never invent facts, numbers, names or dates.
- Every bullet is about exactly ONE source: first give its number in "source", then one sentence on what happened and why it matters to this reader.
- {language}"""

TASK = """Write the brief as JSON:
- top_source: the number of the single most important source today
- headline: at most 12 words about that one source only
- tldr: the 3 most important stories
- sections: other notable stories grouped by category key, most important first, at most 3 per section; never repeat a tldr story
- market_note: one sentence on the most notable move, using only MARKETS ("" if no MARKETS)
- agenda_note: one sentence to prepare for today's agenda ("" if no AGENDA)
- watch: up to 3 short things to watch today"""

HEADLINE_MAX = 120
BULLET_MAX = 200


def _bullet(ids: list[int]) -> dict:
    return {"type": "object", "properties": {"source": {"type": "integer", "enum": ids},
                                             "text": {"type": "string", "minLength": 10, "maxLength": BULLET_MAX}}}


def brief_schema(ids: list[int], keys: list[str]) -> dict:
    return {"type": "object", "properties": {
        "top_source": {"type": "integer", "enum": ids},
        "headline": {"type": "string", "minLength": 10, "maxLength": HEADLINE_MAX},
        "tldr": {"type": "array", "minItems": min(3, len(ids)), "maxItems": 3, "items": _bullet(ids)},
        "sections": {"type": "array", "minItems": 0, "maxItems": 5, "items": {
            "type": "object", "properties": {"key": {"type": "string", "enum": keys},
                                             "bullets": {"type": "array", "minItems": 1, "maxItems": 3,
                                                         "items": _bullet(ids)}}}},
        "market_note": {"type": "string", "maxLength": 220},
        "agenda_note": {"type": "string", "maxLength": 200},
        "watch": {"type": "array", "minItems": 0, "maxItems": 3,
                  "items": {"type": "string", "minLength": 4, "maxLength": 120}},
    }}


def tidy(text: str, cap: int) -> str:
    """A value that hit its grammar cap was cut mid-word: end it at the last whole word."""
    text = (text or "").strip()
    if len(text) >= cap - 1 and " " in text:
        text = text[: text.rfind(" ")].rstrip(" ,;:-–—") + "…"
    return text


def _num(value) -> str:
    if value is None:
        return "?"
    value = float(value)
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def source_block(n: int, item: dict, lead_chars: int = 330) -> str:
    triage = item.get("triage") or {}
    meta = [item["source_name"]]
    if triage.get("category"):
        meta.append(triage["category"])
    if item["kind"] == "repo":
        m = item.get("metrics") or {}
        meta.append(f"GitHub repo, +{m.get('stars_today') or 0} stars today"
                    + (f", {m['language']}" if m.get("language") else ""))
    lead = truncate((item.get("summary") or "").replace("\n", " "), lead_chars)
    return f"[{n}] {' · '.join(meta)} — {item['title']}" + (f"\n    {lead}" if lead else "")


def market_lines(quotes: list[dict]) -> list[str]:
    lines = []
    for q in quotes:
        m = q["metrics"]
        change = "" if m.get("change_pct") is None else f" ({m['change_pct']:+.2f}% 24h)"
        lines.append(f"{m['name']} ({m['symbol']}): {_num(m.get('price'))} {m.get('currency') or ''}{change}".strip())
    return lines


def agenda_lines(events: list[dict]) -> list[str]:
    lines = []
    for ev in events:
        m = ev["metrics"]
        when = "all day" if m.get("all_day") else m["start"][11:16] + (f"–{m['end'][11:16]}" if m.get("end") else "")
        lines.append(f"{when} {ev['title']}" + (f" ({m['location']})" if m.get("location") else ""))
    return lines


def numbered_groups(sources: list[dict], related: list[list[int]]) -> list[list[int]]:
    """Related groups (item ids) -> lists of source numbers, largest first, at most 3."""
    number = {item["id"]: n for n, item in enumerate(sources, 1)}
    groups = [sorted(number[i] for i in group if i in number) for group in related]
    return sorted((g for g in groups if len(g) > 1), key=len, reverse=True)[:3]


def brief_messages(*, sources: list[dict], quotes: list[dict], events: list[dict] | None, profile: dict,
                   date_label: str, tz: str) -> list[dict]:
    parts = [f"Today: {date_label} ({tz})",
             f"Reader: {profile.get('name') or 'the reader'}; interests: {profile['interests']}",
             "", "SOURCES"]
    parts += [source_block(n, item) for n, item in enumerate(sources, 1)]
    if quotes:
        parts += ["", "MARKETS", *market_lines(quotes)]
    if events:
        parts += ["", "AGENDA", *agenda_lines(events)]
    parts += ["", TASK]
    language = LANGUAGE_RULE.get(profile.get("language"), LANGUAGE_RULE["en"])
    return [{"role": "system", "content": SYSTEM.format(language=language)},
            {"role": "user", "content": "\n".join(parts)}]


def section_keys(sources: list[dict]) -> list[str]:
    present = {(s.get("triage") or {}).get("category") for s in sources}
    if any(s["kind"] == "repo" for s in sources):
        present.add("dev")
    return [c for c in CATEGORIES if c in present] or ["other"]


def _as_cited(bullets) -> list[dict]:
    return [{"text": tidy(b.get("text", ""), BULLET_MAX), "cites": [b["source"]] if isinstance(b.get("source"), int) else []}
            for b in bullets or []]


async def write_brief(*, sources: list[dict], quotes: list[dict], events: list[dict] | None, profile: dict,
                      date_label: str, tz: str, complete: Callable[..., Awaitable]) -> tuple[dict, dict]:
    ids = list(range(1, len(sources) + 1))
    completion = await complete(brief_messages(sources=sources, quotes=quotes, events=events, profile=profile,
                                               date_label=date_label, tz=tz),
                                grammar=compact_json_grammar(brief_schema(ids, section_keys(sources))),
                                max_tokens=1600)
    out = json.loads(completion.text)
    out["headline"] = tidy(out.get("headline", ""), HEADLINE_MAX)
    out["tldr"] = _as_cited(out.get("tldr"))
    for section in out.get("sections") or []:
        section["bullets"] = _as_cited(section.get("bullets"))
    return out, completion.stats


CONNECT_SYSTEM = """You are an intelligence analyst. Decide whether the numbered news items below are about the same story, or whether one directly affects the other. Use only the text given. {language}"""
CONNECT_TASK = """Answer as JSON:
- related: true only if they are about the same story or one directly affects the other
- title: at most 6 words naming the shared story
- text: one sentence of at most 30 words on what links them and why it matters to the reader"""


def connect_schema() -> dict:
    return {"type": "object", "properties": {"related": {"type": "boolean"},
                                             "title": {"type": "string", "minLength": 4, "maxLength": 60},
                                             "text": {"type": "string", "minLength": 10, "maxLength": 320}}}


async def find_connection(group: list[int], sources: list[dict], profile: dict,
                          complete: Callable[..., Awaitable]) -> dict | None:
    language = LANGUAGE_RULE.get(profile.get("language"), LANGUAGE_RULE["en"])
    body = "\n".join(source_block(n, sources[n - 1], 260) for n in group)
    messages = [{"role": "system", "content": CONNECT_SYSTEM.format(language=language)},
                {"role": "user", "content": f"Reader interests: {profile['interests']}\n\n{body}\n\n{CONNECT_TASK}"}]
    completion = await complete(messages, grammar=compact_json_grammar(connect_schema()), max_tokens=200)
    answer = json.loads(completion.text)
    if not answer.get("related"):
        return None
    return {"title": tidy(answer.get("title", ""), 60), "text": tidy(answer.get("text", ""), 320), "cites": group}


WEB_TASK = """Write a digest of these crawled pages as JSON:
- headline: what these pages are about, at most 12 words
- tldr: up to 3 key takeaways across all pages
- connections: up to 2 themes that link several pages ([] if none)
- pages: for each page number, up to 3 short key points from that page"""


def web_schema(ids: list[int]) -> dict:
    point = {"type": "string", "minLength": 8, "maxLength": BULLET_MAX}
    return {"type": "object", "properties": {
        "headline": {"type": "string", "minLength": 8, "maxLength": HEADLINE_MAX},
        "tldr": {"type": "array", "minItems": 1, "maxItems": 3, "items": _bullet(ids)},
        "connections": {"type": "array", "minItems": 0, "maxItems": 2 if len(ids) > 1 else 0, "items": {
            "type": "object", "properties": {"title": {"type": "string", "minLength": 4, "maxLength": 60},
                                             "text": {"type": "string", "minLength": 10, "maxLength": 240},
                                             "cites": {"type": "array", "minItems": 2, "maxItems": 4,
                                                       "items": {"type": "integer", "enum": ids}}}}},
        "pages": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": {
            "type": "object", "properties": {"n": {"type": "integer", "enum": ids},
                                             "points": {"type": "array", "minItems": 1, "maxItems": 3,
                                                        "items": point}}}},
    }}


async def write_web_digest(*, pages: list[dict], profile: dict, complete: Callable[..., Awaitable]) -> tuple[dict, dict]:
    ids = list(range(1, len(pages) + 1))
    budget = max(500, 6000 // max(1, len(pages)))
    blocks = [f"[{n}] {p['title']} — {p['url']}\n"
              f"{truncate((p.get('content') or p.get('summary') or '').replace(chr(10), ' '), budget)}"
              for n, p in enumerate(pages, 1)]
    language = LANGUAGE_RULE.get(profile.get("language"), LANGUAGE_RULE["en"])
    messages = [{"role": "system", "content": SYSTEM.format(language=language)},
                {"role": "user", "content": "PAGES\n" + "\n\n".join(blocks) + "\n\n" + WEB_TASK}]
    completion = await complete(messages, grammar=compact_json_grammar(web_schema(ids)), max_tokens=1400)
    out = json.loads(completion.text)
    out["headline"] = tidy(out.get("headline", ""), HEADLINE_MAX)
    out["tldr"] = _as_cited(out.get("tldr"))
    for page in out.get("pages") or []:
        page["points"] = [tidy(p, BULLET_MAX) for p in page.get("points") or []]
    return out, completion.stats
