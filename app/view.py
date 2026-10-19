"""The summary "view": caption, chart and inline keyboard, and send/edit helpers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from .charts import render_chart
from .config import Settings
from .store import Store
from .summary import caption, device_name

CHART_METRICS = ("co2", "temperature", "humidity", "pm25", "pm10", "tvoc", "tvoc_index", "noise")
SHORT = {
    "co2": "CO₂",
    "temperature": "Темп.",
    "humidity": "Влажн.",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "tvoc": "TVOC",
    "tvoc_index": "TVOC",
    "noise": "Шум",
}
PERIODS = {6: "6 ч", 24: "24 ч", 168: "7 д"}
PHOTO_NAME = "climate.png"


class ClimateCb(CallbackData, prefix="cl"):
    mac: str
    metric: str
    hours: int


@dataclass(frozen=True)
class View:
    text: str
    photo: bytes | None
    keyboard: InlineKeyboardMarkup | None


def _button(text: str, mac: str, metric: str, hours: int, active: bool = False) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=f"• {text} •" if active else text,
        callback_data=ClimateCb(mac=mac, metric=metric, hours=hours).pack(),
    )


def build_keyboard(
    settings: Settings, macs: list[str], mac: str, metrics: list[str], metric: str, hours: int
) -> InlineKeyboardMarkup:
    rows = []
    if len(macs) > 1:
        # Stable button order for the user; the default device is chosen by the caller.
        rows.append([_button(device_name(settings, m), m, metric, hours, m == mac) for m in sorted(macs)])
    chartable = [m for m in CHART_METRICS if m in metrics]
    for i in range(0, len(chartable), 4):
        rows.append([_button(SHORT[m], mac, m, hours, m == metric) for m in chartable[i : i + 4]])
    rows.append([_button(label, mac, metric, h, h == hours) for h, label in PERIODS.items()])
    rows.append([_button("🔄 Обновить", mac, metric, hours)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_view(
    settings: Settings,
    store: Store,
    mac: str | None = None,
    metric: str = "co2",
    hours: int = 24,
    now: float | None = None,
) -> View:
    now = time.time() if now is None else now
    macs = store.devices()
    if not macs:
        return View(caption(settings, None, now), None, None)
    if mac not in macs:
        mac = macs[0]
    reading = store.latest(mac)
    metrics = list(reading.values) if reading else []
    chartable = [m for m in CHART_METRICS if m in metrics]
    if metric not in chartable:
        metric = chartable[0] if chartable else "co2"
    rows = store.history(mac, int(now) - hours * 3600)
    points = [(r.ts, r.values[metric]) for r in rows if metric in r.values]
    photo = await asyncio.to_thread(render_chart, points, metric, ZoneInfo(settings.tz))
    keyboard = build_keyboard(settings, macs, mac, metrics, metric, hours)
    return View(caption(settings, reading, now), photo, keyboard)


async def send_view(bot: Bot, chat_id: int, view: View) -> None:
    if view.photo:
        await bot.send_photo(
            chat_id, BufferedInputFile(view.photo, PHOTO_NAME), caption=view.text, reply_markup=view.keyboard
        )
    else:
        await bot.send_message(chat_id, view.text, reply_markup=view.keyboard)


async def edit_view(message: Message, view: View) -> None:
    """Edit the summary message in place. Recreate it if the type (photo/text) changes."""
    try:
        if view.photo and message.photo:
            media = InputMediaPhoto(media=BufferedInputFile(view.photo, PHOTO_NAME), caption=view.text)
            await message.edit_media(media, reply_markup=view.keyboard)
        elif not view.photo and not message.photo:
            await message.edit_text(view.text, reply_markup=view.keyboard)
        else:
            await message.delete()
            await send_view(message.bot, message.chat.id, view)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
