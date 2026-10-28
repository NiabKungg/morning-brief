import pytest

from mib.hub.db import DB
from mib.hub.settings import Settings, SettingsError


@pytest.fixture
def settings(tmp_path):
    return Settings(DB(tmp_path / "t.sqlite3"))


def test_secrets_never_leave_the_hub_and_survive_an_echoed_masked_value(settings):
    view = settings.update({"delivery": {"telegram": {"token": "123456:ABCDEFsecret", "chat_id": "42"}}})
    assert view["delivery"]["telegram"]["token"] == {"set": True, "hint": "…cret"}
    assert "ABCDEF" not in str(view)
    settings.update({"delivery": {"telegram": view["delivery"]["telegram"]}})  # UI sends the masked object back
    assert settings.data["delivery"]["telegram"]["token"] == "123456:ABCDEFsecret"
    settings.update({"delivery": {"telegram": {"token": ""}}})
    assert settings.data["delivery"]["telegram"]["token"] == ""


def test_invalid_values_are_rejected_or_clamped_and_persisted(tmp_path):
    db = DB(tmp_path / "t.sqlite3")
    s = Settings(db)
    with pytest.raises(SettingsError):
        s.update({"schedule": {"brief_time": "25:00"}})
    with pytest.raises(SettingsError):
        s.update({"sources": {"rss": {"feeds": [{"name": "x", "url": "ftp://nope"}]}}})
    s.update({"pipeline": {"triage_threshold": 99}, "schedule": {"collect_times": ["06:30", "00:30", "06:30"]}})
    reloaded = Settings(db).data
    assert reloaded["pipeline"]["triage_threshold"] == 10
    assert reloaded["schedule"]["collect_times"] == ["00:30", "06:30"]
