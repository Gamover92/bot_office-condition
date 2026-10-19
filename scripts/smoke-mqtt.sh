#!/bin/sh
# Smoke test: Mosquitto -> app.mqtt_listener -> SQLite. Needs Docker. No Telegram token.
set -eu
cd "$(dirname "$0")/.."

NET=climate-smoke
cleanup() { docker rm -f climate-smoke-mq climate-smoke-bot >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker build -q -t office-climate-bot . >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name climate-smoke-mq --network "$NET" \
  -v "$PWD/mosquitto/config:/mosquitto/config:ro" eclipse-mosquitto:2.0.20 >/dev/null

docker run -d --name climate-smoke-bot --network "$NET" \
  -e MQTT_HOST=climate-smoke-mq -e DB_PATH=/tmp/smoke.db -e LOG_LEVEL=DEBUG \
  office-climate-bot python -c "
import asyncio, logging
from app.config import Settings
from app.store import Store
from app.mqtt_listener import run_mqtt
logging.basicConfig(level='DEBUG')
s = Settings.from_env()
asyncio.run(asyncio.wait_for(run_mqtt(s, Store(s.db_path)), 60))
" >/dev/null 2>&1 || true

# Wait until the listener has subscribed.
i=0
until docker logs climate-smoke-bot 2>&1 | grep -q "MQTT connected"; do
  i=$((i + 1)); [ "$i" -lt 30 ] || { echo "FAIL: listener did not connect"; docker logs climate-smoke-bot; exit 1; }
  sleep 0.5
done

NOW=$(date +%s)
docker exec climate-smoke-mq mosquitto_pub -t qingping/582D34AABBCC/up -m \
  "{\"mac\":\"582D34AABBCC\",\"type\":\"17\",\"sensorData\":[{\"timestamp\":{\"value\":$NOW},\"co2\":{\"value\":777}}]}"
sleep 2

RESULT=$(docker exec climate-smoke-bot python -c "
from app.store import Store
r = Store('/tmp/smoke.db').latest('582D34AABBCC')
print(r.values['co2'] if r else 'none')
")
if [ "$RESULT" = "777.0" ]; then echo "OK: reading saved (co2=$RESULT)"; else echo "FAIL: got $RESULT"; docker logs climate-smoke-bot; exit 1; fi
