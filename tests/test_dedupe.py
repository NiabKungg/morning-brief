from mib.hub.pipeline.dedupe import dedupe, rule_reason


def item(i, title, source_name="Feed", summary="", kind="article", source="rss"):
    return {"id": i, "title": title, "summary": summary, "source_name": source_name, "kind": kind, "source": source}


def test_shopping_promos_are_junk_but_business_deals_are_not():
    assert rule_reason(item(1, "The best Black Friday TV deals you can get right now")) == "rule:deal"
    assert rule_reason(item(2, "7 days until Founder Summit: Save up to $100 on your pass")) == "rule:deal"
    assert rule_reason(item(3, "Kodiak lands first commercial deal to supply driverless trucks")) is None
    assert rule_reason(item(4, "Weekly Discussion Thread", source="reddit")) == "rule:meta"


def test_same_story_from_two_outlets_collapses_to_one_with_coverage():
    story = "Liquid AI releases LFM3, a 1.7B model that runs agents on a Raspberry Pi 5"
    result = dedupe([
        item(1, story, "Hacker News"),
        item(2, "LFM3: Liquid AI's 1.7B model runs agents on a Raspberry Pi 5", "r/LocalLLaMA", kind="post"),
        item(3, "SK Hynix posts record third-quarter revenue", "Blognone"),
    ])
    assert sorted(c["id"] for c in result.candidates) == [1, 3]  # the article outranks the post
    assert [(d["id"], reason) for d, reason in result.dropped] == [(2, "dup")]
    assert result.coverage[1] == ["Hacker News", "r/LocalLLaMA"]
