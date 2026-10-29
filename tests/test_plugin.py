"""Registration matches the manifest; the attach hook behaves."""

from pathlib import Path

import yaml

from helpers import PLUGIN_DIR, call
from mpl import needs_matplotlib
import examples


class FakeCtx:
    def __init__(self, config=None):
        self.tools, self.hooks, self.config = {}, {}, config or {}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        assert toolset == "charts" and schema["name"] == name
        self.tools[name] = handler

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def get_config(self, key, default=None):
        return self.config.get(key, default)


def _yaml(name):
    return yaml.safe_load((PLUGIN_DIR / name).read_text(encoding="utf-8"))


def test_registered_capabilities_match_manifest(plugin):
    ctx = FakeCtx()
    plugin.register(ctx)
    manifest = _yaml("plugin.yaml")
    assert manifest["name"] == "jp-charts"
    assert sorted(ctx.tools) == sorted(manifest["provides_tools"])
    assert sorted(ctx.hooks) == sorted(manifest["provides_hooks"]) == [
        "pre_llm_call", "pre_tool_call", "transform_llm_output", "transform_tool_result",
    ]
    assert manifest["manifest_version"] == 2 and manifest["requires_hermes"] == ">=0.21.4"
    assert not manifest.get("requires_env")
    assert not (PLUGIN_DIR / "catalog-entry.yaml").exists()  # the catalog entry lives in hermes-agent


@needs_matplotlib
def test_settings_flow_from_config(plugin):
    ctx = FakeCtx({"preset": "wide"})
    plugin.register(ctx)
    try:
        out = call(plugin, "chart_render", examples.MONTHLY_SALES)
        assert out["chart"]["preset"] == "wide"
    finally:
        plugin.register(FakeCtx())


@needs_matplotlib
def test_hook_attaches_forgotten_chart_on_telegram(plugin):
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["transform_llm_output"]
    out = call(plugin, "chart_render", examples.POPULATION_TOP10, session_id="tg-1")
    reply = hook(response_text="グラフを作りました。", session_id="tg-1", platform="telegram",
                 model="m", turn_id="t")
    assert reply == f"グラフを作りました。\n\nMEDIA:{out['path']}"
    assert hook(response_text="次の返信", session_id="tg-1", platform="telegram") is None  # sent once


@needs_matplotlib
def test_hook_leaves_replies_alone_when_model_attached_or_terminal(plugin):
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["transform_llm_output"]
    out = call(plugin, "chart_render", examples.POPULATION_TOP10, session_id="s-2")
    assert hook(response_text=f"こちらです\n{out['media']}", session_id="s-2", platform="slack") is None
    call(plugin, "chart_render", examples.POPULATION_TOP10, session_id="s-3")
    assert hook(response_text="done", session_id="s-3", platform="cli") is None
    assert hook(response_text="done", session_id="s-3", platform="telegram") is None  # cleared by cli turn


@needs_matplotlib
def test_hook_leaves_api_server_replies_alone(plugin):
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["transform_llm_output"]
    call(plugin, "chart_render", examples.POPULATION_TOP10, session_id="api-1")
    assert hook(response_text="done", session_id="api-1", platform="api_server") is None


@needs_matplotlib
def test_hook_can_be_turned_off(plugin):
    ctx = FakeCtx({"auto_attach": False})
    plugin.register(ctx)
    try:
        call(plugin, "chart_render", examples.POPULATION_TOP10, session_id="s-4")
        assert ctx.hooks["transform_llm_output"](response_text="x", session_id="s-4", platform="telegram") is None
    finally:
        plugin.register(FakeCtx())


@needs_matplotlib
def test_pngs_go_to_hermes_image_cache(plugin, charts_home):
    out = call(plugin, "chart_render", examples.POPULATION_TOP10)
    assert Path(out["path"]).parent == charts_home / "hermes" / "cache" / "images"


def test_notice_credits_prior_work():
    notice = (PLUGIN_DIR / "NOTICE").read_text(encoding="utf-8")
    assert "microsoft/flint-chart" in notice and "Copyright (c) Microsoft Corporation" in notice
    assert "IPA Font License" in notice and "Okabe" in notice
    license_text = (PLUGIN_DIR / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License") and "TakeshiTGAL" in license_text


def test_loads_without_matplotlib_and_explains_how_to_install(tmp_path):
    """Catalog CI probes register() in a runtime without the plugin's dependencies."""
    import subprocess
    import sys
    script = f"""
import importlib.abc, json, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('matplotlib', 'matplotlib_fontja', 'numpy'):
            raise ImportError(f"No module named {{name!r}}", name=name)
sys.meta_path.insert(0, Block())
sys.path.insert(0, {str(PLUGIN_DIR / 'tests')!r})
from helpers import load_plugin
plugin = load_plugin()
class Ctx:
    tools = []
    def register_tool(self, name, **kw): self.tools.append(name)
    def register_hook(self, *a): pass
    def get_config(self, key, default=None): return default
ctx = Ctx(); plugin.register(ctx)
import examples
out = json.loads(plugin.tools.chart_render(examples.POPULATION_TOP10))
print(json.dumps({{"tools": ctx.tools, "error": out["error"]}}))
"""
    env = {"HERMES_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    import json
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["tools"] == ["chart_render", "chart_validate", "chart_types"]
    assert out["error"]["code"] == "missing_dependency"
    assert "hermes plugins enable jp-charts" in out["error"]["fix"]


def test_registers_on_an_older_hermes():
    """No emoji/description keywords and no transform_llm_output hook: tools still register."""
    from helpers import load_plugin
    plugin = load_plugin()

    class OldCtx:
        def __init__(self):
            self.tools = []

        def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False):
            self.tools.append(name)

        def register_hook(self, name, callback):
            raise ValueError(f"unknown hook {name}")

    ctx = OldCtx()
    plugin.register(ctx)
    assert ctx.tools == ["chart_render", "chart_validate", "chart_types"]
    plugin.register(FakeCtx())
