"""Charts that must render, with their verification read back from the figure."""

import copy
import importlib

import pytest

pytest.importorskip(
    "matplotlib",
    reason=(
        "plugin.yaml は matplotlib>=3.8,<4 と matplotlib-fontja>=1.0,<2 を宣言している。"
        "この実行環境には入っていない。Hermes の enable が入れる。"
    ),
)
import matplotlib
from PIL import Image

from helpers import call, load_plugin
import examples

PKG = load_plugin().__name__


def _ok(plugin, args, **kw):
    out = call(plugin, "chart_render", args, **kw)
    assert out["success"] is True, out
    assert out["verification"]["status"] == "ok", out["verification"]
    assert "mismatches" not in out["verification"]
    return out


def test_population_top10_horizontal_sorted(plugin):
    out = _ok(plugin, examples.POPULATION_TOP10)
    v = out["verification"]
    assert out["chart"]["orientation"] == "horizontal"
    assert v["checked"] == {"marks": 10, "labels": 10, "axis_ticks": v["checked"]["axis_ticks"],
                            "categories": 10}
    assert [r["category"] for r in v["rows"][:3]] == ["東京都", "神奈川県", "大阪府"]
    assert all(r["input"] == r["drawn"] for r in v["rows"])
    assert v["value_axis_range"][0] == 0.0
    assert Image.open(out["path"]).size == (1080, 1350)
    assert out["media"] == f"MEDIA:{out['path']}"
    assert "東京都" in out["alt_text"] and "出典" in out["alt_text"]


def test_monthly_sales_line(plugin):
    out = _ok(plugin, examples.MONTHLY_SALES)
    v = out["verification"]
    assert v["checked"]["marks"] == 12
    assert [r["input"] for r in v["rows"]][:3] == [1240, 1185, 1310]
    assert v["zero_on_axis"] is True


def test_sales_mix_share(plugin):
    out = _ok(plugin, examples.SALES_MIX)
    rows = out["verification"]["rows"]
    by_year = {}
    for r in rows:
        by_year.setdefault(r["category"], 0.0)
        by_year[r["category"]] += r["drawn"]
    assert all(abs(total - 100.0) < 1e-6 for total in by_year.values())  # rows are rounded to 1e-9
    first = rows[0]
    assert first["share_pct"] == pytest.approx(6120 / (6120 + 2310 + 1480 + 1150 + 340) * 100)
    assert any("その他" in n for n in out["printed_notes"])  # omitted numbers are said on the chart


@pytest.mark.parametrize("preset,size", [("mobile", (1080, 1350)), ("square", (1080, 1080)),
                                         ("wide", (1600, 900))])
def test_presets(plugin, preset, size):
    args = copy.deepcopy(examples.MONTHLY_SALES)
    args["output"] = {"preset": preset}
    assert Image.open(_ok(plugin, args)["path"]).size == size


def test_grouped_and_stacked_bars(plugin):
    data = {"values": [{"店舗": "新宿", "2024": 1200, "2025": 1450}, {"店舗": "梅田", "2024": 980, "2025": 1010},
                       {"店舗": "博多", "2024": 640, "2025": 720}]}
    for kind in ("bar", "stacked_bar"):
        args = {"data": data, "chart_spec": {"chart_type": kind, "title": "店舗別売上", "unit": "万円",
                                             "source": "サンプル", "encodings": {"x": {"field": "店舗"},
                                                                              "y": {"fields": ["2024", "2025"]}}}}
        out = _ok(plugin, args)
        assert out["verification"]["checked"]["marks"] == 6


def test_negative_bars_include_zero(plugin):
    args = {"data": {"values": [{"部門": "A", "損益": 120}, {"部門": "B", "損益": "△80"}, {"部門": "C", "損益": 30}]},
            "chart_spec": {"chart_type": "bar", "unit": "万円", "source": "サンプル",
                           "encodings": {"x": {"field": "部門"}, "y": {"field": "損益"}}}}
    out = _ok(plugin, args)
    lo, hi = out["verification"]["value_axis_range"]
    assert lo < 0 < hi


def test_line_multi_series_long_table_and_gap(plugin):
    rows = []
    for m in range(1, 7):
        rows.append({"月": f"2026-{m:02d}", "系列": "東日本", "件数": 100 + m})
        rows.append({"月": f"2026-{m:02d}", "系列": "西日本", "件数": "-" if m == 3 else 80 + m})
    args = {"data": {"values": rows}, "chart_spec": {
        "chart_type": "line", "unit": "件", "source": "サンプル",
        "encodings": {"x": {"field": "月"}, "y": {"field": "件数"}, "color": {"field": "系列"}}}}
    out = _ok(plugin, args)
    assert out["chart"]["series"] == ["東日本", "西日本"]
    assert any("値なし" in n for n in out["printed_notes"])


def test_dates_out_of_order_are_sorted(plugin):
    args = copy.deepcopy(examples.MONTHLY_SALES)
    lines = args["data"]["text"].strip().split("\n")
    args["data"]["text"] = "\n".join([lines[0]] + list(reversed(lines[1:])))
    out = _ok(plugin, args)
    assert out["verification"]["rows"][0]["category"] == "2025-04"
    assert out["warnings"]


def test_swapped_axes_are_fixed(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["encodings"] = {"x": {"field": "人口"}, "y": {"field": "都道府県"}}
    out = _ok(plugin, args)
    assert out["chart"]["orientation"] == "horizontal" and out["warnings"]


def test_english_and_compact_numbers(plugin):
    args = {"data": {"values": [{"region": "North", "revenue": 2_400_000}, {"region": "South", "revenue": 1_150_000}]},
            "chart_spec": {"chart_type": "bar", "title": "Revenue by region", "unit": "USD",
                           "source": "Data provided by the user",
                           "encodings": {"x": {"field": "region"}, "y": {"field": "revenue"}}}}
    out = _ok(plugin, args)
    assert out["chart"]["locale"] == "en" and out["chart"]["number_format"] == "en"


def test_top_n_note(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["top_n"] = 5
    out = _ok(plugin, args)
    assert out["chart"]["categories"] == 5
    assert "上位5件を表示（全10件）" in out["printed_notes"]


def test_does_not_touch_global_matplotlib_settings(plugin):
    before = dict(matplotlib.rcParams)
    _ok(plugin, examples.SALES_MIX)
    after = dict(matplotlib.rcParams)
    assert before == after


def test_bundled_font_renders_japanese(plugin):
    fonts = importlib.import_module(f"{PKG}.fonts")
    render = importlib.import_module(f"{PKG}.render")
    spec = importlib.import_module(f"{PKG}.spec")
    verify = importlib.import_module(f"{PKG}.verify")
    assert fonts.bundled_font_path()
    plan = spec.build_plan(copy.deepcopy(examples.POPULATION_TOP10))
    with fonts.missing_glyphs() as missing:
        drawing = render.render(plan, fonts.bundled_only())
        drawing.fig.canvas.draw()
    assert missing == []
    assert verify.verify(plan, drawing)["status"] == "ok"


def test_verifier_catches_a_wrong_bar(plugin):
    render = importlib.import_module(f"{PKG}.render")
    spec = importlib.import_module(f"{PKG}.spec")
    verify = importlib.import_module(f"{PKG}.verify")
    fonts = importlib.import_module(f"{PKG}.fonts")
    plan = spec.build_plan(copy.deepcopy(examples.POPULATION_TOP10))
    drawing = render.render(plan, fonts.family_list())
    drawing.bars[2][2].set_width(drawing.bars[2][2].get_width() * 1.05)
    drawing.labels[0][0].set_text("1,505万")
    out = verify.verify(plan, drawing)
    assert out["status"] == "mismatch"
    assert any("大阪府" in m for m in out["mismatches"])
    assert any("1,505万" in m for m in out["mismatches"])


def test_validate_shows_how_the_table_was_read(plugin):
    out = call(plugin, "chart_validate", examples.SALES_MIX)
    assert out["valid"] is True
    assert out["rows_preview"][0] == {"category": "2023年度", "国内": 6120, "北米": 2310, "欧州": 1480,
                                      "アジア": 1150, "その他": 340}


def test_chart_types_guide(plugin):
    out = call(plugin, "chart_types", {})
    assert set(out["chart_types"]) == {"bar", "line", "stacked_bar", "share_bar"}
    assert out["not_offered"]["pie/donut"] == "use share_bar"


def test_units_on_scaled_labels_and_caption(plugin):
    out = _ok(plugin, examples.POPULATION_TOP10)
    assert "最大は東京都の1,405万人" in out["alt_text"] and "最小は静岡県の363万人" in out["alt_text"]
    line = _ok(plugin, examples.MONTHLY_SALES)
    assert "2025年4月の1,240万円から2026年3月の1,734万円" in line["alt_text"]


def test_share_band_is_compact_and_says_what_it_left_out(plugin):
    out = _ok(plugin, examples.SALES_MIX)
    width, height = out["chart"]["size_px"]
    assert width == 1080 and height < 1350
    assert Image.open(out["path"]).size == (width, height)
    assert out["printed_notes"][0] == "図中の数値は構成比（%）で、各行の合計を100%としている"
    assert "その他は各年度とも3%（幅が狭いため図中の数値を省略）" in out["printed_notes"]
    assert "2023年度は国内 54%、北米 20%、欧州 13%、アジア 10%、その他 3%。2025年度は" in out["alt_text"]


def test_narrow_numbers_move_outside_with_a_leader(plugin):
    render = importlib.import_module(f"{PKG}.render")
    spec = importlib.import_module(f"{PKG}.spec")
    fonts = importlib.import_module(f"{PKG}.fonts")
    args = {"data": {"values": [{"年": "2025年", "A": 48, "B": 3, "C": 49}]},
            "chart_spec": {"chart_type": "share_bar", "unit": "件", "source": "サンプル",
                           "encodings": {"x": {"field": "年"}, "y": {"fields": ["A", "B", "C"]}}}}
    plan = spec.build_plan(args)
    d = render.render(plan, fonts.family_list())
    outside = [lbl for lbl, _v, kind in d.labels if kind == "share" and lbl.get_color() == render.INK
               and lbl.get_verticalalignment() in ("top", "bottom")]
    assert outside, "expected at least one number placed beside its band"
    leaders = [ln for ln in d.ax.get_lines() if len(ln.get_xdata()) == 2 and ln.get_xdata()[0] == ln.get_xdata()[1]]
    assert len(leaders) >= len(outside)


def test_monthly_ticks_keep_both_ends(plugin):
    render = importlib.import_module(f"{PKG}.render")
    spec = importlib.import_module(f"{PKG}.spec")
    fonts = importlib.import_module(f"{PKG}.fonts")
    plan = spec.build_plan(copy.deepcopy(examples.MONTHLY_SALES))
    d = render.render(plan, fonts.family_list())
    texts = [t.get_text().split("\n")[0] for t in d.ax.get_xticklabels()]
    assert texts[0] == "4月" and texts[-1] == "3月"
    assert "2025年" in d.ax.get_xticklabels()[0].get_text()


def test_two_notes_are_numbered(plugin):
    args = copy.deepcopy(examples.POPULATION_TOP10)
    args["chart_spec"]["notes"] = ["数値は千人未満を含む", "沖縄県は対象外"]
    render = importlib.import_module(f"{PKG}.render")
    spec = importlib.import_module(f"{PKG}.spec")
    fonts = importlib.import_module(f"{PKG}.fonts")
    d = render.render(spec.build_plan(args), fonts.family_list())
    footer = [t.get_text() for t in d.fig.texts if "出典" in t.get_text()][0]
    assert "注1：数値は千人未満を含む" in footer and "注2：沖縄県は対象外" in footer


def test_readme_images_match_current_layout(plugin):
    """docs/examples must be re-rendered (scripts/render_examples.py) when the layout changes."""
    from helpers import PLUGIN_DIR
    for name, filename in (("POPULATION_TOP10", "population_top10.png"), ("MONTHLY_SALES", "monthly_sales.png"),
                           ("SALES_MIX", "sales_mix.png")):
        out = _ok(plugin, getattr(examples, name))
        assert Image.open(PLUGIN_DIR / "docs" / "examples" / filename).size == tuple(out["chart"]["size_px"]), filename
