"""LLM triage: LFM3 scores every new item 0-10 for this reader, flags junk and assigns a category.

A short "why" is generated before the verdict: on LFM3-1.7B without it (thinking disabled) the
scores were close to random in testing; with it they matched an editor's judgement.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from mib.common.text import truncate
from mib.hub.grammar import compact_json_grammar

CATEGORIES = ["ai", "dev", "security", "hardware", "business", "science", "crypto", "policy", "thailand", "other"]
CATEGORY_LABELS = {
    "en": {"ai": "AI & Machine Learning", "dev": "Developers & Open Source", "security": "Security & Privacy",
           "hardware": "Hardware & Devices", "business": "Business & Startups", "science": "Science & Space",
           "crypto": "Crypto & Markets", "policy": "Policy & Society", "thailand": "Thailand", "other": "Other"},
    "th": {"ai": "AI และแมชชีนเลิร์นนิง", "dev": "นักพัฒนาและโอเพนซอร์ส", "security": "ความปลอดภัยและความเป็นส่วนตัว",
           "hardware": "ฮาร์ดแวร์และอุปกรณ์", "business": "ธุรกิจและสตาร์ทอัพ", "science": "วิทยาศาสตร์และอวกาศ",
           "crypto": "คริปโตและตลาด", "policy": "นโยบายและสังคม", "thailand": "ประเทศไทย", "other": "อื่น ๆ"},
}
BATCH = 10

SYSTEM = """You are the triage editor of a personal morning intelligence brief.
Reader interests: {interests}

For every item, in the given order, output:
- why: at most 8 words on what it is and whether it matters to this reader
- junk: true for advertising, shopping deals, sponsored or event promotions, clickbait, memes, jokes, vague rumours, low-effort questions or rants
- category: ai, dev, security, hardware, business, science, crypto, policy, thailand or other (thailand = about Thailand)
- score: usefulness for THIS reader from 0 to 10. 9-10 must-know news; 7-8 relevant with substance; 4-6 somewhat relevant; 0-3 irrelevant or junk."""


def schema(ids: list[int]) -> dict:
    return {"type": "object", "properties": {"items": {
        "type": "array", "minItems": len(ids), "maxItems": len(ids),
        "items": {"type": "object", "properties": {
            "id": {"type": "integer", "enum": ids},
            "why": {"type": "string", "minLength": 3, "maxLength": 60},
            "junk": {"type": "boolean"},
            "category": {"type": "string", "enum": CATEGORIES},
            "score": {"type": "integer", "minimum": 0, "maximum": 10},
        }},
    }}}


def item_line(item: dict, coverage: dict[int, list[str]]) -> str:
    line = f"[{item['id']}] {item['source_name']} | {item['title']}"
    lead = truncate(item.get("summary") or "", 170)
    if lead:
        line += f" — {lead}"
    if item["id"] in coverage:
        line += f" (also covered by {len(coverage[item['id']]) - 1} other outlets)"
    return line.replace("\n", " ")


def messages(batch: list[dict], coverage: dict[int, list[str]], interests: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM.format(interests=interests)},
        {"role": "user", "content": "Items:\n" + "\n".join(item_line(it, coverage) for it in batch)},
    ]


def parse(text: str, batch: list[dict]) -> list[dict]:
    """Grammar-constrained output; still validated so a truncated stream cannot corrupt state."""
    by_id = {it["id"]: it for it in batch}
    results, seen = [], set()
    for row in json.loads(text)["items"]:
        item_id = row.get("id")
        if item_id not in by_id or item_id in seen:
            continue
        seen.add(item_id)
        score = max(0, min(10, int(row.get("score", 0))))
        junk = bool(row.get("junk"))
        category = row.get("category") if row.get("category") in CATEGORIES else "other"
        results.append({"item_id": item_id, "score": score, "junk": junk, "category": category,
                        "why": str(row.get("why", ""))[:120]})
    return results


async def triage(batch: list[dict], coverage: dict[int, list[str]], interests: str,
                 complete: Callable[..., Awaitable]) -> list[dict]:
    completion = await complete(messages(batch, coverage, interests),
                                grammar=compact_json_grammar(schema([it["id"] for it in batch])),
                                max_tokens=60 * len(batch) + 60)
    return parse(completion.text, batch)


def verdict(result: dict, threshold: int) -> tuple[bool, str]:
    """(keep, reason) stored for an LLM result: junk is dropped outright, otherwise the score decides."""
    if result["junk"]:
        return False, "llm:junk"
    return result["score"] >= threshold, "llm"


def select(candidates: list[dict], coverage: dict[int, list[str]], *, threshold: int, limit: int) -> list[dict]:
    """Best items with diversity caps (per category and per outlet); tops up from near-misses on quiet days."""
    def rank(item: dict) -> tuple:
        t = item["triage"]
        return (t.get("score") or 0, len(coverage.get(item["id"], [])), item.get("published_at") or "")

    scored = sorted((c for c in candidates if (c.get("triage") or {}).get("reason") == "llm"), key=rank, reverse=True)
    per_cat: dict[str, int] = {}
    per_src: dict[str, int] = {}
    chosen: list[dict] = []
    for item in scored:
        if item["triage"]["score"] < threshold:
            continue
        cat = item["triage"]["category"]
        if per_cat.get(cat, 0) >= 6 or per_src.get(item["source_name"], 0) >= 5:
            continue
        per_cat[cat] = per_cat.get(cat, 0) + 1
        per_src[item["source_name"]] = per_src.get(item["source_name"], 0) + 1
        chosen.append(item)
        if len(chosen) >= limit:
            break
    minimum = min(5, limit)
    if len(chosen) < minimum:
        chosen += [c for c in scored if c not in chosen and c["triage"]["score"] >= 3][:minimum - len(chosen)]
    return chosen
