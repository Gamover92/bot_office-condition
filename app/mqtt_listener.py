"""Subscribe to Qingping topics and save readings. Reconnects on errors."""

from __future__ import annotations

import asyncio
import logging
import secrets

import aiomqtt

from .config import Settings
from .qingping import parse_message
from .store import Store

log = logging.getLogger(__name__)


def client_id() -> str:
    # A unique ID: two bot instances with the same ID would disconnect each other.
    return f"office-climate-bot-{secrets.token_hex(3)}"


def handle_message(store: Store, topic: str, payload: bytes | str) -> int:
    """Parse and save one message. Return the number of saved readings (0 on error)."""
    try:
        readings = parse_message(topic, payload)
        if readings:
            store.add(readings)
            log.debug("Saved %d reading(s) from %s", len(readings), topic)
        return len(readings)
    except Exception:
        log.exception("Failed to handle MQTT message from %s", topic)
        return 0


async def run_mqtt(settings: Settings, store: Store) -> None:
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_user or None,
                password=settings.mqtt_password or None,
                identifier=client_id(),
            ) as client:
                await client.subscribe(settings.mqtt_topic)
                log.info("MQTT connected, topic %s", settings.mqtt_topic)
                async for message in client.messages:
                    handle_message(store, str(message.topic), message.payload)
        except aiomqtt.MqttError as exc:
            log.warning("MQTT error: %s. Reconnect in 5 s.", exc)
            await asyncio.sleep(5)
