"""Access rules: allow-lists for everyone, admin check for settings."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from .chat_settings import ChatStore
from .config import Settings

ADMIN_CACHE_TTL = 300
ADMIN_STATUSES = (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


class AccessMiddleware(BaseMiddleware):
    """Inner middleware: runs only for events that a handler matched."""

    def __init__(self, settings: Settings, chats: ChatStore):
        self.settings = settings
        self.chats = chats

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if getattr(event, "migrate_to_chat_id", None):
            # Telegram's service message about a group upgrade. The handler sends nothing
            # and only moves rows of a chat that is already registered (so it was allowed).
            return await handler(event, data)
        if getattr(event, "migrate_from_chat_id", None):
            # Service message in the new supergroup: nothing to do, and no "no access" reply.
            return None
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        user_id = user.id if user else None
        chat_id = chat.id if chat else None
        if not self.settings.is_allowed(user_id, chat_id):
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Нет доступа. Попросите администратора добавить этот чат.")
            return None
        if chat_id is not None:
            self.chats.register(chat_id)
        return await handler(event, data)


class AdminChecker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache: dict[tuple[int, int], tuple[float, bool]] = {}

    async def is_admin(self, bot: Bot, chat_id: int, chat_type: str, user_id: int) -> bool:
        if chat_type == ChatType.PRIVATE:
            # The user owns a private chat with the bot.
            return user_id == chat_id or user_id in self.settings.admin_users
        key = (chat_id, user_id)
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < ADMIN_CACHE_TTL:
            return cached[1]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except TelegramAPIError:
            return False  # not cached: the next call asks again
        ok = member.status in ADMIN_STATUSES
        self.cache[key] = (time.monotonic(), ok)
        return ok
