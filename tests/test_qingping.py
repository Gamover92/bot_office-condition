import json
import time

from app.qingping import advice, overall, parse_message, rate

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


def test_parse_qingping_json():
    readings = parse_message("qingping/582D34AABBCC/up", json.dumps(QINGPING_MSG))
    assert [r.ts for r in readings] == [1_700_000_000, 1_700_000_900]
    assert readings[0].mac == "582D34AABBCC"
    assert readings[0].values == {"temperature": 23.4, "humidity": 45.1, "co2": 1350, "pm25": 8, "battery": 100}


def test_parse_realtime_type_17():
    msg = {"mac": "582D34AABBCC", "type": "17", "sensorData": [{"timestamp": {"value": 5}, "co2": {"value": 600}}]}
    assert parse_message("qingping/582D34AABBCC/up", json.dumps(msg))[0].values == {"co2": 600}


def test_parse_flat_payload_uses_topic_mac():
    readings = parse_message("qingping/582d34aabbcc/up", b'{"temperature": 21, "pm2.5": 3}')
    assert readings[0].mac == "582D34AABBCC"
    assert readings[0].values == {"temperature": 21.0, "pm25": 3.0}


def test_parse_ignores_garbage():
    assert parse_message("qingping/582D34AABBCC/up", b"\x00\x01") == []
    assert parse_message("qingping/582D34AABBCC/up", b'{"type": "28", "setting": {}}') == []
    assert parse_message("qingping/582D34AABBCC/up", b"[1, 2]") == []


def test_parse_drops_non_finite_values():
    msg = b'{"mac": "582D34AABBCC", "timestamp": 10, "co2": NaN, "temperature": "inf", "humidity": "1e400", "pm25": 3}'
    readings = parse_message("qingping/582D34AABBCC/up", msg)
    assert readings[0].values == {"pm25": 3.0}


def test_parse_non_finite_timestamp_uses_fallback():
    msg = b'{"mac": "582D34AABBCC", "timestamp": 100, "sensorData": [{"timestamp": Infinity, "co2": 600}]}'
    assert parse_message("qingping/582D34AABBCC/up", msg)[0].ts == 100
    before = time.time()
    msg = b'{"mac": "582D34AABBCC", "timestamp": "nan", "sensorData": [{"timestamp": Infinity, "co2": 600}]}'
    assert int(before) <= parse_message("qingping/582D34AABBCC/up", msg)[0].ts <= time.time()


def test_parse_mac_validation():
    long_mac = "A" * 60
    assert parse_message(f"qingping/{long_mac}/up", b'{"co2": 600}') == []
    assert parse_message("qingping/x/up", json.dumps({"mac": long_mac, "co2": 600})) == []
    assert parse_message("qingping/x/up", b'{"co2": 600}') == []
    readings = parse_message("qingping/x/up", b'{"mac": "58:2D:34:AA:BB:CC", "co2": 600}')
    assert readings[0].mac == "582D34AABBCC"
    assert parse_message("qingping/x/up", b'{"mac": "58-2d-34-aa-bb-cc", "co2": 600}')[0].mac == "582D34AABBCC"


def test_rating():
    assert rate("co2", 600) == "good"
    assert rate("co2", 1000) == "fair"
    assert rate("co2", 1500) == "bad"
    assert rate("temperature", 22) == "good"
    assert rate("temperature", 26) == "fair"
    assert rate("humidity", 20) == "bad"
    assert rate("battery", 5) == "none"
    assert overall({"co2": 600, "humidity": 35}) == "fair"


def test_advice():
    assert advice({"co2": 1100})[0].startswith("Проветрите")
    assert advice({"co2": 600, "temperature": 22}) == []


def test_parse_readme_test_payload_uses_current_time():
    before = int(time.time())
    readings = parse_message("qingping/582D34000000/up", b'{"mac":"582D34000000","co2":1300,"temperature":23}')
    assert readings[0].mac == "582D34000000"
    assert readings[0].values == {"co2": 1300.0, "temperature": 23.0}
    assert before <= readings[0].ts <= time.time()
