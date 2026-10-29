"""Remember units seen on tool results and block a chart that relabels them.

The memory is process-local and keyed by session. It is not plugin profile state,
so one company's figures are not written into another profile's JSON.
Other plugins are not imported. The walk looks only for objects that already
carry a numeric `value` and a string `unit`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import OrderedDict
from typing import Any, Optional

if __package__:
    from .numfmt import NotANumber, parse_number
else:
    from numfmt import NotANumber, parse_number

# Grouped thousands (1,234 and 45,095,325,000,000) before a plain integer, so a
# comma is a grouping mark and not a split between numbers. 万/億 stay one token.
_NUMBER_SPAN = re.compile(
    r"[△▲(（]?\d{1,3}(?:,\d{3})+(?:\.\d+)?[)）]?"
    r"|[△▲(（]?\d+(?:\.\d+)?(?:兆|億|万|千)?[)）]?"
)

_MAX = 400
_SKIP_TOOLS = frozenset({"chart_render", "chart_validate", "chart_types"})
_seen: dict[str, "OrderedDict[str, set[str]]"] = {}


def clear(session_id: Optional[str] = None) -> None:
    if session_id is None:
        _seen.clear()
    else:
        _seen.pop(session_id, None)


def _key(value: Any) -> Optional[str]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        if value == 0:
            return None
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        if value == 0:
            return None
        return str(value)
    return None


def _walk(node: Any, found: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        if node.get("found") is not False:
            key = _key(node.get("value"))
            unit = node.get("unit")
            if key and isinstance(unit, str) and unit.strip():
                found.append((key, unit.strip()))
        for child in node.values():
            _walk(child, found)
    elif isinstance(node, list):
        for child in node:
            _walk(child, found)


def remember(session_id: str, tool_name: str, result: Any) -> None:
    if tool_name in _SKIP_TOOLS:
        return
    payload = result
    if isinstance(result, str):
        text = result.strip()
        if not text or text[0] not in "{[":
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
    pairs: list[tuple[str, str]] = []
    _walk(payload, pairs)
    if not pairs:
        return
    bucket = _seen.setdefault(session_id, OrderedDict())
    for key, unit in pairs:
        units = bucket.get(key)
        if units is None:
            units = set()
            bucket[key] = units
        units.add(unit)
        bucket.move_to_end(key)
    while len(bucket) > _MAX:
        bucket.popitem(last=False)


def _chart_unit(args: dict) -> str:
    sources = [args]
    spec = args.get("chart_spec")
    data = args.get("data")
    if isinstance(spec, dict):
        sources.append(spec)
    if isinstance(data, dict):
        sources.append(data)
    for source in sources:
        unit = source.get("unit")
        if isinstance(unit, str) and unit.strip():
            return unit.strip()
    return ""


def _numbers_in_text(raw: str, keys: set[str]) -> None:
    """Read 1,234 and 45,095,325,000,000 as one integer, the same way numfmt does."""
    text = unicodedata.normalize("NFKC", raw)
    for match in _NUMBER_SPAN.finditer(text):
        try:
            number, _was_percent = parse_number(match.group(0))
        except NotANumber:
            continue
        if number is None:
            continue
        key = _key(number)
        if key:
            keys.add(key)


def _take_numbers(node: Any, keys: set[str]) -> None:
    if isinstance(node, dict):
        for child in node.values():
            _take_numbers(child, keys)
    elif isinstance(node, list):
        for child in node:
            _take_numbers(child, keys)
    elif isinstance(node, str):
        _numbers_in_text(node, keys)
    else:
        key = _key(node)
        if key:
            keys.add(key)


def _chart_numbers(args: dict) -> set[str]:
    keys: set[str] = set()
    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    _take_numbers(data.get("values"), keys)
    _take_numbers(data.get("rows"), keys)
    text = data.get("json") if isinstance(data.get("json"), str) else ""
    if text.strip()[:1] in "{[":
        try:
            _take_numbers(json.loads(text), keys)
        except json.JSONDecodeError:
            pass
    raw = data.get("text") if isinstance(data.get("text"), str) else ""
    if raw:
        _numbers_in_text(raw, keys)
    return keys


def mismatch_message(session_id: str, args: dict) -> Optional[str]:
    unit = _chart_unit(args)
    bucket = _seen.get(session_id) or {}
    for key in _chart_numbers(args):
        recorded = bucket.get(key)
        if not recorded or unit in recorded:
            continue
        recorded_text = ", ".join(sorted(recorded))
        shown = unit or "(empty)"
        return (
            f"chart_render blocked: {key} was returned with unit {recorded_text}. "
            f"The chart unit is {shown}. "
            "Copy the unit string from the tool result. The chart was not drawn."
        )
    return None
