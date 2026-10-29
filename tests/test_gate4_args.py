"""Five argument shapes. No session record of argument mistakes exists for this plugin."""
import copy
import json

from helpers import call
import examples


def _validate(plugin, args):
    return call(plugin, "chart_validate", args)


def test_chart_type_case_and_integral_top_n(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["chart_type"] = "Bar"
    args["chart_spec"]["top_n"] = 10.0
    out = _validate(plugin, args)
    assert out["success"] is True
    assert out["chart"]["chart_type"] == "bar"
    assert out["chart"]["categories"] == 10

    args["chart_spec"]["top_n"] = "１０"
    out = _validate(plugin, args)
    assert out["success"] is True and out["chart"]["categories"] == 10


def test_slash_dates_are_ordered(plugin):
    out = _validate(plugin, {
        "data": {"values": [
            {"月": "2026/04", "売上": 10},
            {"月": "2025-12", "売上": 8},
        ]},
        "chart_spec": {
            "chart_type": "line",
            "unit": "万円",
            "source": "ユーザー提供データ",
            "encodings": {"x": {"field": "月"}, "y": {"field": "売上"}},
        },
    })
    assert out["success"] is True
    assert [row["category"] for row in out["rows_preview"]] == ["2025-12", "2026/04"]


def test_extra_argument_hides_the_key(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["pie"] = True
    out = _validate(plugin, args)
    text = json.dumps(out, ensure_ascii=False)
    assert out["ok"] is False
    assert out["error_type"] == "bad_args"
    assert "chart_type bar" in out["error"]["message"]
    assert "pie" not in text


def test_out_of_range_top_n_is_not_rounded(plugin):
    fixed = plugin.spec._TOP_N
    for bad in (0, 7.5):
        args = copy.deepcopy(examples.POPULATION_TOP10)
        args["chart_spec"]["top_n"] = bad
        out = _validate(plugin, args)
        text = json.dumps(out, ensure_ascii=False)
        assert out["ok"] is False
        assert out["error_type"] == "bad_args"
        assert out["error"]["message"] == fixed
        assert "7.5" not in text


def test_unexpected_error_also_has_ok_false_and_error_type(plugin):
    out = json.loads(plugin.tools._internal(RuntimeError("boom")))
    assert out["ok"] is False
    assert out["success"] is False
    assert out["error_type"] == "internal_error"
    assert out["error"]["code"] == "internal_error"
