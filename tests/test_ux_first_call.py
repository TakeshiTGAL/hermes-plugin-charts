"""Flat arguments and Japanese chart names on the first call."""

import copy
import json
from pathlib import Path

from helpers import call
import examples


ROOT = Path(__file__).resolve().parent.parent
CSV = "都道府県,人口\n東京都,14047594\n神奈川県,9237337\n"


def _validate(plugin, args):
    return call(plugin, "chart_validate", args)


def test_skill_points_japanese_requests_at_english_tool_search():
    text = (ROOT / "skills" / "chart-png" / "SKILL.md").read_text(encoding="utf-8")
    assert "tool_search" in text
    assert "bar chart" in text
    assert "requires_toolsets" not in text
    assert "棒グラフ" in text
    assert "share_bar" in text


def test_flat_csv_and_japanese_bar_validate(plugin):
    out = _validate(plugin, {
        "data": CSV,
        "chart_type": "棒グラフ",
        "unit": "人",
        "source": "ユーザー提供データ",
    })
    assert out["success"] is True, out
    assert out["chart"]["chart_type"] == "bar"
    assert out["chart"]["categories"] == 2


def test_nested_spec_still_wins_over_a_flat_type(plugin):
    args = copy.deepcopy(examples.MONTHLY_SALES)
    args["chart_type"] = "棒グラフ"
    out = _validate(plugin, args)
    assert out["success"] is True
    assert out["chart"]["chart_type"] == "line"


def test_pie_japanese_name_points_at_share_bar(plugin):
    args = copy.deepcopy(examples.SALES_MIX)
    args["chart_spec"]["chart_type"] = "円グラフ"
    bad = _validate(plugin, args)
    assert bad["success"] is False
    assert "share_bar" in bad["error"]["fix"]
    args["chart_spec"]["chart_type"] = "share_bar"
    again = _validate(plugin, args)
    assert again["success"] is True


def test_unknown_key_example_still_names_chart_type_bar(plugin):
    args = {"data": CSV, "chart_type": "bar", "unit": "人", "source": "ユーザー提供データ", "footnote": "x"}
    bad = _validate(plugin, args)
    text = json.dumps(bad, ensure_ascii=False)
    assert bad["error_type"] == "bad_args"
    assert "chart_type bar" in bad["error"]["message"]
    assert "footnote" not in text
    again = _validate(plugin, {"data": CSV, "chart_type": "bar", "unit": "人", "source": "ユーザー提供データ"})
    assert again["success"] is True
