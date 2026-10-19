"""Build the climate summary for the bot message and the Mini App API."""

from __future__ import annotations

import html
import time
from datetime import datetime

from .config import Settings
from .qingping import METRICS, advice, fmt_value, overall, rate
from .store import Store

ICONS = {"good": "🟢", "fair": "🟡", "bad": "🔴", "none": "⚪️"}
VERDICT = {
    "good": "Климат в норме",
    "fair": "Климат удовлетворительный",
    "bad": "Климат плохой",
    "none": "Нет оценки",
}


def device_name(settings: Settings, mac: str) -> str:
    return settings.device_names.get(mac, f"Датчик {mac[-4:]}")


def snapshot(settings: Settings, store: Store) -> list[dict]:
    """Latest state of every device, as JSON-ready dicts."""
    now = time.time()
    result = []
    for mac in store.devices():
        r = store.latest(mac)
        if r is None:
            continue
        metrics = [
            {
                "key": k,
                "title": METRICS[k][0],
                "unit": METRICS[k][1],
                "value": round(r.values[k], METRICS[k][2]),
                "rating": rate(k, r.values[k]),
            }
            for k in METRICS
            if k in r.values
        ]
        result.append(
            {
                "mac": mac,
                "name": device_name(settings, mac),
                "ts": r.ts,
                "stale": now - r.ts > settings.stale_after_min * 60,
                "overall": overall({k: v for k, v in r.values.items() if k != "battery"}),
                "metrics": metrics,
                "advice": advice(r.values),
            }
        )
    return result


def summary_html(settings: Settings, store: Store) -> str:
    devices = snapshot(settings, store)
    if not devices:
        return "Данных с датчиков пока нет. Проверьте, что датчик Qingping отправляет данные в MQTT."
    blocks = []
    for d in devices:
        when = datetime.fromtimestamp(d["ts"]).strftime("%d.%m %H:%M")
        lines = [f"<b>{html.escape(d['name'])}</b> — {ICONS[d['overall']]} {VERDICT[d['overall']]}"]
        for m in d["metrics"]:
            lines.append(f"{ICONS[m['rating']]} {m['title']}: <b>{fmt_value(m['key'], m['value'])}</b>")
        lines += [f"💡 {html.escape(t)}" for t in d["advice"]]
        stale = " ⚠️ данные устарели" if d["stale"] else ""
        lines.append(f"<i>Обновлено {when}{stale}</i>")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
