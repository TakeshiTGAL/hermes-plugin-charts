"""Tool handlers: chart_render, chart_validate, chart_types.

Every handler returns a JSON string and never raises.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from . import delivery, numfmt
from .errors import ChartError
from .spec import CHART_TYPES, MAX_CATEGORIES, MAX_SERIES, PRESETS, Plan, build_plan

logger = logging.getLogger(__name__)

# Filled from plugins.entries.jp-charts.settings at register time.
DEFAULT_SETTINGS: Dict[str, Any] = {"preset": "mobile", "locale": "auto", "font_path": "", "auto_attach": True}
SETTINGS: Dict[str, Any] = dict(DEFAULT_SETTINGS)


def _dump(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _fail(err: ChartError) -> str:
    return _dump({"success": False, "error": err.to_dict()})


def _internal(exc: Exception) -> str:
    logger.exception("jp-charts plugin failed")
    return _dump({"success": False, "error": {
        "code": "internal_error", "message": f"{type(exc).__name__}: {exc}",
        "fix": "This is a bug in the jp-charts plugin, not in your data. Try chart_validate with the same "
               "arguments; if it passes, report the arguments at the plugin's issue tracker."}})


def _defaults() -> Dict[str, Any]:
    return {"preset": SETTINGS.get("preset") or "mobile", "locale": SETTINGS.get("locale") or "auto"}


def _summary(plan: Plan) -> Dict[str, Any]:
    return {
        "chart_type": plan.chart_type, "orientation": plan.orientation, "title": plan.title,
        "categories": len(plan.categories), "series": plan.series, "unit": plan.unit,
        "source": plan.source, "locale": plan.locale, "preset": plan.preset,
        "size_px": list(plan.size), "number_format": plan.number_style,
    }


def _when(plan: Plan, i: int) -> str:
    """'2025-04' -> '2025年4月' / 'Apr 2025' for captions; other labels as given."""
    from .spec import _date_keys
    keys = _date_keys(plan.categories)
    if not keys or not (1 <= keys[i][1] <= 12):
        return plan.categories[i]
    y, m, _ = keys[i]
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{y}年{m}月" if plan.locale == "ja" else f"{months[m - 1]} {y}"


def _alt_text(plan: Plan, render_mod, drawing) -> str:
    """A caption that says what the chart shows, in the same rounding as the chart."""
    ja = plan.locale == "ja"
    kind = {"bar": "横棒グラフ" if plan.orientation == "horizontal" else "棒グラフ",
            "line": "折れ線グラフ", "stacked_bar": "積み上げ棒グラフ", "share_bar": "構成比の帯グラフ"}
    kind_en = {"bar": "Bar chart", "line": "Line chart", "stacked_bar": "Stacked bar chart",
               "share_bar": "100% band chart"}
    def fmt(v: float) -> str:
        text = render_mod._value_label(plan, v)
        return text if not ja or text.endswith(plan.unit) else text + plan.unit
    parts = []
    if plan.chart_type == "share_bar":
        one_decimal = any("." in lbl.get_text() for lbl, _v, k in drawing.labels if k == "share")
        rows = [0] if len(plan.categories) == 1 else [0, len(plan.categories) - 1]
        for i in rows:
            total = sum(plan.values[s][i] or 0 for s in plan.series)
            shares = [f"{s} {render_mod._pct((plan.values[s][i] or 0) / total * 100, 1 if one_decimal else 0)}"
                      for s in plan.series]
            parts.append((f"{plan.categories[i]}は" if ja else f"{plan.categories[i]}: ") +
                         ("、".join(shares) if ja else ", ".join(shares)))
    elif plan.chart_type == "line":
        for s in plan.series[:3]:
            idx = [i for i, v in enumerate(plan.values[s]) if v is not None]
            if not idx:
                continue
            a, b = idx[0], idx[-1]
            va, vb = fmt(plan.values[s][a]), fmt(plan.values[s][b])
            parts.append(f"{s}は{_when(plan, a)}の{va}から{_when(plan, b)}の{vb}" if ja else
                         f"{s}: {va} in {_when(plan, a)} to {vb} in {_when(plan, b)} ({plan.unit})")
    else:
        totals = [(c, sum(plan.values[s][i] or 0 for s in plan.series), i) for i, c in enumerate(plan.categories)
                  if any(plan.values[s][i] is not None for s in plan.series)]
        hi, lo = max(totals, key=lambda t: t[1]), min(totals, key=lambda t: t[1])
        word = "合計" if len(plan.series) > 1 else ""
        if ja:
            parts.append(f"{word}最大は{hi[0]}の{fmt(hi[1])}")
            if lo[0] != hi[0]:
                parts.append(f"最小は{lo[0]}の{fmt(lo[1])}")
        else:
            parts.append(f"largest: {hi[0]}, {fmt(hi[1])} ({plan.unit})")
            if lo[0] != hi[0]:
                parts.append(f"smallest: {lo[0]}, {fmt(lo[1])}")
    head = f"{kind[plan.chart_type]}「{plan.title}」" if ja else f"{kind_en[plan.chart_type]}: {plan.title}"
    if ja:
        joiner = "。" if plan.chart_type == "share_bar" else "、"
        return f"{head}。{joiner.join(parts)}。出典：{plan.source}"
    return f"{head}. {'; '.join(parts)}. Source: {plan.source}"


def _omitted_notes(plan: Plan, hidden) -> list:
    """One footnote per part whose numbers had no room, giving the numbers."""
    by_series = {}
    for entry in hidden:
        where, text = entry.rsplit(": ", 1)
        cat, series = where.split(" / ", 1)
        by_series.setdefault(series, []).append((cat, text if text.endswith("%") or plan.chart_type != "share_bar"
                                                 else text + "%"))
    ja = plan.locale == "ja"
    out = []
    for series in sorted(by_series, key=plan.series.index):
        items = by_series[series]
        if len(items) == len(plan.categories) > 1 and len({t for _c, t in items}) == 1:
            values = f"各{plan.x_title}とも{items[0][1]}" if ja else f"{items[0][1]} in every row"
        else:
            values = ("、" if ja else ", ").join(f"{c} {t}" for c, t in items)
        out.append(f"{series}は{values}（幅が狭いため図中の数値を省略）" if ja
                   else f"{series}: {values} (too narrow to print)")
    return out


def _where_glyphs(plan: Plan, chars) -> str:
    fields = {"title": plan.title, "subtitle": plan.subtitle, "source": plan.source,
              "categories": " ".join(plan.categories), "series": " ".join(plan.series),
              "notes": " ".join(plan.notes), "axis titles": plan.x_title + plan.y_title + plan.unit}
    hits = [name for name, text in fields.items() if any(ch in text for ch in chars)]
    return ", ".join(hits) or "chart text"


def _drawing_modules():
    """matplotlib is imported on first use, so Hermes can load and list the plugin
    (and catalog CI can probe it) before the dependencies are installed."""
    try:
        from . import fonts, render, verify
    except ImportError as exc:
        raise ChartError(
            "missing_dependency", f"The chart renderer is not installed ({exc.name or exc}).",
            where="Python environment",
            fix="Install the plugin's Python dependencies (matplotlib, matplotlib-fontja): run "
                "`hermes plugins enable jp-charts` and accept them, or reinstall with "
                "`hermes plugins install <source> --yes-deps`. Then start a new session.") from None
    return fonts, render, verify


def chart_render(args: Dict[str, Any], session_id: Optional[str] = None, **_: Any) -> str:
    try:
        fonts, render_mod, verify_mod = _drawing_modules()
        plan = build_plan(args, _defaults())
        path = delivery.png_path(plan.title, plan.filename)
        families = fonts.family_list(SETTINGS.get("font_path") or None)
        drawing, missing = _draw(render_mod, fonts, plan, families, path)
        if missing:
            families = fonts.bundled_only()
            drawing, missing = _draw(render_mod, fonts, plan, families, path)
        base_notes = list(plan.notes)
        for _ in range(3):
            # Notes depend on the drawing (numbers with no room, "%" dropped): lay out again until stable.
            if missing:
                break
            notes = list(base_notes)
            if drawing.percent_dropped:
                share_note = "各行の合計を100%とした構成比" if plan.locale == "ja" else "Each bar adds up to 100%"
                notes = [("図中の数値は構成比（%）で、各行の合計を100%としている" if plan.locale == "ja"
                          else "Numbers are shares in %; each bar adds up to 100%") if n == share_note else n
                         for n in notes]
            notes += _omitted_notes(plan, drawing.hidden_labels)
            if notes == plan.notes:
                break
            plan.notes = notes
            drawing, missing = _draw(render_mod, fonts, plan, families, path)
        unsaid = [n for n in _omitted_notes(plan, drawing.hidden_labels) if n not in plan.notes]
        if unsaid and not missing:
            _remove(path)
            return _dump({"success": False, "error": {
                "code": "verification_failed",
                "message": "Some numbers have no room on the chart and could not be listed in a note.",
                "where": "; ".join(unsaid),
                "fix": "Use output.preset 'wide', fewer parts (group small ones into 'その他'), or "
                       "chart_type 'bar'."}})
        if missing:
            _remove(path)
            shown = " ".join(missing[:10])
            raise ChartError(
                "missing_glyphs", f"No installed font can draw these characters: {shown}",
                where=_where_glyphs(plan, missing),
                fix="Remove emoji or rare symbols from the labels, or set the plugin's font_path "
                    "setting to a font that has them.")
        check = verify_mod.verify(plan, drawing)
        if check["status"] != "ok":
            _remove(path)
            return _dump({"success": False, "error": {
                "code": "verification_failed",
                "message": "The drawn chart did not match the input, so it was not returned.",
                "where": "; ".join(check.get("mismatches", [])[:5]),
                "fix": "This is a bug in the jp-charts plugin. Please report the arguments used."},
                "verification": check})
        delivery.remember(session_id, path)
        result: Dict[str, Any] = {
            "success": True,
            "path": path,
            "media": delivery.media_line(path),
            "how_to_show": (
                "To send the chart, put the media line on its own line in your reply: "
                f"{delivery.media_line(path)} . Telegram, Slack, Discord and the desktop app show it "
                "as an image (LINE too when LINE_PUBLIC_URL is set). In a terminal (CLI/TUI) give the "
                "path instead."),
            "alt_text": _alt_text(plan, render_mod, drawing),
            "chart": {**_summary(plan), "size_px": list(drawing.size)},
            "font": drawing.font_family,
            "verification": check,
        }
        if plan.notes:
            result["printed_notes"] = plan.notes
        if plan.warnings:
            result["warnings"] = plan.warnings
        if plan.inferred:
            result["inferred"] = plan.inferred
        return _dump(result)
    except ChartError as err:
        return _fail(err)
    except Exception as exc:  # pragma: no cover - reported, never raised to Hermes
        return _internal(exc)


def _draw(render_mod, fonts, plan: Plan, families, path: str):
    with fonts.missing_glyphs() as missing:
        drawing = render_mod.render(plan, families)
        drawing.fig.savefig(path, dpi=render_mod.DPI, facecolor="white", format="png",
                            metadata={"Title": plan.title, "Source": plan.source})
    return drawing, list(missing)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def chart_validate(args: Dict[str, Any], **_: Any) -> str:
    try:
        plan = build_plan(args, _defaults())
        preview = [{"category": c, **{s: plan.values[s][i] for s in plan.series}}
                   for i, c in enumerate(plan.categories[:20])]
        out: Dict[str, Any] = {"success": True, "valid": True, "chart": _summary(plan),
                               "rows_preview": preview, "printed_notes": plan.notes}
        if len(plan.categories) > 20:
            out["rows_omitted"] = len(plan.categories) - 20
        if plan.warnings:
            out["warnings"] = plan.warnings
        if plan.inferred:
            out["inferred"] = plan.inferred
        return _dump(out)
    except ChartError as err:
        return _fail(err)
    except Exception as exc:  # pragma: no cover
        return _internal(exc)


CHART_GUIDE = {
    "bar": {
        "use_for": "Comparing amounts across categories (prefectures, products, branches). Sorted "
                   "largest first by default. Horizontal when labels are long or there are many "
                   "categories; vertical otherwise (override with orientation).",
        "encodings": "x = category column, y = number column (or a list of number columns for grouped "
                     "bars), color = optional series column for a long table.",
        "always_from_zero": True,
        "max_categories": MAX_CATEGORIES["bar"],
        "example": {"chart_spec": {"chart_type": "bar", "title": "都道府県別の人口（上位10）",
                                   "unit": "人", "source": "総務省統計局「人口推計」",
                                   "encodings": {"x": {"field": "都道府県"}, "y": {"field": "人口"}},
                                   "top_n": 10}},
    },
    "line": {
        "use_for": "Change over time (months, quarters, years). Dates are put in time order. Up to "
                   "4 series are labeled at the line end, more get a legend.",
        "encodings": "x = date/period column, y = number column(s), color = optional series column.",
        "always_from_zero": "yes by default; set y_zero false only when the change itself is the point "
                            "(the chart then says so in a note).",
        "max_points": MAX_CATEGORIES["line"],
        "example": {"chart_spec": {"chart_type": "line", "title": "月次売上の推移", "unit": "万円",
                                   "source": "社内販売管理システム",
                                   "encodings": {"x": {"field": "月"}, "y": {"field": "売上"}}}},
    },
    "stacked_bar": {
        "use_for": "Totals split into parts, when both the total and the parts matter.",
        "encodings": "x = category, y = several part columns, or y = one number column plus color = "
                     "part column.",
        "always_from_zero": True,
        "max_categories": MAX_CATEGORIES["stacked_bar"],
    },
    "share_bar": {
        "use_for": "Composition in percent (構成比の帯グラフ), one 100% band per row. Use instead of a "
                   "pie chart. Shares are computed from the values, so pass raw amounts or percents.",
        "encodings": "x = row label (e.g. year), y = several part columns, or y + color for a long table.",
        "max_rows": MAX_CATEGORIES["share_bar"],
        "example": {"chart_spec": {"chart_type": "share_bar", "title": "売上の構成比（2025年度）",
                                   "unit": "万円", "source": "社内販売管理システム",
                                   "encodings": {"x": {"field": "年度"},
                                                 "y": {"fields": ["国内", "北米", "欧州", "アジア"]}}}},
    },
}


def chart_types(args: Optional[Dict[str, Any]] = None, **_: Any) -> str:
    try:
        wanted = (args or {}).get("chart_type")
        types = {wanted: CHART_GUIDE[wanted]} if wanted in CHART_GUIDE else CHART_GUIDE
        return _dump({
            "success": True,
            "chart_types": types,
            "not_offered": {"pie/donut": "use share_bar", "dual axis": "draw two charts",
                            "3d": "use bar"},
            "required": ["chart_spec.chart_type", "chart_spec.unit", "chart_spec.source",
                         "data (values, columns+rows, text, json or path)"],
            "data_formats": {
                "values": "[{\"月\": \"2026-01\", \"売上\": 1200}, ...]",
                "columns+rows": "the e-Stat plugin's estat_get_data result can be passed as data as-is; "
                                "its unit and source are used",
                "text": "CSV, TSV copied from Excel, or a Markdown table; title/note lines around the "
                        "table are skipped",
                "path": "absolute path to a local .csv/.tsv/.txt/.json (UTF-8 or Shift_JIS)",
                "numbers": "1,234 / １２３４ / 3.5万 / 1億2000万 / △120 (negative) are read; -, …, x, *** "
                           "mean no value",
            },
            "output": {"presets": {k: f"{w}x{h}px" for k, (w, h) in PRESETS.items()},
                       "default_preset": SETTINGS.get("preset") or "mobile",
                       "locale": "ja | en | auto", "number_format": "auto | plain | compact (万/億 or K/M)"},
            "limits": {"series": MAX_SERIES, **{f"{k}_categories": v for k, v in MAX_CATEGORIES.items()}},
            "types_offered": list(CHART_TYPES),
        })
    except Exception as exc:  # pragma: no cover
        return _internal(exc)


HANDLERS = {"chart_render": chart_render, "chart_validate": chart_validate, "chart_types": chart_types}
