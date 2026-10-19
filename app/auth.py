"""Validate Telegram Mini App initData.

See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """Return the parsed fields when the signature is valid, else None."""
    try:
        fields = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received = fields.pop("hash", "")
    if not received:
        return None

    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        if time.time() - int(fields.get("auth_date", "0")) > max_age:
            return None
    except ValueError:
        return None

    for key in ("user", "chat", "receiver"):
        if key in fields:
            try:
                fields[key] = json.loads(fields[key])
            except ValueError:
                return None
    return fields
