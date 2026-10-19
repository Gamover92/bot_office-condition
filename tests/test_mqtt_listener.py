import re
import sqlite3

from app.mqtt_listener import client_id, handle_message
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


def test_client_id_is_unique():
    first, second = client_id(), client_id()
    assert re.fullmatch(r"office-climate-bot-[0-9a-f]{6}", first)
    assert first != second
