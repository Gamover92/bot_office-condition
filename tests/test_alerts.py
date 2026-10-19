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
