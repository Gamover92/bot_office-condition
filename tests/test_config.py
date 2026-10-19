import pytest

from app.config import CHAT_ENV_KEYS, Settings


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("TZ", "ALLOWED_CHAT_IDS", "ALLOWED_USER_IDS", "DEVICE_NAMES", *CHAT_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_from_env(clean_env):
    clean_env.setenv("BOT_TOKEN", "1:x")
    clean_env.setenv("ALLOWED_CHAT_IDS", "-100, 5")
    clean_env.setenv("DEVICE_NAMES", "aabb=Офис; ccdd = Переговорка")
    clean_env.setenv("CO2_MAX", "1000")
    s = Settings.from_env()
    assert s.bot_token == "1:x"
    assert s.allowed_chats == {-100, 5}
    assert not hasattr(s, "admin_users")
    assert s.device_names == {"AABB": "Офис", "CCDD": "Переговорка"}
    assert s.chat_defaults == {"CO2_MAX": "1000"}
    assert s.tz == "Europe/Moscow"


def test_is_allowed():
    assert Settings(bot_token="x").is_allowed(1, 2)
    s = Settings(bot_token="x", allowed_chats=frozenset({-100}), allowed_users=frozenset({7}))
    assert s.is_allowed(7, 1)
    assert s.is_allowed(1, -100)
    assert not s.is_allowed(1, 2)
    assert not s.is_allowed(None, None)


def test_from_env_rejects_unknown_tz(clean_env):
    clean_env.setenv("TZ", "Mars/Olympus")
    with pytest.raises(SystemExit, match="Unknown TZ: Mars/Olympus"):
        Settings.from_env()
