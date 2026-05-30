"""Agregats indicateur x performance sur l'historique Builder.

Module pur Python : ne depend ni de streamlit ni de pandas pour le chargement.
Les agregats retournent des `list[dict]` que la page UI peut transformer en DataFrame.

Sources:
- {SESSIONS_ROOT}/<session>/session_summary.json (1 par session)
- Champ pivot par iteration: `used_indicators` + `phase_feedback.code.indicator_contract_violation`
- Filtres par session: symbol, timeframe, model_name, start_time
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Literal

from backtest.result_store import get_builder_sessions_dir

AggregateMode = Literal["iteration", "session_best"]


@dataclass(frozen=True)
class IterationRow:
    """Donnees brutes par iteration utilisees par tous les agregats."""

    session_id: str
    iteration: int | None
    indicators_inferred: tuple[str, ...]
    indicators_declared: tuple[str, ...]
    unexpected: tuple[str, ...]
    telemetry_score: float | None
    sharpe: float | None
    return_pct: float | None
    trades: int
    diagnostic_category: str | None
    symbol: str
    timeframe: str
    model_name: str
    start_time: str | None


@dataclass
class Filters:
    """Filtres a appliquer avant agregat."""

    symbols: frozenset[str] = field(default_factory=frozenset)
    timeframes: frozenset[str] = field(default_factory=frozenset)
    models: frozenset[str] = field(default_factory=frozenset)
    diagnostics: frozenset[str] = field(default_factory=frozenset)
    min_trades: int = 1
    exclude_no_trades: bool = True
    start_after: datetime | None = None
    end_before: datetime | None = None
    indicator_source: Literal["inferred", "declared"] = "inferred"

    def matches(self, row: IterationRow) -> bool:
        if self.symbols and row.symbol not in self.symbols:
            return False
        if self.timeframes and row.timeframe not in self.timeframes:
            return False
        if self.models and row.model_name not in self.models:
            return False
        if self.diagnostics and (row.diagnostic_category or "") not in self.diagnostics:
            return False
        if self.exclude_no_trades and (row.diagnostic_category or "") == "no_trades":
            return False
        if (row.trades or 0) < self.min_trades:
            return False
        if self.start_after or self.end_before:
            ts = _parse_iso(row.start_time)
            if ts is None:
                return False
            if self.start_after and ts < self.start_after:
                return False
            if self.end_before and ts > self.end_before:
                return False
        return True

    def indicators(self, row: IterationRow) -> tuple[str, ...]:
        return row.indicators_declared if self.indicator_source == "declared" else row.indicators_inferred


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iter_session_files(sessions_root: Path) -> Iterable[Path]:
    if not sessions_root.exists():
        return
    for entry in os.scandir(sessions_root):
        if not entry.is_dir():
            continue
        if not entry.name or not entry.name[0].isdigit():
            continue
        summary = Path(entry.path) / "session_summary.json"
        if summary.exists():
            yield summary


def load_iterations(
    sessions_root: Path | None = None,
    *,
    max_sessions: int | None = None,
) -> list[IterationRow]:
    """Charge toutes les iterations de toutes les sessions Builder."""
    root = Path(sessions_root) if sessions_root else get_builder_sessions_dir()
    rows: list[IterationRow] = []
    files = sorted(_iter_session_files(root), reverse=True)
    if max_sessions is not None:
        files = files[:max_sessions]
    for path in files:
        try:
            with path.open(encoding="utf-8") as fh:
                summary = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        session_id = str(summary.get("session_id") or path.parent.name)
        symbol = str(summary.get("symbol") or "")
        timeframe = str(summary.get("timeframe") or "")
        model = str(summary.get("model_name") or "")
        start_time = summary.get("start_time")
        for it in summary.get("iterations") or []:
            if not isinstance(it, dict):
                continue
            used = it.get("used_indicators") or []
            pf = it.get("phase_feedback") or {}
            code_pf = pf.get("code") if isinstance(pf, dict) else None
            contract = (code_pf or {}).get("indicator_contract_violation") or {}
            declared = contract.get("declared") or used
            inferred = contract.get("inferred") or used
            unexpected = contract.get("unexpected") or []
            rows.append(
                IterationRow(
                    session_id=session_id,
                    iteration=it.get("iteration"),
                    indicators_inferred=tuple(sorted({str(x) for x in inferred})),
                    indicators_declared=tuple(sorted({str(x) for x in declared})),
                    unexpected=tuple(sorted({str(x) for x in unexpected})),
                    telemetry_score=_safe_float(it.get("telemetry_score")),
                    sharpe=_safe_float(it.get("sharpe")),
                    return_pct=_safe_float(it.get("return_pct")),
                    trades=_safe_int(it.get("trades")),
                    diagnostic_category=(it.get("diagnostic_category") or None),
                    symbol=symbol,
                    timeframe=timeframe,
                    model_name=model,
                    start_time=str(start_time) if start_time else None,
                )
            )
    return rows


def _reduce_to_session_best(rows: list[IterationRow]) -> list[IterationRow]:
    """Garde une seule ligne par session : iteration au meilleur telemetry_score."""
    best: dict[str, IterationRow] = {}
    for r in rows:
        if r.telemetry_score is None:
            continue
        cur = best.get(r.session_id)
        if cur is None or (r.telemetry_score > (cur.telemetry_score or -math.inf)):
            best[r.session_id] = r
    return list(best.values())


def _apply(rows: list[IterationRow], filters: Filters, mode: AggregateMode) -> list[IterationRow]:
    filtered = [r for r in rows if filters.matches(r)]
    if mode == "session_best":
        filtered = _reduce_to_session_best(filtered)
    return filtered


def per_indicator_stats(
    rows: list[IterationRow],
    *,
    filters: Filters | None = None,
    mode: AggregateMode = "iteration",
    min_n: int = 20,
) -> list[dict[str, Any]]:
    """Une ligne par indicateur : n, mean_score, lift, mean_return, win_rate, mean_sharpe."""
    filters = filters or Filters()
    base = _apply(rows, filters, mode)
    if not base:
        return []

    scores_global = [r.telemetry_score for r in base if r.telemetry_score is not None]
    sum_global = sum(scores_global)
    n_global = len(scores_global)
    if n_global == 0:
        return []

    per_ind: dict[str, list[IterationRow]] = defaultdict(list)
    for r in base:
        for ind in filters.indicators(r):
            per_ind[ind].append(r)

    stats: list[dict[str, Any]] = []
    for ind, sub in per_ind.items():
        scores = [r.telemetry_score for r in sub if r.telemetry_score is not None]
        n = len(scores)
        if n < min_n:
            continue
        mean_in = mean(scores)
        n_out = n_global - n
        mean_out = (sum_global - sum(scores)) / n_out if n_out > 0 else mean_in
        rets = [r.return_pct for r in sub if r.return_pct is not None]
        sharpes = [r.sharpe for r in sub if r.sharpe is not None]
        wins = sum(1 for x in rets if x > 0)
        stats.append(
            {
                "indicator": ind,
                "n": n,
                "mean_score": round(mean_in, 2),
                "lift": round(mean_in - mean_out, 2),
                "mean_return_pct": round(mean(rets), 2) if rets else None,
                "win_rate_pct": round(wins / len(rets) * 100, 1) if rets else None,
                "mean_sharpe": round(mean(sharpes), 2) if sharpes else None,
                "share_pct": round(n / len(base) * 100, 1),
            }
        )
    stats.sort(key=lambda x: x["lift"], reverse=True)
    return stats


def cooccurrence_pairs(
    rows: list[IterationRow],
    *,
    filters: Filters | None = None,
    mode: AggregateMode = "iteration",
    min_n: int = 10,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """Score moyen par paire d'indicateurs (triees, sans doublon)."""
    filters = filters or Filters()
    base = _apply(rows, filters, mode)
    pairs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in base:
        if r.telemetry_score is None:
            continue
        inds = sorted(set(filters.indicators(r)))
        for i in range(len(inds)):
            for j in range(i + 1, len(inds)):
                pairs[(inds[i], inds[j])].append(r.telemetry_score)
    out: list[dict[str, Any]] = []
    for (a, b), scores in pairs.items():
        if len(scores) < min_n:
            continue
        out.append({"a": a, "b": b, "n": len(scores), "mean_score": round(mean(scores), 2)})
    out.sort(key=lambda x: x["mean_score"], reverse=True)
    return out[:top_k]


def unexpected_ranking(
    rows: list[IterationRow],
    *,
    filters: Filters | None = None,
    top_k: int = 30,
) -> list[dict[str, Any]]:
    """Indicateurs utilises sans declaration explicite (auto-honnetete du LLM)."""
    filters = filters or Filters()
    base = [r for r in rows if filters.matches(r)]
    counter: Counter[str] = Counter()
    for r in base:
        counter.update(r.unexpected)
    n_iter = max(len(base), 1)
    return [
        {"indicator": ind, "n_unexpected": n, "share_pct": round(n / n_iter * 100, 1)}
        for ind, n in counter.most_common(top_k)
    ]


def diagnostic_distribution(rows: list[IterationRow]) -> list[dict[str, Any]]:
    """Distribution brute des diagnostic_category (sans filtre, pour la sante pipeline)."""
    counter = Counter((r.diagnostic_category or "(none)") for r in rows)
    n = max(len(rows), 1)
    return [
        {"diagnostic": k, "n": v, "share_pct": round(v / n * 100, 1)}
        for k, v in counter.most_common()
    ]


def available_dimensions(rows: list[IterationRow]) -> dict[str, list[str]]:
    """Valeurs distinctes pour alimenter les filtres UI."""
    return {
        "symbols": sorted({r.symbol for r in rows if r.symbol}),
        "timeframes": sorted({r.timeframe for r in rows if r.timeframe}),
        "models": sorted({r.model_name for r in rows if r.model_name}),
        "diagnostics": sorted({(r.diagnostic_category or "(none)") for r in rows}),
    }


def export_prompt_block(
    stats: list[dict[str, Any]],
    *,
    top_n: int = 5,
    flop_n: int = 5,
    min_lift: float = 1.0,
) -> str:
    """Genere un bloc texte injectable dans le prompt systeme Builder."""
    tops = [s for s in stats if s["lift"] >= min_lift][:top_n]
    flops = [s for s in reversed(stats) if s["lift"] <= -min_lift][:flop_n]
    lines = ["# Indicator guidance (derived from past Builder sessions)"]
    if tops:
        names = ", ".join(s["indicator"] for s in tops)
        lines.append(f"Prefer when relevant: {names}")
    if flops:
        names = ", ".join(s["indicator"] for s in flops)
        lines.append(f"Avoid unless strong rationale: {names}")
    return "\n".join(lines)


def _format_md_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    """Rend une mini-table markdown a partir d'une liste de dicts.

    cols : liste de (cle, libelle).
    """
    if not rows:
        return ""
    header = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = []
    for r in rows:
        cells = []
        for key, _ in cols:
            v = r.get(key)
            if v is None:
                cells.append("-")
            elif isinstance(v, float):
                cells.append(f"{v:+.1f}" if key in {"lift", "mean_return_pct"} else f"{v:.1f}")
            else:
                cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body])


def format_indicator_tables_for_prompt(
    rows: list[IterationRow],
    *,
    filters: Filters | None = None,
    mode: AggregateMode = "session_best",
    top_n: int = 10,
    flop_n: int = 10,
    min_n_known: int = 50,
    underexplored_n_max: int = 30,
    underexplored_n_min: int = 10,
) -> str:
    """Genere les tableaux indicateur x perf prets a injecter dans le prompt LLM.

    3 sections :
    - Top par lift (n >= min_n_known) : indicateurs eprouves qui ressortent
    - Flop par lift (n >= min_n_known) : indicateurs eprouves qui plombent
    - Under-explored candidates (lift > 0, n entre min/max) : invitation a explorer

    Le LLM recoit les chiffres bruts (n, lift, win%, return%) et juge lui-meme.
    `mode='session_best'` par defaut = une ligne par session (meilleure iteration),
    plus representatif que la moyenne sur toutes les variations.
    """
    filters = filters or Filters()
    stats = per_indicator_stats(rows, filters=filters, mode=mode, min_n=1)
    if not stats:
        return ""

    well_known = [s for s in stats if s["n"] >= min_n_known]
    tops = well_known[:top_n]
    flops = [s for s in reversed(well_known) if s["lift"] < 0][:flop_n]
    underexplored = [
        s
        for s in stats
        if underexplored_n_min <= s["n"] < underexplored_n_max and s["lift"] > 0
    ]
    underexplored.sort(key=lambda x: x["lift"], reverse=True)
    underexplored = underexplored[:top_n]

    cols = [
        ("indicator", "indicator"),
        ("n", "n"),
        ("lift", "lift"),
        ("win_rate_pct", "win%"),
        ("mean_return_pct", "return%"),
    ]

    sections: list[str] = [
        "## INDICATOR USAGE STATISTICS (cross-session, for context)",
        "",
        "Aggregated from past Builder sessions (one row per session, best iteration).",
        "`lift` = mean(telemetry_score | uses X) - mean(score | does not use X).",
        "Use these numbers as ONE signal among others. Small `n` means high uncertainty;",
        "you may still try lower-`n` indicators if the hypothesis warrants it.",
        "",
    ]

    if tops:
        sections.append(f"### Well-tested indicators with best lift (n >= {min_n_known})")
        sections.append(_format_md_table(tops, cols))
        sections.append("")

    if flops:
        sections.append(f"### Well-tested indicators with worst lift (n >= {min_n_known})")
        sections.append(_format_md_table(flops, cols))
        sections.append("")

    if underexplored:
        sections.append(
            f"### Under-explored candidates with positive lift "
            f"({underexplored_n_min} <= n < {underexplored_n_max})"
        )
        sections.append(
            "These indicators have promising early stats but small sample. "
            "Worth trying when the hypothesis fits, to reduce uncertainty."
        )
        sections.append(_format_md_table(underexplored, cols))
        sections.append("")

    if len(sections) <= 7:  # entete + 0 tableau
        return ""
    return "\n".join(sections).rstrip()
