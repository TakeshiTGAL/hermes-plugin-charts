"""jp-charts plugin for Hermes Agent: verified PNG charts that read well on a phone.

Three tools (chart_render, chart_validate, chart_types) and hooks that remember
units, block a mismatched chart, and attach a rendered chart when the model
forgot the MEDIA line (see delivery.py).
"""

# Hermes imports this directory as a package. pytest's collector also imports this
# file on its own (the repo root is the package), where relative imports cannot work.
import logging

if __package__:
    from . import delivery, reply_guard, schemas, tools, turn_scope, unit_guard

logger = logging.getLogger(__name__)

_SKILL_DESCRIPTION = (
    "Draw a bar, line, or share chart as a PNG. "
    "Before web_search, use tool_search to find the chart tools and tool_call to run them. "
    "Do not call tool_describe. Copy the unit string from the tool result. "
    "A comma-grouped number such as 1,234 is that integer. "
    "If no number was returned, do not say a chart was drawn."
)


def _setting(ctx, key, default):
    try:
        value = ctx.get_config(key, default=default)
    except Exception:
        return default
    return default if value is None else value


_CHART_NUDGE = (
    "Call chart_render only with numbers and the unit string copied from a tool result. "
    "Do not call tool_describe. The parameters are known. "
    "A comma-grouped number such as 1,234 is the same integer as 1234. "
    "A different unit blocks the chart. If no number was returned, do not say a chart was drawn "
    "and do not write 取得しました."
)


def _nudge_chart(user_message="", session_id="", conversation_history=None, **_kwargs):
    """Add the chart line only on a chart turn. Other turns get nothing."""
    reply_guard.note_user(session_id or "", user_message, conversation_history)
    facts = reply_guard.facts(session_id or "")
    if not facts.get("chart_talk"):
        return None
    return {"context": _CHART_NUDGE}


def _attach_missing_media(response_text="", session_id="", platform="", **_kwargs):
    replaced = reply_guard.rewrite(session_id or "", response_text or "")
    text = replaced if isinstance(replaced, str) else (response_text or "")
    if not tools.SETTINGS.get("auto_attach", True):
        delivery.take(session_id or "")
        return replaced
    attached = delivery.append_missing_media(text, session_id or "", platform or "")
    if isinstance(attached, str) and attached:
        return attached
    return replaced


def _remember_units(tool_name="", result=None, session_id="", **_kwargs):
    """Observe a tool result. Return None so the result string is left as it is."""
    unit_guard.remember(session_id or "", tool_name or "", result)
    reply_guard.remember(session_id or "", tool_name or "", result)
    return None


def _block_mismatched_unit(tool_name="", args=None, session_id="", **_kwargs):
    if tool_name != "chart_render":
        return None
    message = unit_guard.mismatch_message(
        session_id or "", args if isinstance(args, dict) else {},
    )
    if not message:
        return None
    return {"action": "block", "message": message}


def register(ctx):
    """Register the chart tools under the `charts` toolset, and the attach hook."""
    for key, default in tools.DEFAULT_SETTINGS.items():
        tools.SETTINGS[key] = _setting(ctx, key, default)
    for schema in schemas.ALL_SCHEMAS:
        common = dict(name=schema["name"], toolset="charts", schema=schema,
                      handler=tools.HANDLERS[schema["name"]])
        try:
            ctx.register_tool(**common, description=schema["description"], emoji="📊")
        except TypeError:  # older Hermes without the cosmetic keywords
            logger.warning("jp-charts: this Hermes takes no emoji/description for tools; registering without")
            ctx.register_tool(**common)
    for hook_name, callback in (
        ("transform_llm_output", _attach_missing_media),
        ("transform_tool_result", _remember_units),
        ("pre_tool_call", _block_mismatched_unit),
        ("pre_llm_call", _nudge_chart),
    ):
        try:
            ctx.register_hook(hook_name, callback)
        except Exception as exc:  # a Hermes without this hook: the other hooks still register
            logger.warning("jp-charts: %s hook unavailable (%s)", hook_name, exc)
    try:
        from pathlib import Path
        ctx.register_skill(
            "chart-png",
            Path(__file__).resolve().parent / "skills" / "chart-png" / "SKILL.md",
            description=_SKILL_DESCRIPTION,
        )
    except Exception:
        logger.warning("jp-charts skill was not registered", exc_info=True)
