"""/start, /climate, keywords and the summary buttons."""

from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..store import Store
from ..view import ClimateCb, build_view, edit_view, send_view

KEYWORDS = {"климат", "душно", "душновато"}
# Words allowed next to a keyword: "душно-то как", "как душно в офисе". "не" is not here,
# so "тут не душно" does not trigger the bot.
FILLER = {"то", "как", "же", "так", "очень", "что", "тут", "здесь", "у", "нас", "в", "офисе", "сегодня"}


def is_keyword(text: str) -> bool:
    """A short message that asks about the climate. Case, punctuation and emoji do not matter."""
    words = re.findall(r"[а-яё]+", text.lower())
    return any(w in KEYWORDS for w in words) and all(w in KEYWORDS or w in FILLER for w in words)


GREETING = (
    "Привет! Я показываю климат в офисе с датчиков Qingping.\n"
    "/climate — сводка и график, /settings — уведомления и утренний отчёт (для админов)."
)


def build_router(settings: Settings, store: Store) -> Router:
    router = Router(name="climate")

    async def show(message: Message, bot: Bot) -> None:
        await send_view(bot, message.chat.id, await build_view(settings, store))

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot) -> None:
        await message.answer(GREETING)
        await show(message, bot)

    @router.message(Command("climate"))
    async def climate(message: Message, bot: Bot) -> None:
        await show(message, bot)

    @router.message(F.text.func(is_keyword))
    async def keyword(message: Message, bot: Bot) -> None:
        await show(message, bot)

    @router.callback_query(ClimateCb.filter())
    async def on_button(query: CallbackQuery, callback_data: ClimateCb) -> None:
        try:
            view = await build_view(settings, store, callback_data.mac, callback_data.metric, callback_data.hours)
            if isinstance(query.message, Message):
                await edit_view(query.message, view)
        finally:
            await query.answer()

    return router
