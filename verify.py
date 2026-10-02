"""Read the finished figure back and compare it with the input numbers.

Checks, all against the drawn objects rather than the code that drew them:

* every bar/segment length and every line point equals its input value
  (shares are recomputed here from the raw values, independently);
* each mark sits on its own category, and stacked parts start where the
  previous one ended;
* every printed number (data labels, axis ticks) reads back to the value it
  stands for, within the rounding it shows;
* bars start at zero, share bands add up to 100%;
* category labels on the axis are the input labels, in order.

A chart that fails any check is not returned.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from . import numfmt
from .render import Drawing
from .spec import Plan

REL = 1e-9
MAX_ROWS = 60


def _close(a: float, b: float, tol: float = 0.0) -> bool:
    return abs(a - b) <= max(tol, REL * max(1.0, abs(a), abs(b)))


_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _expected_category_names(plan: Plan) -> List[set]:
    """Acceptable printed names per category: the input label, or its month for dated series."""
    from .spec import _date_keys
    keys = _date_keys(plan.categories) if plan.chart_type == "line" else None
    out = []
    for i, cat in enumerate(plan.categories):
        names = {cat}
        if keys and 1 <= keys[i][1] <= 12:
            names |= {f"{keys[i][1]}月", _MONTHS_EN[keys[i][1] - 1]}
        out.append(names)
    return out


def verify(plan: Plan, d: Drawing) -> Dict[str, Any]:
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []
    horizontal = d.value_axis == "x"
    n = len(plan.categories)
    totals = [sum(plan.values[s][i] or 0.0 for s in plan.series) for i in range(n)]

    # ---- bars and stacked segments
    marks = 0
    cumulative = [0.0] * n
    per_series_count: Dict[str, int] = {}
    for s, i, patch, _recorded, kind in d.bars:
        raw = plan.values[s][i]
        if kind == "share":
            expected = (raw or 0.0) / totals[i] * 100.0
        elif kind == "stack":
            expected = raw or 0.0
        else:
            expected = raw
        drawn = patch.get_width() if horizontal else patch.get_height()
        center = (patch.get_y() + patch.get_height() / 2) if horizontal else (patch.get_x() + patch.get_width() / 2)
        start = patch.get_x() if horizontal else patch.get_y()
        marks += 1
        per_series_count[s] = per_series_count.get(s, 0) + 1
        if expected is None:
            problems.append(f"{plan.categories[i]} / {s}: a bar was drawn for a missing value")
            continue
        if not _close(drawn, expected):
            problems.append(f"{plan.categories[i]} / {s}: drawn {drawn!r}, input {expected!r}")
        if abs(center - i) > 0.5:
            problems.append(f"{plan.categories[i]} / {s}: bar is not on its category")
        if kind in ("share", "stack"):
            if not _close(start, cumulative[i]):
                problems.append(f"{plan.categories[i]} / {s}: segment starts at {start!r}, "
                                f"expected {cumulative[i]!r}")
            cumulative[i] += drawn
        elif not _close(start, 0.0):
            problems.append(f"{plan.categories[i]} / {s}: bar does not start at zero")
        if len(rows) < MAX_ROWS:
            row = {"category": plan.categories[i], "series": s, "input": raw}
            if kind == "share":
                row["share_pct"] = round(expected, 6)
            row["drawn"] = round(drawn, 9)
            rows.append(row)
    if plan.chart_type == "bar":
        for s in plan.series:
            want = sum(1 for v in plan.values[s] if v is not None)
            if per_series_count.get(s, 0) != want:
                problems.append(f"series {s}: {per_series_count.get(s, 0)} bars drawn, {want} values given")
    if plan.chart_type == "share_bar":
        for i, total in enumerate(cumulative):
            if not _close(total, 100.0, 1e-6):
                problems.append(f"{plan.categories[i]}: shares add up to {total:.6f}%, not 100%")

    # ---- line points
    for s, (line, _recorded) in d.lines.items():
        xs = list(line.get_xdata())
        ys = list(line.get_ydata())
        if xs != list(range(n)):
            problems.append(f"series {s}: points are not one per category in order")
        for i, (want, got) in enumerate(zip(plan.values[s], ys)):
            marks += 1
            if want is None:
                if not (isinstance(got, float) and math.isnan(got)):
                    problems.append(f"{plan.categories[i]} / {s}: a point was drawn for a missing value")
            elif not _close(float(got), want):
                problems.append(f"{plan.categories[i]} / {s}: drawn {got!r}, input {want!r}")
            if len(rows) < MAX_ROWS:
                rows.append({"category": plan.categories[i], "series": s, "input": want,
                             "drawn": None if want is None else float(got)})

    # ---- printed numbers
    label_checks = 0
    for text_obj, expected, kind in d.labels:
        text = text_obj.get_text()
        number_text = text.rsplit("  ", 1)[-1] if kind == "series_end" else text
        try:
            read = numfmt.parse_label(number_text)
        except (numfmt.NotANumber, ValueError):
            problems.append(f"label {text!r} cannot be read as a number")
            continue
        label_checks += 1
        if not _close(read, expected, numfmt.label_tolerance(number_text)):
            problems.append(f"label {text!r} reads as {read!r} but stands for {expected!r}")
    ax = d.ax
    val_axis = ax.xaxis if horizontal else ax.yaxis
    tick_checks = 0
    for loc, lbl in zip(val_axis.get_ticklocs(), val_axis.get_ticklabels()):
        text = lbl.get_text()
        if not text:
            continue
        try:
            read = numfmt.parse_label(text)
        except (numfmt.NotANumber, ValueError):
            problems.append(f"axis tick {text!r} cannot be read as a number")
            continue
        tick_checks += 1
        if not _close(read, float(loc), numfmt.label_tolerance(text)):
            problems.append(f"axis tick {text!r} is placed at {loc!r}")

    # ---- baseline
    lo, hi = ax.get_xlim() if horizontal else ax.get_ylim()
    lo, hi = min(lo, hi), max(lo, hi)
    zero_ok = lo <= 0.0 <= hi
    if plan.chart_type != "line" or plan.y_zero:
        if not zero_ok:
            problems.append(f"value axis runs {lo:g}..{hi:g} and leaves out zero")

    # ---- category labels
    cat_axis = ax.yaxis if horizontal else ax.xaxis
    shown = {int(round(loc)): lbl.get_text() for loc, lbl in zip(cat_axis.get_ticklocs(), cat_axis.get_ticklabels())}
    expected_names = _expected_category_names(plan)
    for i, text in shown.items():
        first = text.split("\n", 1)[0]
        if not (0 <= i < n) or first not in expected_names[i]:
            problems.append(f"category label at position {i} is {text!r}, input is {plan.categories[i]!r}")

    result: Dict[str, Any] = {
        "status": "ok" if not problems else "mismatch",
        "checked": {"marks": marks, "labels": label_checks, "axis_ticks": tick_checks,
                    "categories": len(shown)},
        "value_axis_range": [float(lo), float(hi)],
        "zero_on_axis": bool(zero_ok),
        "rows": rows,
    }
    if d.hidden_labels:
        result["labels_not_printed"] = d.hidden_labels
    if marks > len(rows):
        result["rows_omitted"] = marks - len(rows)
    if problems:
        result["mismatches"] = problems[:20]
    return result
