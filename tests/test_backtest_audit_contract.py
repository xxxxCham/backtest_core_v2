from __future__ import annotations

import pytest

from backtest.audit_contract import SilentOverrideAuditError, UnknownAuditParamError, reconcile_metrics
from backtest.audit_sentinels import make_sentinel_ohlcv
from backtest.engine import BacktestEngine
from tools.audit_backtest_contract import (
    evaluate_sensitivity_pair,
    recompute_and_reconcile,
    run_audited_once,
    run_reproducibility_check,
    run_sensitivity_suite,
)
from utils.config import Config


def test_unknown_param_is_rejected_in_strict_mode():
    with pytest.raises(UnknownAuditParamError, match="unused params"):
        run_audited_once(
            strategy="always_long",
            df=make_sentinel_ohlcv("trend"),
            params={"foo": 123, "leverage": 1, "fees_bps": 0, "slippage_bps": 0},
        )


def test_effective_config_contains_required_sections():
    run = run_audited_once(
        strategy="always_long",
        df=make_sentinel_ohlcv("trend"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )

    effective = run.audit["effective_config"]

    for key in (
        "provided_params",
        "strategy_defaults",
        "engine_defaults",
        "effective_params",
        "unused_params",
        "overridden_params",
        "coerced_params",
    ):
        assert key in effective
    assert effective["unused_params"] == []
    assert effective["effective_params"]["leverage"] == 1


def test_strict_mode_rejects_silent_engine_fee_override():
    engine = BacktestEngine(initial_capital=10000.0, config=Config(fees_bps=5, slippage_bps=0))

    with pytest.raises(SilentOverrideAuditError, match="silent critical overrides"):
        engine.run(
            df=make_sentinel_ohlcv("trend"),
            strategy="always_long",
            params={"leverage": 1, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            audit_mode=True,
            strict_params=True,
        )


def test_reproducibility_hashes_match_for_identical_runs():
    report, _run_a, _run_b = run_reproducibility_check(
        strategy="always_long",
        df=make_sentinel_ohlcv("trend"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )

    assert report["passed"] is True
    assert report["failures"] == []


def test_never_trade_has_zero_trades_and_reconciles():
    run = run_audited_once(
        strategy="never_trade",
        df=make_sentinel_ohlcv("flat"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0},
    )
    recomputed, reconciliation = recompute_and_reconcile(run)

    assert len(run.trades) == 0
    assert run.metrics["total_trades"] == 0
    assert recomputed["total_trades"] == 0
    assert reconciliation["passed"] is True


def test_always_long_reacts_to_leverage():
    df = make_sentinel_ohlcv("trend")
    base = run_audited_once(
        strategy="always_long",
        df=df,
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )
    variant = run_audited_once(
        strategy="always_long",
        df=df,
        params={"leverage": 3, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )

    assert variant.trades["size"].iloc[0] > base.trades["size"].iloc[0]
    assert variant.metrics["total_pnl"] > base.metrics["total_pnl"]
    assert evaluate_sensitivity_pair(baseline=base, variant=variant)["status"] == "affected"


def test_fees_slippage_reacts_to_fees():
    df = make_sentinel_ohlcv("flat")
    base = run_audited_once(
        strategy="fees_slippage",
        df=df,
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0},
    )
    variant = run_audited_once(
        strategy="fees_slippage",
        df=df,
        params={"leverage": 1, "fees_bps": 1000, "slippage_bps": 0},
    )

    assert variant.trades["fees_paid"].sum() > base.trades["fees_paid"].sum()
    assert variant.metrics["total_pnl"] < base.metrics["total_pnl"]
    assert evaluate_sensitivity_pair(baseline=base, variant=variant)["status"] == "affected"


def test_fees_slippage_reacts_to_slippage():
    df = make_sentinel_ohlcv("flat")
    base = run_audited_once(
        strategy="fees_slippage",
        df=df,
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0},
    )
    variant = run_audited_once(
        strategy="fees_slippage",
        df=df,
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 500},
    )

    assert variant.metrics["total_pnl"] < base.metrics["total_pnl"]
    assert variant.trades["price_entry"].tolist() != base.trades["price_entry"].tolist()
    assert evaluate_sensitivity_pair(baseline=base, variant=variant)["status"] == "affected"


def test_stop_near_exits_by_stop_loss():
    run = run_audited_once(
        strategy="stop_near",
        df=make_sentinel_ohlcv("stop"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 0.1},
    )

    assert "stop_loss" in set(run.trades["exit_reason"])


def test_tp_near_exits_by_take_profit():
    run = run_audited_once(
        strategy="tp_near",
        df=make_sentinel_ohlcv("tp"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 50.0, "take_profit_pct": 0.1},
    )

    assert "take_profit" in set(run.trades["exit_reason"])


def test_reconciliation_detects_falsified_metric():
    run = run_audited_once(
        strategy="always_long",
        df=make_sentinel_ohlcv("trend"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )
    recomputed, _ = recompute_and_reconcile(run)
    falsified = dict(run.metrics)
    falsified["total_pnl"] = float(falsified["total_pnl"]) + 1.0

    reconciliation = reconcile_metrics(falsified, recomputed)

    assert reconciliation["passed"] is False
    assert "total_pnl" in reconciliation["failures"]


def test_sensitivity_pair_reports_no_effect_when_hashes_do_not_change():
    run = run_audited_once(
        strategy="always_long",
        df=make_sentinel_ohlcv("trend"),
        params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
    )

    assert evaluate_sensitivity_pair(baseline=run, variant=run)["status"] == "no_effect"


def test_sensitivity_suite_covers_mvp_params():
    report = run_sensitivity_suite()

    assert {
        "leverage",
        "fees_bps",
        "slippage_bps",
        "k_sl",
        "take_profit_pct",
        "warmup",
        "direction",
    } <= set(report)
    assert all(payload["status"] == "affected" for payload in report.values())
