"""User-editable settings, stored as one JSON document. Secrets never leave the hub in API responses."""

from __future__ import annotations

import copy
import re
from typing import Any

from mib.hub.db import DB

DEFAULT_INTERESTS = (
    "AI & LLMs (especially small/on-device models), Raspberry Pi & self-hosting, developer tools & open source, "
    "cybersecurity, startups & big tech, notable crypto/market moves, Thai tech news"
)

DEFAULTS: dict[str, Any] = {
    "profile": {"name": "", "interests": DEFAULT_INTERESTS, "language": "en"},
    "schedule": {"enabled": True, "collect_times": ["00:30", "02:30", "04:30", "06:30"], "brief_time": "07:30",
                 "prep_minutes": 25},
    "sources": {
        "rss": {
            "enabled": True,
            "per_feed": 10,
            "feeds": [
                {"name": "Hacker News", "url": "https://news.ycombinator.com/rss", "enabled": True},
                {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "enabled": True},
                {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "enabled": True},
                {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "enabled": True},
                {"name": "Blognone", "url": "https://www.blognone.com/atom.xml", "enabled": True},
            ],
        },
        "github": {"enabled": True, "since": "daily", "languages": [""], "limit": 12},
        "reddit": {"enabled": True, "subreddits": ["LocalLLaMA", "selfhosted", "raspberry_pi"], "period": "day",
                   "per_sub": 6, "threads": []},
        "markets": {"enabled": True, "crypto": ["bitcoin", "ethereum", "solana"],
                    "symbols": ["^GSPC", "^IXIC", "NVDA", "^SET.BK", "THB=X"]},
        "calendar": {"enabled": False, "ics_urls": [], "days": 1},
    },
    "pipeline": {"window_hours": 24, "triage_threshold": 6, "max_brief_items": 20, "enrich_limit": 30},
    "delivery": {
        "telegram": {"enabled": True, "token": "", "chat_id": ""},
        "discord": {"enabled": False, "webhook": ""},
    },
}

SECRET_PATHS = (("delivery", "telegram", "token"), ("delivery", "discord", "webhook"), ("sources", "calendar", "ics_urls"))
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LIMITS = {
    ("schedule", "prep_minutes"): (5, 120),
    ("sources", "rss", "per_feed"): (1, 40),
    ("sources", "github", "limit"): (1, 25),
    ("sources", "reddit", "per_sub"): (1, 25),
    ("sources", "calendar", "days"): (1, 7),
    ("pipeline", "window_hours"): (6, 72),
    ("pipeline", "triage_threshold"): (0, 10),
    ("pipeline", "max_brief_items"): (6, 40),
    ("pipeline", "enrich_limit"): (0, 60),
}
_CHOICES = {
    ("profile", "language"): ("en", "th"),
    ("sources", "github", "since"): ("daily", "weekly", "monthly"),
    ("sources", "reddit", "period"): ("hour", "day", "week"),
}


class SettingsError(ValueError):
    pass


def _merge_defaults(defaults: Any, stored: Any) -> Any:
    if isinstance(defaults, dict):
        stored = stored if isinstance(stored, dict) else {}
        return {k: _merge_defaults(v, stored.get(k)) for k, v in defaults.items()}
    return copy.deepcopy(defaults) if stored is None else stored


def _http_url(value: Any, path: tuple) -> str:
    if not isinstance(value, str) or not value.strip().startswith(("http://", "https://")):
        raise SettingsError(f"{'.'.join(path)}: expected an http(s) URL")
    return value.strip()


def _clean(path: tuple, default: Any, value: Any) -> Any:
    """Validate/coerce one leaf against its default's type and the rules above."""
    dotted = ".".join(path)
    if path in SECRET_PATHS:
        if isinstance(default, list):
            if not isinstance(value, list):
                raise SettingsError(f"{dotted}: expected a list of URLs")
            return [_http_url(v, path) for v in value if str(v).strip()]
        if not isinstance(value, str):
            raise SettingsError(f"{dotted}: expected a string")
        return value.strip()
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"{dotted}: expected true/false")
        return value
    if isinstance(default, int):
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{dotted}: expected an integer") from None
        lo, hi = _LIMITS.get(path, (-10**9, 10**9))
        return max(lo, min(hi, number))
    if isinstance(default, str):
        if not isinstance(value, str):
            raise SettingsError(f"{dotted}: expected a string")
        value = value.strip()[:4000]
        if path in _CHOICES and value not in _CHOICES[path]:
            raise SettingsError(f"{dotted}: must be one of {', '.join(_CHOICES[path])}")
        if path == ("schedule", "brief_time") and not _TIME_RE.match(value):
            raise SettingsError("schedule.brief_time: expected HH:MM")
        return value
    if isinstance(default, list):
        if not isinstance(value, list):
            raise SettingsError(f"{dotted}: expected a list")
        if path == ("sources", "rss", "feeds"):
            feeds = []
            for feed in value:
                if not isinstance(feed, dict):
                    raise SettingsError("sources.rss.feeds: expected objects {name, url, enabled}")
                url = _http_url(feed.get("url"), path)
                feeds.append({"name": str(feed.get("name") or url).strip()[:80], "url": url,
                              "enabled": bool(feed.get("enabled", True))})
            return feeds
        items = [str(v).strip() for v in value if str(v).strip()]
        if path == ("schedule", "collect_times"):
            bad = [t for t in items if not _TIME_RE.match(t)]
            if bad:
                raise SettingsError(f"schedule.collect_times: invalid time(s) {', '.join(bad)}")
            return sorted(set(items))
        if path == ("sources", "reddit", "threads"):
            return [_http_url(v, path) for v in items]
        return items[:50]
    raise SettingsError(f"{dotted}: unsupported setting")


def _apply(defaults: dict, current: dict, patch: dict, path: tuple = ()) -> None:
    for key, value in patch.items():
        if key not in defaults:
            continue
        sub_path = (*path, key)
        if isinstance(defaults[key], dict):
            if not isinstance(value, dict):
                raise SettingsError(f"{'.'.join(sub_path)}: expected an object")
            _apply(defaults[key], current[key], value, sub_path)
        elif sub_path in SECRET_PATHS and isinstance(value, dict):
            continue  # the masked {set, hint} view echoed back: keep the stored secret
        else:
            current[key] = _clean(sub_path, defaults[key], value)


def _get(data: dict, path: tuple) -> Any:
    for key in path:
        data = data[key]
    return data


def _set(data: dict, path: tuple, value: Any) -> None:
    for key in path[:-1]:
        data = data[key]
    data[path[-1]] = value


class Settings:
    def __init__(self, db: DB) -> None:
        self._db = db
        self.data = _merge_defaults(DEFAULTS, db.get_setting("settings"))

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise SettingsError("settings patch must be an object")
        updated = copy.deepcopy(self.data)
        _apply(DEFAULTS, updated, patch)
        self.data = updated
        self._db.set_setting("settings", updated)
        return self.public()

    def public(self) -> dict:
        view = copy.deepcopy(self.data)
        for path in SECRET_PATHS:
            value = _get(self.data, path)
            if isinstance(value, list):
                hint = f"{len(value)} URL{'s' if len(value) != 1 else ''} set" if value else None
            else:
                hint = f"…{value[-4:]}" if len(value) > 8 else ("set" if value else None)
            _set(view, path, {"set": bool(value), "hint": hint})
        return view

    # Convenience accessors used across the hub.
    @property
    def telegram_ready(self) -> bool:
        tg = self.data["delivery"]["telegram"]
        return bool(tg["enabled"] and tg["token"] and tg["chat_id"])

    @property
    def discord_ready(self) -> bool:
        dc = self.data["delivery"]["discord"]
        return bool(dc["enabled"] and dc["webhook"])
