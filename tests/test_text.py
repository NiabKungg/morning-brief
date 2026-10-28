from mib.common.text import canonical_url, fingerprint


def test_same_article_from_different_feeds_has_one_fingerprint():
    a = {"kind": "article", "source": "rss", "title": "X", "url": "http://www.example.com/story/?utm_source=hn&ref=rss"}
    b = {"kind": "post", "source": "reddit", "title": "Y", "url": "https://example.com/story#comments"}
    assert fingerprint(a) == fingerprint(b)


def test_canonical_url_keeps_meaningful_query_and_sorts_it():
    assert canonical_url("https://Example.com/watch?v=abc&utm_medium=x&t=10") == "https://example.com/watch?t=10&v=abc"
    assert canonical_url("https://example.com/a?id=1") != canonical_url("https://example.com/a?id=2")


def test_quotes_and_events_are_keyed_by_identity_not_by_url():
    btc_old = {"kind": "quote", "title": "Bitcoin", "url": "https://x/1", "metrics": {"symbol": "BTC", "price": 1}}
    btc_new = {"kind": "quote", "title": "Bitcoin", "url": "https://x/2", "metrics": {"symbol": "BTC", "price": 2}}
    assert fingerprint(btc_old) == fingerprint(btc_new)
    standup = {"kind": "event", "title": "Standup", "metrics": {"uid": "u1", "start": "2026-10-29T09:30+07:00"}}
    tomorrow = {**standup, "metrics": {"uid": "u1", "start": "2026-10-30T09:30+07:00"}}
    assert fingerprint(standup) != fingerprint(tomorrow)
