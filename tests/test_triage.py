import json

from mib.hub.pipeline.triage import parse, select, verdict


def story(i, score, category="ai", source="Feed", reason="llm"):
    return {"id": i, "source_name": source, "published_at": None,
            "triage": {"score": score, "keep": score >= 6, "category": category, "reason": reason}}


def test_select_caps_each_category_and_outlet_and_skips_junk():
    candidates = ([story(i, 9, "ai", f"Feed{i % 3}") for i in range(10)]
                  + [story(100, 8, "security", "Ars")]
                  + [story(200, 10, "ai", "Spam", reason="llm:junk")])
    chosen = select(candidates, {}, threshold=6, limit=20)
    assert sum(c["triage"]["category"] == "ai" for c in chosen) == 6
    assert 100 in {c["id"] for c in chosen}
    assert 200 not in {c["id"] for c in chosen}


def test_quiet_day_tops_up_with_near_misses_but_not_noise():
    candidates = [story(1, 8), story(2, 5), story(3, 4), story(4, 1)]
    assert [c["id"] for c in select(candidates, {}, threshold=6, limit=20)] == [1, 2, 3]


def test_parse_ignores_unknown_and_repeated_ids_and_verdict_drops_junk():
    batch = [{"id": 7}, {"id": 9}]
    text = json.dumps({"items": [
        {"id": 7, "why": "relevant", "junk": False, "category": "ai", "score": 8},
        {"id": 7, "why": "again", "junk": False, "category": "ai", "score": 1},
        {"id": 5, "why": "not in batch", "junk": False, "category": "ai", "score": 9},
        {"id": 9, "why": "an ad", "junk": True, "category": "nope", "score": 9},
    ]})
    results = parse(text, batch)
    assert [(r["item_id"], r["score"], r["category"]) for r in results] == [(7, 8, "ai"), (9, 9, "other")]
    assert verdict(results[1], threshold=6) == (False, "llm:junk")
    assert verdict(results[0], threshold=9) == (False, "llm")
