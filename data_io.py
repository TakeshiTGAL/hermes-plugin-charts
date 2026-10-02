"""Turn whatever the agent has into one table: columns + rows.

Accepted shapes for ``data`` (first match wins):

* ``{"values": [{"col": v, ...}, ...]}`` or a bare list of row objects
* ``{"columns": [...], "rows": [[...], ...]}`` (the shape the e-Stat plugin
  returns; its ``unit`` and ``source`` are picked up as defaults)
* ``{"text": "..."}`` (aliases ``csv``, ``tsv``, ``table``): CSV, TSV (a copy
  from Excel), or a Markdown table. Title or note lines around the table are
  skipped, as in an e-Stat CSV download.
* ``{"json": "..."}`` or a JSON string: either of the first two shapes
* ``{"path": "/abs/file.csv"}``: a local .csv/.tsv/.txt/.json file, UTF-8 or
  Shift_JIS. Hidden files and folders and anything under the Hermes home
  (config, .env, sessions) are refused, because parts of a file can come back
  to the model in previews and error messages.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import ChartError

MAX_ROWS = 5000
MAX_FILE_BYTES = 10 * 1024 * 1024
FILE_EXTENSIONS = (".csv", ".tsv", ".txt", ".json")

_DATA_EXAMPLE = {"values": [{"month": "2026-01", "sales": 1200}, {"month": "2026-02", "sales": 1350}]}


@dataclass
class Table:
    columns: List[str]
    rows: List[List[Any]]
    row_labels: List[str]                      # "data row 3", "line 7 of the text"
    hints: Dict[str, str] = field(default_factory=dict)  # unit/source carried with the data
    origin: str = "values"


def load(data: Any) -> Table:
    if data is None or data == {} or data == [] or data == "":
        raise ChartError(
            "empty_data", "No data was given, so there is nothing to draw.",
            where="data",
            fix="Pass the rows to chart: data.values (a list of row objects), data.text "
                "(CSV/TSV/Markdown table pasted as text), data.columns + data.rows, or "
                "data.path (a local .csv/.json file).",
            example=_DATA_EXAMPLE)
    if isinstance(data, list):
        return _from_records(data, "data")
    if isinstance(data, str):
        return _from_string(data, "data")
    if not isinstance(data, dict):
        raise ChartError("bad_data", f"data must be an object, a list or text, not {type(data).__name__}.",
                         where="data", fix="Wrap rows as {\"values\": [...]}.", example=_DATA_EXAMPLE)

    hints = {k: str(data[k]) for k in ("unit", "source") if isinstance(data.get(k), str) and data.get(k)}
    if "values" in data:
        table = _from_records(data["values"], "data.values")
    elif "columns" in data and "rows" in data:
        table = _from_columns(data["columns"], data["rows"])
    elif any(k in data for k in ("text", "csv", "tsv", "table")):
        key = next(k for k in ("text", "csv", "tsv", "table") if k in data)
        table = _from_text(_require_str(data[key], f"data.{key}"), f"data.{key}")
    elif "json" in data:
        table = _from_string(_require_str(data["json"], "data.json"), "data.json")
    elif "path" in data:
        table = _from_file(_require_str(data["path"], "data.path"), "data.path")
    else:
        raise ChartError(
            "bad_data", "data has none of the keys values, columns+rows, text, json or path.",
            where="data", fix="Use one of: data.values, data.columns + data.rows, data.text, "
                              "data.json, data.path.", example=_DATA_EXAMPLE)
    for k, v in hints.items():
        table.hints.setdefault(k, v)
    _check_size(table)
    return table


def _require_str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ChartError("bad_data", f"{where} must be text.", where=where)
    return value


def _check_size(table: Table) -> None:
    if not table.rows:
        raise ChartError(
            "empty_data", "The table has a header but no data rows.", where="data",
            fix="Include at least one data row under the header.", example=_DATA_EXAMPLE)
    if len(table.rows) > MAX_ROWS:
        raise ChartError(
            "too_many_rows", f"{len(table.rows):,} rows is more than a chart can show "
                             f"(limit {MAX_ROWS:,}).", where="data",
            fix="Aggregate first (for example monthly totals, or the top 20 plus 'Other'), "
                "then chart the summary table.")


def _from_records(records: Any, where: str) -> Table:
    if not isinstance(records, list):
        raise ChartError("bad_data", f"{where} must be a list of row objects.", where=where,
                         example=_DATA_EXAMPLE)
    if not records:
        raise ChartError("empty_data", f"{where} is an empty list, so there is nothing to draw.",
                         where=where, fix="Put at least one row in data.values (one object per row), "
                                          "or pass the table as data.text.", example=_DATA_EXAMPLE)
    columns: List[str] = []
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            raise ChartError("bad_data", f"Row {i} of {where} is {type(rec).__name__}, not an object.",
                             where=f"{where}[{i - 1}]",
                             fix="Each row must be an object like {\"column\": value}.",
                             example=_DATA_EXAMPLE)
        for key in rec:
            if str(key) not in columns:
                columns.append(str(key))
    rows = [[rec.get(c, rec.get(_maybe_int(c))) for c in columns] for rec in records]
    labels = [f"data row {i} ({where}[{i - 1}])" for i in range(1, len(rows) + 1)]
    return Table(columns, rows, labels, origin=where)


def _maybe_int(key: str) -> Any:
    try:
        return int(key)
    except ValueError:
        return key


def _from_columns(columns: Any, rows: Any) -> Table:
    if not isinstance(columns, list) or not all(isinstance(c, (str, int, float)) for c in columns):
        raise ChartError("bad_data", "data.columns must be a list of column names.", where="data.columns")
    if not isinstance(rows, list):
        raise ChartError("bad_data", "data.rows must be a list of lists.", where="data.rows")
    cols = _clean_header([str(c) for c in columns], "data.columns")
    out = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, list):
            raise ChartError("bad_data", f"data.rows[{i - 1}] is not a list.", where=f"data.rows[{i - 1}]")
        if len(row) != len(cols):
            raise ChartError(
                "ragged_rows", f"data.rows[{i - 1}] has {len(row)} cells but there are "
                               f"{len(cols)} columns.", where=f"data row {i} (data.rows[{i - 1}])",
                fix="Give every row one cell per column; use null for a missing value.")
        out.append(list(row))
    labels = [f"data row {i} (data.rows[{i - 1}])" for i in range(1, len(out) + 1)]
    return Table(cols, out, labels, origin="data.rows")


def _from_string(text: str, where: str) -> Table:
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ChartError("bad_json", f"{where} looks like JSON but does not parse: {exc.msg}.",
                             where=f"{where}, line {exc.lineno} column {exc.colno}",
                             fix="Fix the JSON, or pass the table as data.text (CSV/TSV).") from None
        if isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], (dict, list)):
            parsed = parsed["data"]
        return load(parsed)
    return _from_text(text, where)


def _from_text(text: str, where: str) -> Table:
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    if not any(ln.strip() for ln in lines):
        raise ChartError("empty_data", f"{where} is empty, so there is nothing to draw.", where=where,
                         fix="Paste the table, header row first.", example="month,sales\n2026-01,1200")
    if sum(1 for ln in lines if ln.strip().startswith("|")) >= 2:
        parsed = _markdown_rows(lines)
    else:
        parsed = _delimited_rows(lines)
    return _table_from_cells(parsed, where)


def _markdown_rows(lines: List[str]):
    out = []
    for n, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set(":- ") and c for c in cells):
            continue  # |---|:--:| separator
        out.append((n, cells))
    return out


def _delimited_rows(lines: List[str]):
    sample = "\n".join(ln for ln in lines if ln.strip())[:4000]
    if "\t" in sample:
        delim = "\t"
    else:
        counts = {d: sample.count(d) for d in (",", ";")}
        delim = max(counts, key=counts.get) if max(counts.values()) else ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    out = []
    for n, cells in enumerate(reader, 1):
        cells = [c.strip() for c in cells]
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            out.append((n, cells))
    return out


def _table_from_cells(parsed, where: str) -> Table:
    widths = Counter(len(c) for _, c in parsed if len(c) >= 2)
    if not widths:
        raise ChartError("bad_table", f"{where} has no row with two or more columns.", where=where,
                         fix="Separate columns with commas or tabs, header row first.",
                         example="month,sales\n2026-01,1200")
    width = widths.most_common(1)[0][0]
    start = next(i for i, (_, c) in enumerate(parsed) if len(c) == width)
    header_line, header = parsed[start]
    columns = _clean_header(header, f"{where}, line {header_line}")
    rows, labels, trailing_notes = [], [], False
    for line_no, cells in parsed[start + 1:]:
        if len(cells) == 1:
            trailing_notes = True  # "注1) ..." or a blank-ish footnote line
            continue
        if trailing_notes and len(cells) != width:
            continue
        if len(cells) < width:
            cells = cells + [""] * (width - len(cells))
        if len(cells) != width:
            raise ChartError(
                "ragged_rows", f"Line {line_no} has {len(cells)} cells but the header has {width}.",
                where=f"{where}, line {line_no}",
                fix="Check for an unquoted comma inside a value (quote it: \"1,234\") or a stray "
                    "delimiter.")
        rows.append(cells)
        labels.append(f"{where}, line {line_no}")
    return Table(columns, rows, labels, origin=where)


def _clean_header(names: List[str], where: str) -> List[str]:
    out = []
    for i, name in enumerate(names, 1):
        name = name.strip().strip('"').strip()
        if not name:
            name = f"column {i}"
        out.append(name)
    dupes = [n for n, c in Counter(out).items() if c > 1]
    if dupes:
        raise ChartError("duplicate_columns", f"Column name {dupes[0]!r} appears more than once.",
                         where=where, fix="Give every column a distinct name.")
    return out


def _hermes_home() -> str:
    try:
        from hermes_constants import get_hermes_home
        return str(get_hermes_home())
    except Exception:  # outside Hermes (tests, scripts)
        return os.path.expanduser(os.environ.get("HERMES_HOME") or "~/.hermes")


def _from_file(path: str, where: str) -> Table:
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        raise ChartError("bad_path", f"{path!r} is not an absolute path.", where=where,
                         fix="Pass the full path, for example /home/me/data/sales.csv.")
    real = os.path.realpath(expanded)  # a link named x.csv must also point at a table file
    if not (expanded.lower().endswith(FILE_EXTENSIONS) and real.lower().endswith(FILE_EXTENSIONS)):
        raise ChartError("bad_path", f"Only {', '.join(FILE_EXTENSIONS)} files can be read.",
                         where=where, fix="Export the sheet as CSV first, or paste it as data.text.")
    if not os.path.isfile(real):
        raise ChartError("file_not_found", f"No file at {path}.", where=where,
                         fix="Check the path; list the folder first if unsure.")
    hermes_home = os.path.realpath(_hermes_home())
    hidden = any(part.startswith(".") for part in real.split(os.sep) if part not in ("", ".", ".."))
    if hidden or real == hermes_home or real.startswith(hermes_home + os.sep):
        raise ChartError(
            "path_not_allowed", "Hidden files and files inside the Hermes home folder are not read.",
            where=where, fix="Copy the table to a normal folder (for example Documents) or paste it "
                             "as data.text.")
    size = os.path.getsize(real)
    if size > MAX_FILE_BYTES:
        raise ChartError("file_too_large", f"The file is {size / 1e6:.1f} MB (limit 10 MB).",
                         where=where, fix="Aggregate the data first and chart the summary.")
    with open(real, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ChartError("bad_encoding", "The file is neither UTF-8 nor Shift_JIS text.", where=where,
                         fix="Save it as UTF-8 CSV.")
    if real.lower().endswith(".json"):
        return _from_string(text, where)
    return _from_text(text, where)
