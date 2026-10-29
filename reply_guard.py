"""Append one line when this turn's tool record has no figure.

Process-local. Other plugins are not imported. The hook arguments used here
are the public ones: tool_name, result, response_text, session_id, user_message.
The model's sentences are not deleted. Bridge tools are ignored, because a
schema example is not a fetched figure.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

try:
    from . import turn_scope
except ImportError:
    import turn_scope

_SKIP = frozenset({"tool_search", "tool_describe", "tool_call"})
# Public tool names of the company, filing, address, subsidy, statute, and chart plugins.
# A browser or search tool is not one of those results. This file does not import them.
# chart_types and chart_validate are calls, not a figure that backs a number.
_NON_FIGURE = frozenset({"chart_types", "chart_validate"})
# One fixed line. The model's sentences stay. Success wording is not matched.
RECORD_LINE = (
    "Tool record: this turn returned no company, filing, address, subsidy, statute, or chart figure, "
    "so a number or a fetch claim in this reply is not from a tool result."
)
_DATA_TOOLS = frozenset({
    "jp_corp_search",
    "jp_corp_profile",
    "edinet_search_filings",
    "edinet_financials",
    "edinet_save_document",
    "address_split",
    "subsidies_search",
    "subsidies_detail",
    "subsidies_watch_setup",
    "egov_law_search",
    "egov_law_article",
    "egov_law_revisions",
    "chart_render",
    "chart_validate",
    "chart_types",
})
_GROUP_COMMA = re.compile(r"(?<=\d),(?=\d)")
_LONG_DIGITS = re.compile(r"\d{10,}")
_MAX_NOTES = 6
_MAX_DIGITS = 400
_called: dict[str, set[str]] = {}
_notes: dict[str, list[str]] = {}
_digits: dict[str, set[str]] = {}
_facts: dict[str, dict] = {}


def _blank() -> dict:
    return {
        "pref": "",
        "address": False,
        "split": False,
        "industries": [],
        "law_title": "",
        "article": "",
        "law_url": "",
        "asked_filing": False,
        "company_talk": False,
        "chart_talk": False,
        "split_kind": "",
        "bare_errors": 0,
        "data_ok": False,
        "figure": False,
    }


def _substantive(node: Any) -> bool:
    """A returned row: a prefecture, an industry, a law, a metric, or a capital figure."""
    found = {"ok": False}

    def walk(item: Any) -> None:
        if found["ok"] or item is None:
            return
        if isinstance(item, dict):
            pref = item.get("pref")
            if isinstance(pref, str) and pref.strip():
                found["ok"] = True
                return
            industry = item.get("industry")
            if industry not in (None, "", [], {}):
                found["ok"] = True
                return
            title = item.get("law_title") or item.get("law")
            article = item.get("article")
            if isinstance(title, str) and title.strip() and article not in (None, ""):
                found["ok"] = True
                return
            for key in ("corporate_number", "metrics", "capital_stock", "value", "amount"):
                value = item.get(key)
                if value not in (None, "", [], {}, 0, False):
                    found["ok"] = True
                    return
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return found["ok"]


def _is_figure(tool_name: str, result: Any) -> bool:
    """True when this area-A tool returned a figure. A type list is not a figure."""
    if tool_name not in _DATA_TOOLS or tool_name in _NON_FIGURE:
        return False
    if _bare_error(result):
        return False
    raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    if _long_digits(raw):
        return True
    if tool_name == "chart_render":
        return True
    return _substantive(_parse(result))


def clear(session_id: Optional[str] = None) -> None:
    if session_id is None:
        _called.clear()
        _notes.clear()
        _digits.clear()
        _facts.clear()
        return
    _called.pop(session_id, None)
    _notes.pop(session_id, None)
    _digits.pop(session_id, None)
    _facts.pop(session_id, None)


def _parse(result: Any) -> Any:
    if isinstance(result, str):
        text = result.strip()
        if not text or text[0] not in "{[":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return result


def _note(result: Any) -> str:
    payload = _parse(result)
    if not isinstance(payload, dict):
        return ""
    text = payload.get("next_step") or ""
    if not isinstance(text, str) or not text.strip():
        kind = str(payload.get("kind") or "")
        error = str(payload.get("error") or "")
        if error == "token_missing" or kind == "api_key_missing_or_invalid":
            text = payload.get("message") or ""
        else:
            text = ""
    if not isinstance(text, str):
        return ""
    return text.strip()[:1500]


def _bare_error(result: Any) -> bool:
    """A data-tool payload that is only an error: no next_step and no 10-digit number."""
    payload = _parse(result)
    if not isinstance(payload, dict):
        return False
    raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    if _long_digits(raw) or _note(result):
        return False
    error = payload.get("error")
    status = str(payload.get("status") or "")
    if isinstance(error, str) and error.strip():
        return True
    if status in {"bad_args", "upstream", "error"}:
        return True
    return payload.get("ok") is False


def _long_digits(text: str) -> set[str]:
    flat = _GROUP_COMMA.sub("", text)
    return set(_LONG_DIGITS.findall(flat))


def facts(session_id: str) -> dict:
    raw = _facts.get(session_id or "")
    if not raw:
        return _blank()
    return dict(raw)


def note_user(session_id: str, user_message: Any, conversation_history: Any = None) -> None:
    """Start this turn. Tool results from an earlier turn do not back this reply.

    Company talk is a 13-digit number, a legal-form word, a recorded registry
    name, or jp_corp_search / jp_corp_profile called in the previous turn.
    A chart question is separate. A katakana-kanji shape is not company talk.
    """
    sid = session_id or ""
    _called.pop(sid, None)
    _notes.pop(sid, None)
    _digits.pop(sid, None)
    scopes = turn_scope.domains(user_message, conversation_history)
    facts_now = _blank()
    facts_now["asked_filing"] = "filing" in scopes
    facts_now["company_talk"] = "company" in scopes
    facts_now["chart_talk"] = "chart" in scopes
    _facts[sid] = facts_now


def _take_industry(item: Any, found: list[str]) -> None:
    if isinstance(item, str):
        text = item.strip()
        if text and text not in found and len(found) < 8:
            found.append(text)
    elif isinstance(item, list):
        for part in item:
            _take_industry(part, found)


def _note_split(facts: dict, payload: Any) -> None:
    """Remember an address_split that returned no prefecture.

    Calling the tool is not a split. level 0, bad_args, and upstream stay distinct.
    """
    if not isinstance(payload, dict):
        return
    pref = payload.get("pref") if isinstance(payload.get("pref"), str) else ""
    if pref.strip():
        return
    status = str(payload.get("status") or "")
    error_type = str(payload.get("error_type") or "")
    level = payload.get("level")
    absent = payload.get("absent")
    kind = ""
    if status == "bad_args" or error_type == "bad_args":
        kind = "bad_args"
    elif status == "upstream":
        kind = "upstream"
    elif level == 0 or (isinstance(absent, list) and "pref" in absent):
        kind = "level0"
    if kind:
        facts["split_kind"] = kind


def _absorb(sid: str, tool_name: str, result: Any) -> None:
    payload = _parse(result)
    facts = _facts.setdefault(sid, _blank())
    if tool_name == "address_split":
        _note_split(facts, payload)
    titles: list[str] = []
    articles: list[str] = []
    urls: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            pref = node.get("pref")
            if isinstance(pref, str) and pref.strip():
                facts["pref"] = pref.strip()
                facts["split"] = True
            for key in ("address", "location"):
                item = node.get(key)
                if isinstance(item, str) and item.strip():
                    facts["address"] = True
            if "industry" in node:
                _take_industry(node.get("industry"), facts["industries"])
            raw_title = node.get("law_title")
            if not isinstance(raw_title, str) or not raw_title.strip():
                raw_title = node.get("law")
            if isinstance(raw_title, str) and raw_title.strip():
                titles.append(raw_title.strip())
            article = node.get("article")
            if isinstance(article, str) and article.strip():
                articles.append(article.strip())
            elif isinstance(article, int) and not isinstance(article, bool):
                articles.append(str(article))
            source = node.get("source")
            if isinstance(source, dict):
                url = source.get("url")
                if isinstance(url, str) and url.strip():
                    urls.append(url.strip())
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if titles and articles and not facts["law_title"]:
        facts["law_title"] = titles[0]
        facts["article"] = articles[0]
        if urls:
            facts["law_url"] = urls[0]


def remember(session_id: str, tool_name: str, result: Any) -> None:
    if tool_name in _SKIP:
        return
    sid = session_id or ""
    _called.setdefault(sid, set()).add(tool_name or "")
    raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    bucket = _digits.setdefault(sid, set())
    for number in _long_digits(raw):
        bucket.add(number)
        if len(bucket) >= _MAX_DIGITS:
            break
    _absorb(sid, tool_name or "", result)
    note = _note(result)
    if note:
        notes = _notes.setdefault(sid, [])
        if note not in notes:
            notes.append(note)
        del notes[:-_MAX_NOTES]
    if _is_figure(tool_name or "", result):
        facts = _facts.setdefault(sid, _blank())
        facts["figure"] = True


def rewrite(session_id: str, response_text: str) -> Optional[str]:
    """Append one line, or leave the reply untouched.

    The model's sentences are not deleted and not replaced. The line is added
    only when this turn's tool record has no figure and the turn is in scope:
    a tool from the six books was called, or some tool was called on a company
    or filing question. A settings reply, a web_search result, and a copied
    phone number are outside that scope, so they are returned unchanged.
    address_split owns its own reply, so this hook does not take that turn.
    """
    if not isinstance(response_text, str) or not response_text.strip():
        return None
    sid = session_id or ""
    if _facts.get(sid, _blank()).get("figure"):
        return None
    called = {name for name in _called.get(sid, set()) if name}
    area = called & _DATA_TOOLS
    if area and area <= {"address_split"}:
        return None
    facts_now = _facts.get(sid, _blank())
    in_book = bool(area) or (
        bool(called)
        and (facts_now.get("company_talk") or facts_now.get("asked_filing"))
    )
    if not in_book:
        return None
    if RECORD_LINE in response_text:
        return None
    return response_text.rstrip() + "\n" + RECORD_LINE
