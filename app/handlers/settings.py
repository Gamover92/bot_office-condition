"""/settings menu for chat admins."""

from __future__ import annotations

import time
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..access import AdminChecker
from ..chat_settings import ChatConfig, ChatStore, parse_number, parse_range, parse_time, parse_time_range

INPUT_TIMEOUT = 300
TOGGLES = ("alerts", "report", "quiet", "report_days")
FIELDS: dict[str, tuple[str, Callable[[str], Any], str]] = {
    "report_time": ("время утреннего отчёта", parse_time, "09:00"),
    "quiet_hours": ("тихие часы", parse_time_range, "20:00-08:00"),
    "co2_max": ("максимум CO₂, ppm", parse_number, "1000"),
    "temp": ("диапазон температуры, °C", parse_range, "19-26"),
    "humidity": ("диапазон влажности, %", parse_range, "35-60"),
    "pm25_max": ("максимум PM2.5, мкг/м³", parse_number, "25"),
}


class SetCb(CallbackData, prefix="st"):
    action: str
    field: str = ""


class EditValue(StatesGroup):
    waiting = State()


def _onoff(value: bool) -> str:
    return "ВКЛ" if value else "ВЫКЛ"


def menu_text(cfg: ChatConfig) -> str:
    days = "пн–пт" if cfg.report_days == "workdays" else "каждый день"
    return "\n".join(
        [
            "⚙️ <b>Настройки этого чата</b>",
            "",
            f"🔔 Уведомления: <b>{_onoff(cfg.alerts)}</b>",
            f"🌅 Утренний отчёт: <b>{_onoff(cfg.report)}</b>, {cfg.report_time}, {days}",
            f"🌙 Тихие часы: <b>{_onoff(cfg.quiet)}</b>, {cfg.quiet_hours.replace('-', '–')}",
            "",
            "📏 <b>Пороги уведомлений</b>",
            f"CO₂ &gt; {cfg.co2_max:g} ppm",
            f"Температура {cfg.temp[0]:g}–{cfg.temp[1]:g} °C",
            f"Влажность {cfg.humidity[0]:g}–{cfg.humidity[1]:g} %",
            f"PM2.5 &gt; {cfg.pm25_max:g} мкг/м³",
        ]
    )


def _b(text: str, action: str, field: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=SetCb(action=action, field=field).pack())


def menu_keyboard(cfg: ChatConfig) -> InlineKeyboardMarkup:
    days = "📅 Каждый день" if cfg.report_days == "workdays" else "📅 Только пн–пт"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_b(f"🔔 {'Выключить' if cfg.alerts else 'Включить'} уведомления", "toggle", "alerts")],
            [
                _b(f"🌅 {'Выкл.' if cfg.report else 'Вкл.'} отчёт", "toggle", "report"),
                _b("🕘 Время", "edit", "report_time"),
                _b(days, "toggle", "report_days"),
            ],
            [
                _b(f"🌙 {'Выкл.' if cfg.quiet else 'Вкл.'} тихие часы", "toggle", "quiet"),
                _b("🕗 Период", "edit", "quiet_hours"),
            ],
            [
                _b("CO₂", "edit", "co2_max"),
                _b("Темп.", "edit", "temp"),
                _b("Влажн.", "edit", "humidity"),
                _b("PM2.5", "edit", "pm25_max"),
            ],
            [_b("↩️ Сбросить", "reset"), _b("✖️ Закрыть", "close")],
        ]
    )


def toggle_changes(cfg: ChatConfig, field: str) -> dict[str, Any]:
    if field == "report_days":
        return {"report_days": "all" if cfg.report_days == "workdays" else "workdays"}
    if field in TOGGLES:
        return {field: not getattr(cfg, field)}
    raise ValueError(field)


def parse_input(field: str, text: str) -> Any:
    if field not in FIELDS:
        raise ValueError(field)
    return FIELDS[field][1](text)


def build_router(chats: ChatStore, admins: AdminChecker) -> Router:
    router = Router(name="settings")

    @router.message(Command("settings"))
    async def open_menu(message: Message, bot: Bot, state: FSMContext) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if not await admins.is_admin(bot, message.chat.id, message.chat.type, user_id):
            await message.answer("Настройки могут менять только админы чата.")
            return
        await state.clear()
        cfg = chats.get(message.chat.id)
        await message.answer(menu_text(cfg), reply_markup=menu_keyboard(cfg))

    @router.callback_query(SetCb.filter())
    async def on_button(query: CallbackQuery, callback_data: SetCb, bot: Bot, state: FSMContext) -> None:
        msg = query.message
        if not isinstance(msg, Message):
            await query.answer()
            return
        if not await admins.is_admin(bot, msg.chat.id, msg.chat.type, query.from_user.id):
            await query.answer("Только для админов", show_alert=True)
            return
        chat_id = msg.chat.id
        action, field = callback_data.action, callback_data.field

        if action == "close":
            await state.clear()
            try:
                await msg.delete()
            except TelegramBadRequest:
                try:
                    await msg.edit_reply_markup(reply_markup=None)
                except TelegramBadRequest:
                    pass
            await query.answer()
            return
        if action == "edit" and field in FIELDS:
            title, _, example = FIELDS[field]
            await state.set_state(EditValue.waiting)
            await state.update_data(field=field, started=time.time())
            await query.answer()
            await msg.answer(
                f"Введите {title}. Пример: <code>{example}</code>",
                reply_markup=ForceReply(input_field_placeholder=example),
            )
            return
        if action == "toggle" and field in TOGGLES:
            await state.clear()
            cfg = chats.update(chat_id, **toggle_changes(chats.get(chat_id), field))
        elif action == "reset":
            await state.clear()
            chats.reset(chat_id)
            cfg = chats.get(chat_id)
        else:
            await query.answer()
            return
        try:
            await msg.edit_text(menu_text(cfg), reply_markup=menu_keyboard(cfg))
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
        await query.answer("Сохранено")

    @router.message(EditValue.waiting, F.text, ~F.text.startswith("/"))
    async def on_value(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        if time.time() - data.get("started", 0) > INPUT_TIMEOUT:
            await state.clear()
            await message.answer("Время ввода истекло. Откройте /settings снова.")
            return
        field = data["field"]
        try:
            value = parse_input(field, message.text or "")
        except ValueError:
            await message.answer(f"Неверный формат. Пример: <code>{FIELDS[field][2]}</code>")
            return
        await state.clear()
        cfg = chats.update(message.chat.id, **{field: value})
        await message.answer("✅ Сохранено.\n\n" + menu_text(cfg), reply_markup=menu_keyboard(cfg))

    return router
