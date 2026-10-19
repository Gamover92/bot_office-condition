#!/bin/sh
# Create or update an MQTT user: ./scripts/mqtt-passwd.sh <user>
set -e
[ -n "$1" ] || { echo "usage: $0 <user>"; exit 1; }
docker compose run --rm mosquitto mosquitto_passwd -c /mosquitto/config/passwd "$1"
