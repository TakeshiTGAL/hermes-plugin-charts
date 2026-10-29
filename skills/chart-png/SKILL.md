---
name: chart-png
description: "Draw a bar, line, or share chart as a PNG. Before web_search, use tool_search to find the chart tools and tool_call to run them. Do not call tool_describe. Copy the unit string from the tool result. A comma-grouped number such as 1,234 is that integer. If no number was returned, do not say a chart was drawn."
---

For this kind of request, use tool_search to find this plugin's tools before web_search, then call them with tool_call. Write tool_search queries in English (for example: "bar chart").

Tools: `chart_render`, `chart_validate`, `chart_types`. Copy the returned MEDIA line when you send the PNG.

A request in Japanese, such as 「棒グラフにして」, still uses an English tool_search query (for example: "bar chart"). The first call can be flat: `data` as CSV text, `chart_type` `棒グラフ` or `bar`, `unit`, and `source`. When the table has one label column and one number column, encodings are filled in. A pie chart (円グラフ) is refused; the reply says to call again with `chart_type` `share_bar`.

When the numbers come from `edinet_financials` or `jp_corp_profile` finance, copy each line's `unit` string onto `unit`. Do not rewrite `円` as `百万円` or `億円`, and do not divide the numbers. Consolidated and non-consolidated series are two lines only when they share that same unit string. If a plotted number was returned with a different unit, `pre_tool_call` blocks `chart_render` and no image is produced. Say that, and do not invent a chart.
