"""Фаза-1 спайк: HTML-виджет Telegram сырым HTTP (throwaway, без тестов).

Режимы:
    python spike_widget.py            живой прогон: sendWidget + 3 правки public_data
    python spike_widget.py --measure  офлайн: бюджет данных (8 метрик x 3 периода)

Переменные окружения:
    BOT_TOKEN      токен бота (только живой режим)
    SPIKE_CHAT_ID  id личного чата с ботом (только живой режим)
    DB_PATH        путь к SQLite, по умолчанию data/climate.db

aiogram 3.31 не знает методов виджетов (Bot API 10.4), поэтому вызовы идут
сырым HTTP через aiohttp. Имена полей — по docs/tgw-format.md и
scripts/conformance/test-bot.ts из TelegramMessenger/widget-sandbox.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import zlib

from app.store import Store

try:
    from app.view import CHART_METRICS
except ImportError:
    # app.view тянет aiogram/matplotlib; в минимальном окружении их может не быть.
    # Копия app/view.py:CHART_METRICS — при расхождении править там и здесь.
    CHART_METRICS = ("co2", "temperature", "humidity", "pm25", "pm10", "tvoc", "tvoc_index", "noise")

DB_DEFAULT = "data/climate.db"
PERIODS_HOURS = (6, 24, 168)  # как PERIODS в app/view.py
BUDGET_BYTES = 3800  # рабочий бюджет: лимит 4 KB с запасом
EDIT_COUNT = 3
EDIT_INTERVAL_SEC = 5
SPARKLINE_POINTS = 120
MEASURE_CANDIDATES = (480, 360, 288, 240, 192, 160, 128, 96, 64, 48)


def compressed_size(html: str) -> int:
    """То, что считает сервер: len(zlib.compress(html, 9))."""
    return len(zlib.compress(html.encode(), 9))


def open_store() -> Store:
    return Store(os.environ.get("DB_PATH", DB_DEFAULT))


def pick_device(store: Store) -> str:
    macs = store.devices()
    if not macs:
        sys.exit("в БД нет ни одного датчика — спайку нечего показывать")
    return macs[0]


def series(store: Store, mac: str, metric: str, hours: int, max_points: int) -> list[tuple[int, float]]:
    rows = store.history(mac, int(time.time()) - hours * 3600)
    points = [(r.ts, r.values[metric]) for r in rows if metric in r.values]
    return downsample(points, max_points)


def downsample(points: list[tuple[int, float]], max_points: int) -> list[tuple[int, float]]:
    """Равномерное прореживание до max_points, края сохраняются."""
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def compact(value: float) -> float | int:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def public_data_json(store: Store, mac: str, n: int) -> str:
    """Свежие последние значения, компактный JSON (<= 1024 байт с огромным запасом)."""
    reading = store.latest(mac)
    values = reading.values if reading else {}
    payload = {
        "co2": compact(values.get("co2", 0)),
        "t": compact(values.get("temperature", 0)),
        "h": compact(values.get("humidity", 0)),
        "ts": reading.ts if reading else 0,
        "n": n,  # правка без изменений отклоняется ("message is not modified")
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def sparkline_svg(points: list[tuple[int, float]], width: int = 400, height: int = 90) -> str:
    if len(points) < 2:
        return "<div>нет данных за 24 ч</div>"
    t0, t1 = points[0][0], points[-1][0]
    vmin = min(v for _, v in points)
    vmax = max(v for _, v in points)
    vspan = (vmax - vmin) or 1
    tspan = (t1 - t0) or 1
    pts = " ".join(
        f"{(ts - t0) / tspan * width:.1f},{height - (v - vmin) / vspan * (height - 6) - 3:.1f}"
        for ts, v in points
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:100%;height:90px;display:block">'
        f'<polyline points="{pts}" fill="none" stroke="#4caf50" stroke-width="2"/>'
        f'<text x="2" y="12" font-size="11" fill="#888">{compact(vmax)}</text>'
        f'<text x="2" y="{height - 2}" font-size="11" fill="#888">{compact(vmin)}</text>'
        f"</svg>"
    )


def build_spike_html(store: Store, mac: str) -> str:
    """Текущие значения + один спарклайн CO2 за 24 ч. Цифры затем живут из public_data."""
    reading = store.latest(mac)
    values = reading.values if reading else {}
    co2_24h = series(store, mac, "co2", 24, SPARKLINE_POINTS)
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;padding:8px;font:14px/1.5 -apple-system,"Segoe UI",sans-serif}}
.row{{display:flex;gap:12px;margin-bottom:4px}}
.cell{{flex:1;text-align:center;background:rgba(128,128,128,.12);border-radius:8px;padding:6px 0}}
.num{{font-size:20px;font-weight:600}}.lbl{{font-size:11px;opacity:.6}}
</style>
<div class="row">
<div class="cell"><div class="num" id="co2">{compact(values.get("co2", 0))}</div><div class="lbl">CO₂ ppm</div></div>
<div class="cell"><div class="num" id="t">{compact(values.get("temperature", 0))}</div><div class="lbl">Темп. °C</div></div>
<div class="cell"><div class="num" id="h">{compact(values.get("humidity", 0))}</div><div class="lbl">Влажн. %</div></div>
</div>
{sparkline_svg(co2_24h)}
<div class="lbl" id="upd">CO₂ за 24 ч</div>
<script>
var last="";
function tick(){{
try{{
var p=window.TelegramWidget&&TelegramWidget.publicData;
if(p&&p!==last){{last=p;var d=JSON.parse(p);
document.getElementById("co2").textContent=d.co2;
document.getElementById("t").textContent=d.t;
document.getElementById("h").textContent=d.h;
document.getElementById("upd").textContent="CO₂ за 24 ч · обновлено #"+d.n;}}
}}catch(e){{}}
}}
setInterval(tick,2000);tick();
</script>"""


def build_measure_html(store: Store, mac: str, points_per_series: int) -> tuple[str, dict[str, int]]:
    """Все CHART_METRICS x 3 периода, запечённые в HTML компактным JSON.

    Серия кодируется как [t0, dt, [values]]: первый epoch, шаг в секундах,
    значения с округлением до 0.1. Возвращает (html, {ключ: число точек}).
    """
    data: dict[str, list] = {}
    counts: dict[str, int] = {}
    for metric in CHART_METRICS:
        for hours in PERIODS_HOURS:
            points = series(store, mac, metric, hours, points_per_series)
            if len(points) < 2:
                continue
            t0 = points[0][0]
            dt = max(1, round((points[-1][0] - t0) / (len(points) - 1)))
            key = f"{metric}:{hours}"
            data[key] = [t0, dt, [compact(v) for _, v in points]]
            counts[key] = len(points)
    baked = json.dumps(data, separators=(",", ":"))
    html = (
        '<!doctype html><meta charset="utf-8"><style>'
        "body{margin:0;padding:8px;font:14px/1.5 sans-serif}"
        "</style><div id=chart></div>"
        f"<script>var D={baked};</script>"
        "<script>/* отрисовка canvas по D — фаза 2 */</script>"
    )
    return html, counts


def measure() -> None:
    store = open_store()
    mac = pick_device(store)
    print(f"датчик: {mac}, бюджет: {BUDGET_BYTES} сжатых байт (лимит 4096)")
    print(f"метрики: {', '.join(CHART_METRICS)}; периоды: {PERIODS_HOURS} ч")
    chosen = None
    for candidate in MEASURE_CANDIDATES:
        html, counts = build_measure_html(store, mac, candidate)
        size = compressed_size(html)
        series_baked = len(counts)
        series_total = len(CHART_METRICS) * len(PERIODS_HOURS)
        fits = "OK" if size <= BUDGET_BYTES else "OVER"
        print(
            f"{candidate:>4} точек/серия -> исходник {len(html.encode())} B, "
            f"сжатый {size} B [{fits}], серий {series_baked}/{series_total}"
        )
        if chosen is None and size <= BUDGET_BYTES:
            chosen = (candidate, size, counts)
    if chosen is None:
        print("не влезает даже при минимальной плотности — расклад меняется, см. спеку")
        return
    candidate, size, counts = chosen
    real = {k: v for k, v in counts.items() if v < candidate}
    print(f"\nвыбрано: {candidate} точек/серия, сжатый размер {size} B")
    if real:
        print("серий с меньшим числом исходных точек (прореживание не понадобилось):")
        for key, count in sorted(real.items()):
            print(f"  {key}: {count}")


async def api(session, token: str, method: str, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with session.post(url, json=params) as resp:
        body = await resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('description')}")
    return body["result"]


async def live() -> None:
    import aiohttp  # зависимость aiogram, отдельно не ставим

    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("SPIKE_CHAT_ID")
    missing = [name for name, value in (("BOT_TOKEN", token), ("SPIKE_CHAT_ID", chat_id)) if not value]
    if missing:
        sys.exit(
            f"не заданы переменные окружения: {', '.join(missing)}. "
            "Для живого прогона: BOT_TOKEN=<токен> SPIKE_CHAT_ID=<id лички> python spike_widget.py"
        )
    try:
        chat_id = int(chat_id)
    except ValueError:
        pass  # допустим и @username-стиль, Bot API сам разберёт

    store = open_store()
    mac = pick_device(store)
    html = build_spike_html(store, mac)
    print(f"датчик: {mac}")
    print(f"HTML исходник: {len(html.encode())} B")
    print(f"HTML сжатый zlib-9: {compressed_size(html)} B (бюджет {BUDGET_BYTES})")

    async with aiohttp.ClientSession() as session:
        sent = await api(
            session,
            token,
            "sendWidget",
            chat_id=chat_id,
            html=html,
            width=430,
            height=220,
            public_data=public_data_json(store, mac, 0),
        )
        message_id = sent["message_id"]
        print(f"message_id: {message_id}")
        for n in range(1, EDIT_COUNT + 1):
            await asyncio.sleep(EDIT_INTERVAL_SEC)
            data = public_data_json(store, mac, n)
            await api(
                session,
                token,
                "editMessageWidgetData",
                chat_id=chat_id,
                message_id=message_id,
                public_data=data,
            )
            print(f"правка #{n}: public_data={data}")


def main() -> None:
    # Windows-консоль: печатаем UTF-8 независимо от локальной кодовой страницы.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Спайк виджетов Telegram: живой sendWidget + правки, либо офлайн-замер бюджета.",
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help="офлайн-замер: запечь 8 метрик x 3 периода и подобрать плотность точек под 3800 сжатых байт (сеть и BOT_TOKEN не нужны)",
    )
    args = parser.parse_args()
    if args.measure:
        measure()
    else:
        asyncio.run(live())


if __name__ == "__main__":
    main()
