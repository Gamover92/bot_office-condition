import sqlite3

import pytest


@pytest.fixture(autouse=True)
def close_sqlite(monkeypatch):
    """Close every SQLite connection that a test opens (tests create in-memory DBs inline)."""
    opened = []
    connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    yield
    for conn in opened:
        conn.close()
