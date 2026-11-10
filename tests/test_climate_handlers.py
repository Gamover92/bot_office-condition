from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.handlers import climate
from app.store import Store
from app.view import ClimateCb


async def test_button_is_answered_when_edit_fails():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    on_button = next(h for h in router.callback_query.handlers if h.callback.__name__ == "on_button").callback
    query = AsyncMock()
    query.from_user.id = 7
    with patch.object(climate, "build_view", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await on_button(query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24, owner=7))
    query.answer.assert_awaited_once()


def handlers(router):
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


async def test_other_user_cannot_change_the_summary():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    query = AsyncMock()
    query.from_user.id = 8
    with patch.object(climate, "build_view", AsyncMock()) as build:
        await handlers(router)["on_button"](query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24, owner=7))
    build.assert_not_awaited()
    assert "/climate" in query.answer.await_args.args[0]
    assert query.answer.await_args.kwargs["show_alert"] is True


async def test_owner_changes_the_summary():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    query = AsyncMock()
    query.from_user.id = 7
    with patch.object(climate, "build_view", AsyncMock()) as build, patch.object(climate, "edit_view", AsyncMock()):
        await handlers(router)["on_button"](query=query, callback_data=ClimateCb(mac="AA", metric="pm25", hours=6, owner=7))
    assert build.await_args.kwargs["owner"] == 7
    query.answer.assert_awaited_once()


async def test_old_buttons_without_owner_are_answered():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    query = AsyncMock()
    await handlers(router)["on_stale_button"](query=query)
    assert "/climate" in query.answer.await_args.args[0]


def message_handlers(router):
    return {h.callback.__name__: h.callback for h in router.message.handlers}


def fake_message(chat_type: str, chat_id: int = 7, user_id: int = 7):
    message = AsyncMock()
    message.chat.type = chat_type
    message.chat.id = chat_id
    message.from_user.id = user_id
    return message


async def test_private_widget_success_skips_png():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    with patch.object(climate, "send_widget_summary", AsyncMock(return_value=42)) as widget, \
         patch.object(climate, "send_view", AsyncMock()) as png:
        await message_handlers(router)["climate"](message=fake_message("private"), bot=AsyncMock())
    widget.assert_awaited_once()
    png.assert_not_awaited()


async def test_private_widget_error_falls_back_to_png():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    with patch.object(climate, "send_widget_summary", AsyncMock(return_value=None)), \
         patch.object(climate, "send_view", AsyncMock()) as png:
        await message_handlers(router)["climate"](message=fake_message("private"), bot=AsyncMock())
    png.assert_awaited_once()


async def test_group_never_tries_widget():
    router = climate.build_router(Settings(bot_token="x"), Store(":memory:"))
    with patch.object(climate, "send_widget_summary", AsyncMock()) as widget, \
         patch.object(climate, "send_view", AsyncMock()) as png:
        await message_handlers(router)["climate"](message=fake_message("supergroup", chat_id=-100), bot=AsyncMock())
    widget.assert_not_awaited()
    png.assert_awaited_once()


def widget_query(store, chat_id=7, message_id=1, user_id=7):
    import datetime

    from aiogram.types import Chat, Message

    store.add_widget_message(chat_id, message_id, "AA", 1)
    query = AsyncMock()
    query.from_user.id = user_id
    query.message = Message(
        message_id=message_id,
        date=datetime.datetime.now(datetime.timezone.utc),
        chat=Chat(id=chat_id, type="private"),
    )
    return query


async def test_widget_button_recreates_widget_message():
    store = Store(":memory:")
    router = climate.build_router(Settings(bot_token="x"), store)
    query = widget_query(store)
    from aiogram.types import Message

    with patch.object(climate, "send_widget_summary", AsyncMock(return_value=99)) as widget, \
         patch.object(climate, "edit_view", AsyncMock()) as edit, \
         patch.object(Message, "delete", new=AsyncMock()) as delete:
        await handlers(router)["on_button"](
            query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24, owner=7)
        )
    assert widget.await_args.kwargs["mac"] == "AA"
    delete.assert_awaited_once()
    edit.assert_not_awaited()
    assert store.get_widget_message(7, 1) is None


async def test_widget_button_falls_back_to_png_edit():
    store = Store(":memory:")
    router = climate.build_router(Settings(bot_token="x"), store)
    query = widget_query(store)
    from aiogram.types import Message

    with patch.object(climate, "send_widget_summary", AsyncMock(return_value=None)), \
         patch.object(climate, "build_view", AsyncMock()), \
         patch.object(climate, "edit_view", AsyncMock()) as edit, \
         patch.object(Message, "delete", new=AsyncMock()) as delete:
        await handlers(router)["on_button"](
            query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24, owner=7)
        )
    edit.assert_awaited_once()
    delete.assert_not_awaited()
    assert store.get_widget_message(7, 1) == "AA"


def store_with_data(store: Store) -> Store:
    import time

    from app.qingping import Reading

    now = int(time.time())
    store.add([Reading("AA", now - i * 60, {"co2": 700.0}) for i in range(60)])
    return store


async def test_private_widget_build_error_falls_back_to_png(monkeypatch):
    import app.widget as widget

    store = store_with_data(Store(":memory:"))
    router = climate.build_router(Settings(bot_token="x"), store)

    def boom(*a):
        raise RuntimeError("malformed row")

    monkeypatch.setattr(widget, "build_widget_html", boom)
    with patch.object(climate, "send_view", AsyncMock()) as png:
        await message_handlers(router)["climate"](message=fake_message("private"), bot=AsyncMock())
    png.assert_awaited_once()


async def test_widget_button_build_error_falls_back_to_edit(monkeypatch):
    import app.widget as widget
    from aiogram.types import Message

    store = store_with_data(Store(":memory:"))
    router = climate.build_router(Settings(bot_token="x"), store)
    query = widget_query(store)

    def boom(*a):
        raise RuntimeError("malformed row")

    monkeypatch.setattr(widget, "build_widget_html", boom)
    with patch.object(climate, "build_view", AsyncMock()), \
         patch.object(climate, "edit_view", AsyncMock()) as edit, \
         patch.object(Message, "delete", new=AsyncMock()) as delete:
        await handlers(router)["on_button"](
            query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24, owner=7)
        )
    edit.assert_awaited_once()
    delete.assert_not_awaited()
    query.answer.assert_awaited_once()
