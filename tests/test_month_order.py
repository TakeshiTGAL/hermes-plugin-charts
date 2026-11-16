"""Month labels are a time series. Bars keep the given order; lines sort oldest to newest.

The 2026-11-16 chart of Jan 1.2億円, Feb 1.5億円, Mar 9800万円 was drawn
Feb, Jan, Mar because sort=auto did not treat English month names as time.
"""

import importlib

import pytest

from helpers import call, load_plugin

PKG = load_plugin().__name__
spec = importlib.import_module(f"{PKG}.spec")
tools = importlib.import_module(f"{PKG}.tools")


def _chart(plugin, chart_type, pairs, **extra):
    chart_spec = {
        "chart_type": chart_type,
        "unit": extra.pop("unit", "円"),
        "source": extra.pop("source", "sample data"),
        "encodings": {"x": {"field": "month"}, "y": {"field": "sales"}},
    }
    chart_spec.update(extra)
    out = call(plugin, "chart_validate", {
        "data": {"values": [{"month": label, "sales": value} for label, value in pairs]},
        "chart_spec": chart_spec,
        "output": {"preset": "mobile"},
    })
    assert out["success"] is True, out
    return out


def _order(plugin, chart_type, pairs, **extra):
    out = _chart(plugin, chart_type, pairs, **extra)
    return [row["category"] for row in out["rows_preview"]]


def test_jan_feb_mar_sales_stay_in_time_order(plugin):
    """The phone chart: Jan 1.2億円, Feb 1.5億円, Mar 9800万円. Source: sample data."""
    out = _chart(plugin, "bar", [("Jan", "1.2億円"), ("Feb", "1.5億円"), ("Mar", "9800万円")])
    rows = out["rows_preview"]
    assert [row["category"] for row in rows] == ["Jan", "Feb", "Mar"]
    assert rows[0]["sales"] == pytest.approx(120_000_000)
    assert rows[1]["sales"] == pytest.approx(150_000_000)
    assert rows[2]["sales"] == pytest.approx(98_000_000)
    assert out["chart"]["preset"] == "mobile"
    assert out["chart"]["source"] == "sample data"


@pytest.mark.parametrize("pairs", [
    [("January", 1), ("February", 5), ("March", 2)],
    [("JANUARY", 1), ("FEBRUARY", 5), ("MARCH", 2)],
    [("Jan.", 1), ("Feb.", 5), ("Mar.", 2)],
    [("Sept", 1), ("Jan", 5), ("September", 2)],
    [("Jan 2026", 1), ("Feb 2026", 5), ("Mar 2026", 2)],
    [("January, 2026", 1), ("2026-Feb", 5), ("2026/March", 2)],
    [("Ｊａｎ", 1), ("Ｆｅｂ", 5), ("Ｍａｒ", 2)],
    [("一月", 1), ("二月", 5), ("三月", 2)],
    [("2026年三月", 9), ("2026年一月", 1), ("2026年二月", 2)],
    [("1月", 1), ("2月", 5), ("3月", 2)],
    [("３月", 1), ("１月", 9), ("２月", 2)],
    [("1/2026", 1), ("2/2026", 5), ("3/2026", 2)],
    [("01-2026", 1), ("02-2026", 5), ("03-2026", 2)],
])
def test_month_labels_are_not_sorted_by_size(plugin, pairs):
    assert _order(plugin, "bar", pairs) == [label for label, _value in pairs]


@pytest.mark.parametrize("pairs,expected", [
    ([("Mar", 9), ("Jan", 1), ("Feb", 8)], ["Jan", "Feb", "Mar"]),
    ([("March", 1), ("January", 3), ("February", 2)], ["January", "February", "March"]),
    ([("MAR 2026", 1), ("jan 2026", 3), ("Feb. 2026", 2)], ["jan 2026", "Feb. 2026", "MAR 2026"]),
    ([("September", 1), ("Jan", 4), ("Sept", 2)], ["Jan", "September", "Sept"]),
    ([("3/2026", 1), ("1/2026", 4), ("2/2026", 2)], ["1/2026", "2/2026", "3/2026"]),
    ([("2026年三月", 1), ("2026年一月", 4), ("2026年二月", 2)],
     ["2026年一月", "2026年二月", "2026年三月"]),
    ([("2026/04", 10), ("2025-12", 8)], ["2025-12", "2026/04"]),
])
def test_lines_put_months_in_time_order(plugin, pairs, expected):
    assert _order(plugin, "line", pairs, unit="yen") == expected


def test_numeric_japanese_months_on_a_line_stay_as_given(plugin):
    """1月 was already a time series. A line keeps the written order."""
    assert _order(plugin, "line", [("3月", 1), ("1月", 9), ("2月", 2)]) == ["3月", "1月", "2月"]


def test_existing_date_keys_are_unchanged():
    assert spec._date_keys(["2026-01", "2026/2", "2026年3月", "2026.4.5"]) == [
        (2026, 1, 1), (2026, 2, 1), (2026, 3, 1), (2026, 4, 5)]
    assert spec._date_keys(["2025年度", "2026"]) == [(2025, 0, 0), (2026, 0, 0)]
    assert spec._date_keys(["2026 Q1", "2026Q2"]) == [(2026, 3, 0), (2026, 6, 0)]
    assert spec._looks_like_time(["1月", "13月"]) is True
    assert spec._looks_like_time(["1月"]) is False
    assert spec._date_keys(["1月", "2月", "3月"]) is None


def test_other_words_still_sort_largest_first(plugin):
    assert _order(plugin, "bar", [("North", 1), ("South", 5)], unit="yen") == ["South", "North"]
    assert _order(plugin, "bar", [("Maybe", 1), ("Market", 5)], unit="yen") == ["Market", "Maybe"]
    assert _order(plugin, "bar", [("Jan", 1), ("Total", 5)], unit="yen") == ["Total", "Jan"]


def test_explicit_desc_still_sorts_months_by_size(plugin):
    assert _order(plugin, "bar", [("Jan", "1.2億円"), ("Feb", "1.5億円"), ("Mar", "9800万円")],
                  sort="desc") == ["Feb", "Jan", "Mar"]


def test_sort_schema_names_month_names(plugin):
    desc = plugin.schemas.CHART_RENDER["parameters"]["properties"]["chart_spec"]["properties"]["sort"]["description"]
    assert desc == "auto: bars largest first, dates and month names in time order."


def test_caption_keeps_a_bare_month_and_a_real_year(plugin):
    bare = spec.build_plan(_chart_args("line", [("Mar", 9), ("Jan", 1), ("Feb", 8)], unit="yen"))
    assert [bare.categories[i] for i in range(3)] == ["Jan", "Feb", "Mar"]
    assert tools._when(bare, 0) == "Jan"
    assert "-1" not in tools._when(bare, 0)

    dated = spec.build_plan(_chart_args("line", [("Mar 2026", 1), ("Jan 2026", 2)], unit="yen"))
    assert tools._when(dated, 0) == "Jan 2026"

    ja = spec.build_plan(_chart_args("line", [("Mar 2026", 1), ("Jan 2026", 2)], unit="円"))
    assert tools._when(ja, 0) == "2026年1月"


def _chart_args(chart_type, pairs, unit="円"):
    return {
        "data": {"values": [{"month": label, "sales": value} for label, value in pairs]},
        "chart_spec": {
            "chart_type": chart_type, "unit": unit, "source": "sample data",
            "encodings": {"x": {"field": "month"}, "y": {"field": "sales"}},
        },
        "output": {"preset": "mobile"},
    }
