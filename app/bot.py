"""Telegram bot handlers."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from .config import Settings
from .store import Store
from .summary import summary_html


def app_button(settings: Settings, bot_username: str, private: bool) -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    if private:
        button = InlineKeyboardButton(text="📊 Открыть дашборд", web_app=WebAppInfo(url=settings.webapp_url))
    else:
        # Telegram does not allow web_app buttons in groups: use a direct Mini App link.
        path = f"/{settings.miniapp_short_name}" if settings.miniapp_short_name else ""
        button = InlineKeyboardButton(
            text="📊 Открыть дашборд", url=f"https://t.me/{bot_username}{path}?startapp=climate"
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_router(settings: Settings, store: Store) -> Router:
    router = Router()

    async def send_summary(message: Message, bot: Bot) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not settings.is_allowed(user_id, message.chat.id):
            await message.answer("Нет доступа. Попросите администратора добавить вас.")
            return
        me = await bot.me()
        await message.answer(
            "🌡 <b>Климат в офисе</b>\n\n" + summary_html(settings, store),
            reply_markup=app_button(settings, me.username or "", message.chat.type == ChatType.PRIVATE),
        )

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot) -> None:
        await message.answer(
            "Привет! Я показываю климат в офисе с датчиков Qingping.\n"
            "Команда /climate — сводка. Кнопка ниже — дашборд с графиками."
        )
        await send_summary(message, bot)

    @router.message(Command("climate", "climat", "air"))
    async def climate(message: Message, bot: Bot) -> None:
        await send_summary(message, bot)

    @router.message(F.text.lower().in_({"климат", "погода в офисе", "душно?"}))
    async def climate_text(message: Message, bot: Bot) -> None:
        await send_summary(message, bot)

    return router


async def setup_bot_profile(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands([BotCommand(command="climate", description="Сводка климата в офисе")])
    if settings.webapp_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Климат", web_app=WebAppInfo(url=settings.webapp_url))
        )
