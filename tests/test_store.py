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
