"""URL canonicalisation, item fingerprints and plain-text helpers (no third-party deps)."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src",
        "ref_url", "src", "si", "cmpid", "ncid", "ocid", "smid", "spm", "yclid", "_hsenc", "_hsmi",
        "guccounter", "guce_referrer", "guce_referrer_sig",
    }
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further had has
    have having he her here hers him his how i if in into is it its itself just me more most my new no nor
    not now of off on once only or other our out over own same she should so some such than that the their
    them then there these they this those through to too under until up very was we were what when where
    which while who whom why will with you your says said say via report reports today week year years
    one two first last get gets got make makes made use uses using now how why what show hn ask""".split()
)


def canonical_url(url: str | None) -> str | None:
    """Normalise a URL so the same article from different feeds collapses to one key."""
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return url
    host = parts.hostname.lower() if parts.hostname else ""
    if host.startswith("www."):
        host = host[4:]
    if host in ("m.youtube.com", "youtu.be"):
        host = "youtube.com"
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    query.sort()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit(("https", host + port, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    title = unicodedata.normalize("NFKC", title or "").lower()
    return " ".join(_WORD_RE.findall(title))


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def fingerprint(item: dict) -> str:
    """Stable identity of an item across crawls (used for upserts and dedupe)."""
    kind = item.get("kind")
    metrics = item.get("metrics") or {}
    if kind == "quote":
        return f"quote:{metrics.get('symbol') or item.get('title')}"
    if kind == "event":
        return f"event:{_digest((metrics.get('uid') or item.get('title') or '') + '|' + str(metrics.get('start')))}"
    url = canonical_url(item.get("url"))
    if url:
        return f"url:{_digest(url)}"
    return f"title:{_digest(item.get('source', '') + '|' + normalize_title(item.get('title', '')))}"


def html_to_text(fragment: str | None) -> str:
    """Cheap HTML -> text for feed summaries (feeds are small; full pages use trafilatura)."""
    if not fragment:
        return ""
    text = _SCRIPT_RE.sub(" ", fragment)
    text = re.sub(r"<\s*(br|/p|/div|/li|/h\d)\s*/?>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def clean_line(text: str | None) -> str:
    return _WS_RE.sub(" ", html.unescape(text or "")).strip()


def truncate(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"


def tokens(text: str) -> list[str]:
    """Lower-cased content words for similarity (keeps numbers and non-Latin scripts)."""
    words = _WORD_RE.findall(unicodedata.normalize("NFKC", text or "").lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]
