"""Cheap, deterministic stage before the LLM: junk rules and near-duplicate clustering.

Clusters spanning several outlets are also the strongest "connection" signal handed to the writer.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from mib.common.text import normalize_title, tokens

# Shopping/promo patterns only: a plain "deal" is usually business news ("lands first commercial deal").
JUNK_TITLE = re.compile(
    r"\b(?:deals|deal of the day|deal alert|on sale|\d+% off|coupons?|promo codes?|discount codes?|giveaway"
    r"|sponsored|black friday|cyber monday|prime day|gift guide|buying guide|best .{0,40}? (?:to buy|deals?)"
    r"|save (?:up to )?\$\d+|horoscope)\b",
    re.I,
)
REDDIT_META = re.compile(r"\b(?:weekly|daily|monthly)\s+(?:thread|discussion|megathread)\b|\bmegathread\b", re.I)
DUPLICATE = 0.42  # same story from another outlet: keep one representative
RELATED = 0.22  # same topic: kept, but hinted to the writer as a possible connection


def rule_reason(item: dict) -> str | None:
    title = item.get("title") or ""
    if len(normalize_title(title)) < 8:
        return "rule:short"
    if JUNK_TITLE.search(title):
        return "rule:deal"
    if item.get("source") == "reddit" and REDDIT_META.search(title):
        return "rule:meta"
    return None


def _vectors(items: list[dict]) -> list[dict[str, float]]:
    bags = [Counter(tokens(f"{it['title']} {it['title']} {(it.get('summary') or '')[:300]}")) for it in items]
    df = Counter(term for bag in bags for term in bag)
    n = len(bags)
    vectors = []
    for bag in bags:
        vec = {t: (1 + math.log(c)) * (math.log((n + 1) / (df[t] + 1)) + 1) for t, c in bag.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({t: v / norm for t, v in vec.items()})
    return vectors


def clusters(items: list[dict], threshold: float) -> list[list[int]]:
    """Groups of indices whose TF-IDF cosine similarity is >= threshold (single linkage)."""
    vectors = _vectors(items)
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    postings: dict[str, list[int]] = defaultdict(list)
    for i, vec in enumerate(vectors):
        for term in vec:
            postings[term].append(i)
    for i, vec in enumerate(vectors):
        scores: dict[int, float] = defaultdict(float)
        for term, weight in vec.items():
            for j in postings[term]:
                if j > i:
                    scores[j] += weight * vectors[j][term]
        for j, score in scores.items():
            if score >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    return list(groups.values())


@dataclass
class Deduped:
    candidates: list[dict]
    dropped: list[tuple[dict, str]]
    coverage: dict[int, list[str]] = field(default_factory=dict)  # representative id -> outlets covering it


def _rank(item: dict) -> tuple:
    triage = item.get("triage") or {}
    return (triage.get("reason") == "llm", item["kind"] == "article", len(item.get("summary") or ""),
            -(item["id"]))


def dedupe(items: list[dict]) -> Deduped:
    dropped: list[tuple[dict, str]] = []
    pool = []
    for item in items:
        reason = rule_reason(item)
        if reason:
            dropped.append((item, reason))
        else:
            pool.append(item)
    candidates, coverage = [], {}
    for group in clusters(pool, DUPLICATE):
        members = [pool[i] for i in group]
        rep = max(members, key=_rank)
        candidates.append(rep)
        outlets = sorted({m["source_name"] for m in members})
        if len(outlets) > 1:
            coverage[rep["id"]] = outlets
        dropped.extend((m, "dup") for m in members if m is not rep)
    candidates.sort(key=lambda it: it["id"])
    return Deduped(candidates=candidates, dropped=dropped, coverage=coverage)


def related(items: list[dict]) -> list[list[int]]:
    """Groups (by item id, size >= 2) of same-topic items, used as connection hints for the writer."""
    return [[items[i]["id"] for i in group] for group in clusters(items, RELATED) if len(group) > 1]
