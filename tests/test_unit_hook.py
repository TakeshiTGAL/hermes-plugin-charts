"""A chart unit that differs from a remembered tool result is blocked before drawing."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_hermes_src = os.environ.get("HERMES_SRC") or ""
HERMES_SRC = Path(_hermes_src) if _hermes_src else None


def _plugin():
    from helpers import load_plugin
    return load_plugin()


def _chart(unit, value):
    return {
        "data": {"values": [{"year": "2024", "revenue": value}]},
        "chart_spec": {
            "chart_type": "line",
            "unit": unit,
            "source": "EDINET S100TR7I",
            "encodings": {"x": {"field": "year"}, "y": {"field": "revenue"}},
        },
    }


def test_remember_does_not_replace_the_result():
    plugin = _plugin()
    payload = json.dumps({
        "metrics": {"revenue": {"found": True, "value": 45095325000000, "unit": "円"}},
    })
    assert plugin._remember_units(
        tool_name="edinet_financials", result=payload, session_id="s-unit",
    ) is None


def test_mismatched_unit_is_blocked_and_the_same_unit_is_not(monkeypatch):
    plugin = _plugin()
    plugin.unit_guard.clear("s-unit")
    plugin._remember_units(
        tool_name="edinet_financials",
        result=json.dumps({
            "metrics": {"revenue": {"found": True, "value": 45095325000000, "unit": "円"}},
        }),
        session_id="s-unit",
    )
    blocked = plugin._block_mismatched_unit(
        tool_name="chart_render", args=_chart("百万円", 45095325000000), session_id="s-unit",
    )
    assert blocked["action"] == "block"
    assert "円" in blocked["message"]
    assert "百万円" in blocked["message"]
    assert "not drawn" in blocked["message"]
    assert plugin._block_mismatched_unit(
        tool_name="chart_render", args=_chart("円", 45095325000000), session_id="s-unit",
    ) is None
    # A number this session has not seen is not blocked.
    assert plugin._block_mismatched_unit(
        tool_name="chart_render", args=_chart("人", 12), session_id="s-unit",
    ) is None
    # found:false must not be remembered as 0 or as a value.
    plugin.unit_guard.clear("s-miss")
    plugin._remember_units(
        tool_name="edinet_financials",
        result=json.dumps({
            "metrics": {"operating_income": {"found": False, "value": None, "unit": None}},
        }),
        session_id="s-miss",
    )
    assert plugin.unit_guard.mismatch_message("s-miss", _chart("円", 1)) is None
    plugin.unit_guard.clear("s-unit")
    plugin.unit_guard.clear("s-miss")


def test_grouped_text_matches_the_integer_the_parser_reads():
    plugin = _plugin()
    plugin.unit_guard.clear("s-comma")
    plugin.reply_guard.clear("s-comma")
    plugin._remember_units(
        tool_name="edinet_financials",
        result=json.dumps({
            "metrics": {"revenue": {"found": True, "value": 45095325000000, "unit": "円"}},
        }),
        session_id="s-comma",
    )
    args = {
        "data": {"text": "45,095,325,000,000"},
        "chart_spec": {
            "chart_type": "line",
            "unit": "百万円",
            "source": "EDINET S100TR7I",
            "encodings": {"x": {"field": "year"}, "y": {"field": "revenue"}},
        },
    }
    blocked = plugin._block_mismatched_unit(
        tool_name="chart_render", args=args, session_id="s-comma",
    )
    assert blocked is not None
    assert blocked["action"] == "block"
    assert "chart_render blocked" in blocked["message"]
    args["chart_spec"]["unit"] = "円"
    assert plugin._block_mismatched_unit(
        tool_name="chart_render", args=args, session_id="s-comma",
    ) is None
    plugin.unit_guard.clear("s-comma")
    plugin.reply_guard.clear("s-comma")


def _module_from_tree(module, root: Path) -> bool:
    if module is None:
        return False
    filename = getattr(module, "__file__", None)
    if filename:
        return Path(filename).resolve().is_relative_to(root)
    return any(Path(entry).resolve().is_relative_to(root) for entry in (getattr(module, "__path__", None) or ()))


def _host_module(name: str) -> bool:
    return name.split(".", 1)[0] in {"tools", "model_tools"}


def _prefer_hermes_imports(monkeypatch):
    """Read Hermes tools and model_tools, not this repo's tools.py, and restore both afterwards.

    The repo root stays ahead of a Hermes tree that is already on sys.path. Importing
    model_tools then loads this repo's tools.py, which fails on a relative import.
    """
    root = HERMES_SRC.resolve()
    monkeypatch.syspath_prepend(str(root))
    for name, module in list(sys.modules.items()):
        if _host_module(name) and not _module_from_tree(module, root):
            monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.invalidate_caches()
    return root


def _import_model_tools(monkeypatch):
    root = _prefer_hermes_imports(monkeypatch)
    present = {name for name in sys.modules if _host_module(name)}
    import model_tools
    for name in list(sys.modules):
        if _host_module(name) and name not in present:
            monkeypatch.setitem(sys.modules, name, sys.modules.pop(name))
    assert _module_from_tree(model_tools, root), getattr(model_tools, "__file__", None)
    assert _module_from_tree(sys.modules["tools"], root), getattr(sys.modules["tools"], "__file__", None)
    return model_tools


@pytest.fixture
def hermes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    if HERMES_SRC is None or not (HERMES_SRC / "hermes_cli" / "plugins.py").is_file():
        pytest.skip("set HERMES_SRC to a Hermes source tree")
    _prefer_hermes_imports(monkeypatch)
    try:
        import hermes_cli.plugins as hp
    except Exception as exc:
        pytest.skip("Hermes source needs a newer Python: " + str(exc))
    plugin = _plugin()
    mgr = hp.PluginManager(scope_key=str(tmp_path))
    mgr._discovered = True
    mgr._hooks["pre_tool_call"] = [plugin._block_mismatched_unit]
    monkeypatch.setattr(hp, "get_plugin_manager", lambda: mgr)
    monkeypatch.setattr(hp, "_plugin_manager", mgr)
    yield hp
    plugin.unit_guard.clear("s-dispatch")


def test_dispatcher_blocks_before_the_handler(hermes, monkeypatch):
    plugin = _plugin()
    plugin.unit_guard.clear("s-dispatch")
    plugin._remember_units(
        tool_name="jp_corp_profile",
        result=json.dumps({
            "lines": [{"line": "revenue", "found": True, "value": 18259979000000, "unit": "円"}],
        }),
        session_id="s-dispatch",
    )
    model_tools = _import_model_tools(monkeypatch)
    called = []
    monkeypatch.setattr(model_tools, "_execute_tool", lambda *_a, **_k: called.append("handler") or "{}")
    blocked = model_tools.handle_function_call(
        "chart_render",
        _chart("億円", 18259979000000),
        session_id="s-dispatch",
        task_id="t1",
    )
    assert called == []
    assert "blocked" in str(blocked)
    assert "円" in str(blocked)
    plugin.unit_guard.clear("s-dispatch")


def _remember_yen(plugin, session_id: str) -> None:
    plugin.unit_guard.remember(
        session_id,
        "edinet_financials",
        {"value": 1200, "unit": "円"},
    )


def test_forty_sessions_each_keep_the_unit_block():
    plugin = _plugin()
    plugin.unit_guard.clear()
    try:
        cap = plugin.unit_guard._MAX_SESSIONS
        for i in range(cap):
            _remember_yen(plugin, f"u{i:02d}")
        for i in range(cap):
            assert plugin.unit_guard.mismatch_message(f"u{i:02d}", _chart("百万円", 1200))
            assert plugin.unit_guard.mismatch_message(f"u{i:02d}", _chart("円", 1200)) is None
    finally:
        plugin.unit_guard.clear()


def test_the_forty_first_session_drops_the_oldest_unit_and_a_refresh_keeps_it():
    plugin = _plugin()
    plugin.unit_guard.clear()
    try:
        cap = plugin.unit_guard._MAX_SESSIONS
        for i in range(cap):
            _remember_yen(plugin, f"u{i:02d}")
        _remember_yen(plugin, "u00")
        _remember_yen(plugin, f"u{cap:02d}")
        assert plugin.unit_guard.mismatch_message("u01", _chart("百万円", 1200)) is None
        assert plugin.unit_guard.mismatch_message("u00", _chart("百万円", 1200))
        assert plugin.unit_guard.mismatch_message(f"u{cap:02d}", _chart("百万円", 1200))
        assert plugin.unit_guard.mismatch_message("u00", _chart("円", 1200)) is None
        assert len(plugin.unit_guard._seen) <= cap
    finally:
        plugin.unit_guard.clear()


def test_clear_one_unit_session_frees_its_slot():
    plugin = _plugin()
    plugin.unit_guard.clear()
    try:
        cap = plugin.unit_guard._MAX_SESSIONS
        for i in range(cap):
            _remember_yen(plugin, f"u{i:02d}")
        plugin.unit_guard.clear("u00")
        _remember_yen(plugin, "extra")
        assert plugin.unit_guard.mismatch_message("u01", _chart("百万円", 1200))
        assert plugin.unit_guard.mismatch_message("extra", _chart("百万円", 1200))
        assert plugin.unit_guard.mismatch_message("u00", _chart("百万円", 1200)) is None
    finally:
        plugin.unit_guard.clear()
