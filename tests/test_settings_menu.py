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
