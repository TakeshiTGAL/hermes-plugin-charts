"""Reading numbers the way people type them, and writing them back for a chart.

Reading accepts what shows up in Japanese spreadsheets and statistics tables:
full-width digits, thousands separators, 万/億/兆 multipliers, a leading △/▲
for negatives, accounting parentheses, and the "no value" marks used by
e-Stat ("-", "…", "x", "***").

Writing uses the same conventions in reverse, so a label can always be read
back by ``parse_number`` (the verifier relies on that).
"""

from __future__ import annotations

import math
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence, Tuple

# Marks that mean "no value" in statistics tables (e-Stat uses -, …, x, ***).
MISSING_MARKS = frozenset({
    "", "-", "--", "−", "–", "—", "―", "…", "...", "‥", "x", "X", "*", "**", "***",
    "na", "n/a", "nan", "null", "none", "#n/a", "#value!", "#div/0!",
})

_MULTIPLIERS = (("兆", 1e12), ("億", 1e8), ("万", 1e4), ("千", 1e3))
_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
# A unit word the caller did not name ("人", "件", "円"): full-width characters only, so
# "12a" stays an error instead of becoming 12.
_TRAILING_UNIT = re.compile(r"[^\x00-\x7f兆億万千]+$")


class NotANumber(ValueError):
    """The text is present but is not a number."""


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text).strip()
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    return s


def parse_number(value, unit: str = "") -> Tuple[Optional[float], bool]:
    """Return ``(number, was_percent)``; ``(None, False)`` means "no value".

    Raises ``NotANumber`` when the text is present but cannot be read. ``unit``
    is stripped from the end first, so "1,200万円" with unit "万円" is 1200, and
    with unit "円" it is 12,000,000.
    """
    if value is None:
        return None, False
    if isinstance(value, bool):
        raise NotANumber(f"{value!r} is a true/false value, not a number")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None, False
        if isinstance(value, float) and math.isinf(value):
            raise NotANumber(f"{value!r} is infinite")
        return float(value), False
    if not isinstance(value, str):
        raise NotANumber(f"{value!r} is a {type(value).__name__}, not a number")

    s = _normalize(value)
    if s.lower() in MISSING_MARKS:
        return None, False
    s = s.replace(",", "").replace("_", "").replace(" ", "")
    u = _normalize(unit).replace(" ", "") if unit else ""
    if u and s.endswith(u) and len(s) > len(u):
        s = s[: -len(u)]

    negative = False
    if s[:1] in ("△", "▲"):
        negative, s = True, s[1:]
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]

    percent = False
    if s.endswith("%"):
        percent, s = True, s[:-1]

    total = _parse_with_multipliers(s)
    if total is None:
        stripped = _TRAILING_UNIT.sub("", s)
        if stripped != s and stripped:
            total = _parse_with_multipliers(stripped)
    if total is None:
        raise NotANumber(f"{value!r} is not a number")
    return (-total if negative else total), percent


def _parse_with_multipliers(s: str) -> Optional[float]:
    """'1億2000万' -> 120000000, '3.5万' -> 35000, '1234' -> 1234."""
    if not s:
        return None
    if _NUM_RE.match(s):
        return float(s)
    rest, total, matched = s, 0.0, False
    sign = 1.0
    if rest[:1] in "+-":
        sign, rest = (-1.0 if rest[0] == "-" else 1.0), rest[1:]
    for mark, factor in _MULTIPLIERS:
        if mark in rest:
            head, rest = rest.split(mark, 1)
            if not head or not _NUM_RE.match(head):
                return None
            total += float(head) * factor
            matched = True
    if rest:
        if not _NUM_RE.match(rest):
            return None
        total += float(rest)
    return sign * total if matched else None


# ---------------------------------------------------------------- formatting

def round_half_up(n: float, decimals: int = 0) -> float:
    """Round the way Japanese reports do (12.5 -> 13), not banker's rounding (12.5 -> 12)."""
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(float(n))).quantize(q, rounding=ROUND_HALF_UP))


def _group(n: float, decimals: int) -> str:
    rounded = round_half_up(abs(n), decimals)
    text = f"{rounded:,.{decimals}f}"
    return ("−" if n < 0 and rounded != 0 else "") + text


def unit_has_multiplier(unit: str) -> bool:
    return any(m in (unit or "") for m in ("千", "万", "億", "兆"))


def choose_style(values: Sequence[float], unit: str, number_format: str, locale: str) -> str:
    """'plain' (1,234,567) or 'ja' (123万) or 'en' (1.2M)."""
    if number_format in ("plain",):
        return "plain"
    if number_format == "compact":
        return "ja" if locale == "ja" else "en"
    peak = max((abs(v) for v in values), default=0.0)
    if unit_has_multiplier(unit) or unit.strip() == "%" or peak < 1e5:
        return "plain"
    return "ja" if locale == "ja" else "en"


def decimals_for(values: Sequence[float], cap: int = 2) -> int:
    """Smallest number of decimals that shows every input value as given (max ``cap``)."""
    best = 0
    for v in values:
        for d in range(cap + 1):
            if abs(round(v, d) - v) < 1e-9 * max(1.0, abs(v)):
                best = max(best, d)
                break
        else:
            best = cap
    return best


def _ja_scale(peak: float) -> Tuple[float, str]:
    if peak >= 1e12:
        return 1e12, "兆"
    if peak >= 1e8:
        return 1e8, "億"
    if peak >= 1e4:
        return 1e4, "万"
    return 1.0, ""


def _en_scale(peak: float) -> Tuple[float, str]:
    if peak >= 1e9:
        return 1e9, "B"
    if peak >= 1e6:
        return 1e6, "M"
    if peak >= 1e3:
        return 1e3, "K"
    return 1.0, ""


def format_value(v: float, style: str, decimals: int = 0) -> str:
    """One data label. Compact styles keep three significant digits."""
    if style == "plain":
        return _group(v, decimals)
    scale, mark = (_ja_scale if style == "ja" else _en_scale)(abs(v))
    if scale == 1.0:
        return _group(v, decimals)
    scaled = v / scale
    d = 0 if abs(scaled) >= 100 else (1 if abs(scaled) >= 10 else 2)
    if style == "ja" and mark == "万":
        d = 0 if abs(scaled) >= 1000 else (1 if abs(scaled) >= 10 else 2)
    text = _group(scaled, d)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + mark


def format_values(values: Sequence[float], style: str, decimals: int = 0) -> list:
    """Data labels for one chart, with one shared scale and one number of decimals.

    "1,405万 / 924万 / 363万" rather than "1,405万 / 923.7万 / 363.3万".
    """
    if style == "plain":
        return [_group(v, decimals) for v in values]
    peak = max((abs(v) for v in values), default=0.0)
    scale, mark = (_ja_scale if style == "ja" else _en_scale)(peak)
    if scale == 1.0:
        return [_group(v, decimals) for v in values]
    top = peak / scale
    d = 0 if top >= 100 else (1 if top >= 10 else 2)
    out = []
    for v in values:
        text = _group(v / scale, d)
        out.append("0" if float(text.replace(",", "").replace("\u2212", "-")) == 0 else text + mark)
    return out


def format_ticks(ticks: Sequence[float], style: str) -> list:
    """Axis tick labels with one shared scale so the labels line up."""
    if style == "plain":
        d = decimals_for(ticks, cap=3)
        return [_group(t, d) for t in ticks]
    peak = max((abs(t) for t in ticks), default=0.0)
    scale, mark = (_ja_scale if style == "ja" else _en_scale)(peak)
    if scale == 1.0:
        d = decimals_for(ticks, cap=3)
        return [_group(t, d) for t in ticks]
    scaled = [t / scale for t in ticks]
    d = decimals_for(scaled, cap=3)
    return ["0" if t == 0 else _group(s, d) + mark for t, s in zip(ticks, scaled)]


def label_tolerance(label: str) -> float:
    """Half a unit of the last digit a label shows, in base units."""
    s = _TRAILING_UNIT.sub("", _normalize(label)) or _normalize(label)
    s = s.replace(",", "").replace("%", "")
    factor = 1.0
    for mark, f in _MULTIPLIERS + (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if s.endswith(mark):
            factor, s = f, s[: -len(mark)]
            break
    decimals = len(s.split(".", 1)[1]) if "." in s else 0
    return 0.5 * (10 ** -decimals) * factor + 1e-9


def parse_label(label: str) -> float:
    """Read a label this module wrote (including K/M/B) back to a number."""
    s = _normalize(label).replace(",", "").replace("%", "")
    for mark, f in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if s.endswith(mark):
            return float(s[:-1]) * f
    number, _ = parse_number(s)
    if number is None:
        raise NotANumber(label)
    return number
