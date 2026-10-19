# Office Climate Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Telegram bot shows the office climate from a Qingping Air Monitor (via MQTT). It has a `/climate` summary with a PNG chart and buttons, alerts, a morning report, and a `/settings` menu. Everything runs in Docker on one office PC.

**Architecture:** Two Docker containers: `mosquitto` (MQTT broker in the LAN) and `bot` (Python). The bot saves readings to SQLite and uses long polling, so no inbound ports from the Internet. The modules are small: pure logic (`qingping`, `alerts`, `chat_settings` parsers) is separate from I/O (`store`, `view`, handlers, scheduler), so it is easy to test.

**Tech Stack:** Python 3.13, aiogram 3.31.0, aiomqtt 2.5.1, matplotlib 3.11.2, tzdata 2026.5, SQLite (stdlib), pytest 9.1.1, pytest-asyncio 1.4.0, eclipse-mosquitto 2.0.20, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-19-office-climate-bot-design.md`

## Global Constraints

- No Mini App, no HTTP server, no open Internet ports. The bot uses long polling only.
- No external services except Telegram. Charts are drawn locally with matplotlib (`Figure` API, not `pyplot`).
- User-facing texts are in Russian. Code, comments, and commit messages are in English.
- Time zone: env `TZ`, default `Europe/Moscow`.
- Default chat settings: CO₂ max 1200 ppm, temperature 18–27 °C, humidity 30–70 %, PM2.5 max 35, alerts on, report on 09:00 Mon–Fri, quiet hours on 20:00–08:00.
- Alerts: one message on `ok → bad`, one on `bad → ok`, no repeats. Hysteresis 5 %. Messages during quiet hours wait. No alert evaluation on data older than `STALE_AFTER_MIN` (default 30).
- Morning report: once per day, CO₂ chart for the last 12 h. Catch-up until 12:00, or 10 min after the report time if that is later.
- `/settings` only for group admins (`getChatMember`, cache 5 min) or `ADMIN_USER_IDS` in private chats. Value input timeout 5 min.
- Bot parse mode: HTML. Escape user-controlled text (device names) with `html.escape`.
- Run tests with `python -m pytest -q` from the repository root.

## File Structure

| File | Task | Purpose |
|---|---|---|
| `app/config.py` | 1 | `Settings` from env |
| `app/qingping.py` | (kept) | Parse Qingping JSON, comfort rating, advice |
| `app/store.py` | (kept) | Readings in SQLite |
| `app/mqtt_listener.py` | (kept) | MQTT subscribe + save |
| `app/chat_settings.py` | 2 | `ChatConfig`, input parsers, `AlertState`, `ChatStore` |
| `app/alerts.py` | 3 | Pure alert rules, quiet hours |
| `app/charts.py` | 4 | PNG chart |
| `app/summary.py` | 5 | Caption text, alert text |
| `app/view.py` | 5 | `View`, keyboard, `build_view`, `send_view`, `edit_view` |
| `app/access.py` | 6 | `AccessMiddleware`, `AdminChecker` |
| `app/handlers/climate.py` | 6 | `/start`, `/climate`, keywords, summary buttons |
| `app/handlers/settings.py` | 7 | `/settings` menu and value input |
| `app/scheduler.py` | 8 | `report_due`, `tick`, `run_scheduler` |
| `app/main.py` | 9 | Start everything |
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md` | 9 | Deployment |

Files to delete (Mini App draft): `app/web.py`, `app/auth.py`, `app/bot.py`, `app/summary.py` (rewritten in Task 5), `app/main.py` (rewritten in Task 9), `app/static/`, `tests/test_app.py`.

---

### Task 1: Remove the Mini App draft, update config and dependencies

**Files:**
- Delete: `app/web.py`, `app/auth.py`, `app/bot.py`, `app/summary.py`, `app/main.py`, `app/static/`, `tests/test_app.py`
- Modify: `app/config.py` (full rewrite)
- Modify: `requirements.txt`, `requirements-dev.txt`
- Create: `tests/test_config.py`, `tests/test_qingping.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `app/qingping.py` and `app/store.py` as they are now (`parse_message`, `rate`, `overall`, `advice`, `fmt_value`, `METRICS`, `LIMITS`, `BANDS`, `Reading(mac, ts, values)`, `Store(path)` with `.db`, `add`, `devices`, `latest`, `history`, `prune`).
- Produces: `Settings` (frozen dataclass) with fields `bot_token: str`, `allowed_chats: frozenset[int]`, `allowed_users: frozenset[int]`, `admin_users: frozenset[int]`, `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password`, `mqtt_topic`, `device_names: dict[str, str]`, `db_path`, `history_days: int`, `stale_after_min: int`, `tz: str`, `chat_defaults: dict[str, str]`; methods `Settings.from_env()` and `is_allowed(user_id, chat_id=None) -> bool`. Constant `CHAT_ENV_KEYS: tuple[str, ...]`.

- [ ] **Step 1: Delete the Mini App files**

```bash
git rm -r -q app/web.py app/auth.py app/bot.py app/summary.py app/main.py app/static tests/test_app.py
```

- [ ] **Step 2: Update dependencies**

`requirements.txt`:
```
aiogram==3.31.0
aiomqtt==2.5.1
matplotlib==3.11.2
tzdata==2026.5
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==9.1.1
pytest-asyncio==1.4.0
```

Run: `pip install -q -r requirements-dev.txt`
Expected: no errors.

- [ ] **Step 3: Write the failing tests**

`tests/test_config.py`:
```python
import pytest

from app.config import CHAT_ENV_KEYS, Settings


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("TZ", "ALLOWED_CHAT_IDS", "ALLOWED_USER_IDS", "ADMIN_USER_IDS", "DEVICE_NAMES", *CHAT_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_from_env(clean_env):
    clean_env.setenv("BOT_TOKEN", "1:x")
    clean_env.setenv("ALLOWED_CHAT_IDS", "-100, 5")
    clean_env.setenv("ADMIN_USER_IDS", "7")
    clean_env.setenv("DEVICE_NAMES", "aabb=Офис; ccdd = Переговорка")
    clean_env.setenv("CO2_MAX", "1000")
    s = Settings.from_env()
    assert s.bot_token == "1:x"
    assert s.allowed_chats == {-100, 5}
    assert s.admin_users == {7}
    assert s.device_names == {"AABB": "Офис", "CCDD": "Переговорка"}
    assert s.chat_defaults == {"CO2_MAX": "1000"}
    assert s.tz == "Europe/Moscow"


def test_is_allowed():
    assert Settings(bot_token="x").is_allowed(1, 2)
    s = Settings(bot_token="x", allowed_chats=frozenset({-100}), allowed_users=frozenset({7}))
    assert s.is_allowed(7, 1)
    assert s.is_allowed(1, -100)
    assert not s.is_allowed(1, 2)
    assert not s.is_allowed(None, None)
```

`tests/test_qingping.py`:
```python
import json

from app.qingping import advice, overall, parse_message, rate

QINGPING_MSG = {
    "id": 7,
    "mac": "582D34AABBCC",
    "type": "12",
    "need_ack": 1,
    "sensorData": [
        {
            "timestamp": {"value": 1_700_000_000},
            "temperature": {"value": 23.4, "status": 0},
            "humidity": {"value": 45.1},
            "co2": {"value": 1350},
            "pm25": {"value": 8},
            "battery": {"value": 100},
        },
        {"timestamp": {"value": 1_700_000_900}, "co2": {"value": 700}},
    ],
}


def test_parse_qingping_json():
    readings = parse_message("qingping/582D34AABBCC/up", json.dumps(QINGPING_MSG))
    assert [r.ts for r in readings] == [1_700_000_000, 1_700_000_900]
    assert readings[0].mac == "582D34AABBCC"
    assert readings[0].values == {"temperature": 23.4, "humidity": 45.1, "co2": 1350, "pm25": 8, "battery": 100}


def test_parse_realtime_type_17():
    msg = {"mac": "AA", "type": "17", "sensorData": [{"timestamp": {"value": 5}, "co2": {"value": 600}}]}
    assert parse_message("qingping/AA/up", json.dumps(msg))[0].values == {"co2": 600}


def test_parse_flat_payload_uses_topic_mac():
    readings = parse_message("qingping/aabb/up", b'{"temperature": 21, "pm2.5": 3}')
    assert readings[0].mac == "AABB"
    assert readings[0].values == {"temperature": 21.0, "pm25": 3.0}


def test_parse_ignores_garbage():
    assert parse_message("qingping/x/up", b"\x00\x01") == []
    assert parse_message("qingping/x/up", b'{"type": "28", "setting": {}}') == []
    assert parse_message("qingping/x/up", b"[1, 2]") == []


def test_rating():
    assert rate("co2", 600) == "good"
    assert rate("co2", 1000) == "fair"
    assert rate("co2", 1500) == "bad"
    assert rate("temperature", 22) == "good"
    assert rate("temperature", 26) == "fair"
    assert rate("humidity", 20) == "bad"
    assert rate("battery", 5) == "none"
    assert overall({"co2": 600, "humidity": 35}) == "fair"


def test_advice():
    assert advice({"co2": 1100})[0].startswith("Проветрите")
    assert advice({"co2": 600, "temperature": 22}) == []
```

`tests/test_store.py`:
```python
import json
import time

from app.qingping import parse_message
from app.store import Store
from tests.test_qingping import QINGPING_MSG


def test_store_merges_latest_values():
    store = Store(":memory:")
    store.add(parse_message("qingping/x/up", json.dumps(QINGPING_MSG)))
    latest = store.latest("582D34AABBCC")
    assert latest.ts == 1_700_000_900
    assert latest.values["co2"] == 700
    assert latest.values["temperature"] == 23.4
    assert store.devices() == ["582D34AABBCC"]


def test_store_merges_partial_message_with_same_ts():
    store = Store(":memory:")
    store.add(parse_message("qingping/AA/up", b'{"timestamp": 10, "co2": 500}'))
    store.add(parse_message("qingping/AA/up", b'{"timestamp": 10, "humidity": 40}'))
    assert store.history("AA", 0)[0].values == {"co2": 500, "humidity": 40}


def test_store_history_and_prune():
    now = int(time.time())
    store = Store(":memory:")
    store.add(parse_message("qingping/AA/up", json.dumps({"timestamp": now - 40 * 86400, "co2": 1})))
    store.add(parse_message("qingping/AA/up", json.dumps({"timestamp": now, "co2": 2})))
    assert [r.values["co2"] for r in store.history("AA", now - 3600)] == [2]
    store.prune(30)
    assert [r.values["co2"] for r in store.history("AA", 0)] == [2]


def test_latest_unknown_device():
    assert Store(":memory:").latest("NOPE") is None
```

Also create an empty `tests/__init__.py` if it does not exist (it exists in the draft).

- [ ] **Step 4: Run tests to verify the config test fails**

Run: `python -m pytest -q`
Expected: `tests/test_config.py` FAILS (ImportError: `CHAT_ENV_KEYS`). `test_qingping.py` and `test_store.py` PASS.

- [ ] **Step 5: Rewrite `app/config.py`**

```python
"""Settings read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Env names for the default chat settings. app.chat_settings parses them.
CHAT_ENV_KEYS = (
    "ALERTS",
    "REPORT",
    "REPORT_TIME",
    "REPORT_DAYS",
    "QUIET",
    "QUIET_HOURS",
    "CO2_MAX",
    "TEMP_RANGE",
    "HUMIDITY_RANGE",
    "PM25_MAX",
)


def _int_set(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _device_names(raw: str) -> dict[str, str]:
    # "AABBCCDDEEFF=Open space;112233445566=Meeting room"
    names: dict[str, str] = {}
    for item in raw.split(";"):
        if "=" in item:
            mac, name = item.split("=", 1)
            names[mac.strip().upper()] = name.strip()
    return names


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_chats: frozenset[int] = frozenset()
    allowed_users: frozenset[int] = frozenset()
    admin_users: frozenset[int] = frozenset()
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_topic: str = "qingping/+/up"
    device_names: dict[str, str] = field(default_factory=dict)
    db_path: str = "/data/climate.db"
    history_days: int = 30
    stale_after_min: int = 30
    tz: str = "Europe/Moscow"
    chat_defaults: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            bot_token=e("BOT_TOKEN", ""),
            allowed_chats=_int_set(e("ALLOWED_CHAT_IDS", "")),
            allowed_users=_int_set(e("ALLOWED_USER_IDS", "")),
            admin_users=_int_set(e("ADMIN_USER_IDS", "")),
            mqtt_host=e("MQTT_HOST", "mosquitto"),
            mqtt_port=int(e("MQTT_PORT", "1883")),
            mqtt_user=e("MQTT_USER", ""),
            mqtt_password=e("MQTT_PASSWORD", ""),
            mqtt_topic=e("MQTT_TOPIC", "qingping/+/up"),
            device_names=_device_names(e("DEVICE_NAMES", "")),
            db_path=e("DB_PATH", "/data/climate.db"),
            history_days=int(e("HISTORY_DAYS", "30")),
            stale_after_min=int(e("STALE_AFTER_MIN", "30")),
            tz=e("TZ", "Europe/Moscow"),
            chat_defaults={k: v for k in CHAT_ENV_KEYS if (v := e(k, ""))},
        )

    def is_allowed(self, user_id: int | None, chat_id: int | None = None) -> bool:
        """Empty allow-lists mean everyone is allowed."""
        if not self.allowed_chats and not self.allowed_users:
            return True
        return (user_id in self.allowed_users) or (chat_id in self.allowed_chats)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all PASS (12 tests).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Remove Mini App draft, add admin/TZ/chat defaults to config"
```

---

### Task 2: Chat settings, input parsers, alert state storage

**Files:**
- Create: `app/chat_settings.py`
- Test: `tests/test_chat_settings.py`

**Interfaces:**
- Consumes: `sqlite3.Connection` (from `Store.db`).
- Produces:
  - `ChatConfig` (frozen dataclass): `alerts: bool`, `report: bool`, `report_time: str` ("HH:MM"), `report_days: str` ("workdays" | "all"), `quiet: bool`, `quiet_hours: str` ("HH:MM-HH:MM"), `co2_max: float`, `temp: tuple[float, float]`, `humidity: tuple[float, float]`, `pm25_max: float`; method `with_changes(changes: dict) -> ChatConfig`.
  - Parsers (raise `ValueError` on bad input): `parse_number(text) -> float`, `parse_range(text) -> tuple[float, float]`, `parse_time(text) -> str`, `parse_time_range(text) -> str`, `parse_bool(text) -> bool`, `parse_days(text) -> str`.
  - `defaults_from_env(raw: dict[str, str]) -> ChatConfig`.
  - `AlertState` (frozen dataclass): `state: str = "ok"`, `sent: str = "ok"`.
  - `ChatStore(db, defaults: ChatConfig)`: `register(chat_id)`, `chats() -> list[int]`, `get(chat_id) -> ChatConfig`, `update(chat_id, **changes) -> ChatConfig`, `reset(chat_id)`, `disable(chat_id)`, `alert_states(chat_id, mac) -> dict[str, AlertState]`, `save_alert_states(chat_id, mac, states)`, `last_report(chat_id) -> str | None`, `mark_report(chat_id, date: str)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_chat_settings.py`:
```python
import sqlite3

import pytest

from app.chat_settings import (
    AlertState,
    ChatConfig,
    ChatStore,
    defaults_from_env,
    parse_bool,
    parse_days,
    parse_number,
    parse_range,
    parse_time,
    parse_time_range,
)


def make_store(defaults: ChatConfig | None = None) -> ChatStore:
    return ChatStore(sqlite3.connect(":memory:"), defaults or ChatConfig())


def test_parse_number():
    assert parse_number("1000") == 1000.0
    assert parse_number(" 12,5 ") == 12.5
    for bad in ("", "abc", "0", "-5", "10 20"):
        with pytest.raises(ValueError):
            parse_number(bad)


def test_parse_range():
    assert parse_range("19-26") == (19.0, 26.0)
    assert parse_range("19.5 – 26") == (19.5, 26.0)
    for bad in ("26-19", "20-20", "20", "a-b"):
        with pytest.raises(ValueError):
            parse_range(bad)


def test_parse_time():
    assert parse_time("9:00") == "09:00"
    assert parse_time("09.30") == "09:30"
    for bad in ("24:00", "9:60", "9", "ab:cd"):
        with pytest.raises(ValueError):
            parse_time(bad)


def test_parse_time_range():
    assert parse_time_range("20:00-08:00") == "20:00-08:00"
    assert parse_time_range("22:00 – 7:00") == "22:00-07:00"
    for bad in ("20:00", "20:00-20:00", "x-y"):
        with pytest.raises(ValueError):
            parse_time_range(bad)


def test_parse_bool_and_days():
    assert parse_bool("on") is True and parse_bool("0") is False
    assert parse_days("all") == "all"
    with pytest.raises(ValueError):
        parse_bool("maybe")
    with pytest.raises(ValueError):
        parse_days("weekends")


def test_defaults_from_env():
    cfg = defaults_from_env({"CO2_MAX": "1000", "TEMP_RANGE": "19-26", "QUIET": "off", "REPORT_TIME": "8:30"})
    assert cfg.co2_max == 1000
    assert cfg.temp == (19, 26)
    assert cfg.quiet is False
    assert cfg.report_time == "08:30"
    assert cfg.humidity == (30, 70)


def test_chat_store_settings_roundtrip():
    store = make_store(ChatConfig(co2_max=1100))
    store.register(5)
    store.register(5)
    assert store.chats() == [5]
    assert store.get(5).co2_max == 1100
    cfg = store.update(5, temp=(19.0, 25.0), alerts=False)
    assert cfg.temp == (19.0, 25.0) and cfg.alerts is False
    assert make_store_reloaded(store, 5).temp == (19.0, 25.0)
    store.reset(5)
    assert store.get(5) == ChatConfig(co2_max=1100)


def make_store_reloaded(store: ChatStore, chat_id: int) -> ChatConfig:
    # A new ChatStore on the same connection reads the saved JSON.
    return ChatStore(store.db, store.defaults).get(chat_id)


def test_disable_and_register_keeps_settings():
    store = make_store()
    store.register(1)
    store.disable(1)
    store.register(1)
    cfg = store.get(1)
    assert cfg.alerts is False and cfg.report is False


def test_alert_states_and_report_log():
    store = make_store()
    assert store.alert_states(1, "AA") == {}
    store.save_alert_states(1, "AA", {"co2": AlertState("bad", "ok")})
    assert store.alert_states(1, "AA") == {"co2": AlertState("bad", "ok")}
    assert store.last_report(1) is None
    store.mark_report(1, "2026-10-19")
    assert store.last_report(1) == "2026-10-19"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat_settings'`.

- [ ] **Step 3: Write `app/chat_settings.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_settings.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/chat_settings.py tests/test_chat_settings.py
git commit -m "Add per-chat settings, input parsers and alert state storage"
```

---

### Task 3: Alert rules

**Files:**
- Create: `app/alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `ChatConfig`, `AlertState` from `app.chat_settings`.
- Produces:
  - `Bounds = tuple[float | None, float | None]`
  - `bounds(cfg: ChatConfig) -> dict[str, Bounds]` with keys `co2`, `temperature`, `humidity`, `pm25`.
  - `Event` (frozen dataclass): `metric: str`, `kind: str` ("bad" | "ok"), `value: float`, `bounds: Bounds`.
  - `step(values: dict[str, float], cfg: ChatConfig, states: dict[str, AlertState], quiet: bool) -> tuple[dict[str, AlertState], list[Event]]`
  - `in_quiet_hours(cfg: ChatConfig, now: datetime) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_alerts.py`:
```python
from datetime import datetime

from app.alerts import bounds, in_quiet_hours, step
from app.chat_settings import AlertState, ChatConfig

CFG = ChatConfig()  # CO₂ max 1200, temperature 18–27


def run(values_seq, quiet_seq=None, cfg=CFG):
    """Feed a series of CO₂ values. Return the event kinds of each step."""
    states: dict[str, AlertState] = {}
    out = []
    for i, value in enumerate(values_seq):
        quiet = quiet_seq[i] if quiet_seq else False
        states, events = step({"co2": value}, cfg, states, quiet)
        out.append([e.kind for e in events])
    return out, states


def test_bounds():
    b = bounds(CFG)
    assert b["co2"] == (None, 1200) and b["temperature"] == (18, 27) and b["pm25"] == (None, 35)


def test_one_alert_and_no_repeat():
    out, states = run([800, 1300, 1400, 1500])
    assert out == [[], ["bad"], [], []]
    assert states["co2"] == AlertState("bad", "bad")


def test_back_to_normal_needs_hysteresis():
    # 1200 * 0.95 = 1140: 1150 is inside the limit, but not by 5 %.
    out, _ = run([1300, 1150, 1100])
    assert out == [["bad"], [], ["ok"]]


def test_no_series_near_limit():
    out, _ = run([1195, 1205, 1198, 1203, 1199])
    assert out == [[], ["bad"], [], [], []]


def test_quiet_hours_delay_alert():
    out, _ = run([1300, 1300, 1300], quiet_seq=[True, True, False])
    assert out == [[], [], ["bad"]]


def test_quiet_hours_problem_gone_before_morning():
    out, states = run([1300, 900, 900], quiet_seq=[True, True, False])
    assert out == [[], [], []]
    assert states["co2"] == AlertState("ok", "ok")


def test_range_metric_low_and_high():
    states, events = step({"temperature": 17.5}, CFG, {}, False)
    assert [(e.metric, e.kind, e.bounds) for e in events] == [("temperature", "bad", (18, 27))]
    # Margin is 5 % of 9 = 0.45, so 18.3 is not yet back.
    states, events = step({"temperature": 18.3}, CFG, states, False)
    assert events == []
    states, events = step({"temperature": 18.5}, CFG, states, False)
    assert [e.kind for e in events] == ["ok"]


def test_metrics_without_data_are_skipped():
    states, events = step({"battery": 5}, CFG, {}, False)
    assert states == {} and events == []


def test_in_quiet_hours():
    cfg = ChatConfig(quiet_hours="20:00-08:00")
    assert in_quiet_hours(cfg, datetime(2026, 10, 19, 23, 0))
    assert in_quiet_hours(cfg, datetime(2026, 10, 19, 7, 59))
    assert not in_quiet_hours(cfg, datetime(2026, 10, 19, 8, 0))
    assert not in_quiet_hours(cfg, datetime(2026, 10, 19, 12, 0))
    day = ChatConfig(quiet_hours="13:00-14:00")
    assert in_quiet_hours(day, datetime(2026, 10, 19, 13, 30))
    assert not in_quiet_hours(day, datetime(2026, 10, 19, 14, 0))
    assert not in_quiet_hours(ChatConfig(quiet=False), datetime(2026, 10, 19, 23, 0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alerts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.alerts'`.

- [ ] **Step 3: Write `app/alerts.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alerts.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/alerts.py tests/test_alerts.py
git commit -m "Add alert rules with hysteresis and quiet hours"
```

---

### Task 4: PNG charts

**Files:**
- Create: `app/charts.py`
- Test: `tests/test_charts.py`

**Interfaces:**
- Consumes: `METRICS`, `LIMITS`, `BANDS` from `app.qingping`.
- Produces: `render_chart(points: list[tuple[int, float]], metric: str, tz: ZoneInfo) -> bytes | None`. It returns PNG bytes, 960×480 px, or `None` if there are fewer than 2 points. It is thread-safe (no `pyplot`), so callers can run it in `asyncio.to_thread`.

- [ ] **Step 1: Write the failing tests**

`tests/test_charts.py`:
```python
import struct
from zoneinfo import ZoneInfo

from app.charts import render_chart

TZ = ZoneInfo("Europe/Moscow")


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_too_few_points():
    assert render_chart([], "co2", TZ) is None
    assert render_chart([(1, 500.0)], "co2", TZ) is None


def test_chart_png_for_limit_metric():
    points = [(1_700_000_000 + i * 600, 500.0 + i * 10) for i in range(100)]
    data = render_chart(points, "co2", TZ)
    assert png_size(data) == (960, 480)
    assert len(data) > 5000


def test_chart_for_band_metric_and_long_period():
    points = [(1_700_000_000 + i * 3600, 20.0 + (i % 10) / 2) for i in range(24 * 7)]
    assert png_size(render_chart(points, "temperature", TZ)) == (960, 480)


def test_chart_flat_line_and_metric_without_zones():
    points = [(1_700_000_000, 90.0), (1_700_000_600, 90.0)]
    assert png_size(render_chart(points, "battery", TZ)) == (960, 480)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_charts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.charts'`.

- [ ] **Step 3: Write `app/charts.py`**

```python
"""Draw a PNG chart for one metric. Uses the Figure API, so it is safe in threads."""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from .qingping import BANDS, LIMITS, METRICS

ZONE_COLORS = {"good": "#22b07d", "fair": "#f2a516", "bad": "#ec4c47"}
LINE_COLOR = "#2f80ed"
INF = float("inf")


def _zones(metric: str) -> list[tuple[float, float, str]]:
    if metric in LIMITS:
        good, fair = LIMITS[metric]
        return [(-INF, good, "good"), (good, fair, "fair"), (fair, INF, "bad")]
    if metric in BANDS:
        (g_lo, g_hi), (f_lo, f_hi) = BANDS[metric]
        return [
            (-INF, f_lo, "bad"),
            (f_lo, g_lo, "fair"),
            (g_lo, g_hi, "good"),
            (g_hi, f_hi, "fair"),
            (f_hi, INF, "bad"),
        ]
    return []


def render_chart(points: list[tuple[int, float]], metric: str, tz: ZoneInfo) -> bytes | None:
    if len(points) < 2:
        return None
    times = [datetime.fromtimestamp(ts, tz) for ts, _ in points]
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.15 or 1.0
    y0, y1 = lo - pad, hi + pad

    fig = Figure(figsize=(8, 4), dpi=120)
    ax = fig.subplots()
    for a, b, level in _zones(metric):
        a, b = max(a, y0), min(b, y1)
        if a < b:
            ax.axhspan(a, b, color=ZONE_COLORS[level], alpha=0.12, linewidth=0)
    ax.plot(times, values, color=LINE_COLOR, linewidth=2)
    ax.set_ylim(y0, y1)
    ax.set_xlim(times[0], times[-1])

    title, unit, _ = METRICS[metric]
    ax.set_title(f"{title}, {unit}" if unit else title, loc="left", fontsize=13)
    long_period = (points[-1][0] - points[0][0]) > 2 * 86400
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m" if long_period else "%H:%M", tz=tz))
    ax.grid(alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_charts.py -q`
Expected: 4 passed. If the size is not 960×480, check that `savefig` has no `bbox_inches` argument.

- [ ] **Step 5: Commit**

```bash
git add app/charts.py tests/test_charts.py
git commit -m "Add PNG chart rendering with comfort zones"
```

---

### Task 5: Summary texts and the summary view

**Files:**
- Create: `app/summary.py`, `app/view.py`
- Test: `tests/test_summary.py`, `tests/test_view.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `Store`, `Reading`, `METRICS`, `rate`, `overall`, `advice`, `fmt_value` (qingping), `Event`, `Bounds` (Task 3), `render_chart` (Task 4).
- Produces:
  - `summary.NO_DATA: str`
  - `summary.device_name(settings, mac) -> str`
  - `summary.caption(settings, reading: Reading | None, now: float) -> str` (HTML)
  - `summary.alert_text(settings, mac: str, event: Event) -> str` (HTML)
  - `view.ClimateCb(CallbackData, prefix="cl")`: `mac: str`, `metric: str`, `hours: int`
  - `view.View` (frozen dataclass): `text: str`, `photo: bytes | None`, `keyboard: InlineKeyboardMarkup | None`
  - `view.build_keyboard(settings, macs: list[str], mac: str, metrics: list[str], metric: str, hours: int) -> InlineKeyboardMarkup`
  - `async view.build_view(settings, store, mac: str | None = None, metric: str = "co2", hours: int = 24, now: float | None = None) -> View`
  - `async view.send_view(bot: Bot, chat_id: int, view: View) -> None`
  - `async view.edit_view(message: Message, view: View) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_summary.py`:
```python
from app.alerts import Event
from app.config import Settings
from app.qingping import Reading
from app.summary import NO_DATA, alert_text, caption, device_name

S = Settings(bot_token="x", device_names={"AABB": "Опен<спейс>"}, tz="Europe/Moscow", stale_after_min=30)
NOW = 1_700_000_000


def test_device_name():
    assert device_name(S, "AABB") == "Опен<спейс>"
    assert device_name(S, "112233445566") == "Датчик 5566"


def test_caption_with_data():
    r = Reading("AABB", NOW - 60, {"temperature": 23.4, "humidity": 45, "co2": 1350, "battery": 90})
    text = caption(S, r, NOW)
    assert "Опен&lt;спейс&gt;" in text
    assert "🔴 Климат плохой" in text
    assert "🔴 CO₂: <b>1350 ppm</b>" in text
    assert "🟢 Температура: <b>23.4 °C</b>" in text
    assert "💡 Проветрите" in text
    assert "Обновлено 15.11 01:12" in text  # NOW - 60 in Moscow time
    assert "устарели" not in text


def test_caption_stale_and_no_data():
    r = Reading("AABB", NOW - 3600, {"co2": 600})
    assert "⚠️ данные устарели" in caption(S, r, NOW)
    assert caption(S, None, NOW) == NO_DATA


def test_alert_texts():
    bad = alert_text(S, "AABB", Event("co2", "bad", 1250, (None, 1200)))
    assert bad.startswith("🔴 <b>Опен&lt;спейс&gt;</b>: CO₂ 1250 ppm (норма до 1200).")
    assert "Проветрите" in bad
    temp = alert_text(S, "AABB", Event("temperature", "bad", 17.5, (18, 27)))
    assert "(норма 18–27)" in temp
    ok = alert_text(S, "AABB", Event("co2", "ok", 780, (None, 1200)))
    assert ok == "🟢 <b>Опен&lt;спейс&gt;</b>: CO₂ снова в норме: 780 ppm."
```

`tests/test_view.py`:
```python
import time
from unittest.mock import AsyncMock

from aiogram.types import BufferedInputFile

from app.config import Settings
from app.qingping import Reading
from app.store import Store
from app.view import ClimateCb, View, build_keyboard, build_view, send_view

S = Settings(bot_token="x", tz="Europe/Moscow")


def texts(markup):
    return [[b.text for b in row] for row in markup.inline_keyboard]


def test_keyboard_one_device():
    kb = build_keyboard(S, ["AA"], "AA", ["co2", "temperature", "battery"], "co2", 24)
    assert texts(kb) == [["• CO₂ •", "Темп."], ["6 ч", "• 24 ч •", "7 д"], ["🔄 Обновить"]]
    data = ClimateCb.unpack(kb.inline_keyboard[1][2].callback_data)
    assert (data.mac, data.metric, data.hours) == ("AA", "co2", 168)


def test_keyboard_two_devices():
    kb = build_keyboard(S, ["AA", "BB"], "BB", ["co2"], "co2", 6)
    assert texts(kb)[0] == ["Датчик AA", "• Датчик BB •"]


def fill(store: Store, mac: str, values: dict, count: int = 10) -> float:
    now = time.time()
    store.add([Reading(mac, int(now) - i * 600, values) for i in range(count)])
    return now


async def test_build_view_with_data():
    store = Store(":memory:")
    now = fill(store, "AA", {"co2": 700.0, "temperature": 22.0})
    view = await build_view(S, store, now=now)
    assert view.photo[:4] == b"\x89PNG"
    assert "CO₂" in view.text
    assert texts(view.keyboard)[0] == ["• CO₂ •", "Темп."]


async def test_build_view_falls_back_to_available_metric_and_device():
    store = Store(":memory:")
    now = fill(store, "AA", {"temperature": 22.0})
    view = await build_view(S, store, mac="ZZ", metric="co2", now=now)
    assert texts(view.keyboard)[0] == ["• Темп. •"]


async def test_build_view_no_data():
    view = await build_view(S, Store(":memory:"))
    assert view.photo is None and view.keyboard is None
    assert "Данных с датчиков пока нет" in view.text


async def test_build_view_one_point_has_no_photo():
    store = Store(":memory:")
    now = fill(store, "AA", {"co2": 700.0}, count=1)
    view = await build_view(S, store, now=now)
    assert view.photo is None and view.keyboard is not None


async def test_send_view():
    bot = AsyncMock()
    await send_view(bot, 5, View("text", b"png", None))
    args = bot.send_photo.await_args
    assert args.args[0] == 5 and isinstance(args.args[1], BufferedInputFile)
    assert args.kwargs["caption"] == "text"
    await send_view(bot, 5, View("only text", None, None))
    bot.send_message.assert_awaited_once_with(5, "only text", reply_markup=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_summary.py tests/test_view.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.summary'`.

- [ ] **Step 3: Write `app/summary.py`**

```python
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
```

- [ ] **Step 4: Write `app/view.py`**

```python
"""The summary "view": caption, chart and inline keyboard, and send/edit helpers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from .charts import render_chart
from .config import Settings
from .store import Store
from .summary import caption, device_name

CHART_METRICS = ("co2", "temperature", "humidity", "pm25", "pm10", "tvoc", "tvoc_index", "noise")
SHORT = {
    "co2": "CO₂",
    "temperature": "Темп.",
    "humidity": "Влажн.",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "tvoc": "TVOC",
    "tvoc_index": "TVOC",
    "noise": "Шум",
}
PERIODS = {6: "6 ч", 24: "24 ч", 168: "7 д"}
PHOTO_NAME = "climate.png"


class ClimateCb(CallbackData, prefix="cl"):
    mac: str
    metric: str
    hours: int


@dataclass(frozen=True)
class View:
    text: str
    photo: bytes | None
    keyboard: InlineKeyboardMarkup | None


def _button(text: str, mac: str, metric: str, hours: int, active: bool = False) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=f"• {text} •" if active else text,
        callback_data=ClimateCb(mac=mac, metric=metric, hours=hours).pack(),
    )


def build_keyboard(
    settings: Settings, macs: list[str], mac: str, metrics: list[str], metric: str, hours: int
) -> InlineKeyboardMarkup:
    rows = []
    if len(macs) > 1:
        rows.append([_button(device_name(settings, m), m, metric, hours, m == mac) for m in macs])
    chartable = [m for m in CHART_METRICS if m in metrics]
    for i in range(0, len(chartable), 4):
        rows.append([_button(SHORT[m], mac, m, hours, m == metric) for m in chartable[i : i + 4]])
    rows.append([_button(label, mac, metric, h, h == hours) for h, label in PERIODS.items()])
    rows.append([_button("🔄 Обновить", mac, metric, hours)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_view(
    settings: Settings,
    store: Store,
    mac: str | None = None,
    metric: str = "co2",
    hours: int = 24,
    now: float | None = None,
) -> View:
    now = time.time() if now is None else now
    macs = store.devices()
    if not macs:
        return View(caption(settings, None, now), None, None)
    if mac not in macs:
        mac = macs[0]
    reading = store.latest(mac)
    metrics = list(reading.values) if reading else []
    chartable = [m for m in CHART_METRICS if m in metrics]
    if metric not in chartable:
        metric = chartable[0] if chartable else "co2"
    rows = store.history(mac, int(now) - hours * 3600)
    points = [(r.ts, r.values[metric]) for r in rows if metric in r.values]
    photo = await asyncio.to_thread(render_chart, points, metric, ZoneInfo(settings.tz))
    keyboard = build_keyboard(settings, macs, mac, metrics, metric, hours)
    return View(caption(settings, reading, now), photo, keyboard)


async def send_view(bot: Bot, chat_id: int, view: View) -> None:
    if view.photo:
        await bot.send_photo(
            chat_id, BufferedInputFile(view.photo, PHOTO_NAME), caption=view.text, reply_markup=view.keyboard
        )
    else:
        await bot.send_message(chat_id, view.text, reply_markup=view.keyboard)


async def edit_view(message: Message, view: View) -> None:
    """Edit the summary message in place. Recreate it if the type (photo/text) changes."""
    try:
        if view.photo and message.photo:
            media = InputMediaPhoto(media=BufferedInputFile(view.photo, PHOTO_NAME), caption=view.text)
            await message.edit_media(media, reply_markup=view.keyboard)
        elif not view.photo and not message.photo:
            await message.edit_text(view.text, reply_markup=view.keyboard)
        else:
            await message.delete()
            await send_view(message.bot, message.chat.id, view)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_summary.py tests/test_view.py -q`
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add app/summary.py app/view.py tests/test_summary.py tests/test_view.py
git commit -m "Add summary caption, alert texts and summary view with chart and buttons"
```

---

### Task 6: Access control and the `/climate` handlers

**Files:**
- Create: `app/access.py`, `app/handlers/__init__.py` (empty), `app/handlers/climate.py`
- Test: `tests/test_access.py`

**Interfaces:**
- Consumes: `Settings`, `ChatStore` (Task 2), `Store`, `build_view`, `send_view`, `edit_view`, `ClimateCb` (Task 5).
- Produces:
  - `AccessMiddleware(settings, chats)`: aiogram inner middleware. It blocks users and chats that are not allowed, and registers allowed chats with `chats.register`.
  - `AdminChecker(settings)`: `async is_admin(bot, chat_id: int, chat_type: str, user_id: int) -> bool`.
  - `handlers.climate.build_router(settings, store) -> Router`.

- [ ] **Step 1: Write the failing tests**

`tests/test_access.py`:
```python
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChatMember

from app.access import AccessMiddleware, AdminChecker
from app.chat_settings import ChatConfig, ChatStore
from app.config import Settings

LIMITED = Settings(bot_token="x", allowed_chats=frozenset({-100}), admin_users=frozenset({7}))


def data(user_id, chat_id):
    return {"event_from_user": SimpleNamespace(id=user_id), "event_chat": SimpleNamespace(id=chat_id)}


async def test_middleware_allows_and_registers():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    handler = AsyncMock(return_value="ok")
    result = await AccessMiddleware(LIMITED, chats)(handler, object(), data(1, -100))
    assert result == "ok"
    assert chats.chats() == [-100]


async def test_middleware_blocks():
    chats = ChatStore(sqlite3.connect(":memory:"), ChatConfig())
    handler = AsyncMock()
    result = await AccessMiddleware(LIMITED, chats)(handler, object(), data(1, 2))
    assert result is None
    handler.assert_not_awaited()
    assert chats.chats() == []


async def test_admin_in_private_chat():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    assert await checker.is_admin(bot, 7, "private", 7)
    assert not await checker.is_admin(bot, 8, "private", 8)
    bot.get_chat_member.assert_not_awaited()


async def test_admin_in_group_is_cached():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)
    assert await checker.is_admin(bot, -100, "supergroup", 1)
    assert await checker.is_admin(bot, -100, "supergroup", 1)
    assert bot.get_chat_member.await_count == 1


async def test_group_member_and_error_are_not_admin():
    checker = AdminChecker(LIMITED)
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    assert not await checker.is_admin(bot, -100, "group", 1)
    bot.get_chat_member.side_effect = TelegramBadRequest(
        method=GetChatMember(chat_id=-100, user_id=2), message="user not found"
    )
    assert not await checker.is_admin(bot, -100, "group", 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_access.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.access'`.

- [ ] **Step 3: Write `app/access.py`**

```python
"""Access rules: allow-lists for everyone, admin check for settings."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from .chat_settings import ChatStore
from .config import Settings

ADMIN_CACHE_TTL = 300
ADMIN_STATUSES = (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


class AccessMiddleware(BaseMiddleware):
    """Inner middleware: runs only for events that a handler matched."""

    def __init__(self, settings: Settings, chats: ChatStore):
        self.settings = settings
        self.chats = chats

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        user_id = user.id if user else None
        chat_id = chat.id if chat else None
        if not self.settings.is_allowed(user_id, chat_id):
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Нет доступа. Попросите администратора добавить этот чат.")
            return None
        if chat_id is not None:
            self.chats.register(chat_id)
        return await handler(event, data)


class AdminChecker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache: dict[tuple[int, int], tuple[float, bool]] = {}

    async def is_admin(self, bot: Bot, chat_id: int, chat_type: str, user_id: int) -> bool:
        if chat_type == ChatType.PRIVATE:
            return user_id in self.settings.admin_users
        key = (chat_id, user_id)
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < ADMIN_CACHE_TTL:
            return cached[1]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            ok = member.status in ADMIN_STATUSES
        except TelegramAPIError:
            ok = False
        self.cache[key] = (time.monotonic(), ok)
        return ok
```

- [ ] **Step 4: Write `app/handlers/__init__.py` (empty file) and `app/handlers/climate.py`**

```python
"""/start, /climate, keywords and the summary buttons."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..store import Store
from ..view import ClimateCb, build_view, edit_view, send_view

KEYWORDS = {"климат", "душно?", "душно"}
GREETING = (
    "Привет! Я показываю климат в офисе с датчиков Qingping.\n"
    "/climate — сводка и график, /settings — уведомления и утренний отчёт (для админов)."
)


def build_router(settings: Settings, store: Store) -> Router:
    router = Router(name="climate")

    async def show(message: Message, bot: Bot) -> None:
        await send_view(bot, message.chat.id, await build_view(settings, store))

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot) -> None:
        await message.answer(GREETING)
        await show(message, bot)

    @router.message(Command("climate"))
    async def climate(message: Message, bot: Bot) -> None:
        await show(message, bot)

    @router.message(F.text.lower().in_(KEYWORDS))
    async def keyword(message: Message, bot: Bot) -> None:
        await show(message, bot)

    @router.callback_query(ClimateCb.filter())
    async def on_button(query: CallbackQuery, callback_data: ClimateCb) -> None:
        view = await build_view(settings, store, callback_data.mac, callback_data.metric, callback_data.hours)
        if isinstance(query.message, Message):
            await edit_view(query.message, view)
        await query.answer()

    return router
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_access.py -q`
Expected: 5 passed.

Run: `python -c "from app.config import Settings; from app.store import Store; from app.handlers.climate import build_router; build_router(Settings(bot_token='x'), Store(':memory:'))"`
Expected: no output, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add app/access.py app/handlers tests/test_access.py
git commit -m "Add access middleware, admin check and /climate handlers"
```

---

### Task 7: `/settings` menu

**Files:**
- Create: `app/handlers/settings.py`
- Test: `tests/test_settings_menu.py`

**Interfaces:**
- Consumes: `ChatConfig`, `ChatStore`, parsers (Task 2), `AdminChecker` (Task 6).
- Produces:
  - `SetCb(CallbackData, prefix="st")`: `action: str` ("toggle" | "edit" | "reset" | "close"), `field: str = ""`.
  - `FIELDS: dict[str, tuple[str, Callable[[str], Any], str]]` (title, parser, example).
  - `menu_text(cfg: ChatConfig) -> str`, `menu_keyboard(cfg: ChatConfig) -> InlineKeyboardMarkup`.
  - `toggle_changes(cfg: ChatConfig, field: str) -> dict[str, Any]`.
  - `parse_input(field: str, text: str) -> Any` (raises `ValueError`).
  - `build_router(chats: ChatStore, admins: AdminChecker) -> Router`.

- [ ] **Step 1: Write the failing tests**

`tests/test_settings_menu.py`:
```python
import pytest

from app.chat_settings import ChatConfig
from app.handlers.settings import SetCb, menu_keyboard, menu_text, parse_input, toggle_changes


def test_menu_text_shows_values():
    text = menu_text(ChatConfig(co2_max=1000, temp=(19, 26), report_days="all", quiet=False))
    assert "🔔 Уведомления: <b>ВКЛ</b>" in text
    assert "🌅 Утренний отчёт: <b>ВКЛ</b>, 09:00, каждый день" in text
    assert "🌙 Тихие часы: <b>ВЫКЛ</b>, 20:00–08:00" in text
    assert "CO₂ &gt; 1000 ppm" in text
    assert "Температура 19–26 °C" in text


def test_menu_keyboard_callbacks():
    kb = menu_keyboard(ChatConfig())
    packed = [SetCb.unpack(b.callback_data) for row in kb.inline_keyboard for b in row]
    pairs = {(c.action, c.field) for c in packed}
    assert {("toggle", "alerts"), ("toggle", "report"), ("toggle", "report_days"), ("toggle", "quiet")} <= pairs
    assert {("edit", f) for f in ("report_time", "quiet_hours", "co2_max", "temp", "humidity", "pm25_max")} <= pairs
    assert {("reset", ""), ("close", "")} <= pairs
    assert kb.inline_keyboard[0][0].text == "🔔 Выключить уведомления"


def test_toggle_changes():
    cfg = ChatConfig()
    assert toggle_changes(cfg, "alerts") == {"alerts": False}
    assert toggle_changes(cfg, "report_days") == {"report_days": "all"}
    assert toggle_changes(ChatConfig(report_days="all"), "report_days") == {"report_days": "workdays"}
    with pytest.raises(ValueError):
        toggle_changes(cfg, "co2_max")


def test_parse_input():
    assert parse_input("co2_max", "1000") == 1000
    assert parse_input("temp", "19-26") == (19, 26)
    assert parse_input("report_time", "8:30") == "08:30"
    assert parse_input("quiet_hours", "21:00-07:00") == "21:00-07:00"
    with pytest.raises(ValueError):
        parse_input("temp", "26-19")
    with pytest.raises(ValueError):
        parse_input("unknown", "1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_menu.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.handlers.settings'`.

- [ ] **Step 3: Write `app/handlers/settings.py`**

```python
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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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
            await msg.delete()
            await query.answer()
            return
        if action == "edit" and field in FIELDS:
            title, _, example = FIELDS[field]
            await state.set_state(EditValue.waiting)
            await state.update_data(field=field, started=time.time())
            await query.answer()
            await msg.answer(f"Введите {title}. Пример: <code>{example}</code>")
            return
        if action == "toggle" and field in TOGGLES:
            cfg = chats.update(chat_id, **toggle_changes(chats.get(chat_id), field))
        elif action == "reset":
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_menu.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/handlers/settings.py tests/test_settings_menu.py
git commit -m "Add /settings menu for chat admins"
```

---

### Task 8: Scheduler (alerts and morning report)

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `step`, `in_quiet_hours` (Task 3), `ChatConfig`, `ChatStore` (Task 2), `alert_text` (Task 5), `build_view`, `send_view` (Task 5), `Store`, `Settings`.
- Produces:
  - `report_due(cfg: ChatConfig, now: datetime, last_date: str | None) -> bool`
  - `async tick(bot, settings, store, chats, now_ts: float | None = None) -> None`
  - `async run_scheduler(bot, settings, store, chats, interval: float = 60) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler.py`:
```python
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from app.chat_settings import ChatConfig, ChatStore
from app.config import Settings
from app.qingping import Reading
from app.scheduler import report_due, tick
from app.store import Store

TZ = ZoneInfo("Europe/Moscow")
S = Settings(bot_token="x", tz="Europe/Moscow", stale_after_min=30)
MONDAY_10 = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)


def test_report_due():
    cfg = ChatConfig()  # 09:00, workdays
    assert report_due(cfg, MONDAY_10, None)
    assert not report_due(cfg, MONDAY_10, "2026-10-19")
    assert report_due(cfg, MONDAY_10, "2026-10-18")
    assert not report_due(cfg, datetime(2026, 10, 19, 8, 59, tzinfo=TZ), None)
    assert not report_due(cfg, datetime(2026, 10, 19, 12, 0, tzinfo=TZ), None)
    assert not report_due(cfg, datetime(2026, 10, 18, 10, 0, tzinfo=TZ), None)  # Sunday
    assert report_due(ChatConfig(report_days="all"), datetime(2026, 10, 18, 10, 0, tzinfo=TZ), None)
    assert not report_due(ChatConfig(report=False), MONDAY_10, None)
    late = ChatConfig(report_time="14:00")
    assert report_due(late, datetime(2026, 10, 19, 14, 9, tzinfo=TZ), None)
    assert not report_due(late, datetime(2026, 10, 19, 14, 10, tzinfo=TZ), None)


def setup(co2: float, age_s: int = 60, **cfg):
    store = Store(":memory:")
    chats = ChatStore(store.db, ChatConfig(report=False, quiet=False).with_changes(cfg))
    chats.register(1)
    now = MONDAY_10.timestamp()
    store.add([Reading("AA", int(now) - age_s, {"co2": co2})])
    return store, chats, now


async def test_alert_sent_once():
    store, chats, now = setup(1300)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    await tick(bot, S, store, chats, now + 60)
    bot.send_message.assert_awaited_once()
    assert "CO₂ 1300 ppm" in bot.send_message.await_args.args[1]


async def test_no_alert_on_stale_data():
    store, chats, now = setup(1300, age_s=3600)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    bot.send_message.assert_not_awaited()


async def test_alerts_off():
    store, chats, now = setup(1300, alerts=False)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    bot.send_message.assert_not_awaited()


async def test_forbidden_disables_chat():
    store, chats, now = setup(1300)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=1, text="x"), message="bot was kicked"
    )
    await tick(bot, S, store, chats, now)
    cfg = chats.get(1)
    assert cfg.alerts is False and cfg.report is False


async def test_morning_report_once():
    store, chats, now = setup(700, report=True)
    bot = AsyncMock()
    await tick(bot, S, store, chats, now)
    await tick(bot, S, store, chats, now + 60)
    sent = bot.send_message.await_count + bot.send_photo.await_count
    assert sent == 1
    assert chats.last_report(1) == "2026-10-19"


async def test_error_in_one_chat_does_not_stop_others():
    store, chats, now = setup(1300)
    chats.register(2)
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("boom"), None]
    await tick(bot, S, store, chats, now)
    assert bot.send_message.await_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scheduler'`.

- [ ] **Step 3: Write `app/scheduler.py`**

```python
"""Each minute: check alerts and send morning reports."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

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
        await send_view(bot, chat_id, await build_view(settings, store, hours=REPORT_HOURS, now=now_ts))


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
        except Exception:
            log.exception("Scheduler failed for chat %s", chat_id)


async def run_scheduler(
    bot: Bot, settings: Settings, store: Store, chats: ChatStore, interval: float = 60
) -> None:
    while True:
        await tick(bot, settings, store, chats)
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: 7 passed.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: 61 passed.

- [ ] **Step 6: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "Add scheduler for alerts and morning report"
```

---

### Task 9: Entry point, Docker, README, smoke test

**Files:**
- Create: `app/main.py`, `README.md`, `scripts/smoke-mqtt.sh`
- Modify: `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`

**Interfaces:**
- Consumes: everything above, plus `run_mqtt(settings, store)` from `app/mqtt_listener.py`.
- Produces: a runnable `python -m app.main` and `docker compose up -d`.

- [ ] **Step 1: Write `app/main.py`**

```python
"""Start the bot (long polling), the MQTT listener and the scheduler."""

from __future__ import annotations

import asyncio
import contextlib
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
    try:
        await dp.start_polling(bot)
    finally:
        for task in background:
            task.cancel()
        for task in background:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Run: `python -c "import app.main"`
Expected: no output, exit code 0.

- [ ] **Step 2: Update `Dockerfile`**

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
VOLUME /data

CMD ["python", "-m", "app.main"]
```

- [ ] **Step 3: Update `docker-compose.yml`**

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2.0.20
    restart: unless-stopped
    ports:
      - "1883:1883"   # Qingping devices connect here (office PC IP)
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data

  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      MQTT_HOST: mosquitto
      DB_PATH: /data/climate.db
    volumes:
      - ./data:/data
    depends_on:
      - mosquitto
```

- [ ] **Step 4: Update `.env.example`**

```
# Токен от @BotFather
BOT_TOKEN=123456:ABC...

# Часовой пояс для графиков, тихих часов и утреннего отчёта
TZ=Europe/Moscow

# Доступ. Пусто = всем. ID через запятую.
# ID группы можно узнать, например, через @getidsbot (у групп ID отрицательный).
ALLOWED_CHAT_IDS=
ALLOWED_USER_IDS=
# Кто может менять /settings в личном чате с ботом (в группах — админы группы)
ADMIN_USER_IDS=

# MQTT (брокер из docker-compose)
MQTT_PORT=1883
MQTT_USER=
MQTT_PASSWORD=
MQTT_TOPIC=qingping/+/up

# Имена датчиков: MAC=Имя;MAC=Имя (MAC без двоеточий, как в топике)
DEVICE_NAMES=582D34000000=Опенспейс

# Хранить историю, дней
HISTORY_DAYS=30
# Через сколько минут без данных показывать «данные устарели» и не слать уведомления
STALE_AFTER_MIN=30
LOG_LEVEL=INFO

# Настройки чатов по умолчанию (каждый чат может поменять их в /settings)
ALERTS=on
REPORT=on
REPORT_TIME=09:00
# workdays = пн–пт, all = каждый день
REPORT_DAYS=workdays
QUIET=on
QUIET_HOURS=20:00-08:00
CO2_MAX=1200
TEMP_RANGE=18-27
HUMIDITY_RANGE=30-70
PM25_MAX=35
```

Also add `docs` to `.dockerignore` (new line `docs`).

- [ ] **Step 5: Write `scripts/smoke-mqtt.sh`**

This script checks the MQTT path in Docker without a real bot token: broker → listener → SQLite.

```sh
#!/bin/sh
# Smoke test: Mosquitto -> app.mqtt_listener -> SQLite. Needs Docker. No Telegram token.
set -eu
cd "$(dirname "$0")/.."

NET=climate-smoke
cleanup() { docker rm -f climate-smoke-mq climate-smoke-bot >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker build -q -t office-climate-bot . >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name climate-smoke-mq --network "$NET" \
  -v "$PWD/mosquitto/config:/mosquitto/config:ro" eclipse-mosquitto:2.0.20 >/dev/null

docker run -d --name climate-smoke-bot --network "$NET" \
  -e MQTT_HOST=climate-smoke-mq -e DB_PATH=/tmp/smoke.db -e LOG_LEVEL=DEBUG \
  office-climate-bot python -c "
import asyncio, logging
from app.config import Settings
from app.store import Store
from app.mqtt_listener import run_mqtt
logging.basicConfig(level='DEBUG')
s = Settings.from_env()
asyncio.run(asyncio.wait_for(run_mqtt(s, Store(s.db_path)), 60))
" >/dev/null 2>&1 || true

# Wait until the listener has subscribed.
i=0
until docker logs climate-smoke-bot 2>&1 | grep -q "MQTT connected"; do
  i=$((i + 1)); [ "$i" -lt 30 ] || { echo "FAIL: listener did not connect"; docker logs climate-smoke-bot; exit 1; }
  sleep 0.5
done

NOW=$(date +%s)
docker exec climate-smoke-mq mosquitto_pub -t qingping/582D34AABBCC/up -m \
  "{\"mac\":\"582D34AABBCC\",\"type\":\"17\",\"sensorData\":[{\"timestamp\":{\"value\":$NOW},\"co2\":{\"value\":777}}]}"
sleep 2

RESULT=$(docker exec climate-smoke-bot python -c "
from app.store import Store
r = Store('/tmp/smoke.db').latest('582D34AABBCC')
print(r.values['co2'] if r else 'none')
")
if [ "$RESULT" = "777.0" ]; then echo "OK: reading saved (co2=$RESULT)"; else echo "FAIL: got $RESULT"; docker logs climate-smoke-bot; exit 1; fi
```

Run: `chmod +x scripts/smoke-mqtt.sh && ./scripts/smoke-mqtt.sh`
Expected: `OK: reading saved (co2=777.0)`.

If Docker is not running, start it first. In a sandbox, `docker build` can need `--network=host` and proxy build args; that is a sandbox issue, not a project issue. If the result is `none`, read the `docker logs` output: check the topic, the JSON, and that "MQTT connected" appears before the publish. (Note: the draft's first e2e run returned 0 devices because the message was published before the listener subscribed. The wait loop above prevents this.)

- [ ] **Step 6: Write `README.md`**

````markdown
# Климат в офисе — Telegram-бот для Qingping

Бот показывает температуру, влажность, CO₂ и пыль с датчика **Qingping Air Monitor** (2 / Lite).
Данные идут по MQTT на ваш ПК в офисе. Всё работает локально в Docker: без домена,
без открытых портов в интернет и без внешних сервисов (кроме самого Telegram).

## Что умеет

- `/climate` (или слова «климат», «душно?») — сводка 🟢🟡🔴 и график. Кнопки под сообщением
  меняют показатель (CO₂, температура, влажность, PM2.5…), период (6 ч / 24 ч / 7 д) и датчик.
- Уведомления в чат: одно сообщение, когда показатель вышел за порог, и одно, когда вернулся в норму.
  Без повторов. Ночью (тихие часы) бот молчит и, если проблема осталась, пишет утром.
- Утренний отчёт по расписанию (по умолчанию 09:00, пн–пт) с графиком CO₂ за ночь.
- `/settings` — пороги, время отчёта, тихие часы, вкл/выкл. Менять могут только админы чата.

## Как это устроено

```
Qingping Air Monitor ──MQTT──▶ mosquitto (порт 1883, только офисная сеть)
                                   │
                                   ▼
                           bot (Python) ──▶ SQLite ./data/climate.db
                                   │ long polling (только исходящие соединения)
                                   ▼
                               Telegram
```

## Установка

### 1. Создайте бота

1. Напишите [@BotFather](https://t.me/BotFather) команду `/newbot` и получите токен.
2. Если хотите, чтобы бот отвечал на слово «климат» в группе, отключите режим приватности:
   `/mybots` → ваш бот → Bot Settings → Group Privacy → Turn off.
   Команды `/climate` и `/settings` работают и без этого.
3. Добавьте бота в рабочую группу.

### 2. Запустите на ПК в офисе

Нужен Docker с Docker Compose (Docker Desktop на Windows/macOS или Docker Engine на Linux).

```bash
git clone <этот репозиторий> office-climate
cd office-climate
cp .env.example .env
# откройте .env и впишите BOT_TOKEN, при желании ALLOWED_CHAT_IDS и ADMIN_USER_IDS
docker compose up -d --build
docker compose logs -f bot
```

В логе должно быть `MQTT connected`. Порт 1883 должен быть доступен из офисной сети
(на Windows разрешите его в брандмауэре). У ПК должен быть постоянный IP в локальной сети
(закрепите его в настройках роутера).

### 3. Настройте датчик Qingping

Air Monitor умеет отправлять данные на свой MQTT-брокер («частный доступ»):

1. Войдите на [developer.qingping.co](https://developer.qingping.co) тем же аккаунтом, что в приложении Qingping+.
2. Откройте раздел частного доступа (Private Access Config) и создайте конфигурацию **MQTT**:
   - Host: локальный IP вашего ПК, например `192.168.1.50`
   - Port: `1883`
   - Username / Password: пусто (или см. «Пароль для MQTT» ниже)
   - Up topic: `qingping/<MAC>/up`, Down topic: `qingping/<MAC>/down`
   - Интервал отправки: 1–5 минут
3. Привяжите конфигурацию к устройству. Датчик должен быть в той же сети, что и ПК.

Названия пунктов в портале могут немного отличаться — ищите «Private access» / «MQTT».

Проверка: выполните в Telegram `/climate`. Если бот пишет «Данных с датчиков пока нет», посмотрите,
что приходит в брокер:

```bash
docker compose exec mosquitto mosquitto_sub -t 'qingping/#' -v
```

### 4. Проверка без датчика

```bash
docker compose exec mosquitto mosquitto_pub -t qingping/582D34000000/up -m \
  "{\"mac\":\"582D34000000\",\"type\":\"17\",\"sensorData\":[{\"timestamp\":{\"value\":$(date +%s)},\"co2\":{\"value\":1300},\"temperature\":{\"value\":23}}]}"
```

Затем `/climate` в Telegram покажет CO₂ 1300 ppm. Через минуту придёт уведомление о высоком CO₂
(если сейчас не тихие часы).

## Настройки

Значения по умолчанию задаются в `.env` (см. комментарии в `.env.example`).
Каждый чат может поменять их в `/settings`. Формат ввода: число `1000`, диапазон `19-26`,
время `09:00`, период `20:00-08:00`.

| Переменная | Что значит |
|---|---|
| `ALLOWED_CHAT_IDS`, `ALLOWED_USER_IDS` | Где и кому бот отвечает. Пусто = всем |
| `ADMIN_USER_IDS` | Кто меняет `/settings` в личке с ботом. В группах — админы группы |
| `DEVICE_NAMES` | Имена датчиков: `MAC=Имя;MAC=Имя` |
| `TZ` | Часовой пояс |
| `STALE_AFTER_MIN` | Через сколько минут без данных они считаются устаревшими |

## Пароль для MQTT (по желанию)

По умолчанию брокер без пароля — это нормально для закрытой офисной сети. Чтобы включить пароль:

```bash
./scripts/mqtt-passwd.sh qingping
```

В `mosquitto/config/mosquitto.conf` замените `allow_anonymous true` на:

```
allow_anonymous false
password_file /mosquitto/config/passwd
```

Впишите `MQTT_USER` / `MQTT_PASSWORD` в `.env`, укажите те же данные в портале Qingping
и перезапустите: `docker compose up -d`.

## Обновление и данные

```bash
git pull
docker compose up -d --build
```

История хранится в `./data/climate.db` (30 дней по умолчанию). Для резервной копии достаточно
скопировать папку `data`.

## Разработка

```bash
pip install -r requirements-dev.txt
python -m pytest -q
./scripts/smoke-mqtt.sh   # проверка цепочки MQTT → бот → SQLite в Docker
```
````

- [ ] **Step 7: Run all checks**

Run: `python -m pytest -q`
Expected: all tests pass.

Run: `docker compose config -q`
Expected: no output (the file is valid). It needs a `.env` file: run `cp .env.example .env` first if there is none, and delete it after the check if you created it.

Run: `./scripts/smoke-mqtt.sh`
Expected: `OK: reading saved (co2=777.0)`.

- [ ] **Step 8: Commit**

```bash
git add app/main.py Dockerfile docker-compose.yml .env.example .dockerignore README.md scripts/smoke-mqtt.sh
git commit -m "Add entry point, Docker setup, README and MQTT smoke test"
```

---

## Manual acceptance (after deployment, with a real bot token)

1. `docker compose up -d --build`; the log shows `MQTT connected` and no errors.
2. Send the test message from README section 4.
3. `/climate` in the group: photo + caption + buttons. Push "Темп." and "7 д": the same message changes.
4. `/settings` as a group admin: the menu opens. As a non-admin: "Настройки могут менять только админы чата."
5. Set CO₂ to `400` in `/settings`, send the test message again: within 1 minute, one 🔴 alert. No repeat in the next minutes.
6. Set CO₂ back to `1200`. Send a message with CO₂ 600: one 🟢 message.
7. Restart the bot (`docker compose restart bot`): no duplicate alerts or reports.
