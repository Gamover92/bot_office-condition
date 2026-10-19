"""Group upgraded to a supergroup: move the chat's settings to the new chat ID."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from ..chat_settings import ChatStore

log = logging.getLogger(__name__)


def build_router(chats: ChatStore) -> Router:
    router = Router(name="migration")

    @router.message(F.migrate_to_chat_id)
    async def on_migrate(message: Message) -> None:
        log.info("Chat %s moved to %s", message.chat.id, message.migrate_to_chat_id)
        chats.migrate(message.chat.id, message.migrate_to_chat_id)

    return router
