"""Check a chart request and turn it into a plan the renderer can draw as-is.

The request shape follows the familiar semantic-spec layout (data +
``chart_spec`` with a chart type, title and ``encodings`` that map channels to
column names). Everything that can be wrong is caught here, before drawing,
and reported with the row/column or key at fault and the next step.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import numfmt
from .data_io import Table, load
from .errors import ChartError

CHART_TYPES = ("bar", "line", "stacked_bar", "share_bar")
_ALIASES = {
    "column": ("bar", "vertical"), "columns": ("bar", "vertical"), "vertical_bar": ("bar", "vertical"),
    "barh": ("bar", "horizontal"), "horizontal_bar": ("bar", "horizontal"), "bars": ("bar", None),
    "lines": ("line", None), "time_series": ("line", None),
    "stacked": ("stacked_bar", None), "stacked_column": ("stacked_bar", "vertical"),
    "share": ("share_bar", None), "100_stacked_bar": ("share_bar", None),
    "percent_stacked_bar": ("share_bar", None), "band": ("share_bar", None),
    "composition": ("share_bar", None),
}
_REFUSED = {
    "pie": "Pie and donut charts make shares hard to compare. Use chart_type 'share_bar' "
           "(a 100% band); it shows the same shares as lengths.",
    "donut": "Pie and donut charts make shares hard to compare. Use chart_type 'share_bar'.",
    "doughnut": "Pie and donut charts make shares hard to compare. Use chart_type 'share_bar'.",
    "3d": "3D charts distort lengths. Use 'bar'.",
    "dual_axis": "Two value axes on one chart invite false comparisons. Draw two charts.",
}

MAX_SERIES = 8
MAX_CATEGORIES = {"bar": 40, "stacked_bar": 30, "share_bar": 15, "line": 500}
PRESETS = {  # width, height in pixels
    "mobile": (1080, 1350),   # 4:5, fills a phone screen in Telegram/LINE/Slack
    "square": (1080, 1080),
    "wide": (1600, 900),      # 16:9, slides and reports
}

_SPEC_EXAMPLE = {
    "data": {"values": [{"pref": "東京都", "pop": 14178000}, {"pref": "神奈川県", "pop": 9229000}]},
    "chart_spec": {
        "chart_type": "bar", "title": "都道府県別の人口", "unit": "人",
        "source": "総務省統計局「人口推計」2023年10月1日現在",
        "encodings": {"x": {"field": "pref"}, "y": {"field": "pop", "title": "人口"}},
    },
}


@dataclass
class Plan:
    chart_type: str
    orientation: str                      # horizontal | vertical (line: vertical)
    categories: List[str]
    series: List[str]
    values: Dict[str, List[Optional[float]]]
    unit: str
    source: str
    title: str
    subtitle: str
    x_title: str
    y_title: str
    locale: str
    number_style: str
    decimals: int
    preset: str
    size: Tuple[int, int]
    y_zero: bool = True
    highlight: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)      # printed under the chart
    warnings: List[str] = field(default_factory=list)   # returned to the agent only
    inferred: Dict[str, Any] = field(default_factory=dict)
    filename: str = ""
    category_total: int = 0

    def numbers(self) -> List[float]:
        return [v for s in self.series for v in self.values[s] if v is not None]


def _has_japanese(text: str) -> bool:
    return any("CJK" in unicodedata.name(ch, "") or "HIRAGANA" in unicodedata.name(ch, "")
               or "KATAKANA" in unicodedata.name(ch, "") for ch in text)


def _field_name(enc: Any, channel: str) -> Any:
    if enc is None:
        return None
    if isinstance(enc, str):
        return enc
    if isinstance(enc, list):
        return [_field_name(e, channel) for e in enc]
    if isinstance(enc, dict):
        if "field" in enc:
            return enc["field"]
        if "fields" in enc:
            return list(enc["fields"])
    raise ChartError("bad_spec", f"encodings.{channel} must name a column, like {{\"field\": \"sales\"}}.",
                     where=f"chart_spec.encodings.{channel}", example=_SPEC_EXAMPLE["chart_spec"])


def _enc_title(enc: Any) -> str:
    return str(enc.get("title") or "") if isinstance(enc, dict) else ""


def _require_column(table: Table, name: str, where: str) -> str:
    if name in table.columns:
        return name
    folded = {unicodedata.normalize("NFKC", c).strip().lower(): c for c in table.columns}
    hit = folded.get(unicodedata.normalize("NFKC", str(name)).strip().lower())
    if hit:
        return hit
    raise ChartError("unknown_column", f"There is no column {name!r}.", where=where,
                     fix=f"Use one of the columns in the data: {', '.join(map(repr, table.columns))}.")


def _is_numeric_column(table: Table, col: str) -> bool:
    i = table.columns.index(col)
    seen = 0
    for row in table.rows:
        try:
            num, _ = numfmt.parse_number(row[i])
        except numfmt.NotANumber:
            return False
        seen += num is not None
    return seen > 0


def _parse_column(table: Table, col: str, unit: str, problems: List[str]) -> Tuple[List[Optional[float]], set, bool]:
    i = table.columns.index(col)
    out, marks, percent = [], set(), False
    for row, label in zip(table.rows, table.row_labels):
        raw = row[i]
        try:
            num, pct = numfmt.parse_number(raw, unit)
        except numfmt.NotANumber:
            problems.append(f"{label}, column {col!r}: {raw!r} is not a number")
            out.append(None)
            continue
        percent |= pct
        if num is None and raw not in (None, ""):
            marks.add(str(raw))
        out.append(num)
    return out, marks, percent


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def build_plan(args: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Plan:
    if not isinstance(args, dict):
        raise ChartError("bad_spec", "Arguments must be an object with data and chart_spec.",
                         example=_SPEC_EXAMPLE)
    defaults = defaults or {}
    table = load(args.get("data"))
    spec = args.get("chart_spec")
    if spec is None:
        raise ChartError("missing_spec", "chart_spec is missing.", where="chart_spec",
                         fix="Add chart_spec with chart_type, encodings, unit and source.",
                         example=_SPEC_EXAMPLE["chart_spec"])
    if not isinstance(spec, dict):
        raise ChartError("bad_spec", "chart_spec must be an object.", where="chart_spec",
                         example=_SPEC_EXAMPLE["chart_spec"])
    output = args.get("output") or {}
    if not isinstance(output, dict):
        raise ChartError("bad_spec", "output must be an object.", where="output",
                         example={"preset": "mobile"})
    display = args.get("field_display_names") or {}
    if not isinstance(display, dict):
        raise ChartError("bad_spec", "field_display_names must map column names to labels.",
                         where="field_display_names")
    warnings: List[str] = []
    inferred: Dict[str, Any] = {}

    # ---- chart type
    raw_type = str(spec.get("chart_type") or spec.get("chartType") or spec.get("type") or "").strip()
    key = re.sub(r"[\s%-]+", "_", raw_type.lower()).strip("_")
    orientation = str(spec.get("orientation") or "auto").lower()
    if key in _REFUSED:
        raise ChartError("unsupported_chart", f"chart_type {raw_type!r} is not offered.",
                         where="chart_spec.chart_type", fix=_REFUSED[key])
    if key in _ALIASES:
        key, forced = _ALIASES[key]
        if forced and orientation == "auto":
            orientation = forced
    if not key:
        raise ChartError("missing_chart_type", "chart_spec.chart_type is missing.",
                         where="chart_spec.chart_type",
                         fix=f"Use one of: {', '.join(CHART_TYPES)}. Call chart_types for when to use each.")
    if key not in CHART_TYPES:
        raise ChartError("unsupported_chart", f"chart_type {raw_type!r} is not one of {', '.join(CHART_TYPES)}.",
                         where="chart_spec.chart_type",
                         fix="Pick the closest supported type; call chart_types for guidance.")
    if orientation not in ("auto", "horizontal", "vertical"):
        raise ChartError("bad_spec", "orientation must be auto, horizontal or vertical.",
                         where="chart_spec.orientation")

    # ---- encodings
    enc = spec.get("encodings") or {}
    if not isinstance(enc, dict):
        raise ChartError("bad_spec", "encodings must be an object like {\"x\": {\"field\": ...}}.",
                         where="chart_spec.encodings", example=_SPEC_EXAMPLE["chart_spec"]["encodings"])
    x_name = _field_name(enc.get("x"), "x")
    y_name = _field_name(enc.get("y"), "y")
    c_name = _field_name(enc.get("color") or enc.get("series"), "color")
    if isinstance(x_name, list):
        raise ChartError("bad_spec", "encodings.x takes one column (the categories or dates).",
                         where="chart_spec.encodings.x")

    # x and y swapped (a habit from horizontal bars elsewhere): swap back.
    if (isinstance(x_name, str) and isinstance(y_name, str) and x_name in table.columns
            and y_name in table.columns and _is_numeric_column(table, x_name)
            and not _is_numeric_column(table, y_name)):
        x_name, y_name = y_name, x_name
        if key in ("bar", "stacked_bar") and orientation == "auto":
            orientation = "horizontal"
        warnings.append("encodings.x held the numbers and encodings.y the labels; they were swapped. "
                        "In this tool x is always the category/date column and y the numbers, "
                        "for horizontal bars too.")

    numeric_cols = [c for c in table.columns if _is_numeric_column(table, c)]
    if x_name is None:
        candidates = [c for c in table.columns if c not in numeric_cols and c != c_name]
        if not candidates:
            raise ChartError("missing_x", "Could not tell which column holds the categories or dates.",
                             where="chart_spec.encodings.x",
                             fix=f"Set encodings.x to one of {', '.join(map(repr, table.columns))}.")
        x_name = candidates[0]
        inferred["x"] = x_name
    x_col = _require_column(table, x_name, "chart_spec.encodings.x")
    if c_name is not None:
        c_name = _require_column(table, c_name, "chart_spec.encodings.color")
    if y_name is None:
        y_cols = [c for c in numeric_cols if c not in (x_col, c_name)]
        if not y_cols:
            raise ChartError("missing_y", "No numeric column was found to draw.",
                             where="chart_spec.encodings.y",
                             fix="Set encodings.y to the column with the numbers, and check that it "
                                 "holds numbers.")
        inferred["y"] = y_cols if len(y_cols) > 1 else y_cols[0]
    else:
        y_cols = y_name if isinstance(y_name, list) else [y_name]
        y_cols = [_require_column(table, y, "chart_spec.encodings.y") for y in y_cols]
    if c_name is not None and len(y_cols) > 1:
        raise ChartError("bad_spec", "Use either several y columns (wide table) or a color column "
                                     "(long table), not both.", where="chart_spec.encodings",
                         fix="Keep encodings.color and a single encodings.y, or drop encodings.color.")

    # ---- unit and source: always printed, so required
    unit = str(spec.get("unit") or _enc_unit(enc.get("y")) or table.hints.get("unit") or "").strip()
    if not unit:
        raise ChartError(
            "missing_unit", "chart_spec.unit is missing. Every chart prints its unit on the value axis.",
            where="chart_spec.unit",
            fix="Set unit to what one number counts, e.g. '人', '万円', '円', '%', '件', 'kWh', "
                "or 'index (2020=100)'.")
    source = str(spec.get("source") or table.hints.get("source") or "").strip()
    if not source:
        raise ChartError(
            "missing_source", "chart_spec.source is missing. Every chart prints where its numbers "
                              "come from.", where="chart_spec.source",
            fix="Set source to the publisher and date, e.g. '総務省統計局「人口推計」2023年10月1日現在'. "
                "If the user typed or pasted the numbers, use 'ユーザー提供データ' / 'Data provided by "
                "the user'.")

    # ---- numbers
    problems: List[str] = []
    parsed: Dict[str, List[Optional[float]]] = {}
    marks: set = set()
    percent_seen = False
    for col in y_cols:
        vals, m, pct = _parse_column(table, col, unit, problems)
        parsed[col] = vals
        marks |= m
        percent_seen |= pct
    if problems:
        shown = problems[:5]
        more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        raise ChartError(
            "type_mismatch", f"{len(problems)} value(s) in the number column(s) are not numbers{more}.",
            where="; ".join(shown),
            fix="Fix or remove those cells. Thousands separators, full-width digits, 万/億 and "
                "△ for negatives are fine; leave a cell empty (or '-') when there is no value.")

    x_values = [_text(row[table.columns.index(x_col)]) for row in table.rows]
    for label, xv in zip(table.row_labels, x_values):
        if not xv:
            raise ChartError("missing_label", f"{label} has an empty {x_col!r}.", where=f"{label}, column {x_col!r}",
                             fix="Every row needs a category or date label; remove the row or fill it in.")

    # ---- reshape into categories x series
    categories: List[str] = []
    series: List[str] = []
    values: Dict[str, List[Optional[float]]] = {}
    if c_name is not None:
        y = y_cols[0]
        seen: Dict[Tuple[str, str], str] = {}
        c_values = [_text(row[table.columns.index(c_name)]) for row in table.rows]
        for xv, cv in zip(x_values, c_values):
            if xv not in categories:
                categories.append(xv)
            if cv not in series:
                series.append(cv)
        index = {c: i for i, c in enumerate(categories)}
        values = {s: [None] * len(categories) for s in series}
        for label, xv, cv, v in zip(table.row_labels, x_values, c_values, parsed[y]):
            if (xv, cv) in seen:
                raise ChartError(
                    "duplicate_rows", f"{xv!r} / {cv!r} appears in two rows.",
                    where=f"{seen[(xv, cv)]} and {label}",
                    fix="Each category and series pair needs one row. Sum or average the duplicates "
                        "first.")
            seen[(xv, cv)] = label
            values[cv][index[xv]] = v
    else:
        first_seen: Dict[str, str] = {}
        for label, xv in zip(table.row_labels, x_values):
            if xv in first_seen:
                raise ChartError(
                    "duplicate_rows", f"{xv!r} appears in more than one row.",
                    where=f"{first_seen[xv]} and {label}, column {x_col!r}",
                    fix="Each category or date needs one row. Sum the duplicates first, or name a "
                        "series column in encodings.color if the rows belong to different series.")
            first_seen[xv] = label
        categories = list(x_values)
        series = list(y_cols)
        values = {s: list(parsed[s]) for s in series}

    if len(series) > MAX_SERIES:
        raise ChartError(
            "too_many_series", f"{len(series)} series is more than {MAX_SERIES} distinguishable colors.",
            where="chart_spec.encodings.color" if c_name else "chart_spec.encodings.y",
            fix=f"Keep the {MAX_SERIES - 1} largest series and add the rest together as 'その他' "
                f"(Other), or split the data into several charts.")
    if all(v is None for s in series for v in values[s]):
        raise ChartError("empty_data", "Every value is empty, so there is nothing to draw.",
                         where="data", fix="Check that encodings.y names the column with the numbers.")

    # ---- sort / top_n
    sort = str(spec.get("sort") or "auto").lower()
    if sort not in ("auto", "desc", "asc", "none"):
        raise ChartError("bad_spec", "sort must be auto, desc, asc or none.", where="chart_spec.sort")
    if sort == "auto":
        sort = "desc" if key == "bar" and len(series) == 1 and not _looks_like_time(categories) else "none"
    if key == "line":
        dates = _date_keys(categories)
        if dates and dates != sorted(dates):
            order = sorted(range(len(categories)), key=lambda i: dates[i])
            categories = [categories[i] for i in order]
            values = {s: [values[s][i] for i in order] for s in series}
            warnings.append("The dates were not in order; they were sorted oldest to newest.")
        if sort != "none":
            warnings.append("sort is ignored for line charts; dates stay in time order.")
            sort = "none"
    if sort in ("desc", "asc"):
        totals = [sum(values[s][i] or 0 for s in series) for i in range(len(categories))]
        order = sorted(range(len(categories)), key=lambda i: totals[i], reverse=(sort == "desc"))
        categories = [categories[i] for i in order]
        values = {s: [values[s][i] for i in order] for s in series}
    category_total = len(categories)
    top_n = spec.get("top_n")
    if top_n is not None:
        if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
            raise ChartError("bad_spec", "top_n must be a whole number of 1 or more.", where="chart_spec.top_n")
        if top_n < len(categories):
            if sort == "none" and key != "line":
                warnings.append("top_n kept the first rows as given; set sort to 'desc' to keep the largest.")
            categories = categories[:top_n]
            values = {s: v[:top_n] for s, v in values.items()}

    limit = MAX_CATEGORIES[key]
    if len(categories) > limit:
        raise ChartError(
            "too_many_categories", f"{len(categories)} categories is more than a {key} chart can label "
                                   f"legibly (limit {limit}).", where="chart_spec.top_n",
            fix=f"Set top_n (for example 10) with sort 'desc', or group the small ones into 'その他'.")

    # ---- type-specific honesty checks
    if key in ("stacked_bar", "share_bar"):
        for s in series:
            for cat, v in zip(categories, values[s]):
                if v is not None and v < 0:
                    raise ChartError(
                        "negative_in_stack", f"{s!r} for {cat!r} is negative ({v:g}); stacked parts "
                                             "must be zero or more.", where=f"category {cat!r}, series {s!r}",
                        fix="Use chart_type 'bar' (grouped bars show negatives honestly).")
    if key == "share_bar":
        for i, cat in enumerate(categories):
            parts = [values[s][i] for s in series]
            if any(p is None for p in parts):
                missing = [s for s, p in zip(series, parts) if p is None]
                raise ChartError("missing_part", f"{cat!r} has no value for {', '.join(map(repr, missing))}.",
                                 where=f"category {cat!r}",
                                 fix="A share needs every part. Fill in 0 if the part is truly zero.")
            if sum(parts) <= 0:
                raise ChartError("zero_total", f"The parts of {cat!r} add up to 0, so there is no share.",
                                 where=f"category {cat!r}", fix="Remove that row or check the numbers.")
        if len(series) < 2:
            raise ChartError("too_few_parts", "A share band needs at least two parts.",
                             where="chart_spec.encodings",
                             fix="Pass the parts as several y columns, or as rows with encodings.color.")

    # ---- presentation
    loc = str(output.get("locale") or defaults.get("locale") or "auto").lower()
    if loc == "auto":
        sample = " ".join([str(spec.get("title") or ""), x_col, unit, source] + categories[:5] + series[:5])
        loc = "ja" if _has_japanese(sample) else "en"
    if loc not in ("ja", "en"):
        raise ChartError("bad_spec", "output.locale must be ja, en or auto.", where="output.locale")
    preset = str(output.get("preset") or defaults.get("preset") or "mobile").lower()
    if preset not in PRESETS:
        raise ChartError("bad_spec", f"output.preset must be one of {', '.join(PRESETS)}.",
                         where="output.preset",
                         fix="mobile (4:5, for phones), square, or wide (16:9, for slides).")
    number_format = str(output.get("number_format") or "auto").lower()
    if number_format not in ("auto", "plain", "compact"):
        raise ChartError("bad_spec", "output.number_format must be auto, plain or compact.",
                         where="output.number_format")
    numbers = [v for s in series for v in values[s] if v is not None]
    style = "plain" if key == "share_bar" else numfmt.choose_style(numbers, unit, number_format, loc)
    decimals = 1 if key == "share_bar" else numfmt.decimals_for(numbers)

    if orientation == "auto":
        if key == "line":
            orientation = "vertical"
        elif key == "share_bar":
            orientation = "horizontal"
        else:
            longest = max((_display_len(c) for c in categories), default=0)
            narrow = preset != "wide"
            orientation = ("horizontal" if longest > 4 or len(categories) > (6 if narrow else 12)
                           else "vertical")
    if key == "line":
        orientation = "vertical"
    if key == "share_bar" and orientation == "vertical":
        warnings.append("share_bar is always drawn horizontally so the labels stay readable.")
        orientation = "horizontal"

    y_title = str(_enc_title(enc.get("y")) or (display.get(y_cols[0]) if len(y_cols) == 1 else "")
                  or (y_cols[0] if len(y_cols) == 1 and c_name is None else "") or "")
    x_title = str(_enc_title(enc.get("x")) or display.get(x_col) or x_col)
    if c_name is None and len(series) > 1:
        series_labels = {s: str(display.get(s) or s) for s in series}
    else:
        series_labels = {s: s for s in series}
    if any(series_labels[s] != s for s in series):
        values = {series_labels[s]: values[s] for s in series}
        series = [series_labels[s] for s in series]

    title = str(spec.get("title") or "").strip()
    if not title:
        what = y_title or (series[0] if len(series) == 1 else "")
        title = (f"{x_title}別の{what}" if what else f"{x_title}別") if loc == "ja" else \
                (f"{what} by {x_title}" if what else f"By {x_title}")
        inferred["title"] = title
    y_zero = spec.get("y_zero", True)
    if not isinstance(y_zero, bool):
        raise ChartError("bad_spec", "y_zero must be true or false.", where="chart_spec.y_zero")
    if not y_zero and key != "line":
        raise ChartError(
            "truncated_axis", "Bars must start at zero; a cut axis makes small differences look big.",
            where="chart_spec.y_zero",
            fix="Remove y_zero, or use chart_type 'line' if the change over time is the point.")
    highlight = spec.get("highlight") or []
    if isinstance(highlight, str):
        highlight = [highlight]
    if not isinstance(highlight, list):
        raise ChartError("bad_spec", "highlight must be a list of category labels.", where="chart_spec.highlight")
    highlight = [_text(h) for h in highlight]
    unknown = [h for h in highlight if h not in categories]
    if unknown:
        raise ChartError("unknown_category", f"highlight names {unknown[0]!r}, which is not a category.",
                         where="chart_spec.highlight",
                         fix=f"Use labels exactly as in the data, e.g. {', '.join(map(repr, categories[:3]))}.")
    if highlight and (key != "bar" or len(series) != 1):
        raise ChartError("bad_spec", "highlight works on single-series bar charts.",
                         where="chart_spec.highlight", fix="Remove highlight for this chart type.")

    notes: List[str] = []
    user_notes = spec.get("notes") or spec.get("note") or []
    if isinstance(user_notes, str):
        user_notes = [user_notes]
    notes.extend(str(n) for n in user_notes if str(n).strip())
    ja = loc == "ja"
    if top_n is not None and top_n < category_total:
        notes.append(f"上位{top_n}件を表示（全{category_total}件）" if ja
                     else f"Top {top_n} of {category_total} shown")
    if marks:
        listed = "、".join(sorted(marks)) if ja else ", ".join(sorted(marks))
        notes.append(f"「{listed}」は値なしとして扱った" if ja else f"Cells marked {listed} are drawn as no value")
    missing_n = sum(1 for s in series for v in values[s] if v is None)
    if missing_n and key in ("bar", "stacked_bar") and not marks:
        notes.append("空欄は値なし（棒を描かない）" if ja else "Empty cells are drawn as no bar")
    if missing_n and key == "line":
        notes.append("値のない月・期間は線を切っている" if ja else "Gaps in the line are periods with no value")
    if percent_seen and unit.strip() not in ("%", "％", "percent", "パーセント"):
        warnings.append(f"Some cells end in % but unit is {unit!r}; check that the unit is right.")
    if key == "share_bar":
        notes.append("各行の合計を100%とした構成比" if ja else "Each bar adds up to 100%")
    if not y_zero:
        notes.append("縦軸は0から始まっていない" if ja else "The value axis does not start at zero")

    filename = str(output.get("filename") or "")
    return Plan(
        chart_type=key, orientation=orientation, categories=categories, series=series, values=values,
        unit=unit, source=source, title=title, subtitle=str(spec.get("subtitle") or "").strip(),
        x_title=x_title, y_title=y_title, locale=loc, number_style=style, decimals=decimals,
        preset=preset, size=PRESETS[preset], y_zero=y_zero, highlight=highlight, notes=notes,
        warnings=warnings, inferred=inferred, filename=filename, category_total=category_total)


def _enc_unit(enc: Any) -> str:
    return str(enc.get("unit") or "") if isinstance(enc, dict) else ""


def _display_len(text: str) -> float:
    return sum(1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.55 for ch in text)


_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?月?$"), "ymd"),
    (re.compile(r"^(\d{4})年?度?$"), "y"),
    (re.compile(r"^(\d{4})\s*[QqＱ]([1-4])$"), "yq"),
)


def _date_keys(labels: List[str]) -> Optional[List[Tuple[int, int, int]]]:
    out = []
    for label in labels:
        s = unicodedata.normalize("NFKC", label).strip()
        for pat, kind in _DATE_PATTERNS:
            m = pat.match(s)
            if m:
                if kind == "ymd":
                    out.append((int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)))
                elif kind == "y":
                    out.append((int(m.group(1)), 0, 0))
                else:
                    out.append((int(m.group(1)), int(m.group(2)) * 3, 0))
                break
        else:
            return None
    return out


def _looks_like_time(labels: List[str]) -> bool:
    if _date_keys(labels):
        return True
    months = [re.match(r"^(\d{1,2})月$", unicodedata.normalize("NFKC", c)) for c in labels]
    return all(months) and len(labels) > 1
