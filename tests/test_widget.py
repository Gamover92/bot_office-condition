"""Тесты app/widget.py — сырой HTTP-клиент методов виджетов Bot API."""

from types import SimpleNamespace

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.widget import edit_widget_data, send_widget


class RecordingSession:
    """Подмена bot.session: записывает (method, payload), отвечает заготовкой."""

    def __init__(self, response: dict):
        self.calls: list[tuple[str, dict]] = []
        self._response = response

    def post(self, url: str, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, kwargs.get("data", {})))
        session = self

        class _Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def json(self):
                return session._response

        return _Resp()


def fake_bot_with_session(**response):
    return SimpleNamespace(session=RecordingSession(response), token="123456:ABC")


async def test_send_widget_returns_message_id():
    bot = fake_bot_with_session(ok=True, result={"message_id": 42})
    mid = await send_widget(bot, 7, "<html>…</html>", "caption", None)
    assert mid == 42
    method, payload = bot.session.calls[0]
    assert method == "sendWidget" and payload["chat_id"] == 7


async def test_send_widget_sends_html_caption_and_keyboard():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Обновить", callback_data="r")]]
    )
    await send_widget(bot, 7, "<html>x</html>", "cap", kb)
    _, payload = bot.session.calls[0]
    assert payload["html"] == "<html>x</html>"
    assert payload["caption"] == "cap"
    assert payload["reply_markup"] == kb.model_dump_json(exclude_none=True)


async def test_send_widget_omits_keyboard_when_none():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    await send_widget(bot, 7, "<html>x</html>", "cap", None)
    _, payload = bot.session.calls[0]
    assert "reply_markup" not in payload


async def test_send_widget_raises_on_api_error():
    bot = fake_bot_with_session(ok=False, description="INPUT_MEDIA_WIDGET_NOT_ALLOWED")
    with pytest.raises(RuntimeError, match="INPUT_MEDIA_WIDGET_NOT_ALLOWED"):
        await send_widget(bot, -100, "<html/>", "c", None)


async def test_edit_widget_data_payload():
    bot = fake_bot_with_session(ok=True, result=True)
    await edit_widget_data(bot, 7, 42, '{"co2":700}')
    method, payload = bot.session.calls[0]
    assert method == "editMessageWidgetData"
    assert payload["chat_id"] == 7 and payload["message_id"] == 42
    assert payload["public_data"] == '{"co2":700}'


async def test_edit_widget_data_raises_on_api_error():
    bot = fake_bot_with_session(ok=False, description="message is not modified")
    with pytest.raises(RuntimeError, match="message is not modified"):
        await edit_widget_data(bot, 7, 42, "{}")
