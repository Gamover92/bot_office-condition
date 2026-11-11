import json
import time

from app.qingping import Reading, parse_message
from app.store import Store
from tests.test_qingping import QINGPING_MSG


def test_store_merges_latest_values():
    store = Store(":memory:")
    store.add(parse_message("qingping/582D34AABBCC/up", json.dumps(QINGPING_MSG)))
    latest = store.latest("582D34AABBCC")
    assert latest.ts == 1_700_000_900
    assert latest.values["co2"] == 700
    assert latest.values["temperature"] == 23.4
    assert store.devices() == ["582D34AABBCC"]


def test_store_merges_partial_message_with_same_ts():
    store = Store(":memory:")
    store.add(parse_message("qingping/582D34AABBCC/up", b'{"timestamp": 10, "co2": 500}'))
    store.add(parse_message("qingping/582D34AABBCC/up", b'{"timestamp": 10, "humidity": 40}'))
    assert store.history("582D34AABBCC", 0)[0].values == {"co2": 500, "humidity": 40}


def test_store_history_and_prune():
    now = int(time.time())
    store = Store(":memory:")
    store.add(parse_message("qingping/582D34AABBCC/up", json.dumps({"timestamp": now - 40 * 86400, "co2": 1})))
    store.add(parse_message("qingping/582D34AABBCC/up", json.dumps({"timestamp": now, "co2": 2})))
    assert [r.values["co2"] for r in store.history("582D34AABBCC", now - 3600)] == [2]
    store.prune(30)
    assert [r.values["co2"] for r in store.history("582D34AABBCC", 0)] == [2]


def test_latest_unknown_device():
    assert Store(":memory:").latest("NOPE") is None


def test_devices_newest_reading_first():
    store = Store(":memory:")
    store.add([Reading("AA", 100, {"co2": 1}), Reading("BB", 300, {"co2": 1}), Reading("CC", 200, {"co2": 1})])
    assert store.devices() == ["BB", "CC", "AA"]


def test_delete_device():
    store = Store(":memory:")
    store.add([Reading("AA", 100, {"co2": 1}), Reading("AA", 200, {"co2": 2}), Reading("BB", 100, {"co2": 3})])
    store.delete_device("AA")
    assert store.devices() == ["BB"]
    assert store.latest("AA") is None


def test_delete_device_normalises_mac_and_returns_count():
    store = Store(":memory:")
    store.add([Reading("582D34AABBCC", 100, {"co2": 1}), Reading("582D34AABBCC", 200, {"co2": 2})])
    assert store.delete_device("58:2d:34:aa:bb:cc") == 2
    assert store.devices() == []
    assert store.delete_device("58-2d-34-aa-bb-cc") == 0


def test_widget_messages_roundtrip():
    store = Store(":memory:")
    store.add_widget_message(-100, 5, "AA", sent_at=1000, owner=7)
    store.add_widget_message(-100, 6, "BB", sent_at=300)
    assert store.get_widget_message(-100, 5) == "AA"
    assert store.get_widget_message(-100, 9) is None
    assert store.widget_messages(max_age_sec=600, now=1000) == [(-100, 5, "AA", 7)]
    store.drop_widget_message(-100, 5)
    assert store.get_widget_message(-100, 5) is None


def test_prune_widget_messages():
    store = Store(":memory:")
    store.add_widget_message(1, 1, "AA", sent_at=100)
    store.prune_widget_messages(older_than=200)
    assert store.widget_messages(max_age_sec=10**9, now=300) == []


def test_ignored_metrics_hidden_also_in_old_rows():
    store = Store(":memory:")
    store.add([Reading("582D34AABBCC", 100, {"co2": 700, "pm25": 999999999})])  # stored before the fix
    store.ignored = frozenset({"pm10"})
    assert store.latest("582D34AABBCC").values == {"co2": 700}  # implausible pm25 dropped on read
    ignoring = Store(":memory:", ignored=frozenset({"pm25"}))
    ignoring.add([Reading("582D34AABBCC", 100, {"co2": 700, "pm25": 10})])
    assert ignoring.latest("582D34AABBCC").values == {"co2": 700}
    assert ignoring.history("582D34AABBCC", 0)[0].values == {"co2": 700}
