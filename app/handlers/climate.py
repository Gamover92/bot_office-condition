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


NOT_YOURS = "Эти кнопки — у того, кто вызвал сводку. Чтобы посмотреть свои графики, отправьте /climate."
STALE = "Эта сводка устарела. Отправьте /climate, чтобы получить новую."
GREETING = (
    "Привет! Я показываю климат в офисе с датчиков Qingping.\n"
    "/climate — сводка и график, /settings — уведомления и утренний отчёт (для админов)."
)


def build_router(settings: Settings, store: Store) -> Router:
    router = Router(name="climate")

    async def show(message: Message, bot: Bot) -> None:
        owner = message.from_user.id if message.from_user else 0
        await send_view(bot, message.chat.id, await build_view(settings, store, owner=owner))

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
        if query.from_user.id != callback_data.owner:
            # The summary is shared in the chat: only the user who asked for it can change it.
            await query.answer(NOT_YOURS, show_alert=True)
            return
        try:
            view = await build_view(
                settings, store, callback_data.mac, callback_data.metric, callback_data.hours, owner=callback_data.owner
            )
            if isinstance(query.message, Message):
                await edit_view(query.message, view)
        finally:
            await query.answer()

    @router.callback_query(F.data.startswith(f"{ClimateCb.__prefix__}:"))
    async def on_stale_button(query: CallbackQuery) -> None:
        # Buttons of a summary sent before buttons had an owner.
        await query.answer(STALE, show_alert=True)

    return router
