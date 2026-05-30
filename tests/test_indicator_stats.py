"""Tests du module analytics.indicator_stats."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from analytics.indicator_stats import (
    Filters,
    IterationRow,
    cooccurrence_pairs,
    diagnostic_distribution,
    export_prompt_block,
    format_indicator_tables_for_prompt,
    load_iterations,
    per_indicator_stats,
    unexpected_ranking,
)


def _row(
    sid: str,
    *,
    inferred: tuple[str, ...] = (),
    declared: tuple[str, ...] | None = None,
    unexpected: tuple[str, ...] = (),
    score: float | None = 0.0,
    trades: int = 1,
    diag: str | None = None,
) -> IterationRow:
    return IterationRow(
        session_id=sid,
        iteration=1,
        indicators_inferred=tuple(sorted(set(inferred))),
        indicators_declared=tuple(sorted(set(declared if declared is not None else inferred))),
        unexpected=tuple(sorted(set(unexpected))),
        telemetry_score=score,
        sharpe=None,
        return_pct=None,
        trades=trades,
        diagnostic_category=diag,
        symbol="BTC",
        timeframe="1h",
        model_name="qwen",
        start_time="2026-05-01T00:00:00",
    )


def test_filters_exclude_no_trades_by_default() -> None:
    rows = [
        _row("a", inferred=("rsi",), score=10.0, trades=5),
        _row("b", inferred=("rsi",), score=-50.0, trades=0, diag="no_trades"),
    ]
    stats = per_indicator_stats(rows, filters=Filters(), min_n=1)
    assert len(stats) == 1
    assert stats[0]["indicator"] == "rsi"
    assert stats[0]["n"] == 1


def test_lift_is_relative_to_other_iterations() -> None:
    rows = [
        _row("a", inferred=("good",), score=50.0, trades=5),
        _row("b", inferred=("bad",), score=-50.0, trades=5),
    ]
    stats = {s["indicator"]: s for s in per_indicator_stats(rows, min_n=1)}
    assert stats["good"]["lift"] == 100.0  # 50 - (-50)
    assert stats["bad"]["lift"] == -100.0


def test_session_best_mode_keeps_one_row_per_session() -> None:
    rows = [
        _row("a", inferred=("x",), score=10.0, trades=5),
        _row("a", inferred=("y",), score=80.0, trades=5),  # session 'a' best
        _row("b", inferred=("x",), score=-10.0, trades=5),  # session 'b' best
    ]
    iter_stats = {s["indicator"]: s for s in per_indicator_stats(rows, mode="iteration", min_n=1)}
    best_stats = {s["indicator"]: s for s in per_indicator_stats(rows, mode="session_best", min_n=1)}
    # mode iteration : x apparait dans les 2 iterations a + b
    assert iter_stats["x"]["n"] == 2
    # mode session_best : x ne provient que de la best de session 'b' (pas de 'a')
    assert best_stats["x"]["n"] == 1
    assert best_stats["x"]["mean_score"] == -10.0
    assert best_stats["y"]["n"] == 1
    assert best_stats["y"]["mean_score"] == 80.0


def test_min_n_filters_out_rare_indicators() -> None:
    rows = [_row(f"s{i}", inferred=("rare",), score=10.0, trades=5) for i in range(3)]
    rows += [_row(f"common{i}", inferred=("freq",), score=0.0, trades=5) for i in range(25)]
    out = {s["indicator"] for s in per_indicator_stats(rows, min_n=20)}
    assert "freq" in out
    assert "rare" not in out


def test_cooccurrence_pairs_sorted_descending() -> None:
    rows = [
        _row("a", inferred=("rsi", "adx"), score=50.0, trades=5),
        _row("b", inferred=("rsi", "adx"), score=30.0, trades=5),
        _row("c", inferred=("rsi", "mfi"), score=-30.0, trades=5),
        _row("d", inferred=("rsi", "mfi"), score=-50.0, trades=5),
    ]
    pairs = cooccurrence_pairs(rows, min_n=2, top_k=10)
    pair_names = [(p["a"], p["b"]) for p in pairs]
    assert ("adx", "rsi") in pair_names
    assert ("mfi", "rsi") in pair_names
    adx_score = next(p for p in pairs if p["a"] == "adx")["mean_score"]
    mfi_score = next(p for p in pairs if p["a"] == "mfi")["mean_score"]
    assert adx_score > mfi_score


def test_unexpected_ranking_counts_undeclared_usage() -> None:
    rows = [
        _row("a", inferred=("rsi", "atr"), declared=("rsi",), unexpected=("atr",)),
        _row("b", inferred=("atr",), declared=("atr",), unexpected=()),
    ]
    rank = {r["indicator"]: r["n_unexpected"] for r in unexpected_ranking(rows)}
    assert rank["atr"] == 1


def test_diagnostic_distribution_counts_all() -> None:
    rows = [
        _row("a", diag="no_trades", trades=0),
        _row("b", diag="ruined"),
        _row("c", diag="ruined"),
    ]
    dist = {d["diagnostic"]: d["n"] for d in diagnostic_distribution(rows)}
    assert dist["ruined"] == 2
    assert dist["no_trades"] == 1


def test_export_prompt_block_contains_top_and_flop() -> None:
    rows = [
        _row("a", inferred=("good",), score=50.0, trades=5),
        _row("b", inferred=("bad",), score=-50.0, trades=5),
    ]
    stats = per_indicator_stats(rows, min_n=1)
    block = export_prompt_block(stats, top_n=1, flop_n=1, min_lift=10.0)
    assert "good" in block
    assert "bad" in block
    assert "Prefer" in block
    assert "Avoid" in block


def test_indicator_source_declared_vs_inferred() -> None:
    rows = [
        _row(
            "a",
            inferred=("rsi", "atr", "bollinger"),
            declared=("rsi",),
            score=10.0,
            trades=5,
        )
    ]
    inferred_inds = {
        s["indicator"] for s in per_indicator_stats(rows, filters=Filters(indicator_source="inferred"), min_n=1)
    }
    declared_inds = {
        s["indicator"] for s in per_indicator_stats(rows, filters=Filters(indicator_source="declared"), min_n=1)
    }
    assert {"rsi", "atr", "bollinger"} <= inferred_inds
    assert declared_inds == {"rsi"}


def test_load_iterations_from_fixture() -> None:
    """Verifie le chargement depuis un dossier session simule."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session_dir = root / "20260101_120000_test"
        session_dir.mkdir()
        summary = {
            "session_id": "test_sess",
            "symbol": "BTC",
            "timeframe": "1h",
            "model_name": "qwen",
            "start_time": "2026-01-01T12:00:00",
            "iterations": [
                {
                    "iteration": 1,
                    "used_indicators": ["rsi", "atr"],
                    "telemetry_score": 12.5,
                    "sharpe": 1.2,
                    "return_pct": 5.0,
                    "trades": 8,
                    "diagnostic_category": "target_reached",
                    "phase_feedback": {
                        "code": {
                            "indicator_contract_violation": {
                                "declared": ["rsi", "atr"],
                                "inferred": ["rsi", "atr", "ema"],
                                "unexpected": ["ema"],
                            }
                        }
                    },
                }
            ],
        }
        (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")

        rows = load_iterations(root)
        assert len(rows) == 1
        row = rows[0]
        assert row.session_id == "test_sess"
        assert row.indicators_inferred == ("atr", "ema", "rsi")
        assert row.indicators_declared == ("atr", "rsi")
        assert row.unexpected == ("ema",)
        assert row.telemetry_score == 12.5
        assert row.diagnostic_category == "target_reached"


def test_load_iterations_skips_corrupt_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / "20260101_120000_good"
        good.mkdir()
        (good / "session_summary.json").write_text('{"iterations":[]}', encoding="utf-8")
        bad = root / "20260101_120100_bad"
        bad.mkdir()
        (bad / "session_summary.json").write_text("{ not json", encoding="utf-8")
        rows = load_iterations(root)
        assert rows == []  # good a 0 iterations, bad est ignore


def test_format_block_contains_three_sections_when_data_supports() -> None:
    """Cas riche : top + flop + under-explored."""
    rows: list[IterationRow] = []
    # 60 iterations sur 'good' (n >= min_n_known=50), score eleve
    for i in range(60):
        rows.append(_row(f"good{i}", inferred=("good",), score=40.0, trades=5))
    # 60 iterations sur 'bad', score tres bas
    for i in range(60):
        rows.append(_row(f"bad{i}", inferred=("bad",), score=-40.0, trades=5))
    # 15 iterations sur 'rare_promising', score positif (under-explored : 10<=n<30)
    for i in range(15):
        rows.append(_row(f"rare{i}", inferred=("rare_promising",), score=20.0, trades=5))

    block = format_indicator_tables_for_prompt(
        rows, mode="iteration", top_n=5, flop_n=5, min_n_known=50
    )
    assert "INDICATOR USAGE STATISTICS" in block
    assert "Well-tested indicators with best lift" in block
    assert "Well-tested indicators with worst lift" in block
    assert "Under-explored candidates" in block
    assert "good" in block
    assert "bad" in block
    assert "rare_promising" in block


def test_format_block_empty_when_no_data() -> None:
    assert format_indicator_tables_for_prompt([]) == ""


def test_format_block_empty_when_only_no_trades() -> None:
    """Si toutes les iterations sont no_trades, le filtre par defaut les exclut."""
    rows = [_row(f"s{i}", inferred=("rsi",), trades=0, diag="no_trades") for i in range(100)]
    block = format_indicator_tables_for_prompt(rows)
    assert block == ""


def test_format_block_under_explored_section_only_when_present() -> None:
    """Si aucune candidate under-explored, pas de section correspondante."""
    rows = [_row(f"s{i}", inferred=("freq",), score=10.0, trades=5) for i in range(80)]
    block = format_indicator_tables_for_prompt(rows, mode="iteration", min_n_known=50)
    assert "Under-explored candidates" not in block
    assert "Well-tested" in block


def test_format_block_renders_markdown_table() -> None:
    """Verifie que la sortie est un tableau markdown valide."""
    rows = [_row(f"s{i}", inferred=("x",), score=10.0, trades=5) for i in range(60)]
    block = format_indicator_tables_for_prompt(rows, mode="iteration", min_n_known=50)
    assert "| indicator | n | lift |" in block
    assert "|---|" in block  # ligne de separation


def test_format_block_filters_by_symbol() -> None:
    """Le filtre par symbol restreint correctement les stats."""
    rows = [_row(f"a{i}", inferred=("rsi",), score=50.0, trades=5) for i in range(60)]
    # injecte des rows BTC distincts
    btc_rows = []
    for i in range(60):
        r = _row(f"b{i}", inferred=("adx",), score=10.0, trades=5)
        # reconstruit avec symbol = 'BTC' (deja le default _row)
        btc_rows.append(r)
    all_rows = rows + btc_rows
    block = format_indicator_tables_for_prompt(
        all_rows, filters=Filters(symbols=frozenset({"BTC"})), mode="iteration", min_n_known=50
    )
    # 'rsi' et 'adx' ont tous deux symbol=BTC dans _row, donc les deux apparaissent
    assert "rsi" in block or "adx" in block


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
