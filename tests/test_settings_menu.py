import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ForceReply, Message

from app.chat_settings import ChatConfig, ChatStore
from app.handlers.settings import EditValue, SetCb, build_router, menu_keyboard, menu_text, parse_input, toggle_changes


def test_menu_text_shows_values():
    text = menu_text(ChatConfig(co2_max=1000, temp=(19, 26), report_days="all", quiet=False))
    assert "🔔 Уведомления: <b>ВКЛ</b>" in text
    assert "🌅 Утренний отчёт: <b>ВКЛ</b>, 09:00, каждый день" in text
    assert "🌙 Тихие часы: <b>ВЫКЛ</b>, 20:00–08:00" in text
    assert "CO₂ &gt; 1000 ppm" in text
    assert "Температура 19–26 °C" in text


def test_menu_keyboard_callbacks():
    kb = menu_keyboard(ChatConfig())
    packed = [SetCb.unpack(b.callback_data) for row in kb.inline_keyboard for b in row]
    pairs = {(c.action, c.field) for c in packed}
    assert {("toggle", "alerts"), ("toggle", "report"), ("toggle", "report_days"), ("toggle", "quiet")} <= pairs
    assert {("edit", f) for f in ("report_time", "quiet_hours", "co2_max", "temp", "humidity", "pm25_max")} <= pairs
    assert {("reset", ""), ("close", "")} <= pairs
    assert kb.inline_keyboard[0][0].text == "🔔 Выключить уведомления"


def test_toggle_changes():
    cfg = ChatConfig()
    assert toggle_changes(cfg, "alerts") == {"alerts": False}
    assert toggle_changes(cfg, "report_days") == {"report_days": "all"}
    assert toggle_changes(ChatConfig(report_days="all"), "report_days") == {"report_days": "workdays"}
    with pytest.raises(ValueError):
        toggle_changes(cfg, "co2_max")


def test_parse_input():
    assert parse_input("co2_max", "1000") == 1000
    assert parse_input("temp", "19-26") == (19, 26)
    assert parse_input("report_time", "8:30") == "08:30"
    assert parse_input("quiet_hours", "21:00-07:00") == "21:00-07:00"
    with pytest.raises(ValueError):
        parse_input("temp", "26-19")
    with pytest.raises(ValueError):
        parse_input("unknown", "1")


PROMPT_ID = 42


def _handler_env(chat_type="supergroup"):
    admins = SimpleNamespace(is_admin=AsyncMock(return_value=True))
    router = build_router(ChatStore(sqlite3.connect(":memory:"), ChatConfig()), admins)
    on_button = next(h for h in router.callback_query.handlers if h.callback.__name__ == "on_button").callback
    on_value = next(h for h in router.message.handlers if h.callback.__name__ == "on_value").callback
    msg = AsyncMock(spec=Message)
    msg.chat = SimpleNamespace(id=5, type=chat_type)  # pydantic fields are not visible to spec
    msg.message_id = 1
    msg.answer = AsyncMock(return_value=SimpleNamespace(message_id=PROMPT_ID))
    msg.edit_text = AsyncMock()
    query = AsyncMock()
    query.message = msg
    query.from_user = SimpleNamespace(id=7, first_name="<Ann>")
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=5, user_id=7))

    async def press(action, field=""):
        await on_button(query=query, callback_data=SetCb(action=action, field=field), bot=AsyncMock(), state=state)

    async def send(text, reply_to=None):
        reply = SimpleNamespace(message_id=reply_to) if reply_to else None
        message = AsyncMock(spec=Message)
        message.chat = msg.chat
        message.text = text
        message.reply_to_message = reply
        message.answer = AsyncMock()
        await on_value(message=message, state=state)
        return message

    return msg, state, press, send


async def test_edit_prompt_uses_selective_force_reply():
    msg, state, press, _ = _handler_env()
    await press("edit", "co2_max")
    assert await state.get_state() == EditValue.waiting.state
    assert (await state.get_data())["prompt_id"] == PROMPT_ID
    text = msg.answer.await_args.args[0]
    assert text.startswith('<a href="tg://user?id=7">&lt;Ann&gt;</a>, введите')
    markup = msg.answer.await_args.kwargs["reply_markup"]
    assert isinstance(markup, ForceReply)
    assert markup.selective is True
    assert markup.input_field_placeholder == "1000"


async def test_group_value_must_reply_to_prompt():
    _, state, press, send = _handler_env()
    await press("edit", "co2_max")
    with pytest.raises(SkipHandler):
        await send("hello")
    assert await state.get_state() == EditValue.waiting.state
    with pytest.raises(SkipHandler):
        await send("900", reply_to=PROMPT_ID + 1)
    assert await state.get_state() == EditValue.waiting.state
    reply = await send("900", reply_to=PROMPT_ID)
    assert await state.get_state() is None
    assert reply.answer.await_args.args[0].startswith("✅ Сохранено.")


async def test_private_value_needs_no_reply():
    _, state, press, send = _handler_env("private")
    await press("edit", "co2_max")
    reply = await send("900")
    assert await state.get_state() is None
    assert reply.answer.await_args.args[0].startswith("✅ Сохранено.")


async def test_group_timeout_is_silent_without_reply():
    _, state, press, send = _handler_env()
    await press("edit", "co2_max")
    await state.update_data(started=0)
    with pytest.raises(SkipHandler):
        await send("hello")
    assert await state.get_state() is None
    await press("edit", "co2_max")
    await state.update_data(started=0)
    message = await send("900", reply_to=PROMPT_ID)
    assert message.answer.await_args.args[0].startswith("Время ввода истекло")


@pytest.mark.parametrize("action,field", [("toggle", "alerts"), ("reset", "")])
async def test_toggle_and_reset_clear_pending_input(action, field):
    _, state, press, _ = _handler_env()
    await press("edit", "co2_max")
    await press(action, field)
    assert await state.get_state() is None
