"""Subscribe to Qingping topics and save readings. Reconnects on errors."""

from __future__ import annotations

import asyncio
import logging

import aiomqtt

from .config import Settings
from .qingping import parse_message
from .store import Store

log = logging.getLogger(__name__)


async def run_mqtt(settings: Settings, store: Store) -> None:
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_user or None,
                password=settings.mqtt_password or None,
                identifier="office-climate-bot",
            ) as client:
                await client.subscribe(settings.mqtt_topic)
                log.info("MQTT connected, topic %s", settings.mqtt_topic)
                async for message in client.messages:
                    readings = parse_message(str(message.topic), message.payload)
                    if readings:
                        store.add(readings)
                        log.debug("Saved %d reading(s) from %s", len(readings), message.topic)
        except aiomqtt.MqttError as exc:
            log.warning("MQTT error: %s. Reconnect in 5 s.", exc)
            await asyncio.sleep(5)
