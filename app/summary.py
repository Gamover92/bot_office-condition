"""Texts: summary caption and alert messages (Telegram HTML)."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from .alerts import Bounds, Event
from .config import Settings
from .qingping import METRICS, Reading, advice, fmt_value, overall, rate

ICONS = {"good": "🟢", "fair": "🟡", "bad": "🔴", "none": "⚪️"}
VERDICT = {
    "good": "Климат в норме",
    "fair": "Климат удовлетворительный",
    "bad": "Климат плохой",
    "none": "Нет оценки",
}
NO_DATA = (
    "Данных с датчиков пока нет.\n"
    "Проверьте, что Qingping отправляет данные на MQTT-брокер этого ПК "
    "(порт 1883, топик qingping/&lt;MAC&gt;/up)."
)
ACTIONS = {
    "co2": "Проветрите помещение.",
    "pm25": "Закройте окна, включите очиститель воздуха.",
    "temperature": "Проверьте отопление или кондиционер.",
    "humidity": "Проверьте увлажнитель или проветрите.",
}


def device_name(settings: Settings, mac: str) -> str:
    return settings.device_names.get(mac, f"Датчик {mac[-4:]}")


def caption(settings: Settings, reading: Reading | None, now: float) -> str:
    if reading is None:
        return NO_DATA
    values = reading.values
    state = overall({k: v for k, v in values.items() if k != "battery"})
    name = html.escape(device_name(settings, reading.mac))
    lines = [f"🌡 <b>{name}</b> — {ICONS[state]} {VERDICT[state]}", ""]
    for key in METRICS:
        if key in values:
            lines.append(f"{ICONS[rate(key, values[key])]} {METRICS[key][0]}: <b>{fmt_value(key, values[key])}</b>")
    tips = advice(values)
    if tips:
        lines.append("")
        lines += [f"💡 {html.escape(t)}" for t in tips]
    when = datetime.fromtimestamp(reading.ts, ZoneInfo(settings.tz)).strftime("%d.%m %H:%M")
    stale = " ⚠️ данные устарели" if now - reading.ts > settings.stale_after_min * 60 else ""
    lines += ["", f"<i>Обновлено {when}{stale}</i>"]
    return "\n".join(lines)


def _norm(b: Bounds) -> str:
    lo, hi = b
    if lo is not None and hi is not None:
        return f"норма {lo:g}–{hi:g}"
    return f"норма до {hi:g}" if hi is not None else f"норма от {lo:g}"


def alert_text(settings: Settings, mac: str, event: Event) -> str:
    name = html.escape(device_name(settings, mac))
    title = METRICS[event.metric][0]
    value = fmt_value(event.metric, event.value)
    if event.kind == "bad":
        return f"🔴 <b>{name}</b>: {title} {value} ({_norm(event.bounds)}). {ACTIONS[event.metric]}"
    return f"🟢 <b>{name}</b>: {title} снова в норме: {value}."
