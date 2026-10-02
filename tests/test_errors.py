"""Inputs that must fail, and fail with a position and a next step."""

import copy

from helpers import call
import examples


def _err(plugin, args, tool="chart_render"):
    out = call(plugin, tool, args)
    assert out["success"] is False, out
    return out["error"]


def test_type_mismatch_names_row_and_column(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["data"]["values"][3]["人口"] = "七百万"
    args["data"]["values"][6]["人口"] = "n.a"
    err = _err(plugin, args)
    assert err["code"] == "type_mismatch"
    assert "data row 4" in err["where"] and "'人口'" in err["where"] and "'七百万'" in err["where"]
    assert "data row 7" in err["where"]
    assert "2 value(s)" in err["message"]
    assert err["fix"]


def test_type_mismatch_in_csv_gives_line(plugin):
    args = copy.deepcopy(examples.MONTHLY_SALES)
    args["data"]["text"] = args["data"]["text"].replace("2025-08,1198", "2025-08,12O0")
    err = _err(plugin, args)
    assert err["code"] == "type_mismatch" and "data.text, line 6" in err["where"]


def test_empty_data_guides(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["data"] = {"values": []}
    err = _err(plugin, args)
    assert err["code"] == "empty_data"
    assert "data.values" in err["fix"] and err["example"]


def test_all_empty_values(plugin):
    args = {"data": {"values": [{"k": "a", "v": "-"}, {"k": "b", "v": ""}]},
            "chart_spec": {"chart_type": "bar", "unit": "件", "source": "x",
                           "encodings": {"x": {"field": "k"}, "y": {"field": "v"}}}}
    err = _err(plugin, args)
    assert err["code"] == "empty_data"


def test_too_many_series_gives_the_limit(plugin):
    rows = [{"月": f"2026-{m:02d}", "店舗": f"店{s}", "売上": 100 + s} for m in (1, 2) for s in range(11)]
    args = {"data": {"values": rows},
            "chart_spec": {"chart_type": "line", "unit": "万円", "source": "社内",
                           "encodings": {"x": {"field": "月"}, "y": {"field": "売上"},
                                         "color": {"field": "店舗"}}}}
    err = _err(plugin, args)
    assert err["code"] == "too_many_series"
    assert "11 series" in err["message"] and "8" in err["message"]
    assert "その他" in err["fix"]


def test_too_many_categories_suggests_top_n(plugin):
    rows = [{"k": f"c{i}", "v": i} for i in range(60)]
    args = {"data": {"values": rows}, "chart_spec": {"chart_type": "bar", "unit": "件", "source": "x",
                                                     "encodings": {"x": {"field": "k"}, "y": {"field": "v"}}}}
    err = _err(plugin, args)
    assert err["code"] == "too_many_categories" and "top_n" in err["fix"]
    args["chart_spec"]["top_n"] = 10
    assert call(plugin, "chart_render", args)["success"] is True


def test_unit_and_source_are_required(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    del args["chart_spec"]["unit"]
    assert _err(plugin, args)["code"] == "missing_unit"
    args = copy.deepcopy(examples.POPULATION_TOP10)
    del args["chart_spec"]["source"]
    err = _err(plugin, args)
    assert err["code"] == "missing_source" and "ユーザー提供データ" in err["fix"]


def test_misleading_forms_are_refused(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["chart_type"] = "pie"
    err = _err(plugin, args)
    assert err["code"] == "unsupported_chart" and "share_bar" in err["fix"]
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["y_zero"] = False
    assert _err(plugin, args)["code"] == "truncated_axis"


def test_negative_parts_cannot_stack(plugin):
    args = copy.deepcopy(examples.SALES_MIX)
    args["data"]["text"] = args["data"]["text"].replace("| 340 |", "| △40 |")
    err = _err(plugin, args)
    assert err["code"] == "negative_in_stack" and "2023年度" in err["where"]


def test_duplicate_rows_named(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["data"]["values"].append({"都道府県": "東京都", "人口": 1})
    err = _err(plugin, args)
    assert err["code"] == "duplicate_rows" and "data row 1" in err["where"] and "data row 11" in err["where"]


def test_unknown_column_lists_columns(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["encodings"]["y"]["field"] = "population"
    err = _err(plugin, args)
    assert err["code"] == "unknown_column" and "'人口'" in err["fix"]


def test_emoji_reports_missing_glyphs(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["title"] = "人口ランキング \U0001F3C6"
    err = _err(plugin, args)
    assert err["code"] == "missing_glyphs" and "title" in err["where"]


def test_validate_reports_same_errors(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["data"]["values"][0]["人口"] = "?"
    assert _err(plugin, args, "chart_validate")["code"] == "type_mismatch"
