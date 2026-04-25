"""Module-ID: tools.generate_html_report

Purpose: Generate lightweight static HTML analysis reports.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


def _fmt_number(value: Any, *, digits: int = 2, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,.{digits}f}{suffix}"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return "-"


def _params_preview(params: dict[str, Any]) -> str:
    if not params:
        return "-"
    parts = [f"{key}={value}" for key, value in sorted(params.items())]
    return ", ".join(parts[:8])


def _render_top_rows(results: list[dict[str, Any]], top_n: int) -> str:
    rows = []
    for rank, result in enumerate(results[:top_n], 1):
        rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{escape(str(result.get('strategy') or '-'))}</td>"
            f"<td>{escape(str(result.get('symbol') or '-'))}</td>"
            f"<td>{escape(str(result.get('tf') or '-'))}</td>"
            f"<td>{_fmt_number(result.get('pnl'))}</td>"
            f"<td>{_fmt_number(result.get('return_pct'), suffix='%')}</td>"
            f"<td>{_fmt_number(result.get('sharpe'))}</td>"
            f"<td>{_fmt_number(result.get('profit_factor'))}</td>"
            f"<td>{_fmt_number(result.get('max_drawdown'), suffix='%')}</td>"
            f"<td>{_fmt_int(result.get('trades'))}</td>"
            f"<td>{_fmt_number(result.get('win_rate'), suffix='%')}</td>"
            f"<td>{_fmt_int(result.get('duplicate_run_count') or 1)}</td>"
            f"<td>{escape(_params_preview(result.get('params') or {}))}</td>"
            "</tr>",
        )
    return "\n".join(rows)


def _render_run_rows(results: list[dict[str, Any]], limit: int = 300) -> str:
    rows = []
    for result in results[:limit]:
        rows.append(
            "<tr>"
            f"<td>{escape(str(result.get('run_id') or '-'))}</td>"
            f"<td>{escape(str(result.get('strategy') or '-'))}</td>"
            f"<td>{escape(str(result.get('symbol') or '-'))}</td>"
            f"<td>{escape(str(result.get('tf') or '-'))}</td>"
            f"<td>{escape(str(result.get('timestamp') or '-'))}</td>"
            f"<td>{_fmt_number(result.get('return_pct'), suffix='%')}</td>"
            f"<td>{_fmt_number(result.get('sharpe'))}</td>"
            f"<td>{_fmt_int(result.get('trades'))}</td>"
            f"<td>{_fmt_int(result.get('duplicate_run_count') or 1)}</td>"
            f"<td>{'yes' if result.get('account_ruined') else 'no'}</td>"
            "</tr>",
        )
    return "\n".join(rows)


def generate_html_report(
    results: Iterable[dict[str, Any]],
    output_path: Path | str,
    *,
    title: str,
    top_n: int = 100,
    filters_description: str = "",
    csv_path: Path | str | None = None,
) -> Path:
    output_path = Path(output_path)
    rows = list(results)

    profitable = sum(1 for row in rows if float(row.get("return_pct") or 0) > 0)
    ruined = sum(1 for row in rows if bool(row.get("account_ruined")))
    collapsed_runs = sum(max(int(row.get("duplicate_run_count") or 1) - 1, 0) for row in rows)
    total_pnl = sum(float(row.get("pnl") or 0) for row in rows)
    avg_return = sum(float(row.get("return_pct") or 0) for row in rows) / len(rows) if rows else 0.0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f1c17;
      --muted: #786c5d;
      --accent: #9b5d33;
      --line: #dfd2bf;
    }}
    body {{
      margin: 0;
      padding: 32px;
      background: linear-gradient(180deg, #efe6d5 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
    }}
    .wrap {{
      max-width: 1480px;
      margin: 0 auto;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(77, 57, 34, 0.08);
      padding: 24px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0 0 12px;
      font-size: 32px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: #fffaf1;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric .value {{
      font-size: 24px;
      font-weight: 700;
    }}
    h2 {{
      margin-top: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #fbf4e8;
    }}
    .scroll {{
      overflow: auto;
      max-height: 720px;
    }}
    .caption {{
      color: var(--muted);
      margin-bottom: 16px;
    }}
    code {{
      background: #f4eadb;
      border-radius: 6px;
      padding: 2px 6px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{escape(title)}</h1>
      <div class="meta">Updated {escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</div>
      <div class="meta">Filters: {escape(filters_description or "none")}</div>
      <div class="meta">CSV source: <code>{escape(str(csv_path) if csv_path else "-")}</code></div>
      <div class="metrics">
        <div class="metric"><div class="label">Unique configs</div><div class="value">{len(rows):,}</div></div>
        <div class="metric"><div class="label">Profitable</div><div class="value">{profitable:,}</div></div>
        <div class="metric"><div class="label">Total PnL</div><div class="value">{_fmt_number(total_pnl)}</div></div>
        <div class="metric"><div class="label">Avg Return</div><div class="value">{_fmt_number(avg_return, suffix="%")}</div></div>
      </div>
      <div class="meta" style="margin-top:12px;">Ruined accounts in selection: {ruined:,} | Collapsed duplicate runs: {collapsed_runs:,}</div>
    </section>

    <section class="panel">
      <h2>Top {top_n} Configurations</h2>
      <div class="caption">Ranked by return, then pnl, sharpe, profit factor and trade count.</div>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Strategy</th>
              <th>Symbol</th>
              <th>TF</th>
              <th>PnL</th>
              <th>Return%</th>
              <th>Sharpe</th>
              <th>PF</th>
              <th>Max DD</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Dup runs</th>
              <th>Params</th>
            </tr>
          </thead>
          <tbody>
            {_render_top_rows(rows, top_n)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>Run Inventory</h2>
      <div class="caption">First {min(len(rows), 300):,} rows shown. Use the CSV export for deeper slicing.</div>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Strategy</th>
              <th>Symbol</th>
              <th>TF</th>
              <th>Timestamp</th>
              <th>Return%</th>
              <th>Sharpe</th>
              <th>Trades</th>
              <th>Dup runs</th>
              <th>Ruined</th>
            </tr>
          </thead>
          <tbody>
            {_render_run_rows(rows)}
          </tbody>
        </table>
      </div>
    </section>
  </div>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    return output_path


def _fmt_ratio_pct(value: Any, *, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:.{digits}f}%"


def _fmt_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _fmt_compact_list(value: Any, *, limit: int = 6) -> str:
    if not value:
        return "-"
    if not isinstance(value, (list, tuple, set)):
        return escape(str(value))
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        return "-"
    preview = ", ".join(items[:limit])
    if len(items) > limit:
        preview += f", +{len(items) - limit}"
    return escape(preview)


def _sort_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return str(len(value))
    return str(value).lower()


def _render_sortable_table(
    table_id: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    empty_message: str,
) -> str:
    header_cells = []
    for column in columns:
        label = escape(str(column.get("label") or ""))
        col_type = escape(str(column.get("type") or "text"))
        header_cells.append(
            f'<th data-type="{col_type}"><button type="button">{label}<span class="sort-indicator">↕</span></button></th>',
        )

    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            getter = column.get("value")
            raw_value = getter(row) if callable(getter) else row.get(str(column.get("key") or ""))
            sort_getter = column.get("sort_value")
            sort_raw = sort_getter(row, raw_value) if callable(sort_getter) else raw_value
            renderer = column.get("display")
            if callable(renderer):
                rendered = renderer(raw_value, row)
            else:
                rendered = escape(str(raw_value if raw_value not in (None, "") else "-"))
            class_name = escape(str(column.get("class_name") or ""))
            title = ""
            title_getter = column.get("title")
            if callable(title_getter):
                title_raw = title_getter(raw_value, row)
                if title_raw not in (None, ""):
                    title = f' title="{escape(str(title_raw))}"'
            cells.append(
                f'<td data-sort-value="{escape(_sort_value(sort_raw))}" class="{class_name}"{title}>{rendered}</td>',
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    if not body_rows:
        body_rows.append(
            f'<tr class="empty-row"><td colspan="{len(columns)}">{escape(empty_message)}</td></tr>',
        )

    return (
        f'<table id="{escape(table_id)}" class="sortable-table">'
        "<thead><tr>" + "".join(header_cells) + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def generate_llm_benchmark_html_report(
    payload: dict[str, Any],
    output_path: Path | str,
    *,
    title: str = "LLM Token Matrix Benchmark",
) -> Path:
    output_path = Path(output_path)
    summary = dict(payload.get("summary", {}) or {})
    config = dict(payload.get("config", {}) or {})
    model_rows = list(summary.get("model_summaries", []) or [])
    run_rows = list(payload.get("run_rows", []) or [])
    probe_rows = list(payload.get("probe_records", []) or [])

    common_errors = [
        {"error_type": key, "count": value} for key, value in dict(summary.get("error_type_counts", {}) or {}).items()
    ]
    common_errors.sort(key=lambda item: (-int(item.get("count", 0) or 0), str(item.get("error_type", ""))))

    missing_tokens = [
        {"token": key, "count": value} for key, value in dict(summary.get("missing_token_counts", {}) or {}).items()
    ]
    invalid_indicators = [
        {"indicator": key, "count": value}
        for key, value in dict(summary.get("invalid_indicator_counts", {}) or {}).items()
    ]

    total_runs = int(summary.get("executed_runs", len(run_rows)) or 0)
    success_runs = int(dict(summary.get("run_status_counts", {}) or {}).get("success", 0) or 0)
    success_rate = (success_runs / total_runs) if total_runs else 0.0

    model_columns = [
        {
            "label": "Model",
            "key": "model_name",
            "type": "text",
            "class_name": "mono",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Category",
            "key": "category",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Params (B)",
            "key": "params_billions",
            "type": "number",
            "display": lambda value, _: _fmt_number(value, digits=1),
        },
        {
            "label": "Success",
            "type": "number",
            "value": lambda row: int(row.get("success_runs", 0) or 0),
            "display": lambda value, _: _fmt_int(value),
        },
        {
            "label": "Attempts",
            "type": "number",
            "value": lambda row: int(row.get("attempts", 0) or 0),
            "display": lambda value, _: _fmt_int(value),
        },
        {
            "label": "Success Rate",
            "type": "number",
            "value": lambda row: float(row.get("success_rate", 0.0) or 0.0),
            "display": lambda value, _: _fmt_ratio_pct(value),
        },
        {
            "label": "Avg Coverage",
            "type": "number",
            "value": lambda row: float(row.get("avg_coverage_ratio", 0.0) or 0.0),
            "display": lambda value, _: _fmt_ratio_pct(value),
        },
        {
            "label": "Avg Latency (ms)",
            "type": "number",
            "value": lambda row: float(row.get("avg_latency_ms", 0.0) or 0.0),
            "display": lambda value, _: _fmt_number(value, digits=0),
        },
        {
            "label": "Avg Valid Tokens",
            "type": "number",
            "value": lambda row: float(row.get("avg_valid_tokens", 0.0) or 0.0),
            "display": lambda value, _: _fmt_number(value, digits=1),
        },
        {
            "label": "Fallback Runs",
            "type": "number",
            "value": lambda row: int(row.get("fallback_runs", 0) or 0),
            "display": lambda value, _: _fmt_int(value),
        },
        {
            "label": "Cloud",
            "type": "number",
            "value": lambda row: bool(row.get("cloud_billed", False)),
            "display": lambda value, _: _fmt_bool(value),
        },
    ]

    run_columns = [
        {
            "label": "Model",
            "key": "model_name",
            "type": "text",
            "class_name": "mono",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Category",
            "key": "category",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Status",
            "key": "status",
            "type": "text",
            "display": lambda value, _: (
                f'<span class="badge status-{escape(str(value or "unknown"))}">{escape(str(value or "-"))}</span>'
            ),
        },
        {
            "label": "Error Type",
            "key": "error_type",
            "type": "text",
            "class_name": "mono",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Latency (ms)",
            "key": "latency_ms",
            "type": "number",
            "display": lambda value, _: _fmt_number(value, digits=0),
        },
        {
            "label": "Coverage",
            "key": "coverage_ratio",
            "type": "number",
            "display": lambda value, _: _fmt_ratio_pct(value),
        },
        {
            "label": "Valid Tokens",
            "key": "valid_token_count",
            "type": "number",
            "display": lambda value, _: _fmt_int(value),
        },
        {
            "label": "Missing",
            "type": "number",
            "value": lambda row: len(list(row.get("missing_tokens", []) or [])),
            "display": lambda value, row: _fmt_compact_list(row.get("missing_tokens", [])),
            "title": lambda _, row: ", ".join(row.get("missing_tokens", []) or []),
        },
        {
            "label": "Extra",
            "type": "number",
            "value": lambda row: len(list(row.get("extra_tokens", []) or [])),
            "display": lambda value, row: _fmt_compact_list(row.get("extra_tokens", [])),
            "title": lambda _, row: ", ".join(row.get("extra_tokens", []) or []),
        },
        {
            "label": "Bad Indicators",
            "key": "invalid_indicator_count",
            "type": "number",
            "display": lambda value, _: _fmt_int(value),
        },
        {
            "label": "Parse Mode",
            "key": "parse_mode",
            "type": "text",
            "class_name": "mono",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Fallback Selected",
            "key": "fallback_selected",
            "type": "number",
            "display": lambda value, _: _fmt_bool(value),
        },
        {
            "label": "Primary Status",
            "key": "primary_status",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Fallback Status",
            "key": "fallback_status",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
    ]

    probe_columns = [
        {
            "label": "Model",
            "key": "canonical_name",
            "type": "text",
            "class_name": "mono",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Category",
            "key": "category",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Params (B)",
            "key": "params_billions",
            "type": "number",
            "display": lambda value, _: _fmt_number(value, digits=1),
        },
        {
            "label": "Probe Status",
            "key": "probe_status",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Chat Policy",
            "key": "chat_policy",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {
            "label": "Cloud",
            "key": "cloud_billed",
            "type": "number",
            "display": lambda value, _: _fmt_bool(value),
        },
        {
            "label": "Manual Approval",
            "key": "requires_manual_approval",
            "type": "number",
            "display": lambda value, _: _fmt_bool(value),
        },
        {
            "label": "Probe Message",
            "key": "probe_message",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
            "title": lambda value, _: str(value or ""),
        },
    ]

    common_error_columns = [
        {
            "label": "Error Type",
            "key": "error_type",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {"label": "Count", "key": "count", "type": "number", "display": lambda value, _: _fmt_int(value)},
    ]
    missing_token_columns = [
        {"label": "Token", "key": "token", "type": "text", "display": lambda value, _: escape(str(value or "-"))},
        {"label": "Missing Count", "key": "count", "type": "number", "display": lambda value, _: _fmt_int(value)},
    ]
    invalid_indicator_columns = [
        {
            "label": "Indicator",
            "key": "indicator",
            "type": "text",
            "display": lambda value, _: escape(str(value or "-")),
        },
        {"label": "Invalid Count", "key": "count", "type": "number", "display": lambda value, _: _fmt_int(value)},
    ]

    source_json = payload.get("__source_path", "")
    prompt_version = str(config.get("prompt_version", "") or "-")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f1c17;
      --muted: #786c5d;
      --accent: #9b5d33;
      --line: #dfd2bf;
      --ok-bg: #e6f7ee;
      --ok-ink: #1d6f46;
      --warn-bg: #fff0d9;
      --warn-ink: #8a5a00;
      --bad-bg: #fbe5e5;
      --bad-ink: #8a2f2f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 28px;
      background: linear-gradient(180deg, #efe6d5 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
    }}
    .wrap {{
      max-width: 1680px;
      margin: 0 auto;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(77, 57, 34, 0.08);
      padding: 24px;
      margin-bottom: 18px;
    }}
    .hero h1 {{
      margin: 0 0 12px;
      font-size: 32px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
      margin-top: 4px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: #fffaf1;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric .value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 24px;
    }}
    .caption {{
      color: var(--muted);
      margin-bottom: 14px;
      font-size: 14px;
    }}
    .scroll {{
      overflow: auto;
      max-height: 720px;
      border: 1px solid var(--line);
      border-radius: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: #fffdf8;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #fbf4e8;
      z-index: 1;
    }}
    th button {{
      all: unset;
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      cursor: pointer;
      font-weight: 700;
    }}
    .sort-indicator {{
      color: var(--muted);
      font-size: 12px;
    }}
    .mono {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
    }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
    }}
    .status-success {{
      background: var(--ok-bg);
      color: var(--ok-ink);
    }}
    .status-timeout, .status-invalid_json, .status-warmup_failed {{
      background: var(--bad-bg);
      color: var(--bad-ink);
    }}
    .status-token_set_mismatch, .status-missing_tokens_array {{
      background: var(--warn-bg);
      color: var(--warn-ink);
    }}
    .empty-row td {{
      color: var(--muted);
      text-align: center;
      padding: 18px;
    }}
    code {{
      background: #f4eadb;
      border-radius: 6px;
      padding: 2px 6px;
    }}
    @media (max-width: 1200px) {{
      .metrics, .grid-3 {{
        grid-template-columns: 1fr;
      }}
      body {{
        padding: 18px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{escape(title)}</h1>
      <div class="meta">Generated at {escape(str(payload.get("generated_at", "") or "-"))}</div>
      <div class="meta">Prompt version: <code>{escape(prompt_version)}</code> | Timeframe: <code>{escape(str(config.get("timeframe", "") or "-"))}</code> | Tokens: <code>{escape(str(config.get("tokens_count", len(payload.get("token_universe", []) or []))))}</code></div>
      <div class="meta">Source JSON: <code>{escape(str(source_json or output_path.with_suffix(".json")))}</code></div>
      <div class="meta">Click any column header to sort ascending/descending.</div>
      <div class="metrics">
        <div class="metric"><div class="label">Probe Models</div><div class="value">{_fmt_int(summary.get("probe_models", 0))}</div></div>
        <div class="metric"><div class="label">Executed Runs</div><div class="value">{_fmt_int(total_runs)}</div></div>
        <div class="metric"><div class="label">Final Success</div><div class="value">{_fmt_int(success_runs)}</div></div>
        <div class="metric"><div class="label">Success Rate</div><div class="value">{_fmt_ratio_pct(success_rate)}</div></div>
        <div class="metric"><div class="label">Successful Models</div><div class="value">{_fmt_int(summary.get("successful_models", 0))}</div></div>
      </div>
    </section>

    <section class="grid-3">
      <div class="panel">
        <h2>Common Errors</h2>
        <div class="caption">Sorted by count by default in the JSON summary.</div>
        <div class="scroll">
          {_render_sortable_table("common-errors", common_error_columns, common_errors, empty_message="No execution errors recorded.")}
        </div>
      </div>
      <div class="panel">
        <h2>Most Missing Tokens</h2>
        <div class="caption">Tokens most frequently absent from malformed outputs.</div>
        <div class="scroll">
          {_render_sortable_table("missing-tokens", missing_token_columns, missing_tokens, empty_message="No missing tokens recorded.")}
        </div>
      </div>
      <div class="panel">
        <h2>Invalid Indicators</h2>
        <div class="caption">Indicators returned outside the allowed contract.</div>
        <div class="scroll">
          {_render_sortable_table("invalid-indicators", invalid_indicator_columns, invalid_indicators, empty_message="No invalid indicators recorded.")}
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>Model Summary</h2>
      <div class="caption">One row per model. Good for ranking by reliability, latency and coverage.</div>
      <div class="scroll">
        {_render_sortable_table("model-summary", model_columns, model_rows, empty_message="No model summaries available.")}
      </div>
    </section>

    <section class="panel">
      <h2>Run Details</h2>
      <div class="caption">One row per executed run. Use this table to sort by status, coverage, missing tokens or fallback usage.</div>
      <div class="scroll">
        {_render_sortable_table("run-details", run_columns, run_rows, empty_message="No run rows available.")}
      </div>
    </section>

    <section class="panel">
      <h2>Probe Inventory</h2>
      <div class="caption">Includes models skipped because they were unaccepted or marked expensive.</div>
      <div class="scroll">
        {_render_sortable_table("probe-inventory", probe_columns, probe_rows, empty_message="No probe records available.")}
      </div>
    </section>
  </div>
  <script>
    (() => {{
      function parseValue(value, type) {{
        if (type === "number") {{
          const parsed = Number(value);
          return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
        }}
        return String(value || "").toLowerCase();
      }}

      function attachSorting(table) {{
        const headers = Array.from(table.querySelectorAll("thead th"));
        headers.forEach((header, index) => {{
          const button = header.querySelector("button");
          const type = header.dataset.type || "text";
          if (!button) {{
            return;
          }}
          button.addEventListener("click", () => {{
            const tbody = table.querySelector("tbody");
            const rows = Array.from(tbody.querySelectorAll("tr:not(.empty-row)"));
            const current = header.dataset.sortDirection === "asc" ? "asc" : header.dataset.sortDirection === "desc" ? "desc" : "";
            const next = current === "asc" ? "desc" : "asc";

            headers.forEach((other) => {{
              if (other !== header) {{
                other.dataset.sortDirection = "";
                const icon = other.querySelector(".sort-indicator");
                if (icon) {{
                  icon.textContent = "↕";
                }}
              }}
            }});

            rows.sort((left, right) => {{
              const leftCell = left.children[index];
              const rightCell = right.children[index];
              const leftValue = parseValue(leftCell.dataset.sortValue || leftCell.textContent.trim(), type);
              const rightValue = parseValue(rightCell.dataset.sortValue || rightCell.textContent.trim(), type);
              if (type === "number") {{
                return next === "asc" ? leftValue - rightValue : rightValue - leftValue;
              }}
              return next === "asc"
                ? leftValue.localeCompare(rightValue)
                : rightValue.localeCompare(leftValue);
            }});

            rows.forEach((row) => tbody.appendChild(row));
            header.dataset.sortDirection = next;
            const icon = header.querySelector(".sort-indicator");
            if (icon) {{
              icon.textContent = next === "asc" ? "↑" : "↓";
            }}
          }});
        }});
      }}

      document.querySelectorAll("table.sortable-table").forEach(attachSorting);
    }})();
  </script>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    return output_path
