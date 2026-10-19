"""HTTP server: Mini App static files and a small JSON API."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from aiogram import Bot
from aiohttp import web

from .auth import validate_init_data
from .config import Settings
from .qingping import METRICS
from .store import Store
from .summary import snapshot

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
MEMBER_TTL = 600


class Access:
    """Check Mini App users. Members of an allowed chat are also allowed."""

    def __init__(self, settings: Settings, bot: Bot | None):
        self.settings = settings
        self.bot = bot
        self.cache: dict[int, tuple[float, bool]] = {}

    async def check(self, user_id: int) -> bool:
        s = self.settings
        if s.is_allowed(user_id):
            return True
        if not s.allowed_chats or self.bot is None:
            return False
        cached = self.cache.get(user_id)
        if cached and time.time() - cached[0] < MEMBER_TTL:
            return cached[1]
        ok = False
        for chat_id in s.allowed_chats:
            try:
                member = await self.bot.get_chat_member(chat_id, user_id)
            except Exception as exc:  # user or chat not found, bot not in chat
                log.debug("get_chat_member %s/%s failed: %s", chat_id, user_id, exc)
                continue
            if member.status in ("creator", "administrator", "member", "restricted"):
                ok = True
                break
        self.cache[user_id] = (time.time(), ok)
        return ok


def downsample(points: list[tuple[int, float]], limit: int = 240) -> list[tuple[int, float]]:
    """Average points into at most `limit` buckets."""
    if len(points) <= limit:
        return points
    t0, t1 = points[0][0], points[-1][0]
    size = (t1 - t0) / limit or 1
    buckets: dict[int, list[tuple[int, float]]] = {}
    for ts, v in points:
        buckets.setdefault(min(int((ts - t0) / size), limit - 1), []).append((ts, v))
    return [
        (int(sum(t for t, _ in b) / len(b)), sum(v for _, v in b) / len(b))
        for _, b in sorted(buckets.items())
    ]


def build_app(settings: Settings, store: Store, bot: Bot | None) -> web.Application:
    access = Access(settings, bot)

    @web.middleware
    async def auth_mw(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        data = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""), settings.bot_token)
        if data is None:
            raise web.HTTPUnauthorized(text="Откройте приложение из Telegram")
        user_id = (data.get("user") or {}).get("id")
        if user_id is None or not await access.check(int(user_id)):
            raise web.HTTPForbidden(text="Нет доступа")
        return await handler(request)

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "devices": len(store.devices())})

    async def state(_: web.Request) -> web.Response:
        return web.json_response({"now": int(time.time()), "devices": snapshot(settings, store)})

    async def history(request: web.Request) -> web.Response:
        mac = request.query.get("mac", "").upper()
        metric = request.query.get("metric", "co2")
        if metric not in METRICS:
            raise web.HTTPBadRequest(text="unknown metric")
        try:
            hours = max(1, min(int(request.query.get("hours", "24")), settings.history_days * 24))
        except ValueError:
            raise web.HTTPBadRequest(text="bad hours")
        rows = store.history(mac, int(time.time()) - hours * 3600)
        points = [(r.ts, r.values[metric]) for r in rows if metric in r.values]
        return web.json_response({"metric": metric, "points": downsample(points)})

    app = web.Application(middlewares=[auth_mw])
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/history", history)
    app.router.add_static("/static/", STATIC)
    return app
