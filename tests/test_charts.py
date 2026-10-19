import struct
from zoneinfo import ZoneInfo

from app.charts import render_chart

TZ = ZoneInfo("Europe/Moscow")


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_too_few_points():
    assert render_chart([], "co2", TZ) is None
    assert render_chart([(1, 500.0)], "co2", TZ) is None


def test_chart_png_for_limit_metric():
    points = [(1_700_000_000 + i * 600, 500.0 + i * 10) for i in range(100)]
    data = render_chart(points, "co2", TZ)
    assert png_size(data) == (960, 480)
    assert len(data) > 5000


def test_chart_for_band_metric_and_long_period():
    points = [(1_700_000_000 + i * 3600, 20.0 + (i % 10) / 2) for i in range(24 * 7)]
    assert png_size(render_chart(points, "temperature", TZ)) == (960, 480)


def test_chart_flat_line_and_metric_without_zones():
    points = [(1_700_000_000, 90.0), (1_700_000_600, 90.0)]
    assert png_size(render_chart(points, "battery", TZ)) == (960, 480)
