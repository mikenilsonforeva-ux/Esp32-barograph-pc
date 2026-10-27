"""Построение графиков (matplotlib). Функции работают с объектом Figure, поэтому годятся и для GUI, и для PNG."""
import math
from datetime import datetime

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from .timeutil import fmt_ts
from .units import convert_pressure, pressure_label

METRIC_INFO = {
    "pressure": ("Давление", "#1e6fd9"),
    "temperature": ("Температура", "#d9531e"),
    "humidity": ("Влажность", "#1e9e5a"),
}
METRIC_INDEX = {"pressure": 1, "temperature": 2, "humidity": 3}


def new_figure(width=9.0, height=5.5, dpi=100) -> Figure:
    return Figure(figsize=(width, height), dpi=dpi)


def _gap_threshold(ts_list):
    if len(ts_list) < 3:
        return float("inf")
    diffs = sorted(b - a for a, b in zip(ts_list, ts_list[1:]))
    median = diffs[len(diffs) // 2]
    return max(median * 4, 300)


def draw_figure(fig: Figure, rows, metrics, tz, unit="mmHg", title=None):
    """Рисует выбранные параметры (друг под другом, общая ось времени). rows: (ts, p_mmHg, t, h)."""
    fig.clear()
    try:
        fig.set_layout_engine("constrained")
    except Exception:
        pass
    metrics = [m for m in metrics if m in METRIC_INDEX]
    if not rows or not metrics:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "Нет данных за выбранный период", ha="center", va="center",
                transform=ax.transAxes, fontsize=13, color="gray")
        ax.set_axis_off()
        return fig

    ts_list = [r[0] for r in rows]
    gap = _gap_threshold(ts_list)
    times = [datetime.fromtimestamp(t, tz) for t in ts_list]
    axes = fig.subplots(len(metrics), 1, sharex=True, squeeze=False)[:, 0]

    for ax, metric in zip(axes, metrics):
        name, color = METRIC_INFO[metric]
        idx = METRIC_INDEX[metric]
        if metric == "pressure":
            vals = [convert_pressure(r[idx], unit) for r in rows]
            unit_txt = pressure_label(unit)
        else:
            vals = [r[idx] for r in rows]
            unit_txt = "°C" if metric == "temperature" else "%"
        xs, ys = [], []
        for i, (x, v) in enumerate(zip(times, vals)):
            if i and ts_list[i] - ts_list[i - 1] > gap:      # разрыв в данных (устройство было выключено)
                xs.append(x)
                ys.append(math.nan)
            xs.append(x)
            ys.append(math.nan if v is None else v)
        ax.set_ylabel(f"{name}, {unit_txt}")
        ax.grid(True, alpha=0.3)
        valid = [(x, v) for x, v in zip(times, vals) if v is not None]
        if not valid:
            ax.text(0.5, 0.5, "нет данных (датчик не измеряет этот параметр)", ha="center", va="center",
                    transform=ax.transAxes, color="gray")
            continue
        ax.plot(xs, ys, color=color, linewidth=1.3)
        ax.margins(y=0.18)
        lo = min(valid, key=lambda p: p[1])
        hi = max(valid, key=lambda p: p[1])
        for pt, label in ((hi, "макс"), (lo, "мин")):
            ax.plot([pt[0]], [pt[1]], "o", color=color, markersize=4)
            ax.annotate(f"{label} {pt[1]:.1f}", xy=pt, xytext=(0, 9 if label == "макс" else -14),
                        textcoords="offset points", ha="center", fontsize=8, color=color)

    locator = mdates.AutoDateLocator(tz=tz)
    axes[-1].xaxis.set_major_locator(locator)
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        locator, tz=tz,
        formats=["%Y", "%m.%Y", "%d.%m", "%H:%M", "%H:%M", "%H:%M:%S"],
        zero_formats=["", "%Y", "%d.%m", "%d.%m", "%H:%M", "%H:%M"],
        offset_formats=["", "", "%Y", "%d.%m.%Y", "%d.%m.%Y", "%d.%m.%Y %H:%M"]))     # числовые даты без англ. месяцев
    fig.suptitle(title or f"{fmt_ts(ts_list[0], tz, '%d.%m.%Y %H:%M')} — {fmt_ts(ts_list[-1], tz, '%d.%m.%Y %H:%M')}",
                 fontsize=11)
    return fig


def save_png(path, rows, metrics, tz, unit="mmHg", title=None, width=12.0, height=6.5, dpi=130):
    fig = new_figure(width, height, dpi)
    draw_figure(fig, rows, metrics, tz, unit, title)
    fig.savefig(path, dpi=dpi)
    return len(rows)
