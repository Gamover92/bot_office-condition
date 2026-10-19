import sqlite3

from app.mqtt_listener import handle_message
from app.store import Store

PAYLOAD = b'{"mac": "582D34AABBCC", "timestamp": 10, "co2": 500}'


def test_handle_message_saves_readings():
    store = Store(":memory:")
    assert handle_message(store, "qingping/582D34AABBCC/up", PAYLOAD) == 1
    assert store.latest("582D34AABBCC").values == {"co2": 500}


def test_handle_message_survives_store_error(caplog):
    class BrokenStore:
        def add(self, readings):
            raise sqlite3.OperationalError("database is locked")

    assert handle_message(BrokenStore(), "qingping/582D34AABBCC/up", PAYLOAD) == 0
    assert "database is locked" in caplog.text
