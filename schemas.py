"""Tool schemas: what the model reads to decide when and how to call each tool."""

_ENCODING = {
    "type": "object",
    "properties": {
        "field": {"type": "string", "description": "Column name."},
        "fields": {"type": "array", "items": {"type": "string"},
                   "description": "y only: several number columns (grouped bars, several lines, or the "
                                  "parts of a stacked/share bar)."},
        "title": {"type": "string", "description": "Axis title; defaults to the column name."},
    },
}

_DATA = {
    "type": "object",
    "description": (
        "The table to draw. Give exactly one of: values (row objects), columns + rows, text (CSV, "
        "TSV copied from Excel, or a Markdown table), json (JSON text), or path (absolute path of a "
        "local .csv/.tsv/.txt/.json; hidden files and the Hermes home folder are refused). An "
        "estat_get_data result can be passed as data unchanged."),
    "properties": {
        "values": {"type": "array", "items": {"type": "object"},
                   "description": "Rows, e.g. [{\"月\": \"2026-01\", \"売上\": 1200}]."},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array"}},
        "text": {"type": "string", "description": "Pasted table text, header row first."},
        "json": {"type": "string"},
        "path": {"type": "string"},
        "unit": {"type": "string", "description": "Used when chart_spec.unit is not given."},
        "source": {"type": "string", "description": "Used when chart_spec.source is not given."},
    },
}

_CHART_SPEC = {
    "type": "object",
    "description": "What to draw. x is always the category/date column and y the numbers, for "
                   "horizontal bars too.",
    "properties": {
        "chart_type": {"type": "string",
                       "enum": ["bar", "line", "stacked_bar", "share_bar",
                                "棒グラフ", "横棒グラフ", "折れ線グラフ", "積み上げ棒グラフ",
                                "構成比", "帯グラフ", "円グラフ"],
                       "description": "bar (棒グラフ): compare categories. line (折れ線グラフ): change over time. "
                                      "stacked_bar (積み上げ棒グラフ): totals and their parts. "
                                      "share_bar (構成比): composition in % (use instead of a pie chart)."},
        "title": {"type": "string", "description": "Headline. Say what the reader should see."},
        "subtitle": {"type": "string", "description": "Optional: who/what/when is measured."},
        "unit": {"type": "string", "description": "REQUIRED. What one number counts, as given in the "
                                                  "data: 人, 万円, 円, %, 件, kWh, index (2020=100)."},
        "source": {"type": "string", "description": "REQUIRED. Publisher and date of the numbers. If "
                                                    "the user typed them: 'ユーザー提供データ' or 'Data "
                                                    "provided by the user'."},
        "encodings": {
            "type": "object",
            "properties": {"x": _ENCODING, "y": _ENCODING,
                           "color": {"type": "object", "properties": {"field": {"type": "string"}},
                                     "description": "Series column of a long table (one row per "
                                                    "category and series)."}},
        },
        "orientation": {"type": "string", "enum": ["auto", "horizontal", "vertical"]},
        "sort": {"type": "string", "enum": ["auto", "desc", "asc", "none"],
                 "description": "auto: bars largest first, dates in time order."},
        "top_n": {"type": "integer", "description": "Keep the first N categories after sorting; the "
                                                    "chart notes 'top N of M'."},
        "highlight": {"type": "array", "items": {"type": "string"},
                      "description": "Single-series bar: categories to color; the rest turn grey."},
        "y_zero": {"type": "boolean", "description": "Line charts only. Default true. false lets the "
                                                    "axis start above zero and prints a note saying so."},
        "notes": {"type": "array", "items": {"type": "string"},
                  "description": "Footnotes printed under the chart."},
    },
    "required": ["chart_type", "unit", "source"],
}

_OUTPUT = {
    "type": "object",
    "properties": {
        "preset": {"type": "string", "enum": ["mobile", "square", "wide"],
                   "description": "mobile 1080x1350 (default, for chat apps on phones), square "
                                  "1080x1080, wide 1600x900 (slides and reports)."},
        "locale": {"type": "string", "enum": ["auto", "ja", "en"]},
        "number_format": {"type": "string", "enum": ["auto", "plain", "compact"],
                          "description": "auto writes 1,418万 / 3.2億 (or 1.4M) for large numbers."},
        "filename": {"type": "string", "description": "Optional file name (letters, digits, - _)."},
    },
}

_RENDER_PARAMS = {
    "type": "object",
    "properties": {
        "data": _DATA,
        "chart_spec": _CHART_SPEC,
        "chart_type": {"type": "string",
                       "description": "Flat form of chart_spec.chart_type. Used when chart_spec omits it."},
        "unit": {"type": "string",
                 "description": "Flat form of chart_spec.unit. Used when chart_spec omits it."},
        "source": {"type": "string",
                   "description": "Flat form of chart_spec.source. Used when chart_spec omits it."},
        "title": {"type": "string",
                  "description": "Flat form of chart_spec.title. Used when chart_spec omits it."},
        "field_display_names": {"type": "object",
                                "description": "Column name -> label to print, e.g. {\"pop\": \"人口\"}."},
        "output": _OUTPUT,
    },
    "required": ["data"],
}

CHART_RENDER = {
    "name": "chart_render",
    "description": (
        "Draw a bar, line, or share chart as a PNG. "
        "Every drawn bar, point and printed number is read back and compared with the input before "
        "the image is returned. Japanese text, 万/億 number formatting, color-blind-safe colors, axis titles with "
        "units and a source line are built in; bars always start at zero. Use it whenever the user "
        "wants to see numbers as a graph or needs a chart image for a report or a chat. To send the "
        "chart, copy the returned media line (MEDIA:/path.png) onto its own line in your reply; in a "
        "terminal, give the path. A share chart shows a percentage, including a stacked bar. "
        "Use alt_text from the result as the caption. On an error, follow "
        "error.fix and call again. Make or generate a graph from spreadsheet rows, with Japanese labels. "
        "Keywords: chart, graph, plot, visualize, image, report, sales, "
        "population, statistics."),
    "parameters": _RENDER_PARAMS,
}

CHART_VALIDATE = {
    "name": "chart_validate",
    "description": (
        "Check a chart table before a PNG is drawn. "
        "It reads the data, reports the row and column at fault, and shows categories, series, unit, and sort. "
        "Takes the same arguments as chart_render."),
    "parameters": _RENDER_PARAMS,
}

CHART_TYPES = {
    "name": "chart_types",
    "description": (
        "List chart types for a bar, line, or share graph. "
        "It names when to use each, the encodings, data formats, size presets, and limits."),
    "parameters": {
        "type": "object",
        "properties": {"chart_type": {"type": "string", "enum": ["bar", "line", "stacked_bar", "share_bar"],
                                      "description": "Optional: only this type."}},
    },
}

ALL_SCHEMAS = [CHART_RENDER, CHART_VALIDATE, CHART_TYPES]
