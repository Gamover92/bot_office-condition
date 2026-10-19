"""Start the bot (long polling), the MQTT listener and the scheduler."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .access import AccessMiddleware, AdminChecker
from .chat_settings import ChatStore, defaults_from_env
from .config import Settings
from .handlers import climate, settings as settings_menu
from .mqtt_listener import run_mqtt
from .scheduler import run_scheduler
from .store import Store

log = logging.getLogger("office_climate")


async def prune_loop(store: Store, days: int) -> None:
    while True:
        try:
            store.prune(days)
        except Exception:
            log.exception("Prune failed")
        await asyncio.sleep(3600)


def on_task_done(task: asyncio.Task) -> None:
    """A background task must run forever: if it fails, exit so Docker restarts the bot."""
    if task.cancelled() or task.exception() is None:
        return
    log.critical("Background task %s failed, exiting", task.get_name(), exc_info=task.exception())
    os._exit(1)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")

    store = Store(settings.db_path)
    chats = ChatStore(store.db, defaults_from_env(settings.chat_defaults))
    for chat_id in settings.allowed_chats:
        chats.register(chat_id)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    access = AccessMiddleware(settings, chats)
    dp.message.middleware(access)
    dp.callback_query.middleware(access)
    # Settings first: its value-input handler must see text before the keyword handler.
    dp.include_router(settings_menu.build_router(chats, AdminChecker(settings)))
    dp.include_router(climate.build_router(settings, store))

    await bot.set_my_commands(
        [
            BotCommand(command="climate", description="Климат в офисе: сводка и график"),
            BotCommand(command="settings", description="Уведомления и отчёт (для админов)"),
        ]
    )

    background = [
        asyncio.create_task(run_mqtt(settings, store)),
        asyncio.create_task(prune_loop(store, settings.history_days)),
        asyncio.create_task(run_scheduler(bot, settings, store, chats)),
    ]
    for task in background:
        task.add_done_callback(on_task_done)
    try:
        await dp.start_polling(bot)
    finally:
        for task in background:
            task.remove_done_callback(on_task_done)
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
