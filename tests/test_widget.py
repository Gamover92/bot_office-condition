"""Тесты app/widget.py — сырой HTTP-клиент методов виджетов Bot API и сборка HTML."""

import json
import os
import re
import time
from types import SimpleNamespace

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.qingping import METRICS, Reading
from app.store import Store
from app.view import CHART_METRICS
from app.widget import (
    MAX_COMPRESSED_BYTES,
    MAX_WIDGET_AGE_HOURS,
    build_public_data,
    build_widget_html,
    compressed_size,
    edit_widget_data,
    send_widget,
    send_widget_summary,
    update_widget_data_once,
    widgets_allowed,
)

S = Settings(bot_token="x", tz="Europe/Moscow")


def fill(store: Store, mac: str, values: dict, minutes: int = 24 * 60) -> float:
    """Засыпает показания с шагом в минуту, возвращает now."""
    now = time.time()
    store.add([Reading(mac, int(now) - i * 60, values) for i in range(minutes)])
    return now


class RecordingSession:
    """Подмена bot.session (aiogram AiohttpSession): create_session() -> объект с post()."""

    def __init__(self, response: dict):
        self.calls: list[tuple[str, dict]] = []
        self._response = response

    def _next_response(self, data: dict) -> dict:
        return self._response

    async def create_session(self):
        outer = self

        class _Client:
            def post(self, url: str, **kwargs):
                method = url.rsplit("/", 1)[-1]
                data = kwargs.get("data", {})
                outer.calls.append((method, data))
                response = outer._next_response(data)

                class _Resp:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *exc):
                        return False

                    async def json(self):
                        return response

                return _Resp()

        return _Client()


def fake_bot_with_session(**response):
    return SimpleNamespace(session=RecordingSession(response), token="123456:ABC")


async def test_send_widget_returns_message_id():
    bot = fake_bot_with_session(ok=True, result={"message_id": 42})
    mid = await send_widget(bot, 7, "<html>…</html>", "caption", None)
    assert mid == 42
    method, payload = bot.session.calls[0]
    assert method == "sendWidget" and payload["chat_id"] == 7


async def test_send_widget_sends_html_caption_and_keyboard():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Обновить", callback_data="r")]]
    )
    await send_widget(bot, 7, "<html>x</html>", "cap", kb)
    _, payload = bot.session.calls[0]
    assert payload["html"] == "<html>x</html>"
    assert payload["caption"] == "cap"
    assert payload["reply_markup"] == kb.model_dump_json(exclude_none=True)


async def test_send_widget_omits_keyboard_when_none():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    await send_widget(bot, 7, "<html>x</html>", "cap", None)
    _, payload = bot.session.calls[0]
    assert "reply_markup" not in payload


async def test_send_widget_raises_on_api_error():
    bot = fake_bot_with_session(ok=False, description="INPUT_MEDIA_WIDGET_NOT_ALLOWED")
    with pytest.raises(RuntimeError, match="INPUT_MEDIA_WIDGET_NOT_ALLOWED"):
        await send_widget(bot, -100, "<html/>", "c", None)


async def test_edit_widget_data_payload():
    bot = fake_bot_with_session(ok=True, result=True)
    await edit_widget_data(bot, 7, 42, '{"co2":700}')
    method, payload = bot.session.calls[0]
    assert method == "editMessageWidgetData"
    assert payload["chat_id"] == 7 and payload["message_id"] == 42
    assert payload["public_data"] == '{"co2":700}'


def test_public_data_fits_budget_with_all_metrics():
    values = {k: 12345.6 for k in METRICS}
    data = build_public_data(Reading("AA", 1730000000, values))
    assert len(data.encode()) <= 1000


def test_public_data_roundtrip():
    data = build_public_data(Reading("AA", 1730000000, {"co2": 700.0, "temperature": 22.5}))
    parsed = json.loads(data)
    assert parsed["co2"] == 700 and parsed["ts"] == 1730000000


def test_public_data_rounds_by_metric_digits():
    data = build_public_data(Reading("AA", 1730000000, {"temperature": 22.55, "humidity": 45.6}))
    parsed = json.loads(data)
    assert parsed["temperature"] == 22.6 and parsed["humidity"] == 46


def test_public_data_includes_counter():
    parsed = json.loads(build_public_data(Reading("AA", 1, {"co2": 700.0})))
    assert parsed["n"] == 0
    parsed = json.loads(build_public_data(Reading("AA", 1, {"co2": 700.0}), n=5))
    assert parsed["n"] == 5


def test_public_data_follows_metrics_order():
    data = build_public_data(Reading("AA", 1, {"co2": 700.0, "temperature": 22.5}))
    assert data.index("temperature") < data.index("co2")


async def test_edit_widget_data_raises_on_api_error():
    bot = fake_bot_with_session(ok=False, description="message is not modified")
    with pytest.raises(RuntimeError, match="message is not modified"):
        await edit_widget_data(bot, 7, 42, "{}")


def test_html_none_without_data():
    assert build_widget_html(S, Store(":memory:"), "AA", time.time()) is None


def test_html_fits_budget_with_dense_history():
    store = Store(":memory:")
    now = time.time()
    values = {m: 100.0 for m in CHART_METRICS}
    store.add([Reading("AA", int(now) - i * 60, values) for i in range(7 * 24 * 60)])
    html = build_widget_html(S, store, "AA", now)
    assert html is not None
    assert compressed_size(html) <= MAX_COMPRESSED_BYTES
    assert len(html.encode()) <= 32 * 1024


def test_html_bakes_all_metrics_periods_and_office_tz():
    store = Store(":memory:")
    now = fill(store, "AA", {"co2": 700.0, "temperature": 22.0})
    html = build_widget_html(S, store, "AA", now)
    assert html is not None
    for metric in ("co2", "temperature"):
        assert metric in html
    assert "Europe/Moscow" in html or "+03:00" in html


def test_html_breaks_series_at_sensor_gap():
    """Разрыв в данных (перезапуск датчика) — два сегмента, хвост не сдвигается."""
    store = Store(":memory:")
    base = int(time.time())
    readings = [Reading("AA", base - 7200 + i * 60, {"co2": 600.0 + i}) for i in range(60)]
    readings += [Reading("AA", base + i * 60, {"co2": 700.0 + i}) for i in range(60)]
    store.add(readings)
    html = build_widget_html(S, store, "AA", base + 3600)
    data = json.loads(re.search(r"var D=(\{.*?\}),Z=", html).group(1))
    segments = data["co2:6"]
    assert len(segments) == 2
    # Второй сегмент начинается с реальной метки времени после разрыва,
    # а не с t0 + dt*i равномерной сетки.
    assert segments[1][0] == base


def test_widgets_allowed_routing():
    on = Settings(bot_token="x")  # widgets_enabled=True, in_groups=False
    off = Settings(bot_token="x", widgets_enabled=False)
    groups = Settings(bot_token="x", widgets_in_groups=True)
    assert widgets_allowed(on, "private") and not widgets_allowed(on, "supergroup")
    assert not widgets_allowed(off, "private")
    assert widgets_allowed(groups, "supergroup")


async def test_send_widget_summary_falls_back_on_api_error():
    bot = fake_bot_with_session(ok=False, description="INPUT_MEDIA_WIDGET_NOT_ALLOWED")
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    assert await send_widget_summary(bot, S, store, -100, owner=7) is None


async def test_send_widget_summary_registers_message():
    bot = fake_bot_with_session(ok=True, result={"message_id": 42})
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    mid = await send_widget_summary(bot, S, store, 7, owner=7)
    assert mid == 42
    assert store.get_widget_message(7, mid) == "AA"


async def test_send_widget_summary_none_without_data():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    assert await send_widget_summary(bot, S, Store(":memory:"), 7, owner=7) is None
    assert bot.session.calls == []


async def test_send_widget_summary_none_on_size_overflow(monkeypatch):
    import app.widget as widget

    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    monkeypatch.setattr(widget, "build_widget_html", lambda *a: os.urandom(4 * MAX_COMPRESSED_BYTES).hex())
    assert await send_widget_summary(bot, S, store, 7, owner=7) is None
    assert bot.session.calls == []


async def test_send_widget_summary_sends_initial_public_data():
    bot = fake_bot_with_session(ok=True, result={"message_id": 42})
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    assert await send_widget_summary(bot, S, store, 7, owner=7) is not None
    method, payload = bot.session.calls[0]
    assert method == "sendWidget"
    parsed = json.loads(payload["public_data"])
    latest = store.latest("AA")
    assert parsed == json.loads(build_public_data(latest, n=1))
    assert parsed["n"] == 1 and parsed["co2"] == 700 and parsed["ts"] == latest.ts


async def test_send_widget_omits_public_data_by_default():
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    await send_widget(bot, 7, "<html>x</html>", "cap", None)
    _, payload = bot.session.calls[0]
    assert "public_data" not in payload


async def test_send_widget_summary_falls_back_on_build_error(monkeypatch):
    import app.widget as widget

    def boom(*a):
        raise RuntimeError("malformed row")

    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    monkeypatch.setattr(widget, "build_widget_html", boom)
    assert await send_widget_summary(bot, S, store, 7, owner=7) is None
    assert bot.session.calls == []


async def test_send_widget_summary_falls_back_on_store_error(monkeypatch):
    bot = fake_bot_with_session(ok=True, result={"message_id": 1})
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})

    def boom(*a):
        raise RuntimeError("sqlite is busy")

    monkeypatch.setattr(store, "latest", boom)
    assert await send_widget_summary(bot, S, store, 7, owner=7) is None
    assert bot.session.calls == []


def edit_calls(bot) -> list[tuple[str, dict]]:
    return [c for c in bot.session.calls if c[0] == "editMessageWidgetData"]


def widget_store(sent_at: int | None = None, messages: int = 1) -> Store:
    store = Store(":memory:")
    fill(store, "AA", {"co2": 700.0})
    base = int(time.time()) if sent_at is None else sent_at
    for i in range(messages):
        store.add_widget_message(7, 100 + i, "AA", base)
    return store


async def test_update_edits_only_on_change():
    bot = fake_bot_with_session(ok=True, result=True)
    store = widget_store()
    cache: dict = {}
    await update_widget_data_once(bot, S, store, cache)
    await update_widget_data_once(bot, S, store, cache)
    assert len(edit_calls(bot)) == 1


async def test_update_edits_again_when_values_change():
    bot = fake_bot_with_session(ok=True, result=True)
    store = widget_store()
    cache: dict = {}
    await update_widget_data_once(bot, S, store, cache)
    store.add([Reading("AA", int(time.time()), {"co2": 900.0})])
    await update_widget_data_once(bot, S, store, cache)
    assert len(edit_calls(bot)) == 2


async def test_update_throttles_per_cycle_and_drops_dead_messages():
    dead_mid = 101

    class FlakySession(RecordingSession):
        def _next_response(self, data):
            if data.get("message_id") == dead_mid:
                return {"ok": False, "description": "message not found"}
            return {"ok": True, "result": True}

    bot = SimpleNamespace(session=FlakySession({}), token="123456:ABC")
    store = widget_store(messages=3)
    cache: dict = {}
    await update_widget_data_once(bot, S, store, cache)
    calls = edit_calls(bot)
    # не больше одной правки на сообщение за проход
    assert sorted(payload["message_id"] for _, payload in calls) == [100, 101, 102]
    assert store.get_widget_message(7, dead_mid) is None
    assert (7, dead_mid) not in cache
    # Цикл живёт: следующий проход не трогает мёртвое сообщение и не правит без изменений
    await update_widget_data_once(bot, S, store, cache)
    assert edit_calls(bot) == calls


async def test_update_ignores_old_messages():
    bot = fake_bot_with_session(ok=True, result=True)
    old = int(time.time()) - (MAX_WIDGET_AGE_HOURS + 1) * 3600
    store = widget_store(sent_at=old)
    await update_widget_data_once(bot, S, store, {})
    assert edit_calls(bot) == []


async def test_update_warns_and_continues_on_other_errors():
    bot = fake_bot_with_session(ok=False, description="Forbidden: bot was blocked")
    store = widget_store()
    await update_widget_data_once(bot, S, store, {})
    assert store.get_widget_message(7, 100) == "AA"  # запись не вычищена


async def test_update_skips_messages_without_readings():
    bot = fake_bot_with_session(ok=True, result=True)
    store = Store(":memory:")
    store.add_widget_message(7, 100, "AA", int(time.time()))
    await update_widget_data_once(bot, S, store, {})
    assert edit_calls(bot) == []
