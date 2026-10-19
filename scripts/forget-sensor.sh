#!/bin/sh
# Delete all readings of a sensor (for example the test sensor): ./scripts/forget-sensor.sh <MAC>
set -e
[ -n "$1" ] || { echo "usage: $0 <MAC>"; exit 1; }
docker compose exec bot python -c "from app.store import Store; import sys; Store('/data/climate.db').delete_device(sys.argv[1].upper())" "$1"
