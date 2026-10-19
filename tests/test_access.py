import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChatMember

from app.access import AccessMiddleware, AdminChecker
from app.chat_settings import ChatConfig, ChatStore
from app.config import Settings

LIMITED = Settings(bot_token="x", allowed_chats=frozenset({-100}), admin_users=frozenset({7}))


def data(user_id, chat_id):
    return {"event_from_user": SimpleNamespace(id=user_id), "event_chat": SimpleNamespace(id=chat_id)}


async def test_middleware_allows_and_registers():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    handler = AsyncMock(return_value="ok")
    result = await AccessMiddleware(LIMITED, chats)(handler, object(), data(1, -100))
    assert result == "ok"
    assert chats.chats() == [-100]


async def test_middleware_blocks():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    handler = AsyncMock()
    result = await AccessMiddleware(LIMITED, chats)(handler, object(), data(1, 2))
    assert result is None
    handler.assert_not_awaited()
    assert chats.chats() == []


async def test_admin_in_private_chat():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    assert await checker.is_admin(bot, 8, "private", 8)  # owner of the private chat
    assert await checker.is_admin(bot, 9, "private", 7)  # in ADMIN_USER_IDS
    assert not await checker.is_admin(bot, 9, "private", 8)
    bot.get_chat_member.assert_not_awaited()


async def test_admin_in_group_is_cached():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)
    assert await checker.is_admin(bot, -100, "supergroup", 1)
    assert await checker.is_admin(bot, -100, "supergroup", 1)
    assert bot.get_chat_member.await_count == 1


async def test_group_member_and_error_are_not_admin():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    assert not await checker.is_admin(bot, -100, "group", 1)
    bot.get_chat_member.side_effect = TelegramBadRequest(
        method=GetChatMember(chat_id=-100, user_id=2), message="user not found"
    )
    assert not await checker.is_admin(bot, -100, "group", 2)
    # An error is not cached: the next call asks the API again.
    bot.get_chat_member.side_effect = None
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.CREATOR)
    assert await checker.is_admin(bot, -100, "group", 2)
    assert bot.get_chat_member.await_count == 3


async def test_middleware_passes_migration_service_message():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    handler = AsyncMock(return_value="ok")
    event = SimpleNamespace(migrate_to_chat_id=-200)
    result = await AccessMiddleware(LIMITED, chats)(handler, event, data(1, 2))
    assert result == "ok"
    assert chats.chats() == []  # the chat is not registered
