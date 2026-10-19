"""SQLite storage for readings. One connection, used from the event loop."""

from __future__ import annotations

import json
import os
import sqlite3
import time

from .qingping import Reading


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS readings ("
            " mac TEXT NOT NULL, ts INTEGER NOT NULL, data TEXT NOT NULL,"
            " PRIMARY KEY (mac, ts))"
        )
        self.db.commit()

    def add(self, readings: list[Reading]) -> None:
        # Devices can send one sample as several partial messages: merge them.
        for r in readings:
            row = self.db.execute(
                "SELECT data FROM readings WHERE mac=? AND ts=?", (r.mac, r.ts)
            ).fetchone()
            values = {**json.loads(row[0]), **r.values} if row else r.values
            self.db.execute(
                "INSERT OR REPLACE INTO readings (mac, ts, data) VALUES (?, ?, ?)",
                (r.mac, r.ts, json.dumps(values)),
            )
        self.db.commit()

    def devices(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT mac FROM readings ORDER BY mac")]

    def latest(self, mac: str) -> Reading | None:
        """Newest value of each metric, with the newest timestamp."""
        rows = self.db.execute(
            "SELECT ts, data FROM readings WHERE mac=? ORDER BY ts DESC LIMIT 20", (mac,)
        ).fetchall()
        if not rows:
            return None
        values: dict[str, float] = {}
        for _, data in reversed(rows):
            values.update(json.loads(data))
        return Reading(mac=mac, ts=rows[0][0], values=values)

    def history(self, mac: str, since: int) -> list[Reading]:
        rows = self.db.execute(
            "SELECT ts, data FROM readings WHERE mac=? AND ts>=? ORDER BY ts", (mac, since)
        )
        return [Reading(mac=mac, ts=ts, values=json.loads(d)) for ts, d in rows]

    def prune(self, keep_days: int) -> None:
        self.db.execute("DELETE FROM readings WHERE ts < ?", (int(time.time()) - keep_days * 86400,))
        self.db.commit()
