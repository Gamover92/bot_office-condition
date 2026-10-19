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
