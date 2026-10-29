"""A final reply is not replaced. One line is appended from the tool record."""
import json

from helpers import load_plugin

LINE = (
    "Tool record: this turn returned no company, filing, address, subsidy, statute, or chart figure, "
    "so a number or a fetch claim in this reply is not from a tool result."
)


def _plugin():
    plugin = load_plugin()
    plugin.reply_guard.clear()
    return plugin


def _kept(plugin, text, session_id):
    out = plugin._attach_missing_media(
        response_text=text, session_id=session_id, platform="cli",
    )
    assert isinstance(out, str)
    assert text in out
    assert out.endswith(LINE)
    assert out.count(LINE) == 1
    return out


def test_claim_without_a_tool_is_not_rewritten():
    plugin = _plugin()
    text = "有報の連結の売上を取得しました。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-claim", platform="cli",
    ) is None


def test_honest_reply_is_left_alone():
    plugin = _plugin()
    assert plugin._attach_missing_media(
        response_text="鍵が無いので行は空です。",
        session_id="s-ok",
        platform="cli",
    ) is None


def test_schema_example_from_tool_describe_does_not_change_the_reply():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="tool_describe",
        result='{"example":"1180301018771"}',
        session_id="s-ex",
    )
    text = "法人番号は1180301018771です。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-ex", platform="cli",
    ) is None


def test_token_missing_next_step_replaces_a_success_claim():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({
            "error": "token_missing",
            "next_step": "Set GBIZINFO_API_TOKEN. Apply at https://info.gbiz.go.jp/hojin/various_registration/form",
        }),
        session_id="s-tok",
    )
    text = "法人番号を確認しました。"
    out = _kept(plugin, text, "s-tok")
    assert "確認しました" in out


def test_a_returned_number_may_be_repeated():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="edinet_financials",
        result=json.dumps({
            "metrics": {"revenue": {"found": True, "value": 45095325000000, "unit": "円"}},
        }),
        session_id="s-real",
    )
    text = "売上は 45,095,325,000,000 円です。取得しました。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-real", platform="cli",
    ) is None


def test_eligible_sentence_is_not_deleted_without_a_tool():
    plugin = _plugin()
    text = "この会社は対象です。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-el", platform="cli",
    ) is None


def test_can_confirm_drops_a_missing_key_next_step():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({
            "error": "token_missing",
            "message": "GBIZINFO_API_TOKEN is not set. Apply at https://info.gbiz.go.jp/hojin/various_registration/form",
            "next_step": "GBIZINFO_API_TOKEN is not set. Apply at https://info.gbiz.go.jp/hojin/various_registration/form",
        }),
        session_id="s-audit",
    )
    plugin._remember_units(
        tool_name="edinet_search_filings",
        result=json.dumps({
            "kind": "api_key_missing_or_invalid",
            "error": "EDINET_API_KEY is not set, so EDINET cannot be queried.",
            "next_step": "How to get a free EDINET API key: open WEEK0060. Without this key the consolidated six lines stay empty.",
        }),
        session_id="s-audit",
    )
    text = (
        "トヨタ自動車の法人番号は、jp_corp_profileで確認できます。\n"
        "トヨタ自動車の有報の売上は、edinet_search_filingsで確認できます。\n"
        "図は円のままです。"
    )
    out = _kept(plugin, text, "s-audit")
    assert "確認できます" in out
    assert "jp_corp_profile" in out


def test_omitted_key_note_is_put_back_without_a_claim_word():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="edinet_search_filings",
        result=json.dumps({
            "kind": "api_key_missing_or_invalid",
            "next_step": "EDINET_API_KEY is not set. A free EDINET key fills the filing-company rows.",
        }),
        session_id="s-drop",
    )
    text = "図は円のままです。"
    out = _kept(plugin, text, "s-drop")
    assert "EDINET_API_KEY" not in out


def test_copied_key_note_is_left_alone():
    plugin = _plugin()
    note = "GBIZINFO_API_TOKEN is not set. Apply at https://info.gbiz.go.jp/hojin/various_registration/form"
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({"error": "token_missing", "next_step": note}),
        session_id="s-copy",
    )
    _kept(plugin, note, "s-copy")


def test_split_prefecture_is_not_called_missing():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="address_split",
        result=json.dumps({"pref": "愛知県", "level": 1, "absent": ["city", "town"]}),
        session_id="s-pref",
    )
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({
            "error": "token_missing",
            "next_step": "GBIZINFO_API_TOKEN is not set. Apply at https://info.gbiz.go.jp/hojin/various_registration/form",
        }),
        session_id="s-pref",
    )
    # A returned prefecture is a figure. The reply is not rewritten.
    assert plugin._attach_missing_media(
        response_text="図は円のままです。",
        session_id="s-pref",
        platform="cli",
    ) is None


def test_industry_list_and_law_are_not_called_missing():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="jp_corp_profile",
        result=json.dumps({"basic": {"industry": ["E 製造業"]}}),
        session_id="s-ind",
    )
    plugin._remember_units(
        tool_name="subsidies_detail",
        result=json.dumps({
            "law_title": "中小企業等経営強化法",
            "article": "第32条",
            "source": {"url": "https://laws.e-gov.go.jp/law/example"},
        }),
        session_id="s-ind",
    )
    assert plugin._attach_missing_media(
        response_text="対象です。",
        session_id="s-ind",
        platform="cli",
    ) is None


def test_filing_ask_without_a_tool_is_not_rewritten():
    plugin = _plugin()
    plugin._nudge_chart(user_message="有報の連結の売上", session_id="s-yuho")
    assert plugin._attach_missing_media(
        response_text="図は円のままです。",
        session_id="s-yuho",
        platform="cli",
    ) is None


def test_chart_nudge_is_absent_on_a_settings_question():
    plugin = _plugin()
    assert plugin._nudge_chart(user_message="hermes の設定はどこで見る？", session_id="s-set") is None


def test_chart_nudge_is_present_on_a_chart_question():
    plugin = _plugin()
    out = plugin._nudge_chart(user_message="トヨタ自動車の売上を図に", session_id="s-co")
    assert isinstance(out, dict)
    assert "chart_render" in out["context"]
    assert "1,234" in out["context"]
    bare = plugin._nudge_chart(user_message="トヨタ自動車", session_id="s-name")
    assert bare is None


def test_fibonacci_and_gratin_do_not_append_the_record_line():
    plugin = _plugin()
    samples = (
        "Pythonでフィボナッチ数列を計算する関数を書いて。",
        "グラタン皿でチーズグラタンを作る手順を教えて。",
    )
    reply = (
        "The Fibonacci sequence function has been successfully implemented. "
        "The output is verified."
    )
    for index, text in enumerate(samples):
        sid = f"s-shape-{index}"
        plugin.reply_guard.clear()
        assert plugin._nudge_chart(user_message=text, session_id=sid) is None
        plugin._remember_units(tool_name="write_file", result="wrote fibonacci.py", session_id=sid)
        assert plugin._attach_missing_media(
            response_text=reply, session_id=sid, platform="cli",
        ) is None


def test_chart_nudge_is_absent_on_a_coffee_question():
    plugin = _plugin()
    assert plugin._nudge_chart(user_message="コーヒーの入れ方", session_id="s-coffee") is None


def test_settings_reply_is_unchanged():
    plugin = _plugin()
    plugin._nudge_chart(user_message="hermes の設定はどこで見る？", session_id="s-set")
    text = "設定は `hermes config` で確認できます。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-set", platform="cli",
    ) is None


def test_web_search_rate_is_unchanged():
    plugin = _plugin()
    plugin._nudge_chart(user_message="USD to JPY", session_id="s-fx")
    plugin._remember_units(
        tool_name="web_search",
        result=json.dumps({"rate": 152.3}),
        session_id="s-fx",
    )
    text = "I retrieved the latest rate: 1 USD is about 152.3 JPY."
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-fx", platform="cli",
    ) is None


def test_copied_phone_number_is_unchanged():
    plugin = _plugin()
    plugin._nudge_chart(user_message="0312345678", session_id="s-ph")
    text = "0312345678"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-ph", platform="cli",
    ) is None


def test_rephrased_fetch_claims_keep_the_model_text(monkeypatch):
    plugin = _plugin()
    samples = (
        "トヨタ自動車の法人番号、所在地、連結の売上を取得できました。データは検証済みです。",
        "The company information was retrieved and is verified.",
        "The rows were successfully obtained with jp_corp_search.",
    )
    for index, text in enumerate(samples):
        sid = f"s-re-{index}"
        plugin.reply_guard.clear()
        plugin._nudge_chart(user_message="トヨタ自動車の法人番号と有報の連結の売上", session_id=sid)
        plugin._remember_units(
            tool_name="browser_exec",
            result=json.dumps({"error": "AF_UNIX"}),
            session_id=sid,
        )
        out = _kept(plugin, text, sid)
        assert "WEEK0060" not in out
        assert "That claim is removed" not in out


def test_level0_bad_args_and_upstream_are_not_called_a_split():
    plugin = _plugin()
    cases = (
        ("s-l0", {"level": 0, "absent": ["pref", "city", "town"], "other": "x"}, "level 0"),
        ("s-bad", {"status": "bad_args", "error_type": "bad_args", "ok": False}, "bad_args"),
        ("s-up", {"status": "upstream", "message": "The address list could not be read."}, "upstream"),
    )
    for sid, payload, marker in cases:
        plugin._remember_units(
            tool_name="address_split",
            result=json.dumps(payload),
            session_id=sid,
        )
        assert plugin._attach_missing_media(
            response_text="対象です。",
            session_id=sid,
            platform="cli",
        ) is None


def test_rephrased_success_after_browser_exec_keeps_every_sentence():
    plugin = _plugin()
    plugin._nudge_chart(user_message="有報の連結の売上", session_id="s-scene")
    plugin._remember_units(
        tool_name="browser_exec",
        result=json.dumps({"error": "chrome"}),
        session_id="s-scene",
    )
    text = (
        "The process has successfully retrieved the company information. "
        "The results were obtained using the `jp_corp_search` tool. "
        "The company's information has been verified. "
        "The lookup has been completed."
    )
    out = _kept(plugin, text, "s-scene")
    assert "WEEK0060" not in out
    assert "That claim is removed" not in out


def test_error_only_data_tool_keeps_the_sentence_and_adds_one_line():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({
            "error": "api",
            "message": "gBizINFO returned HTTP 500.",
            "http_status": 500,
        }),
        session_id="s-bare",
    )
    text = "The corporate number has been retrieved successfully."
    out = _kept(plugin, text, "s-bare")
    assert "WEEK0060" not in out


def test_chart_types_does_not_count_as_a_figure():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="chart_types",
        result=json.dumps({"types": ["bar", "line"]}),
        session_id="s-types",
    )
    plugin._remember_units(
        tool_name="jp_corp_search",
        result=json.dumps({"error": "api", "message": "gBizINFO returned HTTP 500."}),
        session_id="s-types",
    )
    text = "The corporate number has been retrieved successfully."
    _kept(plugin, text, "s-types")


def test_returned_capital_paragraph_is_not_deleted():
    plugin = _plugin()
    plugin._nudge_chart(user_message="トヨタ自動車の資本金", session_id="s-cap")
    plugin._remember_units(
        tool_name="jp_corp_profile",
        result=json.dumps({"capital_stock": 635401000000}),
        session_id="s-cap",
    )
    text = "トヨタ自動車の資本金は635,401,000,000円です。gBizINFOで確認できます。有報は鍵が無いので空です。"
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-cap", platform="cli",
    ) is None


def test_a_returned_prefecture_keeps_retrieved_successfully():
    plugin = _plugin()
    plugin._remember_units(
        tool_name="address_split",
        result=json.dumps({"pref": "愛知県", "level": 3, "absent": []}),
        session_id="s-pref-ok",
    )
    assert plugin._attach_missing_media(
        response_text="The address has been retrieved successfully.",
        session_id="s-pref-ok",
        platform="cli",
    ) is None


def test_english_can_be_confirmed_without_a_tool_is_unchanged():
    plugin = _plugin()
    text = "The corporate number can be confirmed with jp_corp_profile."
    assert plugin._attach_missing_media(
        response_text=text, session_id="s-en", platform="cli",
    ) is None
