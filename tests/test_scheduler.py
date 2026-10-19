import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.methods import SendMessage

from app import scheduler
from app.chat_settings import ChatConfig, ChatStore
from app.config import Settings
from app.qingping import Reading
from app.scheduler import report_due, tick
from app.store import Store

TZ = ZoneInfo("Europe/Moscow")
S = Settings(bot_token="x", tz="Europe/Moscow", stale_after_min=30)
MONDAY_10 = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)


def test_report_due():
    cfg = ChatConfig()  # 09:00, workdays
    assert report_due(cfg, MONDAY_10, None)
    assert not report_due(cfg, MONDAY_10, "2026-10-19")
    assert report_due(cfg, MONDAY_10, "2026-10-18")
    assert not report_due(cfg, datetime(2026, 10, 19, 8, 59, tzinfo=TZ), None)
    assert not report_due(cfg, datetime(2026, 10, 19, 12, 0, tzinfo=TZ), None)
    assert not report_due(cfg, datetime(2026, 10, 18, 10, 0, tzinfo=TZ), None)  # Sunday
    assert report_due(ChatConfig(report_days="all"), datetime(2026, 10, 18, 10, 0, tzinfo=TZ), None)
    assert not report_due(ChatConfig(report=False), MONDAY_10, None)
    late = ChatConfig(report_time="14:00")
    assert report_due(late, datetime(2026, 10, 19, 14, 9, tzinfo=TZ), None)
    assert not report_due(late, datetime(2026, 10, 19, 14, 10, tzinfo=TZ), None)


def setup(co2: float, age_s: int = 60, **cfg):
    store = Store(":memory:")
    chats = ChatStore(store.db, ChatConfig(report=False, quiet=False).with_changes(cfg))
    chats.register(1)
    now = MONDAY_10.timestamp()
    store.add([Reading("AA", int(now) - age_s, {"co2": co2})])
    return store, chats, now


async def test_alert_sent_once():
    store, chats, now = setup(1300)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    await tick(bot, S, store, chats, now + 60)
    bot.send_message.assert_awaited_once()
    assert "CO₂ 1300 ppm" in bot.send_message.await_args.args[1]


async def test_no_alert_on_stale_data():
    store, chats, now = setup(1300, age_s=3600)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    bot.send_message.assert_not_awaited()


async def test_alerts_off():
    store, chats, now = setup(1300, alerts=False)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    bot.send_message.assert_not_awaited()


async def test_forbidden_disables_chat():
    store, chats, now = setup(1300)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=1, text="x"), message="bot was kicked"
    )
    await tick(bot, S, store, chats, now)
    cfg = chats.get(1)
    assert cfg.alerts is False and cfg.report is False


async def test_chat_not_found_forgets_chat():
    store, chats, now = setup(1300)
    chats.update(1, co2_max=1000)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"), message="Bad Request: chat not found"
    )
    await tick(bot, S, store, chats, now)
    assert chats.chats() == []
    assert chats.get(1).co2_max == 1200  # settings rows are gone too
    await tick(bot, S, store, chats, now + 60)
    bot.send_message.assert_awaited_once()  # not retried every minute


async def test_morning_report_once():
    store, chats, now = setup(700, report=True)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    await tick(bot, S, store, chats, now + 60)
    sent = bot.send_message.await_count + bot.send_photo.await_count
    assert sent == 1
    assert chats.last_report(1) == "2026-10-19"


async def test_error_in_one_chat_does_not_stop_others():
    store, chats, now = setup(1300)
    chats.register(2)
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("boom"), None]
    await tick(bot, S, store, chats, now)
    assert bot.send_message.await_count == 2


async def test_run_scheduler_survives_tick_error(monkeypatch):
    calls = 0

    async def flaky_tick(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("chats() failed")

    monkeypatch.setattr(scheduler, "tick", flaky_tick)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(scheduler.run_scheduler(AsyncMock(), S, None, None, interval=0.01), 0.2)
    assert calls >= 2


async def test_migrated_chat_is_moved():
    store, chats, now = setup(1300)
    chats.update(1, co2_max=1000)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramMigrateToChat(
        method=SendMessage(chat_id=1, text="x"), message="group upgraded", migrate_to_chat_id=-100
    )
    await tick(bot, S, store, chats, now)
    assert chats.chats() == [-100]
    assert chats.get(-100).co2_max == 1000


async def test_migration_does_not_overwrite_new_chat_settings():
    store, chats, now = setup(1300)  # chat 1 is registered with defaults
    chats.register(-1)
    chats.update(-100, co2_max=900, alerts=False)
    bot = AsyncMock()

    async def send(chat_id, text, **kwargs):
        if chat_id == -1:
            raise TelegramMigrateToChat(
                method=SendMessage(chat_id=-1, text="x"), message="group upgraded", migrate_to_chat_id=-100
            )

    bot.send_message.side_effect = send
    store.db.execute("DELETE FROM chat_settings WHERE chat_id=1")
    await tick(bot, S, store, chats, now)
    assert chats.get(-100).co2_max == 900
    assert chats.get(-100).alerts is False
    assert -1 not in chats.chats()


async def test_report_is_not_lost_when_scheduler_finds_a_migration():
    store, chats, now = setup(700, report=True)  # chat 1, report due at 10:00
    bot = AsyncMock()
    sent = []

    async def send(chat_id, *args, **kwargs):
        if chat_id == 1:
            raise TelegramMigrateToChat(
                method=SendMessage(chat_id=1, text="x"), message="group upgraded", migrate_to_chat_id=-100
            )
        sent.append(chat_id)

    bot.send_message.side_effect = send
    bot.send_photo.side_effect = send
    await tick(bot, S, store, chats, now)
    assert chats.chats() == [-100]
    assert chats.last_report(-100) is None
    await tick(bot, S, store, chats, now + 60)
    assert sent == [-100]
    assert chats.last_report(-100) == "2026-10-19"
