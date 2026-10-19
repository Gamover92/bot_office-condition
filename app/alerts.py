"""Alert rules: pure functions, no Telegram and no database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from .chat_settings import AlertState, ChatConfig

HYSTERESIS = 0.05

Bounds = tuple[float | None, float | None]


@dataclass(frozen=True)
class Event:
    metric: str
    kind: str  # "bad" or "ok"
    value: float
    bounds: Bounds


def bounds(cfg: ChatConfig) -> dict[str, Bounds]:
    return {
        "co2": (None, cfg.co2_max),
        "temperature": cfg.temp,
        "humidity": cfg.humidity,
        "pm25": (None, cfg.pm25_max),
    }


def _outside(value: float, b: Bounds) -> bool:
    lo, hi = b
    return (lo is not None and value < lo) or (hi is not None and value > hi)


def _well_inside(value: float, b: Bounds) -> bool:
    lo, hi = b
    if lo is not None and hi is not None:
        margin = (hi - lo) * HYSTERESIS
        return lo + margin <= value <= hi - margin
    if hi is not None:
        return value <= hi - abs(hi) * HYSTERESIS
    assert lo is not None
    return value >= lo + abs(lo) * HYSTERESIS


def _next_state(value: float, b: Bounds, prev: str) -> str:
    if prev == "ok":
        return "bad" if _outside(value, b) else "ok"
    return "ok" if _well_inside(value, b) else "bad"


def step(
    values: dict[str, float], cfg: ChatConfig, states: dict[str, AlertState], quiet: bool
) -> tuple[dict[str, AlertState], list[Event]]:
    """Update alert states from new values. Return the new states and the messages to send.

    A message is sent when the state differs from the last sent state, outside quiet hours.
    """
    new_states = dict(states)
    events = []
    for metric, b in bounds(cfg).items():
        if metric not in values:
            continue
        prev = states.get(metric, AlertState())
        state = _next_state(values[metric], b, prev.state)
        sent = prev.sent
        if not quiet and state != sent:
            events.append(Event(metric, state, values[metric], b))
            sent = state
        new_states[metric] = AlertState(state, sent)
    return new_states, events


def _time(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def in_quiet_hours(cfg: ChatConfig, now: datetime) -> bool:
    if not cfg.quiet:
        return False
    start, end = (_time(t) for t in cfg.quiet_hours.split("-"))
    t = now.time()
    if start < end:
        return start <= t < end
    return t >= start or t < end
