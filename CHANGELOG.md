# Changelog

## 0.1.10

What was understood: company talk treated two katakana characters followed by kanji as a registry name. `Pythonでフィボナッチ数列を計算する関数を書いて。` and `グラタン皿でチーズグラタンを作る手順を教えて。` therefore received the chart paragraph, and a later `write_file` appended the tool-record line. The same shape was copied into the other five books. Pytest before this change, on 0.1.9: 137 passed, 23 skipped.

What changed: `pre_llm_call` adds the chart paragraph only for a chart question (図, グラフ, チャート, or the word chart) or when `chart_render`, `chart_validate`, or `chart_types` was called in the previous turn. A company name and a filing word do not add it. The shared decision is `turn_scope.domains`. It matches a 13-digit corporate number, a legal-form word, a name in the recorded registry table, or a tool from the six books called in the previous turn. It does not match a katakana-kanji shape or a tool name typed in the message. The record line is unchanged: it is still appended only when this turn's tool record has no figure and the turn is in scope. Pytest on this commit: 141 passed, 23 skipped. matplotlib was not installed.

## 0.1.9

What was understood: `transform_llm_output` replaced a whole reply when a word list matched, including a settings answer that said 確認できます, a `web_search` sentence that said "I retrieved" and a rate, and a 10-digit phone number the user had written. The same path deleted a Japanese paragraph that repeated a capital amount a tool had returned, because the sentence split required a space after the period. A success sentence whose wording was not in the list stayed. `chart_types` counted as a data return. `pre_llm_call` added the chart paragraph on every turn. The README said one hook, and its opening section still said a reply is replaced. The catalog on main is version 0.1.0 at `870b5fcb1c9ca3db00f4fe956ee8d860f20ea661`, which registers only `transform_llm_output`.

What changed: the hook no longer replaces or deletes the model's text. It appends one fixed line when the tool record for this turn has no figure and the turn called a tool from the six company books, or called some tool on a company or filing question. Other turns are unchanged. `chart_types` and `chart_validate` are not a figure. `pre_llm_call` adds its paragraph only on a company, filing, or chart question. Company talk is a 13-digit corporate number, a legal-form word, a registry-style name such as トヨタ自動車, or a tool name from the six books. The README lists four hooks, quotes the paragraph, and the opening section states the same rule. Pytest on this commit: 137 passed, 23 skipped. matplotlib was not installed.

## 0.1.8

What was understood: `_CLAIM` matched "retrieved successfully" and did not match "successfully retrieved", "has been verified", "has been completed", or "obtained using". On a securities-report reply those sentences stayed and the free-key paragraph was appended. When a data tool had been called and had returned only an error, with no next_step and no 10-digit number, "retrieved successfully" also stayed, because the tool name alone made `false_claim` false. Pytest before this change, on 0.1.7: 128 passed, 23 skipped.

What changed: those phrases are success claims and are removed. On a securities-report reply they are not left in place while the free-key steps are added. An error-only data-tool result does not keep "retrieved successfully" on other replies either. A prefecture returned by `address_split` still leaves that sentence in place. Pytest on this commit: 131 passed, 23 skipped.

## 0.1.7

What was understood: `_CLAIM` matched "I retrieved" and "can be confirmed" and did not match "have been retrieved successfully" or "has been confirmed". On a securities-report reply, with only `browser_exec` returned, those sentences stayed and the free-key paragraph was appended. `address_split` with no `pref` set `split` from the tool name, so the replacement said the address was split. level 0 lists pref in `absent`. Pytest before this change, on 0.1.6: 126 passed, 23 skipped.

What changed: those two English phrases are success claims and are removed. The free-key paragraph is not appended onto a reply that still contains them. A browser tool does not make the claim true. When `address_split` returned no prefecture, the replacement does not say the address was split. level 0, bad_args, and upstream are separate sentences. Pytest on this commit: 128 passed, 23 skipped. matplotlib was not installed.

## 0.1.6

What was understood: when no long number was returned, `transform_llm_output` added four sentences that the address was not split, that no industry text was copied, and that no article URL was written, without reading the address, industry, or law fields in the tool result. A returned prefecture was then described as missing. A securities-report reply that never called the EDINET tool also omitted the free-key steps. Pytest on this commit: 126 passed, 23 skipped. matplotlib was not installed.

What changed: those sentences follow the tool result. A returned prefecture is named and is not described as missing. Industry text, including a list, is named and is not described as missing. A returned law title and article are named, with `source.url` when present, and the sentence does not say that no article URL was written. When the user asked for a securities report and `EDINET_API_KEY` is unset, the replacement keeps the free-key steps (WEEK0060, five periods, the unit, and the filing URL once a document id is known) unless a tool note already has them. A file date is not invented.

## 0.1.5

What was understood: `transform_llm_output` replaced a reply that said 取得しました or 確認しました, wrote a long number no tool result contained, or said 対象です. On a small model the reply said 確認できます, so the missing-key `next_step` did not reach the screen. Pytest on this commit: 121 passed, 23 skipped. matplotlib was not installed.

What changed: 確認できます, で確認でき, を確認でき, and the English phrases "can be confirmed" and "can be checked" also replace the reply. A missing-key `next_step` that the reply omits is put back when no long number was returned. When no figure was returned, the replacement also says the address was not split, names `absent` by level, says no subsidy was matched and eligibility is `not_claimed`, says no article URL was written, and says no chart was drawn. A reply that repeats a number a tool returned, including one that says 取得しました, is left as it is. Hermes keeps the first non-empty `transform_llm_output`, and this hook is the one that returns that text.

## 0.1.4

What was understood: `pre_tool_call` blocked `chart_render` when `data.values` held an integer already seen with another unit. The same integer written in `data.text` as `45,095,325,000,000` was split on the comma, so it did not match, and the chart was not blocked. The README already said the parser reads `1,234`. A chat reply could also say rows were fetched when no tool had been called. On a small model the skill body was not opened, and the visible reply was that claim.

What changed: the unit check parses comma-grouped text with the same number parser the chart uses, including a numeric string inside `data.values`. `pre_llm_call` tells the model to copy the unit and not to say a chart was drawn when no number was returned. `transform_llm_output` drops a reply that claims a fetch no tool result contained, says 対象です, or writes a long number no tool result contained, and leaves the tool's `next_step` in its place. A reply that repeats a number a tool did return is left as it is. `NOTICE` says this is a separate project and Microsoft does not endorse it.

## 0.1.3

What was understood: `chart_render` checks that the drawn marks match the numbers it was given. It did not know whether that unit string was the unit on the tool result the numbers came from. A reply could label yen as 百万円 and still return a PNG.

What changed: `transform_tool_result` remembers `value` and `unit` pairs from tool results in this process, for the current session only, and returns no string so the result is unchanged. `pre_tool_call` blocks `chart_render` when a plotted number was remembered with a different unit. The chart function does not run. A chart whose numbers were not remembered is unchanged. Profile state is not used, so another company's figures are not stored there.

## 0.1.2

A top-level `chart_type`, `unit`, `source`, and the other chart_spec fields are folded into `chart_spec` before the unknown-key check. `chart_spec` stays optional in the schema because that flat form fills it. Japanese chart names (棒グラフ, 横棒グラフ, 折れ線グラフ, 積み上げ棒グラフ, 構成比, 帯グラフ) map onto the existing types. 円グラフ is still refused, and the reply names `share_bar`.

## 0.1.1

Adds the `chart-png` skill. It tells the model to find the chart tools with tool_search before web_search. It does not set requires_toolsets, so it stays in the model's skill list when Tool Search is left at its default, which hides this plugin's tools.

top_n written as 10.0 or fullwidth digits is accepted. chart_type in any letter case and slash-separated dates are accepted, as before, and tests now check them. Extra arguments and a top_n outside the range are refused with a fix and an example, and the caller's value is not copied into the message.

The first sentence Tool Search shows now uses the words a person would ask with. A sentence that starts by describing the mechanism is not found, and the model falls through to the built-in web_search.

Rendering tests skip when the declared matplotlib packages are not installed. The missing-library reply is unchanged.
