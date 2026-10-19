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
    with patch.object(climate, "build_view", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await on_button(query=query, callback_data=ClimateCb(mac="AA", metric="co2", hours=24))
    query.answer.assert_awaited_once()
