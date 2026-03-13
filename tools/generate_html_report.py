"""
Module-ID: tools.generate_html_report

Purpose: Generate lightweight static HTML analysis reports.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


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


def _params_preview(params: Dict[str, Any]) -> str:
    if not params:
        return "-"
    parts = [f"{key}={value}" for key, value in sorted(params.items())]
    return ", ".join(parts[:8])


def _render_top_rows(results: list[Dict[str, Any]], top_n: int) -> str:
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
            "</tr>"
        )
    return "\n".join(rows)


def _render_run_rows(results: list[Dict[str, Any]], limit: int = 300) -> str:
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
            "</tr>"
        )
    return "\n".join(rows)


def generate_html_report(
    results: Iterable[Dict[str, Any]],
    output_path: Path | str,
    *,
    title: str,
    top_n: int = 100,
    filters_description: str = "",
    csv_path: Optional[Path | str] = None,
) -> Path:
    output_path = Path(output_path)
    rows = list(results)

    profitable = sum(1 for row in rows if float(row.get("return_pct") or 0) > 0)
    ruined = sum(1 for row in rows if bool(row.get("account_ruined")))
    collapsed_runs = sum(max(int(row.get("duplicate_run_count") or 1) - 1, 0) for row in rows)
    total_pnl = sum(float(row.get("pnl") or 0) for row in rows)
    avg_return = (
        sum(float(row.get("return_pct") or 0) for row in rows) / len(rows)
        if rows else 0.0
    )

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
        <div class="metric"><div class="label">Avg Return</div><div class="value">{_fmt_number(avg_return, suffix='%')}</div></div>
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
