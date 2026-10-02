"""Draw a Plan to PNG with matplotlib (Agg, in-process, no browser).

Nothing here touches matplotlib's global rcParams: every text gets explicit
font properties, so other tools in the same Hermes process are unaffected.
The renderer also records which mark stands for which number, so verify.py
can read the drawn geometry and labels back and compare them with the input.
"""

from __future__ import annotations

import math
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

from . import numfmt
from .spec import Plan

DPI = 200
_LOCK = threading.Lock()

# Okabe & Ito (2008) colors, ordered so neighbours differ in lightness as well
# as hue; distinguishable with the common forms of color vision deficiency.
PALETTE = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7", "#F0E442", "#7A7A7A")
SINGLE = "#0072B2"
MUTED = "#BFC8D0"
INK = "#1A1A1A"
INK2 = "#4A4A4A"
GRID = "#E2E2E2"
ZERO = "#333333"
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")

# Sizes in pixels per preset. On mobile every text is >= 30 px on a 1080 px
# canvas: about 11 pt when the image fills a phone screen.
TYPE = {
    "mobile": dict(title=54, subtitle=34, tick=32, label=31, legend=31, axis=31, footer=30, margin=64),
    "square": dict(title=50, subtitle=32, tick=30, label=30, legend=30, axis=30, footer=28, margin=60),
    "wide":   dict(title=46, subtitle=29, tick=26, label=25, legend=25, axis=25, footer=22, margin=64),
}


@dataclass
class Drawing:
    fig: Figure
    ax: Any
    value_axis: str                                   # "x" or "y"
    display_labels: List[str]
    bars: List[Tuple[str, int, Rectangle, float, str]] = field(default_factory=list)
    lines: Dict[str, Tuple[Any, List[Optional[float]]]] = field(default_factory=dict)
    labels: List[Tuple[Any, float, str]] = field(default_factory=list)  # (Text, expected, kind)
    shares: Dict[str, List[float]] = field(default_factory=dict)
    font_family: str = ""
    size: Tuple[int, int] = (0, 0)
    spare_px: float = 0.0          # unused plot height (few rows in a tall canvas)
    percent_dropped: bool = False  # share numbers printed without "%" to fit their segments
    left_title: Any = None
    legend_artists: List[Any] = field(default_factory=list)
    years: List[Optional[int]] = field(default_factory=list)   # line: year of each month label
    hidden_labels: List[str] = field(default_factory=list)     # too narrow to print inside


def _pt(px: float) -> float:
    return px * 72.0 / DPI


class _Type:
    def __init__(self, families: Sequence[str], preset: str):
        self.families = list(families)
        self.sizes = TYPE[preset]

    def fp(self, role: str, weight: str = "normal") -> FontProperties:
        return FontProperties(family=self.families, size=_pt(self.sizes[role]), weight=weight)


def _measure(renderer, text: str, fp: FontProperties) -> float:
    if not text:
        return 0.0
    w, _, _ = renderer.get_text_width_height_descent(text, fp, ismath=False)
    return w


_NO_BREAK_BEFORE = set("、。，．・：；？！）」』】〕ー々ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ%％,.)]")


def _wrap(renderer, text: str, fp: FontProperties, max_px: float) -> List[str]:
    """Greedy wrap that breaks Latin at spaces and Japanese between characters."""
    out: List[str] = []
    for para in str(text).split("\n"):
        tokens: List[str] = []
        buf = ""
        for ch in para:
            wide = unicodedata.east_asian_width(ch) in "WF"
            if wide or ch == " ":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            else:
                buf += ch
        if buf:
            tokens.append(buf)
        line = ""
        for tok in tokens:
            trial = line + tok
            if line and _measure(renderer, trial.rstrip(), fp) > max_px and tok != " " \
                    and tok[0] not in _NO_BREAK_BEFORE:
                out.append(line.rstrip())
                line = tok.lstrip()
            else:
                line = trial
        out.append(line.rstrip())
    return out


def _line_px(fp: FontProperties) -> float:
    return fp.get_size_in_points() * DPI / 72.0 * 1.32


def _contrast_text(hex_color: str) -> str:
    """Black or white, whichever has the higher WCAG contrast on the color."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#000000" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#FFFFFF"


def _with_unit(title: str, unit: str, locale: str) -> str:
    if not unit:
        return title
    nested = any(ch in unit for ch in "()（）")
    if locale == "ja":
        wrapped = f"［{unit}］" if nested else f"（{unit}）"
    else:
        wrapped = f"[{unit}]" if nested else f"({unit})"
    return wrapped if not title else (f"{title}{wrapped}" if locale == "ja" else f"{title} {wrapped}")


def _display_categories(plan: Plan) -> List[str]:
    """Shorter tick labels for monthly series: 1月 … with the year where it changes."""
    if plan.chart_type != "line":
        return list(plan.categories)
    from .spec import _date_keys
    keys = _date_keys(plan.categories)
    if not keys or any(k[1] == 0 for k in keys) or len({k[2] for k in keys}) > 1:
        return list(plan.categories)
    months_en = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    out = []
    for y, m, _d in keys:
        if m > 12:  # quarters were encoded as month*3
            return list(plan.categories)
        out.append(f"{m}月" if plan.locale == "ja" else months_en[m - 1])
    return out


def _years(plan: Plan, labels: List[str]) -> List[Optional[int]]:
    from .spec import _date_keys
    keys = _date_keys(plan.categories) if labels != list(plan.categories) else None
    return [k[0] for k in keys] if keys else [None] * len(labels)


def render(plan: Plan, families: Sequence[str]) -> Drawing:
    """Draw; when a few rows leave the canvas mostly empty, draw again on a shorter canvas
    so the image has no dead space when pasted into a slide or chat."""
    with _LOCK:
        drawing = _render(plan, families, plan.size)
        if drawing.spare_px > 40:
            W, H = plan.size
            shorter = (W, max(int(W * 0.55), int(H - drawing.spare_px)))
            drawing = _render(plan, families, shorter, compact=True)
        return drawing


def _render(plan: Plan, families: Sequence[str], size: Tuple[int, int], compact: bool = False) -> Drawing:
    W, H = size
    fig = Figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor="white")
    canvas = FigureCanvasAgg(fig)
    renderer = canvas.get_renderer()
    t = _Type(families, plan.preset)
    m = t.sizes["margin"]
    content_w = W - 2 * m
    ja = plan.locale == "ja"

    # ---- header (title, subtitle) from the top
    y = m * 0.85
    fp_title = t.fp("title", "bold")
    title_lines = _wrap(renderer, plan.title, fp_title, content_w)
    fig.text(m / W, 1 - y / H, "\n".join(title_lines), fontproperties=fp_title, color=INK,
             ha="left", va="top", linespacing=1.22)
    y += _line_px(fp_title) * len(title_lines) * 0.95
    if plan.subtitle:
        fp_sub = t.fp("subtitle")
        y += t.sizes["subtitle"] * 0.25
        sub_lines = _wrap(renderer, plan.subtitle, fp_sub, content_w)
        fig.text(m / W, 1 - y / H, "\n".join(sub_lines), fontproperties=fp_sub, color=INK2,
                 ha="left", va="top", linespacing=1.3)
        y += _line_px(fp_sub) * len(sub_lines)
    y += t.sizes["subtitle"] * 0.9

    # ---- legend (multi-series), drawn as a row of swatches
    needs_legend = len(plan.series) > 1 and not (plan.chart_type == "line" and len(plan.series) <= 4)
    legend_artists: List[Any] = []
    if needs_legend:
        y += _legend(fig, renderer, t, plan, m, y, content_w, W, H, legend_artists)
        y += t.sizes["legend"] * 0.5

    # ---- footer (notes, source) from the bottom
    fp_foot = t.fp("footer")
    src = plan.source
    if not src.startswith(("出典", "Source", "資料")):
        src = ("出典：" if ja else "Source: ") + src
    foot_lines = _wrap(renderer, src, fp_foot, content_w)
    numbered = len(plan.notes) > 1
    for k, note in enumerate(plan.notes, 1):
        if ja:
            prefix = f"注{k}：" if numbered else "注："
        else:
            prefix = f"Note {k}: " if numbered else "Note: "
        foot_lines += _wrap(renderer, prefix + note, fp_foot, content_w)
    foot_h = _line_px(fp_foot) * len(foot_lines)
    bottom = H - m * 0.7
    fig.text(m / W, 1 - bottom / H, "\n".join(foot_lines), fontproperties=fp_foot, color=INK2,
             ha="left", va="bottom", linespacing=1.32)
    plot_bottom_px = bottom - foot_h - t.sizes["footer"] * 1.2

    # ---- plot area
    area = (m, y, W - m, plot_bottom_px)  # left, top, right, bottom in px from top-left
    ax = fig.add_axes(_rect(area, W, H))
    display = _display_categories(plan)
    drawing = Drawing(fig=fig, ax=ax, value_axis="y", display_labels=display,
                      font_family=families[0] if families else "", years=_years(plan, display),
                      size=(W, H))
    drawing._compact = compact
    if plan.chart_type == "line":
        _draw_line(ax, plan, t, drawing)
    elif plan.chart_type == "share_bar":
        _draw_stack(ax, plan, t, drawing, share=True)
    elif plan.chart_type == "stacked_bar":
        _draw_stack(ax, plan, t, drawing, share=False)
    else:
        _draw_bars(ax, plan, t, drawing)
    drawing.legend_artists = legend_artists
    _style_axes(ax, plan, t, drawing)
    _fit(fig, ax, renderer, area, plan, drawing, W, H)
    return drawing


def _rect(area, W, H):
    left, top, right, bottom = area
    return [left / W, 1 - bottom / H, (right - left) / W, (bottom - top) / H]


def _legend(fig, renderer, t: _Type, plan: Plan, m, y, content_w, W, H, artists: List[Any]) -> float:
    fp = t.fp("legend")
    size = t.sizes["legend"]
    sw, gap, pad = size * 0.85, size * 0.35, size * 1.1
    x, line = m, 0
    row_h = _line_px(fp)
    for i, name in enumerate(plan.series):
        wtxt = _measure(renderer, name, fp)
        item_w = sw + gap + wtxt
        if x > m and x + item_w > m + content_w:
            x, line = m, line + 1
        top = y + line * row_h
        cy = top + row_h / 2
        color = PALETTE[i % len(PALETTE)]
        if plan.chart_type == "line":
            swatch = _line_swatch(fig, x, cy, sw, color, MARKERS[i % len(MARKERS)], W, H)
        else:
            swatch = Rectangle(((x) / W, 1 - (cy + sw / 2) / H), sw / W, sw / H,
                               transform=fig.transFigure, facecolor=color, edgecolor="white")
        artists.append(fig.add_artist(swatch))
        artists.append(fig.text((x + sw + gap) / W, 1 - cy / H, name, fontproperties=fp, color=INK,
                                ha="left", va="center_baseline"))
        x += item_w + pad
    return row_h * (line + 1)


def _line_swatch(fig, x, cy, sw, color, marker, W, H):
    from matplotlib.lines import Line2D
    return Line2D([x / W, (x + sw) / W], [1 - cy / H, 1 - cy / H], transform=fig.transFigure,
                  color=color, linewidth=2.6, marker=marker, markevery=[1], markersize=6)


# ------------------------------------------------------------------ bar charts

def _label_peak(plan: Plan) -> float:
    nums = [abs(v) for v in plan.numbers()]
    if plan.chart_type == "stacked_bar":
        nums += [abs(sum(plan.values[s][i] or 0 for s in plan.series)) for i in range(len(plan.categories))]
    return max(nums, default=0.0)


def _value_label(plan: Plan, v: float) -> str:
    """Every label on one chart shares the scale and decimals of the largest value.

    Labels scaled to 万/億 carry a short unit ("1,405万人"), so they read on their own.
    """
    text = numfmt.format_values([v, _label_peak(plan)], plan.number_style, plan.decimals)[0]
    unit = plan.unit.strip()
    if (plan.number_style == "ja" and text[-1:] in "万億兆" and 0 < len(unit) <= 3
            and not any(ch in unit for ch in "()（）") and not numfmt.unit_has_multiplier(unit)):
        text += unit
    return text


def _pct(v: float, decimals: int) -> str:
    return numfmt.format_values([v], "plain", decimals)[0] + "%"


def _draw_bars(ax, plan: Plan, t: _Type, d: Drawing) -> None:
    n, k = len(plan.categories), len(plan.series)
    band = 0.78
    width = band / k
    horizontal = plan.orientation == "horizontal"
    d.value_axis = "x" if horizontal else "y"
    show_labels = k == 1 or (k <= 3 and n * k <= 24)
    fp = t.fp("label")
    for j, s in enumerate(plan.series):
        for i, v in enumerate(plan.values[s]):
            if v is None:
                continue
            pos = i - band / 2 + width * (j + 0.5)
            if k == 1:
                color = (SINGLE if (not plan.highlight or plan.categories[i] in plan.highlight) else MUTED)
            else:
                color = PALETTE[j % len(PALETTE)]
            if horizontal:
                patch = ax.barh(pos, v, height=width * 0.92, color=color, edgecolor="white",
                                linewidth=0.6)[0]
            else:
                patch = ax.bar(pos, v, width=width * 0.92, color=color, edgecolor="white",
                               linewidth=0.6)[0]
            d.bars.append((s, i, patch, v, "bar"))
            if show_labels:
                text = _value_label(plan, v)
                if horizontal:
                    lbl = ax.annotate(text, (v, pos), xytext=(8 if v >= 0 else -8, 0),
                                      textcoords="offset points", ha="left" if v >= 0 else "right",
                                      va="center", fontproperties=fp, color=INK)
                else:
                    lbl = ax.annotate(text, (pos, v), xytext=(0, 6 if v >= 0 else -6),
                                      textcoords="offset points", ha="center",
                                      va="bottom" if v >= 0 else "top", fontproperties=fp, color=INK)
                d.labels.append((lbl, v, "value"))
    if horizontal:
        ax.set_ylim(n - 0.5, -0.5)
    else:
        ax.set_xlim(-0.5, n - 0.5)


def _draw_stack(ax, plan: Plan, t: _Type, d: Drawing, share: bool) -> None:
    n = len(plan.categories)
    horizontal = plan.orientation == "horizontal"
    d.value_axis = "x" if horizontal else "y"
    fp = t.fp("label")
    fp_in = FontProperties(family=t.families, size=_pt(max(30, t.sizes["label"] * 0.97)
                                                      if plan.preset != "wide" else t.sizes["label"]))
    totals = [sum(plan.values[s][i] or 0.0 for s in plan.series) for i in range(n)]
    thickness = 0.52 if share else 0.62  # thinner bands leave room for numbers between them
    base = [0.0] * n
    for j, s in enumerate(plan.series):
        color = PALETTE[j % len(PALETTE)]
        shares = []
        for i in range(n):
            raw = plan.values[s][i] or 0.0
            v = raw / totals[i] * 100.0 if share else raw
            shares.append(v)
            if horizontal:
                patch = ax.barh(i, v, left=base[i], height=thickness, color=color, edgecolor="white",
                                linewidth=1.2)[0]
            else:
                patch = ax.bar(i, v, bottom=base[i], width=thickness, color=color, edgecolor="white",
                               linewidth=1.2)[0]
            d.bars.append((s, i, patch, v, "share" if share else "stack"))
            if v > 0:
                text = (_pct(v, 1) if share else _value_label(plan, v))
                center = base[i] + v / 2
                xy = (center, i) if horizontal else (i, center)
                lbl = ax.text(*xy, text, ha="center", va="center", fontproperties=fp_in,
                              color=_contrast_text(color))
                lbl._segment = patch
                lbl._where = f"{plan.categories[i]} / {s}"
                d.labels.append((lbl, v, "share" if share else "value"))
            base[i] += v
        if share:
            d.shares[s] = shares
    if not share:
        fp_total = t.fp("label", "bold")
        for i in range(n):
            text = _value_label(plan, totals[i])
            if horizontal:
                lbl = ax.annotate(text, (totals[i], i), xytext=(8, 0), textcoords="offset points",
                                  ha="left", va="center", fontproperties=fp_total, color=INK)
            else:
                lbl = ax.annotate(text, (i, totals[i]), xytext=(0, 6), textcoords="offset points",
                                  ha="center", va="bottom", fontproperties=fp_total, color=INK)
            d.labels.append((lbl, totals[i], "value"))
    if horizontal:
        ax.set_ylim(n - 0.5, -0.5)
        if share:
            ax.set_xlim(0, 100)
    else:
        ax.set_xlim(-0.5, n - 0.5)
        if share:
            ax.set_ylim(0, 100)


# ------------------------------------------------------------------ line chart

def _draw_line(ax, plan: Plan, t: _Type, d: Drawing) -> None:
    n = len(plan.categories)
    xs = list(range(n))
    fp = t.fp("label")
    show_markers = n <= 24
    single = len(plan.series) == 1
    for j, s in enumerate(plan.series):
        color = SINGLE if single else PALETTE[j % len(PALETTE)]
        ys = [math.nan if v is None else v for v in plan.values[s]]
        (line,) = ax.plot(xs, ys, color=color, linewidth=3.2 if single else 2.6,
                          marker=MARKERS[j % len(MARKERS)] if show_markers else None,
                          markersize=7 if single else 6, markerfacecolor=color,
                          markeredgecolor="white", markeredgewidth=1.2, solid_capstyle="round",
                          zorder=3)
        d.lines[s] = (line, list(plan.values[s]))
    if single:
        s = plan.series[0]
        vals = plan.values[s]
        present = [i for i, v in enumerate(vals) if v is not None]
        picks = []
        if present:
            hi = max(present, key=lambda i: vals[i])
            lo = min(present, key=lambda i: vals[i])
            picks = sorted({present[0], present[-1], hi, lo})
        for i in picks:
            v = vals[i]
            above = not (i == lo and i != hi)
            lbl = ax.annotate(_value_label(plan, v), (i, v), xytext=(0, 12 if above else -12),
                              textcoords="offset points", ha="center",
                              va="bottom" if above else "top", fontproperties=fp, color=INK, zorder=4)
            d.labels.append((lbl, v, "value"))
    elif len(plan.series) <= 4:
        # Direct labels at the line ends instead of a legend (no color matching needed).
        ends = []
        for j, s in enumerate(plan.series):
            vals = plan.values[s]
            last = max((i for i, v in enumerate(vals) if v is not None), default=None)
            if last is not None:
                ends.append((vals[last], last, j, s))
        for v, i, j, s in ends:
            lbl = ax.annotate(f"{s}  {_value_label(plan, v)}", (i, v), xytext=(10, 0),
                              textcoords="offset points", ha="left", va="center", fontproperties=fp,
                              color=PALETTE[j % len(PALETTE)] if PALETTE[j % len(PALETTE)] not in
                              ("#F0E442", "#E69F00", "#56B4E9") else INK, zorder=4)
            d.labels.append((lbl, v, "series_end"))
    ax.set_xlim(-0.4, n - 1 + 0.4)


# ------------------------------------------------------------------ axes and fit

def _style_axes(ax, plan: Plan, t: _Type, d: Drawing) -> None:
    fp_tick = t.fp("tick")
    fp_axis = t.fp("axis")
    ja = plan.locale == "ja"
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    value_title = _with_unit(plan.y_title, "%" if plan.chart_type == "share_bar" else plan.unit, plan.locale)
    if plan.chart_type == "share_bar":
        value_title = "構成比（%）" if ja else "Share (%)"
    cat_title = plan.x_title
    horizontal = d.value_axis == "x"
    cat_axis = ax.yaxis if horizontal else ax.xaxis
    val_axis = ax.xaxis if horizontal else ax.yaxis

    # category ticks
    n = len(plan.categories)
    positions = list(range(n))
    labels = list(d.display_labels)
    if plan.chart_type == "line":
        positions, labels = _line_ticks(ax, plan, t, d)
    cat_axis.set_ticks(positions)
    cat_axis.set_ticklabels(labels, fontproperties=fp_tick, color=INK)
    ax.tick_params(axis="y" if horizontal else "x", length=0, pad=8)
    if horizontal:
        ax.spines["left"].set_visible(False)
    else:
        ax.spines["bottom"].set_color("#9A9A9A")

    # value range: bars always include zero; lines include zero unless y_zero is false
    lo, hi = (ax.get_xlim() if horizontal else ax.get_ylim())
    nums = plan.numbers() if plan.chart_type != "share_bar" else [0, 100]
    if plan.chart_type == "stacked_bar":
        nums = nums + [sum(plan.values[s][i] or 0 for s in plan.series) for i in range(n)]
    dmin, dmax = min(nums), max(nums)
    if plan.chart_type == "share_bar":
        lo, hi = 0.0, 100.0
    elif plan.chart_type == "line" and not plan.y_zero:
        span = (dmax - dmin) or abs(dmax) or 1.0
        lo, hi = dmin - span * 0.12, dmax + span * 0.12
    else:
        lo, hi = min(0.0, dmin), max(0.0, dmax)
        span = (hi - lo) or 1.0
        # vertical marks carry their labels above the top value: leave room for them
        room = 0.04 if horizontal else 0.12
        hi = hi + span * room if hi > 0 else hi
        lo = lo - span * room if lo < 0 else lo
    locator = MaxNLocator(nbins=5 if plan.preset != "wide" else 6, steps=[1, 2, 2.5, 5, 10])
    ticks = [tk for tk in locator.tick_values(lo, hi) if lo - 1e-9 <= tk <= hi + 1e-9]
    if plan.chart_type != "line" or plan.y_zero:
        lo = min(lo, ticks[0]) if ticks else lo
        hi = max(hi, ticks[-1]) if ticks else hi
        if lo > 0:
            lo = 0.0
    (ax.set_xlim if horizontal else ax.set_ylim)(lo, hi)
    tick_labels = (["0%", "20%", "40%", "60%", "80%", "100%"] if plan.chart_type == "share_bar"
                   else numfmt.format_ticks(ticks, plan.number_style))
    if plan.chart_type == "share_bar":
        ticks = [0, 20, 40, 60, 80, 100]
    val_axis.set_ticks(ticks)
    val_axis.set_ticklabels(tick_labels, fontproperties=fp_tick, color=INK2)
    ax.tick_params(axis="x" if horizontal else "y", length=0, pad=6)
    ax.grid(True, axis="x" if horizontal else "y", color=GRID, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    if horizontal:
        ax.spines["bottom"].set_visible(False)
        ax.axvline(0, color=ZERO, linewidth=1.4, zorder=2)
    else:
        ax.spines["left"].set_visible(False)
        if lo <= 0 <= hi:
            ax.axhline(0, color=ZERO, linewidth=1.4, zorder=2)

    # axis titles: the left axis gets its title above the plot, the bottom axis below it
    left_title, bottom_title = (cat_title, value_title) if horizontal else (value_title, cat_title)
    ax.set_xlabel(bottom_title, fontproperties=fp_axis, color=INK2, labelpad=10)
    d.left_title = ax.text(0, 1, left_title, transform=ax.transAxes, fontproperties=fp_axis,
                           color=INK2, ha="left", va="bottom")


def _line_ticks(ax, plan: Plan, t: _Type, d: Drawing):
    """Date labels that fit without touching, always including the first and last period.

    Monthly series prefer quarter starts (4月, 7月, 10月, 1月) when a step of three fits.
    The year goes on the first label shown and wherever it changes ("4月 / 2025年").
    """
    n = len(plan.categories)
    renderer = ax.figure.canvas.get_renderer()
    fp = t.fp("tick")
    # Years sit on a second line under only a few labels, so spacing follows the month names.
    widest = max((_measure(renderer, p, fp) for p in d.display_labels), default=1.0)
    axis_px = ax.get_window_extent(renderer).width * 0.9
    slots = max(2, int(axis_px / (widest + t.sizes["tick"] * 0.9)))
    min_step = max(1, math.ceil((n - 1) / max(1, slots - 1)))
    monthly = any(y is not None for y in d.years)
    step = next((s for s in (3, 6, 12) if s >= min_step), min_step) if monthly and min_step > 1 else min_step
    keep = list(range(0, n, step))
    if keep[-1] != n - 1:
        if (n - 1) - keep[-1] < step * 0.6 and len(keep) > 1:
            keep.pop()  # too close to the last period: the last one wins
        keep.append(n - 1)
    labels, last_year = [], None
    for i in keep:
        text = d.display_labels[i]
        y = d.years[i] if i < len(d.years) else None
        if y is not None and y != last_year:
            text += f"\n{y}年" if plan.locale == "ja" else f"\n{y}"
            last_year = y
        elif monthly:
            text += "\n "  # same line count everywhere keeps the month names level
        d.display_labels[i] = text
        labels.append(text)
    return keep, labels


def _fit(fig, ax, renderer, area, plan: Plan, d: Drawing, W, H) -> None:
    """Shrink the axes until labels, ticks and titles sit inside the plot area."""
    left, top, right, bottom = area
    for _ in range(5):
        _place_left_title(fig, ax, renderer, plan, d)
        axb = ax.get_window_extent(renderer)
        tight = ax.get_tightbbox(renderer)
        for lbl, _v, _k in d.labels:
            tight = _union(tight, lbl.get_window_extent(renderer))
        tight = _union(tight, d.left_title.get_window_extent(renderer))
        # convert to top-left pixel space
        t_left, t_right = tight.x0, tight.x1
        t_top, t_bottom = H - tight.y1, H - tight.y0
        dl = max(0.0, left - t_left)
        dr = max(0.0, t_right - right)
        dt = max(0.0, top - t_top)
        db = max(0.0, t_bottom - bottom)
        if max(dl, dr, dt, db) < 0.5:
            break
        cur_left = axb.x0 + dl
        cur_right = axb.x1 - dr
        cur_top = (H - axb.y1) + dt
        cur_bottom = (H - axb.y0) - db
        ax.set_position([cur_left / W, 1 - cur_bottom / H, (cur_right - cur_left) / W,
                         (cur_bottom - cur_top) / H])
    if _make_room_for_labels(fig, ax, renderer, d):
        _fit(fig, ax, renderer, area, plan, d, W, H)
        return
    _shrink_rows(fig, ax, renderer, plan, d, W, H)
    _spread_end_labels(fig, ax, renderer, d)
    _place_left_title(fig, ax, renderer, plan, d)
    _drop_overflowing_labels(fig, ax, renderer, d)


def _make_room_for_labels(fig, ax, renderer, d: Drawing) -> bool:
    """Widen the value range where an end-of-bar label spills past the plot edge
    (a negative bar's label would otherwise sit on the category names)."""
    tries = getattr(d, "_room_tries", 0)
    if tries >= 3:  # widening shrinks the plot a little, so it can take a few rounds
        return False
    d._room_tries = tries + 1
    fig.canvas.draw()
    axb = ax.get_window_extent(renderer)
    horizontal = d.value_axis == "x"
    lo, hi = ax.get_xlim() if horizontal else ax.get_ylim()
    span_px = axb.width if horizontal else axb.height
    per_px = (hi - lo) / span_px
    need_lo = need_hi = 0.0
    for lbl, _v, kind in d.labels:
        if getattr(lbl, "_segment", None) is not None or kind == "series_end":
            continue
        box = lbl.get_window_extent(renderer)
        a, b = (box.x0, box.x1) if horizontal else (box.y0, box.y1)
        start, end = (axb.x0, axb.x1) if horizontal else (axb.y0, axb.y1)
        pad = 14  # px of air between a label and the category names / plot edge
        need_lo = max(need_lo, (start + pad - a) * per_px)
        need_hi = max(need_hi, (b + pad - end) * per_px)
    if need_lo <= 0 and need_hi <= 0:
        return False
    lo -= need_lo * 1.08 if need_lo > 0 else 0
    hi += need_hi * 1.08 if need_hi > 0 else 0
    (ax.set_xlim if horizontal else ax.set_ylim)(lo, hi)
    return True


def _spread_end_labels(fig, ax, renderer, d: Drawing) -> None:
    """Push line-end labels apart vertically so close values do not overprint."""
    ends = [lbl for lbl, _v, kind in d.labels if kind == "series_end"]
    if len(ends) < 2:
        return
    fig.canvas.draw()
    boxes = sorted(((lbl.get_window_extent(renderer), lbl) for lbl in ends), key=lambda bl: bl[0].y0)
    gap = max(b.height for b, _ in boxes) * 1.08
    placed = []
    for box, lbl in boxes:
        y = (box.y0 + box.y1) / 2
        if placed and y - placed[-1] < gap:
            shift_px = placed[-1] + gap - y
            dx, dy = lbl.xyann
            lbl.xyann = (dx, dy + shift_px * 72.0 / fig.dpi)
            y += shift_px
        placed.append(y)


def _place_left_title(fig, ax, renderer, plan: Plan, d: Drawing) -> None:
    """Put the left axis title above the plot, flush with the outermost tick label."""
    fig.canvas.draw()
    axb = ax.get_window_extent(renderer)
    extents = [lbl.get_window_extent(renderer) for lbl in ax.get_yticklabels() if lbl.get_text()]
    tick_left = min((e.x0 for e in extents), default=axb.x0)
    gap = TYPE[plan.preset]["axis"] * 0.6
    d.left_title.set_position(((tick_left - axb.x0) / axb.width, 1 + gap / axb.height))
    fig.canvas.draw()


def _shrink_rows(fig, ax, renderer, plan: Plan, d: Drawing, W, H) -> None:
    """Few horizontal rows in a tall canvas: cap the row height and center the plot."""
    if d.value_axis != "x":
        return
    n = len(plan.categories)
    pos = ax.get_position()
    height_px = pos.height * H
    per_row = TYPE[plan.preset]["tick"] * (5.0 if plan.chart_type == "share_bar" else 3.0)
    want = per_row * n
    if want >= height_px:
        return
    spare = height_px - want
    if not getattr(d, "_compact", False):
        d.spare_px = spare
    down = spare * 0.45  # pixels the plot (and its legend) move down
    ax.set_position([pos.x0, pos.y0 + (spare - down) / H, pos.width, want / H])
    for artist in d.legend_artists:
        _shift(artist, -down / H)
    fig.canvas.draw()


def _shift(artist, dy: float) -> None:
    from matplotlib.lines import Line2D
    from matplotlib.text import Text
    if isinstance(artist, Text):
        x, y = artist.get_position()
        artist.set_position((x, y + dy))
    elif isinstance(artist, Rectangle):
        artist.set_y(artist.get_y() + dy)
    elif isinstance(artist, Line2D):
        artist.set_ydata([v + dy for v in artist.get_ydata()])


def _drop_overflowing_labels(fig, ax, renderer, d: Drawing) -> None:
    """Labels inside stacked segments must fit their segment.

    Shares step down "53.7%" -> "54%" -> "54" for the whole chart (one style
    per chart); numbers that fit at no step do not decide the style. A number
    that still does not fit goes just below its segment (or above it) with a
    leader line; only when neither spot is free is it hidden, and tools.py
    lists it with its value in a footnote.
    """
    fig.canvas.draw()
    pad = 8

    def fits(lbl) -> bool:
        box = lbl.get_window_extent(renderer)
        seg = lbl._segment.get_window_extent(renderer)
        return box.width + pad * 2 <= seg.width and box.height + pad <= seg.height

    inside = [(lbl, v, k) for lbl, v, k in d.labels if getattr(lbl, "_segment", None) is not None]
    if not inside:
        return
    shares = [(lbl, v) for lbl, v, k in inside if k == "share"]
    # One style per chart: "53.7%" -> "54%" -> "54" (the axis title and a note carry the %).
    # Numbers that fit at no step go beside the band anyway, so they do not decide the style.
    styles = (lambda v: _pct(v, 1), lambda v: _pct(v, 0), lambda v: _pct(v, 0)[:-1])
    for lbl, v in shares:
        lbl.set_text(styles[-1](v))
    deciding = [(lbl, v) for lbl, v in shares if fits(lbl)]
    for style in styles:
        for lbl, v in shares:
            lbl.set_text(style(v))
        if all(fits(lbl) for lbl, _v in deciding):
            break
    d.percent_dropped = bool(shares) and not shares[0][0].get_text().endswith("%")
    misfits = [lbl for lbl, _v, _k in inside if not fits(lbl)]
    if not misfits:
        return
    taken = [lbl.get_window_extent(renderer) for lbl, _v, _k in d.labels if lbl not in misfits]
    taken += [p.get_window_extent(renderer) for _s, _i, p, _v, _k in d.bars]
    # Everything else printed near the plot: ticks, axis titles, legend.
    texts = list(ax.get_xticklabels()) + list(ax.get_yticklabels()) + [ax.xaxis.label, d.left_title]
    texts += [a for a in d.legend_artists if hasattr(a, "get_text")]
    taken += [t.get_window_extent(renderer) for t in texts if t is not None and t.get_text().strip()]
    frame = ax.get_window_extent(renderer)
    hidden = set()
    for lbl in misfits:
        if not _place_outside(lbl, d, renderer, taken, frame):
            lbl.set_visible(False)
            hidden.add(id(lbl))
            d.hidden_labels.append(f"{lbl._where}: {lbl.get_text()}")
    d.labels = [(lbl, v, k) for lbl, v, k in d.labels if id(lbl) not in hidden]


def _place_outside(lbl, d: Drawing, renderer, taken, frame) -> bool:
    """Try below, then above, the segment (horizontal bands only); keep the first free spot.

    A short leader line ties the number to its segment, so it cannot be read as
    belonging to the neighbouring band.
    """
    if d.value_axis != "x":
        return False
    ax = d.ax
    patch = lbl._segment
    cx = patch.get_x() + patch.get_width() / 2
    y_top, y_bottom = patch.get_y(), patch.get_y() + patch.get_height()  # y axis runs downward
    gap = 0.11  # in row units: room for the leader line
    for edge, y, va in ((y_bottom, y_bottom + gap, "top"), (y_top, y_top - gap, "bottom")):
        lbl.set_position((cx, y))
        lbl.set_verticalalignment(va)
        lbl.set_color(INK)
        box = lbl.get_window_extent(renderer).padded(3)
        # Stay within the plot's width; above or below it is fine if nothing printed is there.
        within = frame.x0 <= box.x0 and box.x1 <= frame.x1
        if within and not any(box.overlaps(other) for other in taken):
            taken.append(box)
            ax.plot([cx, cx], [edge, y], color=INK2, linewidth=1.2, solid_capstyle="butt", zorder=3)
            return True
    return False

def _union(a, b):
    from matplotlib.transforms import Bbox
    return Bbox.union([a, b])
