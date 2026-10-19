import sqlite3
from types import SimpleNamespace

from app.chat_settings import ChatConfig, ChatStore
from app.handlers import migration


async def test_migration_handler_moves_chat():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    chats.update(-1, alerts=False)
    router = migration.build_router(chats)
    handler = router.message.handlers[0]
    message = SimpleNamespace(chat=SimpleNamespace(id=-1), migrate_to_chat_id=-100)
    assert (await handler.check(message))[0]
    await handler.callback(message)
    assert chats.chats() == [-100]
    assert chats.get(-100).alerts is False
