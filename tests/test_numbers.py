import importlib

import pytest

from helpers import load_plugin

numfmt = importlib.import_module(f"{load_plugin().__name__}.numfmt")


@pytest.mark.parametrize("text,unit,expected", [
    ("1,234", "", 1234), ("１２３４", "", 1234), ("3.5万", "", 35000), ("1億2000万", "", 120_000_000),
    ("△120", "", -120), ("▲1,000", "", -1000), ("(2,500)", "", -2500), ("12.5%", "%", 12.5),
    ("1,200万円", "万円", 1200), ("1,200万円", "円", 12_000_000), ("1,234人", "", 1234),
    ("12万人", "", 120_000), (" 42 ", "", 42), (7, "", 7), (2.5, "", 2.5), ("-3", "", -3),
    ("1e3", "", 1000),
])
def test_reads_numbers_people_type(text, unit, expected):
    value, _ = numfmt.parse_number(text, unit)
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("mark", ["", "-", "…", "x", "***", "N/A", None, float("nan")])
def test_no_value_marks(mark):
    assert numfmt.parse_number(mark)[0] is None


@pytest.mark.parametrize("bad", ["abc", "12a", "1.2.3", True, [1]])
def test_rejects_non_numbers(bad):
    with pytest.raises(numfmt.NotANumber):
        numfmt.parse_number(bad)


def test_shared_scale_labels():
    labels = numfmt.format_values([14047594, 9237337, 3633202], "ja")
    assert labels == ["1,405万", "924万", "363万"]
    assert numfmt.format_values([3.2e8, 4.5e7], "ja") == ["3.20億", "0.45億"]
    assert numfmt.format_values([0, 5e4], "ja")[0] == "0"
    assert numfmt.format_values([1234.5, 99.25], "plain", 2) == ["1,234.50", "99.25"]
    assert numfmt.format_values([2.5e6, 4e5], "en") == ["2.50M", "0.40M"]


def test_ticks_share_one_scale():
    assert numfmt.format_ticks([0, 5e6, 1e7, 1.5e7], "ja") == ["0", "500万", "1,000万", "1,500万"]
    assert numfmt.format_ticks([0, 2.5e8, 5e8], "ja") == ["0", "2.5億", "5.0億"]  # one decimals rule per axis
    assert numfmt.format_ticks([0, 0.5, 1.0], "plain") == ["0.0", "0.5", "1.0"]


@pytest.mark.parametrize("value", [0, 7, 999, 12345, 98765, 123456, 7654321, 14047594, 3.2e8, 5.55e11,
                                   1.2e12, -45678, 0.25])
@pytest.mark.parametrize("style", ["ja", "en", "plain"])
def test_every_label_reads_back(value, style):
    label = numfmt.format_values([value], style, numfmt.decimals_for([value]))[0]
    assert abs(numfmt.parse_label(label) - value) <= numfmt.label_tolerance(label)


def test_style_choice():
    assert numfmt.choose_style([14047594], "人", "auto", "ja") == "ja"
    assert numfmt.choose_style([1734], "万円", "auto", "ja") == "plain"
    assert numfmt.choose_style([2e5], "万円", "auto", "ja") == "plain"  # unit already has 万
    assert numfmt.choose_style([2e6], "USD", "auto", "en") == "en"
    assert numfmt.choose_style([2e6], "人", "plain", "ja") == "plain"


def test_rounds_half_up_like_japanese_reports():
    assert numfmt.format_values([12.5], "plain", 0) == ["13"]
    assert numfmt.format_values([0.125], "plain", 2) == ["0.13"]
    assert numfmt.format_values([2.5e7, 1e8], "ja") == ["0.25億", "1.00億"]
    assert numfmt.round_half_up(-2.5) == -3.0


def test_labels_with_units_read_back():
    assert numfmt.parse_label("1,405万人") == 14_050_000
    assert numfmt.label_tolerance("1,405万人") == pytest.approx(5000, rel=1e-6)
