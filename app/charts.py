"""Draw a PNG chart for one metric. Uses the Figure API, so it is safe in threads."""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from .qingping import BANDS, LIMITS, METRICS

ZONE_COLORS = {"good": "#22b07d", "fair": "#f2a516", "bad": "#ec4c47"}
LINE_COLOR = "#2f80ed"
INF = float("inf")


def _zones(metric: str) -> list[tuple[float, float, str]]:
    if metric in LIMITS:
        good, fair = LIMITS[metric]
        return [(-INF, good, "good"), (good, fair, "fair"), (fair, INF, "bad")]
    if metric in BANDS:
        (g_lo, g_hi), (f_lo, f_hi) = BANDS[metric]
        return [
            (-INF, f_lo, "bad"),
            (f_lo, g_lo, "fair"),
            (g_lo, g_hi, "good"),
            (g_hi, f_hi, "fair"),
            (f_hi, INF, "bad"),
        ]
    return []


def render_chart(points: list[tuple[int, float]], metric: str, tz: ZoneInfo) -> bytes | None:
    if len(points) < 2:
        return None
    times = [datetime.fromtimestamp(ts, tz) for ts, _ in points]
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.15 or 1.0
    y0, y1 = lo - pad, hi + pad

    fig = Figure(figsize=(8, 4), dpi=120)
    ax = fig.subplots()
    for a, b, level in _zones(metric):
        a, b = max(a, y0), min(b, y1)
        if a < b:
            ax.axhspan(a, b, color=ZONE_COLORS[level], alpha=0.12, linewidth=0)
    ax.plot(times, values, color=LINE_COLOR, linewidth=2)
    ax.set_ylim(y0, y1)
    ax.set_xlim(times[0], times[-1])

    title, unit, _ = METRICS[metric]
    ax.set_title(f"{title}, {unit}" if unit else title, loc="left", fontsize=13)
    long_period = (points[-1][0] - points[0][0]) > 2 * 86400
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m" if long_period else "%H:%M", tz=tz))
    ax.grid(alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return buf.getvalue()
