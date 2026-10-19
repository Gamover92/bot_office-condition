"""Parse Qingping JSON MQTT messages and rate the readings.

Qingping devices with private MQTT publish JSON like:
    {"id": 1, "mac": "582D34XXXXXX", "type": "12", "need_ack": 1,
     "sensorData": [{"timestamp": {"value": 1700000000},
                     "temperature": {"value": 23.4, "status": 0},
                     "co2": {"value": 650}, ...}]}
The parser is tolerant: plain numbers and a single sensorData object also work.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

# Metric key -> (title, unit, digits). The order sets the display order.
METRICS: dict[str, tuple[str, str, int]] = {
    "temperature": ("Температура", "°C", 1),
    "humidity": ("Влажность", "%", 0),
    "co2": ("CO₂", "ppm", 0),
    "pm25": ("PM2.5", "мкг/м³", 0),
    "pm10": ("PM10", "мкг/м³", 0),
    "tvoc": ("TVOC", "ppb", 0),
    "tvoc_index": ("TVOC индекс", "", 0),
    "noise": ("Шум", "дБ", 0),
    "pressure": ("Давление", "кПа", 1),
    "battery": ("Батарея", "%", 0),
}

ALIASES = {"pm2.5": "pm25", "pm2_5": "pm25", "temp": "temperature", "hum": "humidity"}

# Upper limits for "good" and "fair"; above "fair" is "bad".
# For temperature and humidity a comfort band is used instead.
LIMITS: dict[str, tuple[float, float]] = {
    "co2": (800, 1200),
    "pm25": (15, 35),
    "pm10": (45, 100),
    "tvoc": (250, 600),
    "tvoc_index": (150, 250),
    "noise": (55, 70),
}
BANDS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    # (good band, fair band)
    "temperature": ((20, 24.5), (18, 27)),
    "humidity": ((40, 60), (30, 70)),
}


@dataclass(frozen=True)
class Reading:
    mac: str
    ts: int
    values: dict[str, float]


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def mac_from_topic(topic: str) -> str:
    parts = topic.split("/")
    return parts[1].upper() if len(parts) >= 3 else ""


def parse_message(topic: str, payload: bytes | str) -> list[Reading]:
    """Return readings found in one MQTT message (empty list if none)."""
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    mac = str(data.get("mac") or mac_from_topic(topic)).upper().replace(":", "")
    if not mac:
        return []
    msg_ts = _num(data.get("timestamp"))

    samples = data.get("sensorData", data)
    if isinstance(samples, dict):
        samples = [samples]
    if not isinstance(samples, list):
        return []

    readings = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        values: dict[str, float] = {}
        for key, raw in sample.items():
            key = ALIASES.get(key.lower(), key.lower())
            if key in METRICS:
                num = _num(raw)
                if num is not None:
                    values[key] = num
        if not values:
            continue
        ts = _num(sample.get("timestamp")) or msg_ts or time.time()
        if ts > 1e12:  # milliseconds
            ts /= 1000
        readings.append(Reading(mac=mac, ts=int(ts), values=values))
    return readings


def rate(metric: str, value: float) -> str:
    """Return "good", "fair", "bad", or "none" (no scale for the metric)."""
    if metric in LIMITS:
        good, fair = LIMITS[metric]
        return "good" if value <= good else "fair" if value <= fair else "bad"
    if metric in BANDS:
        (g_lo, g_hi), (f_lo, f_hi) = BANDS[metric]
        if g_lo <= value <= g_hi:
            return "good"
        return "fair" if f_lo <= value <= f_hi else "bad"
    return "none"


def overall(values: dict[str, float]) -> str:
    rates = {rate(k, v) for k, v in values.items()}
    for level in ("bad", "fair", "good"):
        if level in rates:
            return level
    return "none"


def advice(values: dict[str, float]) -> list[str]:
    tips = []
    co2 = values.get("co2")
    if co2 is not None and co2 > 1000:
        tips.append("Проветрите помещение: CO₂ высокий.")
    t = values.get("temperature")
    if t is not None and t > 26:
        tips.append("Жарко: включите кондиционер.")
    elif t is not None and t < 19:
        tips.append("Холодно: проверьте отопление.")
    h = values.get("humidity")
    if h is not None and h < 30:
        tips.append("Сухой воздух: включите увлажнитель.")
    elif h is not None and h > 70:
        tips.append("Высокая влажность: проветрите.")
    pm = values.get("pm25")
    if pm is not None and pm > 35:
        tips.append("Много пыли PM2.5: закройте окна, включите очиститель.")
    return tips


def fmt_value(metric: str, value: float) -> str:
    _, unit, digits = METRICS[metric]
    text = f"{value:.{digits}f}"
    return f"{text} {unit}".strip()
