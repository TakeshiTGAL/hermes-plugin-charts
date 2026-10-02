import importlib

import pytest

from helpers import load_plugin

PKG = load_plugin().__name__
data_io = importlib.import_module(f"{PKG}.data_io")
ChartError = importlib.import_module(f"{PKG}.errors").ChartError


def test_values():
    t = data_io.load({"values": [{"a": "x", "b": 1}, {"a": "y", "b": 2}]})
    assert t.columns == ["a", "b"] and t.rows == [["x", 1], ["y", 2]]
    assert t.row_labels[1].startswith("data row 2")


def test_estat_result_passes_unit_and_source():
    t = data_io.load({"table": "人口推計", "unit": "千人", "columns": ["地域", "value"],
                      "rows": [["東京都", 14086], ["大阪府", "-"]], "source": "e-Stat 人口推計"})
    assert t.hints == {"unit": "千人", "source": "e-Stat 人口推計"}
    assert t.rows[1] == ["大阪府", "-"]


def test_csv_with_title_lines_and_footnotes():
    text = ("表1 月別売上\n単位：万円\n月,売上,費用\n2026-01,\"1,200\",800\n2026-02,1350,820\n"
            "注1) 税抜き\n")
    t = data_io.load({"text": text})
    assert t.columns == ["月", "売上", "費用"]
    assert t.rows == [["2026-01", "1,200", "800"], ["2026-02", "1350", "820"]]
    assert t.row_labels[0] == "data.text, line 4"


def test_tsv_from_excel():
    t = data_io.load({"text": "地域\t人口\n東京都\t14047594\n"})
    assert t.rows == [["東京都", "14047594"]]


def test_markdown_table():
    t = data_io.load({"table": "| 年 | 国内 |\n|---|---:|\n| 2024 | 6,480 |\n"})
    assert t.columns == ["年", "国内"] and t.rows == [["2024", "6,480"]]


def test_json_string_and_bare_list():
    assert data_io.load('[{"a": "x", "b": 1}]').rows == [["x", 1]]
    assert data_io.load({"json": '{"columns": ["a","b"], "rows": [["x", 2]]}'}).rows == [["x", 2]]
    assert data_io.load([{"a": "x", "b": 3}]).rows == [["x", 3]]


def test_shift_jis_file(tmp_path):
    path = tmp_path / "pop.csv"
    path.write_bytes("都道府県,人口\n東京都,14047594\n".encode("cp932"))
    t = data_io.load({"path": str(path)})
    assert t.rows == [["東京都", "14047594"]]


@pytest.mark.parametrize("data", [None, {}, [], "", {"values": []}, {"text": "   "}, {"text": "a,b\n"}])
def test_empty_data_says_what_to_pass(data):
    with pytest.raises(ChartError) as exc:
        data_io.load(data)
    assert exc.value.code == "empty_data"
    assert exc.value.fix and exc.value.example is not None


def test_ragged_csv_points_at_the_line():
    with pytest.raises(ChartError) as exc:
        data_io.load({"text": "月,売上\n2026-01,1200\n2026-02,1,350,9\n"})
    assert exc.value.code == "ragged_rows"
    assert "line 3" in exc.value.where
    assert "quote" in exc.value.fix


def test_file_rules(tmp_path):
    with pytest.raises(ChartError) as exc:
        data_io.load({"path": "data.csv"})
    assert exc.value.code == "bad_path"
    with pytest.raises(ChartError) as exc:
        data_io.load({"path": str(tmp_path / "secret.key")})
    assert exc.value.code == "bad_path"
    with pytest.raises(ChartError) as exc:
        data_io.load({"path": str(tmp_path / "missing.csv")})
    assert exc.value.code == "file_not_found"


def test_bad_json_points_at_position():
    with pytest.raises(ChartError) as exc:
        data_io.load({"json": '[{"a": 1,}]'})
    assert exc.value.code == "bad_json" and "line 1" in exc.value.where


def test_hidden_and_hermes_home_paths_are_refused(tmp_path, monkeypatch):
    hidden = tmp_path / ".secrets" / "keys.csv"
    hidden.parent.mkdir()
    hidden.write_text("a,b\nx,1\n")
    with pytest.raises(ChartError) as exc:
        data_io.load({"path": str(hidden)})
    assert exc.value.code == "path_not_allowed"
    home = tmp_path / "hh"
    (home / "sessions").mkdir(parents=True)
    inside = home / "sessions" / "log.json"
    inside.write_text('[{"a": "x", "b": 1}]')
    monkeypatch.setenv("HERMES_HOME", str(home))
    with pytest.raises(ChartError) as exc:
        data_io.load({"path": str(inside)})
    assert exc.value.code == "path_not_allowed"


def test_url_alias_is_gone():
    with pytest.raises(ChartError) as exc:
        data_io.load({"url": "/tmp/x.csv"})
    assert exc.value.code == "bad_data"
