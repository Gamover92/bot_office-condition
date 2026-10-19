import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from app.auth import validate_init_data
from app.config import Settings
from app.qingping import overall, parse_message, rate
from app.store import Store
from app.summary import summary_html
from app.web import build_app, downsample

TOKEN = "123:TEST"

QINGPING_MSG = {
    "id": 7,
    "mac": "582D34AABBCC",
    "type": "12",
    "need_ack": 1,
    "sensorData": [
        {
            "timestamp": {"value": 1_700_000_000},
            "temperature": {"value": 23.4, "status": 0},
            "humidity": {"value": 45.1},
            "co2": {"value": 1350},
            "pm25": {"value": 8},
            "battery": {"value": 100},
        },
        {"timestamp": {"value": 1_700_000_900}, "co2": {"value": 700}},
    ],
}


def sign(fields: dict, token: str = TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


def init_data(user_id: int) -> str:
    return sign({"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})})


def test_parse_qingping_json():
    readings = parse_message("qingping/582D34AABBCC/up", json.dumps(QINGPING_MSG))
    assert [r.ts for r in readings] == [1_700_000_000, 1_700_000_900]
    assert readings[0].mac == "582D34AABBCC"
    assert readings[0].values == {"temperature": 23.4, "humidity": 45.1, "co2": 1350, "pm25": 8, "battery": 100}


def test_parse_flat_payload_uses_topic_mac():
    readings = parse_message("qingping/aabb/up", b'{"temperature": 21, "pm2.5": 3}')
    assert readings[0].mac == "AABB"
    assert readings[0].values == {"temperature": 21.0, "pm25": 3.0}


def test_parse_ignores_garbage():
    assert parse_message("qingping/x/up", b"\x00\x01") == []
    assert parse_message("qingping/x/up", b'{"type": "28", "setting": {}}') == []


def test_rating():
    assert rate("co2", 600) == "good"
    assert rate("co2", 1000) == "fair"
    assert rate("co2", 1500) == "bad"
    assert rate("temperature", 22) == "good"
    assert rate("temperature", 26) == "fair"
    assert rate("humidity", 20) == "bad"
    assert rate("battery", 5) == "none"
    assert overall({"co2": 600, "humidity": 35}) == "fair"


def test_store_merges_latest_values():
    store = Store(":memory:")
    store.add(parse_message("qingping/x/up", json.dumps(QINGPING_MSG)))
    latest = store.latest("582D34AABBCC")
    assert latest.ts == 1_700_000_900
    assert latest.values["co2"] == 700  # newest
    assert latest.values["temperature"] == 23.4  # carried from the older sample


def test_summary_text():
    s = Settings(bot_token=TOKEN, webapp_url="", device_names={"582D34AABBCC": "Опенспейс"})
    store = Store(":memory:")
    assert "пока нет" in summary_html(s, store)
    store.add(parse_message("qingping/x/up", json.dumps(QINGPING_MSG)))
    text = summary_html(s, store)
    assert "Опенспейс" in text and "CO₂: <b>700 ppm</b>" in text and "устарели" in text


def test_init_data_validation():
    good = init_data(42)
    assert validate_init_data(good, TOKEN)["user"]["id"] == 42
    assert validate_init_data(good, "other:token") is None
    assert validate_init_data(good.replace("42", "43"), TOKEN) is None
    old = sign({"auth_date": "1000", "user": '{"id":1}'})
    assert validate_init_data(old, TOKEN) is None


def test_downsample():
    pts = [(i, float(i)) for i in range(1000)]
    out = downsample(pts, 100)
    assert len(out) == 100 and out[0][1] < out[-1][1]
    assert downsample(pts[:5], 100) == pts[:5]


async def test_api_access_and_data():
    now = int(time.time())
    store = Store(":memory:")
    store.add(parse_message("qingping/abc/up", json.dumps({"timestamp": now, "co2": 900})))
    s = Settings(bot_token=TOKEN, webapp_url="", allowed_users=frozenset({42}))
    async with TestClient(TestServer(build_app(s, store, bot=None))) as client:
        assert (await client.get("/api/state")).status == 401
        r = await client.get("/api/state", headers={"X-Telegram-Init-Data": init_data(7)})
        assert r.status == 403

        hdr = {"X-Telegram-Init-Data": init_data(42)}
        data = await (await client.get("/api/state", headers=hdr)).json()
        assert data["devices"][0]["metrics"][0] == {
            "key": "co2", "title": "CO₂", "unit": "ppm", "value": 900, "rating": "fair",
        }
        hist = await (await client.get("/api/history?mac=abc&metric=co2&hours=1", headers=hdr)).json()
        assert hist["points"] == [[now, 900]]
        assert (await client.get("/api/history?metric=nope", headers=hdr)).status == 400
        assert (await client.get("/")).status == 200
        assert (await client.get("/static/app.js")).status == 200
