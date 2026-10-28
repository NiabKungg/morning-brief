from datetime import datetime
from zoneinfo import ZoneInfo

from mib.hub.pipeline.render import TELEGRAM_LIMIT, build_doc, date_label, pack, to_telegram

NOW = datetime(2026, 10, 29, 7, 30, tzinfo=ZoneInfo("Asia/Bangkok"))


def src(i, title):
    return {"id": i, "title": title, "url": f"https://example.com/{i}", "source_name": "Feed", "kind": "article"}


def test_citations_are_renumbered_by_first_use_and_uncited_sources_dropped():
    sources = [src(1, "One"), src(2, "Two"), src(3, "Three")]
    out = {"headline": "H", "tldr": [{"text": "about three", "cites": [3]}, {"text": "about one", "cites": [1, 99]}],
           "sections": [], "connections": [], "watch": []}
    doc = build_doc(out, kind="daily", sources=sources, repos=[], quotes=None, events=None, language="en", now=NOW)
    assert [b["cites"] for b in doc["tldr"]] == [[1], [2]]
    assert [(s["n"], s["title"]) for s in doc["sources"]] == [(1, "Three"), (2, "One")]


def test_sections_never_repeat_a_tldr_story_or_each_other():
    sources = [src(1, "One"), src(2, "Two"), src(3, "Three")]
    out = {"headline": "H", "tldr": [{"text": "one", "cites": [1]}], "connections": [], "watch": [],
           "sections": [{"key": "ai", "bullets": [{"text": "one again", "cites": [1]}, {"text": "two", "cites": [2]}]},
                        {"key": "dev", "bullets": [{"text": "two again", "cites": [2]}, {"text": "three", "cites": [3]}]}]}
    doc = build_doc(out, kind="daily", sources=sources, repos=[], quotes=None, events=None, language="en", now=NOW)
    assert [[b["text"] for b in s["bullets"]] for s in doc["sections"]] == [["two"], ["three"]]


def test_telegram_output_escapes_titles_and_respects_the_message_limit():
    sources = [src(i, f"Story {i}") for i in range(1, 41)]
    long_text = "A sentence with <b>markup</b> & ampersands that is long enough to need many messages. " * 2
    out = {"headline": "<script>alert(1)</script>",
           "tldr": [{"text": long_text, "cites": [i]} for i in range(1, 4)],
           "sections": [{"key": "ai", "bullets": [{"text": long_text, "cites": [i]} for i in range(j, j + 3)]}
                        for j in range(4, 40, 3)],
           "connections": [], "watch": []}
    doc = build_doc(out, kind="daily", sources=sources, repos=[], quotes=None, events=None, language="en", now=NOW)
    messages = to_telegram(doc, "en")
    assert len(messages) > 1
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    assert "<script>" not in messages[0] and "&lt;script&gt;" in messages[0]
    assert all(m.count("<b>") == m.count("</b>") for m in messages)


def test_pack_never_splits_a_block_that_fits():
    blocks = ["a" * 30, "b" * 30, "c" * 30]
    assert pack(blocks, 70) == ["a" * 30 + "\n\n" + "b" * 30, "c" * 30]


def test_thai_date_uses_buddhist_era():
    assert date_label(NOW, "th") == "วันพฤหัสบดีที่ 29 ตุลาคม 2569"
    assert date_label(NOW, "en") == "Thursday, 29 October 2026"
