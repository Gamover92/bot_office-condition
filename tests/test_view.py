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


def test_keyboard_devices_sorted_by_mac():
    kb = build_keyboard(S, ["BB", "AA"], "BB", ["co2"], "co2", 6)
    assert texts(kb)[0] == ["Датчик AA", "• Датчик BB •"]


async def test_build_view_defaults_to_freshest_sensor():
    store = Store(":memory:")
    now = time.time()
    store.add([Reading("AA", int(now) - 60, {"co2": 700.0})])
    store.add([Reading("ZZ", int(now) - 3 * 86400, {"co2": 500.0})])
    view = await build_view(S, store, now=now)
    assert texts(view.keyboard)[0] == ["• Датчик AA •", "Датчик ZZ"]
    store.add([Reading("ZZ", int(now), {"co2": 500.0})])
    view = await build_view(S, store, now=now)
    assert texts(view.keyboard)[0] == ["Датчик AA", "• Датчик ZZ •"]
