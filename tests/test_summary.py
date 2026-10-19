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
