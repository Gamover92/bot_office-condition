"""Each minute: check alerts and send morning reports."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat

from .alerts import in_quiet_hours, step
from .chat_settings import ChatConfig, ChatStore
from .config import Settings
from .store import Store
from .summary import alert_text
from .view import build_view, send_view

log = logging.getLogger(__name__)

CATCH_UP_UNTIL_HOUR = 12
CATCH_UP_MIN = 10
REPORT_HOURS = 12


def report_due(cfg: ChatConfig, now: datetime, last_date: str | None) -> bool:
    if not cfg.report or last_date == now.date().isoformat():
        return False
    if cfg.report_days == "workdays" and now.weekday() >= 5:
        return False
    hours, minutes = map(int, cfg.report_time.split(":"))
    start = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    noon = now.replace(hour=CATCH_UP_UNTIL_HOUR, minute=0, second=0, microsecond=0)
    end = max(noon, start + timedelta(minutes=CATCH_UP_MIN))
    return start <= now < end


async def _check_chat(
    bot: Bot, settings: Settings, store: Store, chats: ChatStore, chat_id: int, now_ts: float
) -> None:
    cfg = chats.get(chat_id)
    local = datetime.fromtimestamp(now_ts, ZoneInfo(settings.tz))

    if cfg.alerts:
        quiet = in_quiet_hours(cfg, local)
        for mac in store.devices():
            reading = store.latest(mac)
            if reading is None or now_ts - reading.ts > settings.stale_after_min * 60:
                continue
            states, events = step(reading.values, cfg, chats.alert_states(chat_id, mac), quiet)
            for event in events:
                await bot.send_message(chat_id, alert_text(settings, mac, event))
            chats.save_alert_states(chat_id, mac, states)

    if report_due(cfg, local, chats.last_report(chat_id)):
        # Mark first: an error in sending must not cause a new report each minute.
        chats.mark_report(chat_id, local.date().isoformat())
        try:
            await send_view(bot, chat_id, await build_view(settings, store, hours=REPORT_HOURS, now=now_ts))
        except TelegramMigrateToChat:
            # The report was not delivered: let the new chat get it in the catch-up window.
            chats.unmark_report(chat_id)
            raise


async def tick(
    bot: Bot, settings: Settings, store: Store, chats: ChatStore, now_ts: float | None = None
) -> None:
    now_ts = time.time() if now_ts is None else now_ts
    for chat_id in chats.chats():
        try:
            await _check_chat(bot, settings, store, chats, chat_id, now_ts)
        except TelegramForbiddenError:
            log.warning("No access to chat %s: alerts and report are now off", chat_id)
            chats.disable(chat_id)
        except TelegramMigrateToChat as exc:
            new_id = exc.migrate_to_chat_id
            log.warning(
                "Group %s became a supergroup with ID %s: replace the old ID with the new one in ALLOWED_CHAT_IDS",
                chat_id,
                new_id,
            )
            chats.migrate(chat_id, new_id, overwrite=False)
        except TelegramBadRequest as exc:
            if "chat not found" not in str(exc):
                log.exception("Scheduler failed for chat %s", chat_id)
                continue
            # A wrong ID in ALLOWED_CHAT_IDS, or the bot is not in the chat yet. Forget the chat
            # so it is not retried every minute; a restart or a message there registers it again.
            log.warning(
                "Chat %s not found: check ALLOWED_CHAT_IDS (a supergroup ID starts with -100) "
                "and that the bot is a member of the chat",
                chat_id,
            )
            chats.forget(chat_id)
        except Exception:
            log.exception("Scheduler failed for chat %s", chat_id)


async def run_scheduler(
    bot: Bot, settings: Settings, store: Store, chats: ChatStore, interval: float = 60
) -> None:
    while True:
        try:
            await tick(bot, settings, store, chats)
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(interval)
