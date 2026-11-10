"""Поддержка виджетов Telegram: вызовы Bot API, сборка данных и HTML.

aiogram 3.31 не знает методов виджетов (Bot API 10.4), поэтому HTTP-запросы
идут напрямую через ``bot.session`` (aiohttp).
"""

from __future__ import annotations

import json
import logging
import time
import zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app.charts import LINE_COLOR, ZONE_COLORS, zones
from app.config import Settings
from app.qingping import METRICS, Reading
from app.store import Store
from app.summary import caption
from app.view import CHART_METRICS, PERIODS, SHORT, build_widget_keyboard

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"

PUBLIC_DATA_BUDGET = 1000
MAX_COMPRESSED_BYTES = 3800
MAX_HTML_BYTES = 32 * 1024

# Кандидаты плотности точек на серию: берём первый, влезающий в бюджет.
POINT_CAPS = (480, 360, 288, 240, 192, 160, 128, 96, 64, 48, 32, 24, 16)

# Разрыв серии, если шаг между соседними точками больше медианного во столько раз.
GAP_FACTOR = 3

# Предохранитель: максимум сегментов на серию (оставляются самые длинные).
# Срабатывает только на патологически рваных данных; ограничивает размер HTML.
MAX_SEGMENTS = 32


def build_public_data(reading: Reading, n: int = 0) -> str:
    """Компактный JSON последних значений для public_data виджета.

    Плоский словарь: ``{"ts": <unix>, "n": <счётчик>, "<metric>": <значение>}``.
    Значения округлены по digits из METRICS; порядок метрик — порядок METRICS.
    ``n`` — счётчик изменений: Telegram отклоняет правки с неизменным
    public_data ("message is not modified"), счётчик делает строку уникальной.
    Если JSON не влезает в бюджет, метрики отбрасываются с конца порядка METRICS.
    """
    keys = [k for k in METRICS if k in reading.values]
    while True:
        payload: dict = {"ts": reading.ts, "n": n}
        for key in keys:
            digits = METRICS[key][2]
            value = round(reading.values[key], digits)
            payload[key] = int(value) if digits == 0 else value
        data = json.dumps(payload, separators=(",", ":"))
        if len(data.encode()) <= PUBLIC_DATA_BUDGET or not keys:
            return data
        keys.pop()


async def _api(bot: Bot, method: str, **params):
    url = API_URL.format(token=bot.token, method=method)
    async with bot.session.post(url, data=params) as resp:
        body = await resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('description')}")
    return body["result"]


async def send_widget(
    bot: Bot,
    chat_id: int,
    html: str,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
) -> int:
    """Отправляет виджет в чат, возвращает message_id."""
    params: dict = {
        "chat_id": chat_id,
        "html": html,
        "caption": caption,
        "parse_mode": "HTML",
    }
    if keyboard is not None:
        params["reply_markup"] = keyboard.model_dump_json(exclude_none=True)
    result = await _api(bot, "sendWidget", **params)
    return result["message_id"]


async def edit_widget_data(bot: Bot, chat_id: int, message_id: int, public_data: str) -> None:
    """Обновляет public_data виджета в сообщении."""
    await _api(
        bot,
        "editMessageWidgetData",
        chat_id=chat_id,
        message_id=message_id,
        public_data=public_data,
    )


def compressed_size(html: str) -> int:
    """То, что считает сервер Telegram: len(zlib.compress(html, 9))."""
    return len(zlib.compress(html.encode(), 9))


def _downsample(points: list[tuple[int, float]], max_points: int) -> list[tuple[int, float]]:
    """Равномерное прореживание до max_points, края сохраняются."""
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def _compact(metric: str, value: float) -> float | int:
    digits = METRICS[metric][2]
    rounded = round(value, digits)
    return int(rounded) if digits == 0 else rounded


def _split_segments(points: list[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    """Разбивает серию на сегменты по разрывам > GAP_FACTOR × медианный шаг.

    Кодирование [t0, dt, [values]] предполагает равномерный шаг: без разбиения
    точки после разрыва (перезапуск датчика) рисовались бы не на своих местах.
    """
    if len(points) < 2:
        return [points] if points else []
    steps = sorted(b[0] - a[0] for a, b in zip(points, points[1:]))
    limit = steps[len(steps) // 2] * GAP_FACTOR
    segments = []
    start = 0
    for i in range(1, len(points)):
        if points[i][0] - points[i - 1][0] > limit:
            segments.append(points[start:i])
            start = i
    segments.append(points[start:])
    return segments


def _encode_series(points: list[tuple[int, float]], metric: str, max_points: int) -> list[list]:
    """Компактное кодирование серии: список сегментов [t0, dt, [values]] (спайк, задача 1).

    Сегменты короче двух точек отбрасываются — линию из одной точки не нарисовать.
    """
    segments = []
    for seg in _split_segments(points):
        seg = _downsample(seg, max_points)
        if len(seg) < 2:
            continue
        t0 = seg[0][0]
        dt = max(1, round((seg[-1][0] - t0) / (len(seg) - 1)))
        segments.append([t0, dt, [_compact(metric, v) for _, v in seg]])
    if len(segments) > MAX_SEGMENTS:
        segments.sort(key=lambda s: len(s[2]), reverse=True)
        segments = sorted(segments[:MAX_SEGMENTS], key=lambda s: s[0])
    return segments


def _bake_zones(metric: str) -> list[list]:
    """Зоны метрики как [[lo, hi, color], ...]; края None = бесконечность."""
    inf = float("inf")
    out = []
    for a, b, level in zones(metric):
        out.append([
            None if a == -inf else a,
            None if b == inf else b,
            ZONE_COLORS[level],
        ])
    return out


_CSS = (
    "<style>"
    'body{margin:0;padding:6px;font:13px/1.4 -apple-system,"Segoe UI",sans-serif}'
    ".r{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:2px}"
    ".c{flex:1;min-width:22%;text-align:center;background:rgba(128,128,128,.12);"
    "border-radius:6px;padding:4px 0}"
    ".n{font-size:15px;font-weight:600}.l{font-size:10px;opacity:.6}"
    ".b{display:flex;flex-wrap:wrap;gap:3px;margin:4px 0}"
    ".b button{flex:1;min-width:14%;font-size:11px;padding:3px 1px;border:0;"
    "border-radius:5px;background:rgba(128,128,128,.15);color:inherit;cursor:pointer}"
    ".b button.on{background:#2f80ed;color:#fff}"
    "canvas{width:100%;height:140px;display:block}"
    "</style>"
)

_JS = """<script>
var cur={m:MS[0],h:PS[1]!=null?PS[1]:PS[0]},last="";
function $(i){return document.getElementById(i)}
function fmt(t,lg){var d=new Date((t+OFF*60)*1000);
function p(x){return(x<10?"0":"")+x}
return lg?p(d.getUTCDate())+"."+p(d.getUTCMonth()+1):p(d.getUTCHours())+":"+p(d.getUTCMinutes())}
function draw(){var SG=D[cur.m+":"+cur.h],cv=$("cv");
var w=cv.clientWidth||360,h=140,dpr=window.devicePixelRatio||1;
cv.width=w*dpr;cv.height=h*dpr;
var x=cv.getContext("2d");x.setTransform(dpr,0,0,dpr,0,0);
x.clearRect(0,0,w,h);
x.fillStyle="#888";x.font="10px sans-serif";
if(!SG||!SG.length){x.fillText("нет данных",8,20);return}
var t0=Infinity,t1=-Infinity,lo=Infinity,hi=-Infinity,i,j,sg,V;
for(j=0;j<SG.length;j++){sg=SG[j];V=sg[2];
if(sg[0]<t0)t0=sg[0];
var te=sg[0]+sg[1]*(V.length-1);if(te>t1)t1=te;
for(i=0;i<V.length;i++){if(V[i]<lo)lo=V[i];if(V[i]>hi)hi=V[i]}}
var pad=(hi-lo)*0.15||1;lo-=pad;hi+=pad;
var L=30,B=14,iw=w-L-4,ih=h-B-6;
function X(t){return L+(t-t0)/((t1-t0)||1)*iw}
function Y(v){return 4+(hi-v)/(hi-lo)*ih}
var zs=Z[cur.m]||[];
for(i=0;i<zs.length;i++){var a=Math.max(zs[i][0]==null?lo:zs[i][0],lo),
b=Math.min(zs[i][1]==null?hi:zs[i][1],hi);
if(a<b){x.fillStyle=zs[i][2];x.globalAlpha=0.12;
x.fillRect(L,Y(b),iw,Y(a)-Y(b));x.globalAlpha=1}}
x.strokeStyle=LC;x.lineWidth=1.5;
for(j=0;j<SG.length;j++){sg=SG[j];V=sg[2];x.beginPath();
for(i=0;i<V.length;i++){var px=X(sg[0]+sg[1]*i),py=Y(V[i]);
i?x.lineTo(px,py):x.moveTo(px,py)}
x.stroke()}
var lg=(t1-t0)>172800;
for(i=0;i<=3;i++){var t=t0+(t1-t0)*i/3,s2=fmt(t,lg),px=X(t);
x.fillText(s2,Math.min(Math.max(px-13,0),w-28),h-2)}
x.fillText(""+Math.round(hi*10)/10,2,10);
x.fillText(""+Math.round(lo*10)/10,2,h-B-2)}
function mark(){var i;
for(i=0;i<MS.length;i++)$("m_"+MS[i]).className=MS[i]==cur.m?"on":"";
for(i=0;i<PS.length;i++)$("p_"+PS[i]).className=PS[i]==cur.h?"on":""}
function buttons(){var i,b,mb=$("mb"),pb=$("pb");
for(i=0;i<MS.length;i++){(function(m){b=document.createElement("button");
b.textContent=LB[m];b.id="m_"+m;
b.onclick=function(){cur.m=m;mark();draw()};mb.appendChild(b)})(MS[i])}
for(i=0;i<PS.length;i++){(function(h){b=document.createElement("button");
b.textContent=PL[h];b.id="p_"+h;
b.onclick=function(){cur.h=h;mark();draw()};pb.appendChild(b)})(PS[i])}
mark()}
function tick(){try{var p=window.TelegramWidget&&TelegramWidget.publicData;
if(p&&p!==last){last=p;var d=JSON.parse(p);
for(var i=0;i<MS.length;i++){var v=d[MS[i]];
if(v!=null)$("v_"+MS[i]).textContent=v}}}catch(e){}}
function theme(){try{var tp=window.TelegramWidget&&TelegramWidget.themeParams;
if(tp){if(tp.bg_color)document.body.style.background=tp.bg_color;
if(tp.text_color)document.body.style.color=tp.text_color}}catch(e){}}
theme();buttons();draw();setInterval(tick,2000);tick();
</script>"""


def _render_html(
    settings: Settings,
    reading: Reading,
    metrics: list[str],
    data: dict[str, list],
    now: float,
) -> str:
    tz = ZoneInfo(settings.tz)
    off = int((datetime.fromtimestamp(now, tz).utcoffset() or timedelta(0)).total_seconds() // 60)
    zones = {m: _bake_zones(m) for m in metrics}
    cells = "".join(
        f'<div class="c"><div class="n" id="v_{m}">{_compact(m, reading.values[m])}</div>'
        f'<div class="l">{SHORT[m]} {METRICS[m][1]}</div></div>'
        for m in metrics
    )
    dump = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False)
    head = (
        f"var D={dump(data)},Z={dump(zones)},"
        f"LB={dump({m: SHORT[m] for m in metrics})},"
        f"MS={dump(metrics)},PS={dump(list(PERIODS))},"
        f"PL={dump({str(h): label for h, label in PERIODS.items()})},"
        f'OFF={off},TZ={dump(settings.tz)},LC="{LINE_COLOR}";'
    )
    return (
        '<!doctype html><meta charset="utf-8">'
        + _CSS
        + f'<div class="r">{cells}</div><canvas id="cv"></canvas>'
        + '<div class="b" id="mb"></div><div class="b" id="pb"></div>'
        + "<script>"
        + head
        + _JS[len("<script>") :]
    )


def build_widget_html(settings: Settings, store: Store, mac: str, now: float) -> str | None:
    """HTML виджета /climate: серии всех отображаемых метрик × PERIODS, запечённые в JS.

    None, если по датчику нет данных. Число точек на серию подбирается так,
    чтобы сжатый размер (zlib-9) укладывался в MAX_COMPRESSED_BYTES.
    """
    reading = store.latest(mac)
    if reading is None:
        return None
    metrics = [m for m in CHART_METRICS if m in reading.values]
    if not metrics:
        return None
    raw: dict[tuple[str, int], list[tuple[int, float]]] = {}
    for hours in PERIODS:
        rows = store.history(mac, int(now) - hours * 3600)
        for m in metrics:
            points = [(r.ts, r.values[m]) for r in rows if m in r.values]
            if len(points) >= 2:
                raw[(m, hours)] = points
    if not raw:
        return None
    html = ""
    for cap in POINT_CAPS:
        data = {
            f"{m}:{hours}": encoded
            for (m, hours), points in raw.items()
            if (encoded := _encode_series(points, m, cap))
        }
        html = _render_html(settings, reading, metrics, data, now)
        if compressed_size(html) <= MAX_COMPRESSED_BYTES and len(html.encode()) <= MAX_HTML_BYTES:
            return html
    return html


def widgets_allowed(settings: Settings, chat_type: str) -> bool:
    """Виджеты только в личке, пока widgets_in_groups выключен."""
    return settings.widgets_enabled and (chat_type == "private" or settings.widgets_in_groups)


async def send_widget_summary(
    bot: Bot,
    settings: Settings,
    store: Store,
    chat_id: int,
    owner: int,
    mac: str | None = None,
) -> int | None:
    """Отправляет виджет-сводку, возвращает message_id. None — вызывающий шлёт PNG.

    None при любом сбое: нет данных, HTML не влез в бюджет даже после
    максимального прореживания, ошибка Bot API.
    """
    now = time.time()
    macs = store.devices()
    if not macs:
        log.warning("Widget not sent to %s: no devices", chat_id)
        return None
    if mac not in macs:
        mac = macs[0]
    reading = store.latest(mac)
    if reading is None:
        log.warning("Widget not sent to %s: no data for %s", chat_id, mac)
        return None
    html = build_widget_html(settings, store, mac, now)
    if html is None:
        log.warning("Widget not sent to %s: no chart data for %s", chat_id, mac)
        return None
    if compressed_size(html) > MAX_COMPRESSED_BYTES:
        log.warning("Widget not sent to %s: html too big (%d compressed)", chat_id, compressed_size(html))
        return None
    keyboard = build_widget_keyboard(settings, macs, mac, owner)
    try:
        message_id = await send_widget(bot, chat_id, html, caption(settings, reading, now), keyboard)
    except Exception as exc:
        log.warning("Widget not sent to %s (%s), falling back to PNG", chat_id, exc)
        return None
    store.add_widget_message(chat_id, message_id, mac, int(now))
    return message_id
