"""Start the bot (long polling), the MQTT listener, and the web server."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from .bot import build_router, setup_bot_profile
from .config import Settings
from .mqtt_listener import run_mqtt
from .store import Store
from .web import build_app

log = logging.getLogger("office_climate")


async def prune_loop(store: Store, days: int) -> None:
    while True:
        store.prune(days)
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")
    if not settings.webapp_url:
        log.warning("WEBAPP_URL is not set: the Mini App button is hidden")

    store = Store(settings.db_path)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(settings, store))

    runner = web.AppRunner(build_app(settings, store, bot))
    await runner.setup()
    await web.TCPSite(runner, settings.http_host, settings.http_port).start()
    log.info("Web server on %s:%d", settings.http_host, settings.http_port)

    await setup_bot_profile(bot, settings)
    try:
        await asyncio.gather(
            run_mqtt(settings, store),
            prune_loop(store, settings.history_days),
            dp.start_polling(bot),
        )
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
