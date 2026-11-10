"""Поддержка виджетов Telegram: вызовы Bot API, сборка данных и HTML.

aiogram 3.31 не знает методов виджетов (Bot API 10.4), поэтому HTTP-запросы
идут напрямую через ``bot.session`` (aiohttp).
"""

from __future__ import annotations

import json

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app.qingping import METRICS, Reading

API_URL = "https://api.telegram.org/bot{token}/{method}"

PUBLIC_DATA_BUDGET = 1000


def build_public_data(reading: Reading, n: int = 0) -> str:
    """Компактный JSON последних значений для public_data виджета.

    Плоский словарь: ``{"ts": <unix>, "n": <счётчик>, "<metric>": <значение>}``.
    Значения округлены по digits из METRICS; порядок метрик — порядок METRICS.
    ``n`` — счётчик изменений: Telegram отклоняет правки с неизменным
    public_data ("message is not modified"), счётчик делает строку уникальной.
    Если JSON не влезает в бюджет, метрики отбрасываются с конца порядка METRICS.
    """
    keys = [k for k in METRICS if k in reading.values]
    while True:
        payload: dict = {"ts": reading.ts, "n": n}
        for key in keys:
            digits = METRICS[key][2]
            value = round(reading.values[key], digits)
            payload[key] = int(value) if digits == 0 else value
        data = json.dumps(payload, separators=(",", ":"))
        if len(data.encode()) <= PUBLIC_DATA_BUDGET or not keys:
            return data
        keys.pop()


async def _api(bot: Bot, method: str, **params):
    url = API_URL.format(token=bot.token, method=method)
    async with bot.session.post(url, data=params) as resp:
        body = await resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('description')}")
    return body["result"]


async def send_widget(
    bot: Bot,
    chat_id: int,
    html: str,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
) -> int:
    """Отправляет виджет в чат, возвращает message_id."""
    params: dict = {
        "chat_id": chat_id,
        "html": html,
        "caption": caption,
        "parse_mode": "HTML",
    }
    if keyboard is not None:
        params["reply_markup"] = keyboard.model_dump_json(exclude_none=True)
    result = await _api(bot, "sendWidget", **params)
    return result["message_id"]


async def edit_widget_data(bot: Bot, chat_id: int, message_id: int, public_data: str) -> None:
    """Обновляет public_data виджета в сообщении."""
    await _api(
        bot,
        "editMessageWidgetData",
        chat_id=chat_id,
        message_id=message_id,
        public_data=public_data,
    )
