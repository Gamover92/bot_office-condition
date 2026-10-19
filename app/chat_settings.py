"""Per-chat settings, alert state and report log, stored in SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, fields, replace
from typing import Any, Callable


@dataclass(frozen=True)
class ChatConfig:
    alerts: bool = True
    report: bool = True
    report_time: str = "09:00"
    report_days: str = "workdays"  # "workdays" or "all"
    quiet: bool = True
    quiet_hours: str = "20:00-08:00"
    co2_max: float = 1200.0
    temp: tuple[float, float] = (18.0, 27.0)
    humidity: tuple[float, float] = (30.0, 70.0)
    pm25_max: float = 35.0

    def with_changes(self, changes: dict[str, Any]) -> "ChatConfig":
        names = {f.name for f in fields(self)}
        clean = {k: tuple(v) if isinstance(v, list) else v for k, v in changes.items() if k in names}
        return replace(self, **clean)


@dataclass(frozen=True)
class AlertState:
    state: str = "ok"  # current state: "ok" or "bad"
    sent: str = "ok"  # state of the last message sent to the chat


_NUM = r"\s*(-?\d+(?:[.,]\d+)?)\s*"
_DASH = r"[-–—]"


def _float(text: str) -> float:
    return float(text.replace(",", "."))


def parse_number(text: str) -> float:
    m = re.fullmatch(_NUM, text)
    if not m or _float(m.group(1)) <= 0:
        raise ValueError(text)
    return _float(m.group(1))


def parse_range(text: str) -> tuple[float, float]:
    m = re.fullmatch(_NUM + _DASH + _NUM, text)
    if not m:
        raise ValueError(text)
    lo, hi = _float(m.group(1)), _float(m.group(2))
    if lo >= hi:
        raise ValueError(text)
    return (lo, hi)


def parse_time(text: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(text)
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_time_range(text: str) -> str:
    parts = re.split(r"\s*" + _DASH + r"\s*", text.strip())
    if len(parts) != 2:
        raise ValueError(text)
    start, end = parse_time(parts[0]), parse_time(parts[1])
    if start == end:
        raise ValueError(text)
    return f"{start}-{end}"


def parse_bool(text: str) -> bool:
    t = text.strip().lower()
    if t in ("1", "true", "yes", "on", "да"):
        return True
    if t in ("0", "false", "no", "off", "нет"):
        return False
    raise ValueError(text)


def parse_days(text: str) -> str:
    t = text.strip().lower()
    if t not in ("workdays", "all"):
        raise ValueError(text)
    return t


ENV_PARSERS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "ALERTS": ("alerts", parse_bool),
    "REPORT": ("report", parse_bool),
    "REPORT_TIME": ("report_time", parse_time),
    "REPORT_DAYS": ("report_days", parse_days),
    "QUIET": ("quiet", parse_bool),
    "QUIET_HOURS": ("quiet_hours", parse_time_range),
    "CO2_MAX": ("co2_max", parse_number),
    "TEMP_RANGE": ("temp", parse_range),
    "HUMIDITY_RANGE": ("humidity", parse_range),
    "PM25_MAX": ("pm25_max", parse_number),
}


def defaults_from_env(raw: dict[str, str]) -> ChatConfig:
    changes = {name: parser(raw[env]) for env, (name, parser) in ENV_PARSERS.items() if env in raw}
    return ChatConfig().with_changes(changes)


class ChatStore:
    def __init__(self, db: sqlite3.Connection, defaults: ChatConfig):
        self.db = db
        self.defaults = defaults
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alert_state (
                chat_id INTEGER NOT NULL, mac TEXT NOT NULL, metric TEXT NOT NULL,
                state TEXT NOT NULL, sent TEXT NOT NULL,
                PRIMARY KEY (chat_id, mac, metric));
            CREATE TABLE IF NOT EXISTS report_log (
                chat_id INTEGER PRIMARY KEY, date TEXT NOT NULL);
            """
        )
        db.commit()

    def register(self, chat_id: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO chat_settings (chat_id, data) VALUES (?, '{}')", (chat_id,))
        self.db.commit()

    def chats(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT chat_id FROM chat_settings ORDER BY chat_id")]

    def _overrides(self, chat_id: int) -> dict[str, Any]:
        row = self.db.execute("SELECT data FROM chat_settings WHERE chat_id=?", (chat_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _save(self, chat_id: int, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)", (chat_id, json.dumps(data))
        )
        self.db.commit()

    def get(self, chat_id: int) -> ChatConfig:
        return self.defaults.with_changes(self._overrides(chat_id))

    def update(self, chat_id: int, **changes: Any) -> ChatConfig:
        self._save(chat_id, {**self._overrides(chat_id), **changes})
        return self.get(chat_id)

    def reset(self, chat_id: int) -> None:
        self._save(chat_id, {})

    def disable(self, chat_id: int) -> None:
        self.update(chat_id, alerts=False, report=False)

    def alert_states(self, chat_id: int, mac: str) -> dict[str, AlertState]:
        rows = self.db.execute(
            "SELECT metric, state, sent FROM alert_state WHERE chat_id=? AND mac=?", (chat_id, mac)
        )
        return {metric: AlertState(state, sent) for metric, state, sent in rows}

    def save_alert_states(self, chat_id: int, mac: str, states: dict[str, AlertState]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO alert_state (chat_id, mac, metric, state, sent) VALUES (?, ?, ?, ?, ?)",
            [(chat_id, mac, metric, s.state, s.sent) for metric, s in states.items()],
        )
        self.db.commit()

    def last_report(self, chat_id: int) -> str | None:
        row = self.db.execute("SELECT date FROM report_log WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else None

    def mark_report(self, chat_id: int, date: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO report_log (chat_id, date) VALUES (?, ?)", (chat_id, date))
        self.db.commit()

    def migrate(self, old_id: int, new_id: int, overwrite: bool = True) -> None:
        """Move a chat to its new ID (group upgraded to supergroup).

        With overwrite=True the old rows replace the new chat's rows. With overwrite=False an
        existing new chat keeps its rows and the old chat's rows are deleted.
        """
        tables = ("chat_settings", "alert_state", "report_log")
        with self.db:
            if not overwrite and self.db.execute(
                "SELECT 1 FROM chat_settings WHERE chat_id=?", (new_id,)
            ).fetchone():
                for table in tables:
                    self.db.execute(f"DELETE FROM {table} WHERE chat_id=?", (old_id,))
                return
            for table in tables:
                self.db.execute(f"UPDATE OR REPLACE {table} SET chat_id=? WHERE chat_id=?", (new_id, old_id))
