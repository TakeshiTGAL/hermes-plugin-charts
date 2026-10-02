"""jp-charts plugin for Hermes Agent: verified PNG charts that read well on a phone.

Three tools (chart_render, chart_validate, chart_types) and one optional
output hook that attaches a rendered chart to a chat reply when the model
forgot the MEDIA line (see delivery.py).
"""

# Hermes imports this directory as a package. pytest's collector also imports this
# file on its own (the repo root is the package), where relative imports cannot work.
import logging

if __package__:
    from . import delivery, schemas, tools

logger = logging.getLogger(__name__)


def _setting(ctx, key, default):
    try:
        value = ctx.get_config(key, default=default)
    except Exception:
        return default
    return default if value is None else value


def _attach_missing_media(response_text="", session_id="", platform="", **_kwargs):
    if not tools.SETTINGS.get("auto_attach", True):
        delivery.take(session_id or "")
        return None
    return delivery.append_missing_media(response_text, session_id or "", platform or "")


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
    try:
        ctx.register_hook("transform_llm_output", _attach_missing_media)
    except Exception as exc:  # a Hermes without this hook: charts still work, the model attaches them
        logger.warning("jp-charts: transform_llm_output hook unavailable (%s); charts are sent only when "
                       "the reply includes the MEDIA line", exc)
