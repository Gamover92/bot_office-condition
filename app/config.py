"""Settings read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_set(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _device_names(raw: str) -> dict[str, str]:
    # "AABBCCDDEEFF=Open space;112233445566=Meeting room"
    names: dict[str, str] = {}
    for item in raw.split(";"):
        if "=" in item:
            mac, name = item.split("=", 1)
            names[mac.strip().upper()] = name.strip()
    return names


@dataclass(frozen=True)
class Settings:
    bot_token: str
    webapp_url: str
    miniapp_short_name: str = ""
    allowed_chats: frozenset[int] = field(default_factory=frozenset)
    allowed_users: frozenset[int] = field(default_factory=frozenset)
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_topic: str = "qingping/+/up"
    device_names: dict[str, str] = field(default_factory=dict)
    db_path: str = "/data/climate.db"
    history_days: int = 30
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    stale_after_min: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            bot_token=e("BOT_TOKEN", ""),
            webapp_url=e("WEBAPP_URL", "").rstrip("/"),
            miniapp_short_name=e("MINIAPP_SHORT_NAME", ""),
            allowed_chats=_int_set(e("ALLOWED_CHAT_IDS", "")),
            allowed_users=_int_set(e("ALLOWED_USER_IDS", "")),
            mqtt_host=e("MQTT_HOST", "mosquitto"),
            mqtt_port=int(e("MQTT_PORT", "1883")),
            mqtt_user=e("MQTT_USER", ""),
            mqtt_password=e("MQTT_PASSWORD", ""),
            mqtt_topic=e("MQTT_TOPIC", "qingping/+/up"),
            device_names=_device_names(e("DEVICE_NAMES", "")),
            db_path=e("DB_PATH", "/data/climate.db"),
            history_days=int(e("HISTORY_DAYS", "30")),
            http_host=e("HTTP_HOST", "0.0.0.0"),
            http_port=int(e("HTTP_PORT", "8080")),
            stale_after_min=int(e("STALE_AFTER_MIN", "30")),
        )

    def is_allowed(self, user_id: int | None, chat_id: int | None = None) -> bool:
        """Empty allow-lists mean everyone is allowed."""
        if not self.allowed_chats and not self.allowed_users:
            return True
        return (user_id in self.allowed_users) or (chat_id in self.allowed_chats)
