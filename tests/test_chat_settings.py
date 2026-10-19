import sqlite3

import pytest

from app.chat_settings import (
    AlertState,
    ChatConfig,
    ChatStore,
    defaults_from_env,
    parse_bool,
    parse_days,
    parse_number,
    parse_range,
    parse_time,
    parse_time_range,
)


def make_store(defaults: ChatConfig | None = None) -> ChatStore:
    return ChatStore(sqlite3.connect(":memory:"), defaults or ChatConfig())


def test_parse_number():
    assert parse_number("1000") == 1000.0
    assert parse_number(" 12,5 ") == 12.5
    for bad in ("", "abc", "0", "-5", "10 20"):
        with pytest.raises(ValueError):
            parse_number(bad)


def test_parse_range():
    assert parse_range("19-26") == (19.0, 26.0)
    assert parse_range("19.5 – 26") == (19.5, 26.0)
    for bad in ("26-19", "20-20", "20", "a-b"):
        with pytest.raises(ValueError):
            parse_range(bad)


def test_parse_time():
    assert parse_time("9:00") == "09:00"
    assert parse_time("09.30") == "09:30"
    for bad in ("24:00", "9:60", "9", "ab:cd"):
        with pytest.raises(ValueError):
            parse_time(bad)


def test_parse_time_range():
    assert parse_time_range("20:00-08:00") == "20:00-08:00"
    assert parse_time_range("22:00 – 7:00") == "22:00-07:00"
    for bad in ("20:00", "20:00-20:00", "x-y"):
        with pytest.raises(ValueError):
            parse_time_range(bad)


def test_parse_bool_and_days():
    assert parse_bool("on") is True and parse_bool("0") is False
    assert parse_days("all") == "all"
    with pytest.raises(ValueError):
        parse_bool("maybe")
    with pytest.raises(ValueError):
        parse_days("weekends")


def test_defaults_from_env():
    cfg = defaults_from_env({"CO2_MAX": "1000", "TEMP_RANGE": "19-26", "QUIET": "off", "REPORT_TIME": "8:30"})
    assert cfg.co2_max == 1000
    assert cfg.temp == (19, 26)
    assert cfg.quiet is False
    assert cfg.report_time == "08:30"
    assert cfg.humidity == (30, 70)


def test_chat_store_settings_roundtrip():
    store = make_store(ChatConfig(co2_max=1100))
    store.register(5)
    store.register(5)
    assert store.chats() == [5]
    assert store.get(5).co2_max == 1100
    cfg = store.update(5, temp=(19.0, 25.0), alerts=False)
    assert cfg.temp == (19.0, 25.0) and cfg.alerts is False
    assert make_store_reloaded(store, 5).temp == (19.0, 25.0)
    store.reset(5)
    assert store.get(5) == ChatConfig(co2_max=1100)


def make_store_reloaded(store: ChatStore, chat_id: int) -> ChatConfig:
    # A new ChatStore on the same connection reads the saved JSON.
    return ChatStore(store.db, store.defaults).get(chat_id)


def test_disable_and_register_keeps_settings():
    store = make_store()
    store.register(1)
    store.disable(1)
    store.register(1)
    cfg = store.get(1)
    assert cfg.alerts is False and cfg.report is False


def test_alert_states_and_report_log():
    store = make_store()
    assert store.alert_states(1, "AA") == {}
    store.save_alert_states(1, "AA", {"co2": AlertState("bad", "ok")})
    assert store.alert_states(1, "AA") == {"co2": AlertState("bad", "ok")}
    assert store.last_report(1) is None
    store.mark_report(1, "2026-10-19")
    assert store.last_report(1) == "2026-10-19"


def test_migrate_moves_all_tables():
    store = make_store()
    store.update(-1, co2_max=900)
    store.save_alert_states(-1, "AA", {"co2": AlertState("bad", "bad")})
    store.mark_report(-1, "2026-10-19")
    store.register(-100)  # the new chat already has a row: the old settings win
    store.save_alert_states(-100, "AA", {"co2": AlertState("ok", "ok")})
    store.migrate(-1, -100)
    assert store.chats() == [-100]
    assert store.get(-100).co2_max == 900
    assert store.alert_states(-100, "AA") == {"co2": AlertState("bad", "bad")}
    assert store.alert_states(-1, "AA") == {}
    assert store.last_report(-100) == "2026-10-19"
    assert store.last_report(-1) is None


def test_migrate_without_overwrite_keeps_existing_new_chat():
    store = make_store()
    store.update(-100, co2_max=900, alerts=False)
    store.save_alert_states(-100, "AA", {"co2": AlertState("bad", "bad")})
    store.mark_report(-100, "2026-10-19")
    store.register(-1)
    store.save_alert_states(-1, "AA", {"co2": AlertState("ok", "ok")})
    store.mark_report(-1, "2026-10-18")
    store.migrate(-1, -100, overwrite=False)
    assert store.chats() == [-100]
    assert store.get(-100).co2_max == 900
    assert store.get(-100).alerts is False
    assert store.alert_states(-100, "AA") == {"co2": AlertState("bad", "bad")}
    assert store.alert_states(-1, "AA") == {}
    assert store.last_report(-100) == "2026-10-19"
    assert store.last_report(-1) is None


def test_migrate_without_overwrite_moves_when_new_chat_is_unknown():
    store = make_store()
    store.update(-1, co2_max=900)
    store.migrate(-1, -100, overwrite=False)
    assert store.chats() == [-100]
    assert store.get(-100).co2_max == 900
