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
