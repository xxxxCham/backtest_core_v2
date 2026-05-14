from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import catalog.graduation as graduation_module
import catalog.strategy_catalog as strategy_catalog_module
from backtest.walk_forward import FoldResult, WalkForwardSummary
from catalog.graduation import (
    GraduationCandidate,
    GraduationConfig,
    _default_positive_artifact_roots,
    _extract_numeric_params,
    _generate_neighborhood,
    import_positive_artifacts_to_catalog,
    promote_to_strategies,
    run_full_graduation,
    run_multi_context_validation,
    run_parameter_sensitivity,
    run_positive_import_graduation,
    run_wfa_validation,
    save_graduation_report,
    scan_positive_import_candidates,
    scan_sandbox,
    sync_graduation_to_catalog,
)
from catalog.strategy_catalog import read_catalog, upsert_entry, upsert_from_builder_session
from utils.parameters import ParameterSpec


def _write_session(
    root: Path,
    session_id: str,
    *,
    status: str,
    iterations: list[dict],
    objective: str = "",
    universe_mode: str = "",
    universe_purpose: str = "",
) -> None:
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("# stub\n", encoding="utf-8")
    payload = {
        "session_id": session_id,
        "status": status,
        "objective": objective,
        "iterations": iterations,
        "universe_mode": universe_mode,
        "universe_purpose": universe_purpose,
    }
    (session_dir / "session_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sample_ohlcv() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=120, freq="1h", tz="UTC")
    close = np.linspace(100.0, 120.0, len(index))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(len(index), 1000.0),
        },
        index=index,
    )


def test_pipeline_runtime_report_uses_draft_until_final(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    stable_report = output_dir / "graduation_full.json"
    stable_report.write_text('{"sentinel": "stable"}', encoding="utf-8")

    candidate = GraduationCandidate(
        session_id="sandbox-1",
        session_dir=tmp_path / "sandbox" / "sandbox-1",
        strategy_name="ema_cross",
        phase="P2",
        decision="WATCHLIST",
    )
    ctx = graduation_module._PipelineCtx(
        config=GraduationConfig(output_dir=output_dir, sandbox_dir=tmp_path / "sandbox"),
        stats={"p1_candidates": 1, "p2_processed": 1},
        all_candidates=[candidate],
        report_label="FULL",
        report_filename="graduation_full.json",
        pipeline_label="full_graduation",
        progress_filename="graduation_full_progress.json",
        started_at="2026-05-13T00:00:00+00:00",
        progress_path=output_dir / "graduation_full_progress.json",
        sync_func=lambda candidates, config=None: [],
        sync_conditional=True,
        promoted=[],
    )

    draft_report = graduation_module._ctx_save_report(ctx)

    assert draft_report == output_dir / "graduation_full.running.json"
    assert json.loads(stable_report.read_text(encoding="utf-8")) == {"sentinel": "stable"}
    assert draft_report.exists()

    graduation_module._ctx_write_progress(
        ctx,
        status="running",
        event="candidate_done",
        phase="P3",
        candidate=candidate,
        index=1,
        total=1,
    )
    progress_payload = json.loads((output_dir / "graduation_full_progress.json").read_text(encoding="utf-8"))
    assert progress_payload["report_path"].endswith("graduation_full.running.json")
    assert progress_payload["stable_report_path"].endswith("graduation_full.json")
    assert progress_payload["draft_report_path"].endswith("graduation_full.running.json")

    final_report = graduation_module._ctx_save_report(ctx, final=True)

    assert final_report == stable_report
    assert not draft_report.exists()
    final_payload = json.loads(stable_report.read_text(encoding="utf-8"))
    assert final_payload["stats"]["p1_candidates"] == 1


def test_scan_sandbox_uses_or_based_repechage(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"

    _write_session(
        sandbox,
        "success_candidate",
        status="success",
        objective='{"objective": "trend alpha"}',
        universe_mode="canonical",
        universe_purpose="builder_autonomous",
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 10.0,
                "return_pct": -5.0,
                "profit_factor": 0.8,
                "sharpe": 0.1,
                "trades": 10,
            },
        ],
    )
    _write_session(
        sandbox,
        "score_candidate",
        status="failed",
        objective="score-based idea",
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 55.0,
                "return_pct": -12.0,
                "profit_factor": 0.9,
                "sharpe": -0.3,
                "trades": 14,
            },
        ],
    )
    _write_session(
        sandbox,
        "pf_candidate",
        status="failed",
        objective="pf-based idea",
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 5.0,
                "return_pct": -1.0,
                "profit_factor": 1.3,
                "sharpe": 0.0,
                "trades": 4,
            },
        ],
    )
    _write_session(
        sandbox,
        "rejected_candidate",
        status="failed",
        objective="bad idea",
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 5.0,
                "return_pct": -15.0,
                "profit_factor": 0.7,
                "sharpe": -1.0,
                "trades": 8,
            },
        ],
    )

    candidates = scan_sandbox(GraduationConfig(sandbox_dir=sandbox))

    assert [candidate.session_id for candidate in candidates] == [
        "score_candidate",
        "success_candidate",
        "pf_candidate",
    ]
    assert candidates[1].objective == "trend alpha"
    assert candidates[1].source_universe_mode == "canonical"
    assert candidates[1].source_universe_purpose == "builder_autonomous"
    assert "status=success" in candidates[1].inclusion_reasons
    assert any(reason.startswith("score=") for reason in candidates[0].inclusion_reasons)
    assert any(reason.startswith("PF=") for reason in candidates[2].inclusion_reasons)


def test_scan_sandbox_keeps_all_positive_iterations_from_same_session(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    session_dir = sandbox / "multi_positive"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("# v1\n", encoding="utf-8")
    (session_dir / "strategy_v2.py").write_text("# v2\n", encoding="utf-8")
    (session_dir / "strategy_v3.py").write_text("# v3\n", encoding="utf-8")
    _write_session(
        sandbox,
        "multi_positive",
        status="max_iterations",
        objective="multi candidate session",
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 12.0,
                "return_pct": -4.0,
                "profit_factor": 0.9,
                "sharpe": 0.1,
                "trades": 10,
                "params_used": {"fast_period": 8},
            },
            {
                "iteration": 2,
                "continuous_score": 28.0,
                "return_pct": 6.0,
                "profit_factor": 1.1,
                "sharpe": 0.6,
                "trades": 20,
                "params_used": {"fast_period": 12},
            },
            {
                "iteration": 3,
                "continuous_score": 19.0,
                "return_pct": 3.5,
                "profit_factor": 1.05,
                "sharpe": 0.4,
                "trades": 14,
                "params_used": {"fast_period": 15},
            },
        ],
    )

    candidates = scan_sandbox(GraduationConfig(sandbox_dir=sandbox))

    assert len(candidates) == 2
    assert [candidate.session_id for candidate in candidates] == ["multi_positive", "multi_positive"]
    assert [candidate.best_iteration for candidate in candidates] == [2, 3]
    assert [candidate.strategy_params for candidate in candidates] == [{"fast_period": 12}, {"fast_period": 15}]
    assert all(candidate.best_return_pct > 0 for candidate in candidates)
    assert candidates[0].candidate_id == "builder:multi_positive:2"


def test_extract_numeric_params_reads_specs_and_defaults() -> None:
    class FakeStrategy:
        @property
        def parameter_specs(self):
            return {
                "fast_period": ParameterSpec(
                    name="fast_period",
                    min_val=5,
                    max_val=50,
                    default=12,
                    param_type="int",
                    optimize=True,
                ),
                "warmup": ParameterSpec(
                    name="warmup",
                    min_val=10,
                    max_val=100,
                    default=30,
                    param_type="int",
                    optimize=False,
                ),
            }

        @property
        def default_params(self):
            return {"leverage": 2, "stop_atr_mult": 1.5, "enabled": True}

    params = _extract_numeric_params(FakeStrategy())

    assert params["fast_period"] == 12.0
    assert params["leverage"] == 2.0
    assert params["stop_atr_mult"] == 1.5
    assert "warmup" not in params
    assert "enabled" not in params


def test_generate_neighborhood_caps_combination_count_and_keeps_base() -> None:
    base_params = {
        "a": 10.0,
        "b": 20.0,
        "c": 30.0,
        "d": 40.0,
        "e": 50.0,
    }

    neighborhood = _generate_neighborhood(
        base_params,
        pct=0.10,
        n_steps=3,
        max_combinations=20,
    )

    assert len(neighborhood) <= 20
    assert {"a": 10, "b": 20, "c": 30, "d": 40, "e": 50} in neighborhood


def test_run_wfa_validation_requires_positive_average_test_return(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pass_dir = tmp_path / "pass"
    fail_dir = tmp_path / "fail"
    pass_dir.mkdir()
    fail_dir.mkdir()
    (pass_dir / "strategy_v1.py").write_text("# pass\n", encoding="utf-8")
    (fail_dir / "strategy_v1.py").write_text("# fail\n", encoding="utf-8")

    candidates = [
        GraduationCandidate(
            session_id="pass",
            session_dir=pass_dir,
            best_iteration=1,
            strategy_file="pass/strategy_v1.py",
        ),
        GraduationCandidate(
            session_id="fail",
            session_dir=fail_dir,
            best_iteration=1,
            strategy_file="fail/strategy_v1.py",
        ),
    ]

    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(name=path.parent.name),
    )
    monkeypatch.setattr("data.loader.load_ohlcv", lambda symbol, timeframe: _sample_ohlcv())

    def _fake_wfa(df, strategy_name, params, config, **kwargs):
        if strategy_name.name == "pass":
            folds = [
                FoldResult(
                    fold_id=0,
                    train_start=0,
                    train_end=40,
                    test_start=40,
                    test_end=60,
                    train_metrics={"sharpe_ratio": 1.2},
                    test_metrics={"sharpe_ratio": 0.8, "total_return_pct": 8.0},
                ),
                FoldResult(
                    fold_id=1,
                    train_start=0,
                    train_end=60,
                    test_start=60,
                    test_end=80,
                    train_metrics={"sharpe_ratio": 1.1},
                    test_metrics={"sharpe_ratio": 0.5, "total_return_pct": 4.0},
                ),
            ]
            return WalkForwardSummary(
                config=config,
                folds=folds,
                avg_test_sharpe=0.65,
                test_stability_std=0.15,
                confidence_score=0.72,
                n_valid_folds=2,
            )

        folds = [
            FoldResult(
                fold_id=0,
                train_start=0,
                train_end=40,
                test_start=40,
                test_end=60,
                train_metrics={"sharpe_ratio": 1.0},
                test_metrics={"sharpe_ratio": 0.7, "total_return_pct": -3.0},
            ),
            FoldResult(
                fold_id=1,
                train_start=0,
                train_end=60,
                test_start=60,
                test_end=80,
                train_metrics={"sharpe_ratio": 0.9},
                test_metrics={"sharpe_ratio": 0.4, "total_return_pct": -1.0},
            ),
        ]
        return WalkForwardSummary(
            config=config,
            folds=folds,
            avg_test_sharpe=0.55,
            test_stability_std=0.12,
            confidence_score=0.81,
            n_valid_folds=2,
        )

    monkeypatch.setattr("backtest.walk_forward.run_walk_forward", _fake_wfa)

    survivors = run_wfa_validation(
        candidates,
        GraduationConfig(validation_tokens=["BTCUSDC"], validation_timeframes=["1h"]),
    )

    assert [candidate.session_id for candidate in survivors] == ["pass"]
    assert candidates[0].wfa_stability == 0.72
    assert candidates[0].wfa_avg_test_return_pct == 6.0
    assert candidates[0].wfa_positive_folds_pct == 100.0
    assert "avg_test_return" in candidates[1].rejection_reason


def test_run_parameter_sensitivity_uses_source_market_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_dir = tmp_path / "source"
    session_dir.mkdir()
    (session_dir / "strategy_v1.py").write_text("# source\n", encoding="utf-8")

    candidate = GraduationCandidate(
        session_id="source",
        session_dir=session_dir,
        best_iteration=1,
        source_symbol="ETHUSDC",
        source_timeframe="1d",
        strategy_file="strategy_v1.py",
    )

    load_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(name="source_strategy"),
    )
    monkeypatch.setattr(
        "data.loader.load_ohlcv",
        lambda symbol, timeframe: load_calls.append((symbol, timeframe)) or _sample_ohlcv(),
    )

    survivors = run_parameter_sensitivity(
        [candidate],
        GraduationConfig(
            validation_tokens=["BTCUSDC"],
            validation_timeframes=["1h"],
            source_min_history_bars_by_timeframe={"1d": 100},
        ),
    )

    assert survivors == [candidate]
    assert load_calls == [("ETHUSDC", "1d")]
    assert candidate.p4_verdict == "PASSED"
    assert candidate.sensitivity_scope == "source_market"
    assert candidate.sensitivity_symbol == "ETHUSDC"
    assert candidate.sensitivity_timeframe == "1d"
    assert candidate.sensitivity_history_bars == 120
    assert candidate.sensitivity_min_history_bars == 100


def test_run_wfa_validation_uses_source_market_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_dir = tmp_path / "source_wfa"
    session_dir.mkdir()
    (session_dir / "strategy_v1.py").write_text("# source\n", encoding="utf-8")

    candidate = GraduationCandidate(
        session_id="source_wfa",
        session_dir=session_dir,
        best_iteration=1,
        source_symbol="ETHUSDC",
        source_timeframe="1d",
        strategy_file="strategy_v1.py",
    )

    load_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(name="source_strategy"),
    )
    monkeypatch.setattr(
        "data.loader.load_ohlcv",
        lambda symbol, timeframe: load_calls.append((symbol, timeframe)) or _sample_ohlcv(),
    )

    def _fake_wfa(df, strategy_name, params, config, **kwargs):
        folds = [
            FoldResult(
                fold_id=0,
                train_start=0,
                train_end=40,
                test_start=40,
                test_end=60,
                train_metrics={"sharpe_ratio": 1.2},
                test_metrics={"sharpe_ratio": 0.8, "total_return_pct": 8.0},
            ),
            FoldResult(
                fold_id=1,
                train_start=0,
                train_end=60,
                test_start=60,
                test_end=80,
                train_metrics={"sharpe_ratio": 1.0},
                test_metrics={"sharpe_ratio": 0.7, "total_return_pct": 6.0},
            ),
        ]
        return WalkForwardSummary(
            config=config,
            folds=folds,
            avg_test_sharpe=0.75,
            avg_overfitting_ratio=1.1,
            confidence_score=0.8,
            n_valid_folds=2,
            is_robust=True,
        )

    monkeypatch.setattr("backtest.walk_forward.run_walk_forward", _fake_wfa)

    survivors = run_wfa_validation(
        [candidate],
        GraduationConfig(
            validation_tokens=["BTCUSDC"],
            validation_timeframes=["1h"],
            source_min_history_bars_by_timeframe={"1d": 100},
        ),
    )

    assert survivors == [candidate]
    assert load_calls == [("ETHUSDC", "1d")]
    assert candidate.p5_verdict == "PASSED"
    assert candidate.wfa_scope == "source_market"
    assert candidate.wfa_symbol == "ETHUSDC"
    assert candidate.wfa_timeframe == "1d"
    assert candidate.wfa_history_bars == 120
    assert candidate.wfa_min_history_bars == 100
    assert candidate.wfa_avg_test_return_pct == 7.0
    assert candidate.wfa_valid_folds == 2
    assert candidate.wfa_positive_folds_pct == 100.0


def test_run_wfa_validation_rejects_source_market_without_enough_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = GraduationCandidate(
        session_id="short_source",
        session_dir=tmp_path,
        best_iteration=1,
        source_symbol="ETHUSDC",
        source_timeframe="1d",
    )

    monkeypatch.setattr("data.loader.load_ohlcv", lambda symbol, timeframe: _sample_ohlcv().iloc[:50])
    monkeypatch.setattr(
        "backtest.walk_forward.run_walk_forward",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("WFA should not run")),
    )

    survivors = run_wfa_validation(
        [candidate],
        GraduationConfig(
            validation_tokens=["BTCUSDC"],
            validation_timeframes=["1h"],
            source_min_history_bars_by_timeframe={"1d": 100},
        ),
    )

    assert survivors == []
    assert candidate.p5_verdict == "REJECTED"
    assert candidate.wfa_scope == "source_market"
    assert candidate.wfa_history_bars == 50
    assert "source history insufficient" in candidate.rejection_reason


def test_save_graduation_report_normalizes_json_payload(tmp_path: Path) -> None:
    candidate = GraduationCandidate(
        session_id="candidate",
        session_dir=tmp_path,
        origin_status="failed",
        phase="P2",
        strategy_file="candidate/strategy_v1.py",
        multi_ctx_results={
            "contexts": {
                "BTCUSDC_1h": {
                    "passed": np.bool_(True),
                    "profit_factor": float("inf"),
                },
            },
        },
    )

    report_path = save_graduation_report(
        [candidate],
        tmp_path,
        phase="FULL",
        filename="graduation_full.json",
        stats={"p1_candidates": np.int64(1)},
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["phase"] == "FULL"
    assert payload["stats"]["p1_candidates"] == 1
    assert payload["candidates"][0]["multi_ctx_results"]["contexts"]["BTCUSDC_1h"]["passed"] is True
    assert payload["candidates"][0]["multi_ctx_results"]["contexts"]["BTCUSDC_1h"]["profit_factor"] is None


def test_save_graduation_report_persists_cli_contract_meta(tmp_path: Path) -> None:
    candidate = GraduationCandidate(session_id="candidate", session_dir=tmp_path)

    report_path = save_graduation_report(
        [candidate],
        tmp_path,
        phase="FULL",
        filename="graduation_full.json",
        meta={
            "cli_equivalent": "python -m catalog.graduation --full --sync-catalog",
            "phase_contract": {"P1": {"name": "Inventaire", "purpose": "scan"}},
            "config_snapshot": {"source_market_first": True},
        },
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["meta"]["cli_equivalent"] == "python -m catalog.graduation --full --sync-catalog"
    assert payload["meta"]["phase_contract"]["P1"]["name"] == "Inventaire"
    assert payload["meta"]["config_snapshot"]["source_market_first"] is True


def test_candidate_to_dict_exposes_context_lists_counts_and_benchmark_summaries(tmp_path: Path) -> None:
    candidate = GraduationCandidate(
        session_id="candidate",
        session_dir=tmp_path,
        strategy_name="ema_cross",
        configured_contexts=["BTCUSDC_1h", "ETHUSDC_1h", "BTCUSDC_4h"],
        loaded_contexts=["BTCUSDC_1h", "ETHUSDC_1h"],
        missing_contexts=["BTCUSDC_4h"],
        tested_timeframes=["1h", "4h"],
        multi_ctx_results={
            "contexts": {
                "BTCUSDC_1h": {"passed": True},
                "ETHUSDC_1h": {"passed": True},
                "BTCUSDC_4h": {"passed": False},
            },
            "passed_count": 2,
            "total_contexts": 3,
            "configured_benchmark_slots": 4,
            "loaded_benchmark_slots": 3,
            "excluded_context_count": 1,
            "benchmark_slot_coverage_pct": 75.0,
        },
        benchmark_results={
            "crypto_liquid_benchmark_v1_core": {"tokens": ["BTCUSDC", "ETHUSDC"]},
            "crypto_liquid_benchmark_v3_balanced": {"tokens": ["BTCUSDC", "LINKUSDC"]},
        },
        benchmark_consensus={
            "benchmarks_passed": ["crypto_liquid_benchmark_v1_core"],
            "benchmarks_total": 2,
        },
    )

    payload = candidate.to_dict()

    assert payload["configured_contexts"] == ["BTCUSDC_1h", "ETHUSDC_1h", "BTCUSDC_4h"]
    assert payload["loaded_contexts"] == ["BTCUSDC_1h", "ETHUSDC_1h"]
    assert payload["missing_contexts"] == ["BTCUSDC_4h"]
    assert payload["configured_context_count"] == 3
    assert payload["loaded_context_count"] == 2
    assert payload["missing_context_count"] == 1
    assert payload["configured_benchmark_slot_count"] == 4
    assert payload["loaded_benchmark_slot_count"] == 3
    assert payload["excluded_context_count"] == 1
    assert payload["context_pass_summary"] == "2/3"
    assert payload["benchmark_slot_coverage_pct"] == 75.0
    assert payload["tested_tokens"] == "BTCUSDC,ETHUSDC,LINKUSDC"
    assert payload["tested_benchmark_names"] == ("crypto_liquid_benchmark_v1_core,crypto_liquid_benchmark_v3_balanced")
    assert payload["benchmark_pass_summary"] == "1/2"
    assert payload["tested_timeframes"] == ["1h", "4h"]
    assert payload["timeframes_tested"] == "1h,4h"


def test_sync_graduation_to_catalog_maps_progression_levels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    p1_dir = tmp_path / "p1"
    p3_dir = tmp_path / "p3"
    p5_dir = tmp_path / "p5"
    for path in (p1_dir, p3_dir, p5_dir):
        path.mkdir()
        (path / "strategy_v1.py").write_text("# strategy\n", encoding="utf-8")

    candidates = [
        GraduationCandidate(
            session_id="cand_p1",
            session_dir=p1_dir,
            best_iteration=1,
            strategy_file="p1/strategy_v1.py",
            decision="REJECTED",
            phase="P2",
            p2_verdict="REJECTED",
            multi_ctx_results={"passed_count": 1, "total_contexts": 6},
        ),
        GraduationCandidate(
            session_id="cand_p3",
            session_dir=p3_dir,
            best_iteration=1,
            strategy_file="p3/strategy_v1.py",
            decision="REJECTED",
            phase="P5",
            p2_verdict="PASSED",
            p3_verdict="PASSED",
            p4_verdict="PASSED",
            p5_verdict="REJECTED",
            benchmark_consensus={"consensus_passed": True},
            multi_ctx_results={"passed_count": 3, "total_contexts": 6},
            sweep_robustness_pct=44.0,
            rejection_reason="WFA instable 0.21<0.5",
        ),
        GraduationCandidate(
            session_id="cand_p5",
            session_dir=p5_dir,
            best_iteration=1,
            strategy_file=str(tmp_path / "strategies" / "graduated" / "cand_p5.py"),
            decision="PROMOTED",
            phase="P6",
            p2_verdict="PASSED",
            p3_verdict="PASSED",
            p4_verdict="PASSED",
            p5_verdict="PASSED",
            p6_verdict="PROMOTED",
            benchmark_consensus={"consensus_passed": True},
            multi_ctx_results={"passed_count": 4, "total_contexts": 6},
            sweep_robustness_pct=66.0,
            wfa_stability=0.81,
            wfa_avg_test_return_pct=7.2,
        ),
    ]

    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(
            name=f"strategy_{path.parent.name}",
            default_params={"fast_period": 12, "slow_period": 26},
        ),
    )

    config = GraduationConfig(
        catalog_path=tmp_path / "strategy_catalog.json",
        validation_tokens=["BTCUSDC", "SOLUSDC", "AVAXUSDC"],
        validation_timeframes=["1h", "4h"],
    )

    synced = sync_graduation_to_catalog(candidates, config)
    catalog = read_catalog(config.catalog_path)

    assert len(synced) == 3
    assert len(catalog["entries"]) == 3
    assert [candidate.catalog_category for candidate in candidates] == [
        "p1_builder_inbox",
        "p4_param_robust",
        "p6_paper_candidate",
    ]
    assert all(candidate.catalog_entry_id for candidate in candidates)
    by_session = {entry["meta"]["session_id"]: entry for entry in synced}
    assert by_session["cand_p1"]["builder_state"] == "stopped"
    assert by_session["cand_p3"]["builder_state"] == "completed"
    assert by_session["cand_p5"]["builder_state"] == "completed"


def test_sync_graduation_to_catalog_reuses_builder_iteration_entry(tmp_path: Path, monkeypatch) -> None:
    catalog_path = tmp_path / "strategy_catalog.json"
    session = SimpleNamespace(
        session_id="sess-sync",
        symbol="BTCUSDC",
        timeframe="1h",
        status="success",
        best_iteration=SimpleNamespace(
            iteration=2,
            backtest_result=SimpleNamespace(
                metrics={
                    "total_return_pct": 9.5,
                    "sharpe_ratio": 1.0,
                    "profit_factor": 1.18,
                    "total_trades": 24,
                },
                meta={"params": {"fast_period": 12, "slow_period": 26}},
            ),
            phase_feedback={},
        ),
        target_sharpe=1.0,
        objective="Aligner le catalogue avec la graduation",
        best_sharpe=1.0,
        iterations=[
            SimpleNamespace(
                iteration=2,
                backtest_result=SimpleNamespace(
                    metrics={
                        "total_return_pct": 9.5,
                        "sharpe_ratio": 1.0,
                        "profit_factor": 1.18,
                        "total_trades": 24,
                    },
                    meta={"params": {"fast_period": 12, "slow_period": 26}},
                ),
                phase_feedback={},
            ),
        ],
        universe_mode="canonical",
        universe_purpose="builder_manual",
        universe_strategy_type="trend",
        session_dir=tmp_path / "sandbox" / "sess-sync",
    )
    session.session_dir.mkdir(parents=True, exist_ok=True)
    (session.session_dir / "strategy_v2.py").write_text("# strategy\n", encoding="utf-8")

    builder_entry = upsert_from_builder_session(session, path=catalog_path)

    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(name="ema_cross", default_params={"fast_period": 12, "slow_period": 26}),
    )

    candidate = GraduationCandidate(
        session_id="sess-sync",
        session_dir=session.session_dir,
        candidate_id="builder:sess-sync:2",
        strategy_name="ema_cross",
        strategy_params={"fast_period": 12, "slow_period": 26},
        source_symbol="BTCUSDC",
        source_timeframe="1h",
        best_iteration=2,
        best_return_pct=9.5,
        best_profit_factor=1.18,
        best_sharpe=1.0,
        best_trades=24,
        decision="WATCHLIST",
        phase="P5",
        p2_verdict="PASSED",
        p3_verdict="PASSED",
        p4_verdict="PASSED",
        p5_verdict="PASSED",
        benchmark_consensus={"consensus_passed": True},
        multi_ctx_results={"passed_count": 3, "total_contexts": 6},
        sweep_robustness_pct=52.0,
        wfa_stability=0.73,
        wfa_avg_test_return_pct=6.4,
        strategy_file=str((session.session_dir / "strategy_v2.py").relative_to(tmp_path / "sandbox")),
    )
    config = GraduationConfig(catalog_path=catalog_path, sandbox_dir=tmp_path / "sandbox")

    synced = sync_graduation_to_catalog([candidate], config)
    catalog = read_catalog(catalog_path)

    assert len(synced) == 1
    assert len(catalog["entries"]) == 1
    assert synced[0]["id"] == builder_entry["id"]
    assert synced[0]["category"] == "p5_wfa_candidate"
    assert synced[0]["strategy_name"] == "ema_cross"
    assert candidate.catalog_entry_id == builder_entry["id"]


def test_import_positive_artifacts_imports_overview_rows_and_copies_builder_session(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "legacy_root"
    overview_dir = source_root / "backtest_results" / "_catalog"
    overview_dir.mkdir(parents=True, exist_ok=True)
    sandbox_source = source_root / "sandbox_strategies" / "sess-positive"
    sandbox_source.mkdir(parents=True, exist_ok=True)
    (sandbox_source / "session_summary.json").write_text("{}", encoding="utf-8")

    (overview_dir / "unified_overview.csv").write_text(
        "\n".join(
            [
                "artifact_type,schema,path,run_id,mode,status,strategy,symbol,timeframe,metrics_total_return_pct,metrics_sharpe_ratio,metrics_profit_factor,metrics_total_trades,extra_builder_session_id",
                "saved_run,native_saved_run,runs/run_positive,run_positive,backtest,ok,ema_cross,BTCUSDC,1h,12.5,1.4,1.2,45,sess-positive",
                "saved_run,native_saved_run,runs/run_negative,run_negative,backtest,ok,ema_cross,ETHUSDC,4h,-3.0,0.1,0.9,12,",
            ],
        ),
        encoding="utf-8",
    )

    config = GraduationConfig(
        sandbox_dir=tmp_path / "sandbox_target",
        output_dir=tmp_path / "reports",
        catalog_path=tmp_path / "strategy_catalog.json",
    )

    report = import_positive_artifacts_to_catalog(config, source_roots=[source_root])
    catalog = read_catalog(config.catalog_path)

    assert report["stats"]["overview_positive_rows"] == 1
    assert report["stats"]["catalog_entries_touched"] == 1
    assert report["stats"]["builder_sessions_copied"] == 1
    assert (config.sandbox_dir / "sess-positive" / "session_summary.json").exists()
    assert len(catalog["entries"]) == 1
    entry = catalog["entries"][0]
    assert entry["category"] == "p2_positive_observed"
    assert "positive_import" in entry["tags"]
    assert "positive_return" in entry["tags"]
    assert entry["meta"]["builder_session_id"] == "sess-positive"
    assert entry["meta"]["import_source_kind"] == "unified_overview"
    assert entry["meta"]["positive_return_pct"] == 12.5


def test_default_positive_artifact_roots_requires_explicit_legacy_opt_in(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    artifacts_root = tmp_path / "artifacts"
    legacy_root = tmp_path / "legacy_root"
    workspace_root.mkdir()
    artifacts_root.mkdir()
    legacy_root.mkdir()

    monkeypatch.setattr("catalog.graduation._workspace_root", lambda: workspace_root)
    monkeypatch.setattr("catalog.graduation.get_artifacts_root_dir", lambda *_args, **_kwargs: artifacts_root)
    monkeypatch.setattr("catalog.graduation._LEGACY_ARTIFACT_ROOT_CANDIDATES", (legacy_root,))

    roots_default = _default_positive_artifact_roots(GraduationConfig())
    roots_with_legacy = _default_positive_artifact_roots(
        GraduationConfig(include_legacy_artifact_roots=True),
    )

    assert legacy_root.resolve() not in roots_default
    assert legacy_root.resolve() in roots_with_legacy


def test_import_positive_artifacts_uses_metadata_fallback_and_skips_duplicates(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "mixed_root"
    overview_dir = source_root / "backtest_results" / "_catalog"
    overview_dir.mkdir(parents=True, exist_ok=True)
    run_dir = source_root / "backtest_results" / "run_positive"
    run_dir.mkdir(parents=True, exist_ok=True)
    extra_dir = source_root / "backtest_results" / "run_extra"
    extra_dir.mkdir(parents=True, exist_ok=True)

    (overview_dir / "unified_overview.csv").write_text(
        "\n".join(
            [
                "artifact_type,schema,path,run_id,mode,status,strategy,symbol,timeframe,metrics_total_return_pct,metrics_sharpe_ratio,metrics_profit_factor,metrics_total_trades",
                "saved_run,native_saved_run,backtest_results/run_positive,run_positive,backtest,ok,rsi_reversal,SOLUSDC,1h,8.0,1.1,1.15,31",
            ],
        ),
        encoding="utf-8",
    )

    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "run_positive",
                "strategy": "rsi_reversal",
                "symbol": "SOLUSDC",
                "timeframe": "1h",
                "status": "ok",
                "mode": "builder",
                "metrics": {"total_return_pct": 8.0, "sharpe_ratio": 1.1},
            },
        ),
        encoding="utf-8",
    )
    (extra_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "run_extra",
                "strategy": "ema_cross",
                "symbol": "AVAXUSDC",
                "timeframe": "4h",
                "status": "ok",
                "mode": "builder",
                "metrics": {"total_return_pct": 4.5, "sharpe_ratio": 0.7},
            },
        ),
        encoding="utf-8",
    )

    config = GraduationConfig(
        sandbox_dir=tmp_path / "sandbox_target",
        output_dir=tmp_path / "reports",
        catalog_path=tmp_path / "strategy_catalog.json",
    )

    report = import_positive_artifacts_to_catalog(config, source_roots=[source_root])
    catalog = read_catalog(config.catalog_path)

    assert report["stats"]["overview_positive_rows"] == 1
    assert report["stats"]["metadata_positive_rows"] == 2
    assert report["stats"]["duplicates_skipped"] == 1
    assert report["stats"]["catalog_entries_touched"] == 2
    assert sorted(entry["meta"]["source_run_id"] for entry in catalog["entries"]) == [
        "run_extra",
        "run_positive",
    ]


def test_run_multi_context_validation_uses_unique_context_coverage_and_keeps_benchmark_gaps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sandbox_dir = tmp_path / "sandbox"
    session_dir = sandbox_dir / "sess-1"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("# strategy\n", encoding="utf-8")

    candidate = GraduationCandidate(
        session_id="sess-1",
        session_dir=session_dir,
        best_iteration=1,
        strategy_file="sess-1/strategy_v1.py",
    )

    load_calls: list[tuple[str, str]] = []

    def _fake_load_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame:
        load_calls.append((symbol, timeframe))
        return _sample_ohlcv()

    monkeypatch.setattr("catalog.graduation._load_strategy_from_file", lambda path: SimpleNamespace(name=path.stem))
    monkeypatch.setattr("data.loader.load_ohlcv", _fake_load_ohlcv)
    monkeypatch.setattr(
        "config.market_selection.get_postfilter_benchmark_config",
        lambda: {
            "benchmarks": {
                "bench_a": {"label": "Bench A", "tokens": ["BTCUSDC", "ETHUSDC"]},
                "bench_b": {"label": "Bench B", "tokens": ["BTCUSDC"]},
            },
        },
    )
    monkeypatch.setattr(
        "config.market_selection.evaluate_market_dataset",
        lambda _df, symbol, timeframe, universe_mode, purpose: {
            "accepted": symbol != "ETHUSDC",
            "exclusion_reasons": ["unit_test_excluded"] if symbol == "ETHUSDC" else [],
        },
    )
    monkeypatch.setattr(
        "config.market_selection.infer_strategy_type",
        lambda objective, strategy_key: "trend",
    )

    class _FakeEngine:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self, df, strategy, params, fast_metrics, silent_mode):
            return SimpleNamespace(
                metrics={
                    "total_return_pct": 6.0,
                    "max_drawdown_pct": 12.0,
                    "profit_factor": 1.2,
                    "total_trades": 45,
                    "sharpe_ratio": 0.8,
                },
            )

    monkeypatch.setattr("backtest.engine.BacktestEngine", _FakeEngine)

    config = GraduationConfig(
        benchmark_names=["bench_a", "bench_b"],
        token_count=2,
        validation_timeframes=["1h"],
        required_benchmark_name="bench_a",
        min_benchmarks_pass=1,
        min_contexts_pass=1,
        min_context_coverage_pct=40.0,
    )

    survivors = run_multi_context_validation([candidate], config)

    assert [item.session_id for item in survivors] == ["sess-1"]
    assert candidate.coverage_pct == 100.0
    assert candidate.multi_ctx_results["benchmark_slot_coverage_pct"] == 66.7
    assert candidate.multi_ctx_results["passed_count"] == 1
    assert candidate.multi_ctx_results["total_contexts"] == 1
    assert candidate.multi_ctx_results["configured_context_count"] == 2
    assert candidate.benchmark_results["bench_a"]["missing_context_count"] == 1
    assert candidate.benchmark_results["bench_a"]["coverage_pct"] == 100.0
    assert candidate.benchmark_results["bench_a"]["configured_coverage_pct"] == 50.0
    assert "excluded_by_universe" in candidate.benchmark_results["bench_a"]["contexts"]["ETHUSDC_1h"]["error"]
    assert load_calls.count(("BTCUSDC", "1h")) == 1
    assert load_calls.count(("ETHUSDC", "1h")) == 1


def test_import_positive_artifacts_to_catalog_batches_catalog_write(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    catalog_dir = source_root / "backtest_results" / "_catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "unified_overview.csv").write_text(
        "run_id,strategy,symbol,timeframe,status,metrics_total_return_pct,path\n"
        "run_positive,ema_cross,BTCUSDC,1h,ok,6.5,run_positive\n"
        "run_positive_2,ema_cross,ETHUSDC,4h,ok,7.5,run_positive_2\n",
        encoding="utf-8",
    )

    config = GraduationConfig(
        sandbox_dir=tmp_path / "sandbox_target",
        output_dir=tmp_path / "reports",
        catalog_path=tmp_path / "strategy_catalog.json",
    )

    write_calls: list[int] = []
    original_write_catalog = strategy_catalog_module.write_catalog

    def _tracked_write(payload, path=None):
        write_calls.append(1)
        return original_write_catalog(payload, path=path)

    monkeypatch.setattr(strategy_catalog_module, "write_catalog", _tracked_write)

    report = import_positive_artifacts_to_catalog(config, source_roots=[source_root])

    assert report["stats"]["catalog_entries_touched"] == 2
    assert len(write_calls) == 1
    assert len(read_catalog(config.catalog_path)["entries"]) == 2


def test_run_multi_context_validation_uses_eligible_contexts_for_benchmark_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sandbox_dir = tmp_path / "sandbox"
    session_dir = sandbox_dir / "sess-eligible"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("# strategy\n", encoding="utf-8")

    candidate = GraduationCandidate(
        session_id="sess-eligible",
        session_dir=session_dir,
        best_iteration=1,
        strategy_file="sess-eligible/strategy_v1.py",
    )

    monkeypatch.setattr("catalog.graduation._load_strategy_from_file", lambda path: SimpleNamespace(name=path.stem))
    monkeypatch.setattr("data.loader.load_ohlcv", lambda symbol, timeframe: _sample_ohlcv())
    monkeypatch.setattr(
        "config.market_selection.get_postfilter_benchmark_config",
        lambda: {
            "benchmarks": {
                "bench_core": {"label": "Core", "tokens": ["BTCUSDC", "ETHUSDC"]},
            },
        },
    )
    monkeypatch.setattr(
        "config.market_selection.evaluate_market_dataset",
        lambda _df, symbol, timeframe, universe_mode, purpose: {
            "accepted": symbol == "BTCUSDC",
            "exclusion_reasons": ["unit_test_excluded"] if symbol != "BTCUSDC" else [],
        },
    )
    monkeypatch.setattr("config.market_selection.infer_strategy_type", lambda objective, strategy_key: "trend")

    class _FakeEngine:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self, df, strategy, params, fast_metrics, silent_mode):
            return SimpleNamespace(
                metrics={
                    "total_return_pct": 5.0,
                    "max_drawdown_pct": 10.0,
                    "profit_factor": 1.15,
                    "total_trades": 30,
                    "sharpe_ratio": 0.7,
                },
            )

    monkeypatch.setattr("backtest.engine.BacktestEngine", _FakeEngine)

    survivors = run_multi_context_validation(
        [candidate],
        GraduationConfig(
            benchmark_names=["bench_core"],
            token_count=2,
            validation_timeframes=["1h"],
            required_benchmark_name="bench_core",
            min_benchmarks_pass=1,
            min_contexts_pass=1,
            min_context_coverage_pct=80.0,
        ),
    )

    assert [item.session_id for item in survivors] == ["sess-eligible"]
    assert candidate.coverage_pct == 100.0
    assert candidate.multi_ctx_results["eligible_context_count"] == 1
    assert candidate.multi_ctx_results["configured_context_count"] == 2
    assert candidate.benchmark_results["bench_core"]["coverage_pct"] == 100.0
    assert candidate.benchmark_results["bench_core"]["configured_coverage_pct"] == 50.0
    assert candidate.benchmark_results["bench_core"]["eligible_context_count"] == 1
    assert candidate.benchmark_results["bench_core"]["excluded_context_count"] == 1


def test_sync_graduation_to_catalog_batches_catalog_updates(tmp_path: Path, monkeypatch) -> None:
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    config = GraduationConfig(catalog_path=tmp_path / "strategy_catalog.json", sandbox_dir=sandbox_dir)

    session_dirs = [sandbox_dir / "sess-a", sandbox_dir / "sess-b"]
    for session_dir in session_dirs:
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "strategy_v1.py").write_text("# strategy\n", encoding="utf-8")

    candidates = [
        GraduationCandidate(
            session_id="sess-a",
            session_dir=session_dirs[0],
            candidate_id="builder:sess-a:1",
            strategy_name="ema_cross",
            strategy_params={"fast_period": 12},
            source_symbol="BTCUSDC",
            source_timeframe="1h",
            best_iteration=1,
            decision="REJECTED",
            phase="P2",
            p2_verdict="REJECTED",
            strategy_file="sess-a/strategy_v1.py",
        ),
        GraduationCandidate(
            session_id="sess-b",
            session_dir=session_dirs[1],
            candidate_id="builder:sess-b:1",
            strategy_name="ema_cross",
            strategy_params={"fast_period": 18},
            source_symbol="ETHUSDC",
            source_timeframe="4h",
            best_iteration=1,
            decision="WATCHLIST",
            phase="P5",
            p2_verdict="PASSED",
            p3_verdict="PASSED",
            p4_verdict="PASSED",
            p5_verdict="PASSED",
            benchmark_consensus={"consensus_passed": True},
            multi_ctx_results={"passed_count": 3, "total_contexts": 4},
            strategy_file="sess-b/strategy_v1.py",
        ),
    ]

    monkeypatch.setattr(
        "catalog.graduation._load_strategy_from_file",
        lambda path: SimpleNamespace(name="ema_cross", default_params={"fast_period": 12}),
    )

    captured: dict[str, Any] = {"list_calls": 0, "batch_sizes": []}

    def _fake_list_entries(*, path=None, status=None, **kwargs):
        captured["list_calls"] += 1
        return []

    def _fake_upsert_entries(entries, *, path=None):
        captured["batch_sizes"].append(len(entries))
        return [dict(entry) for entry in entries]

    monkeypatch.setattr("catalog.graduation.list_entries", _fake_list_entries)
    monkeypatch.setattr("catalog.graduation.upsert_entries", _fake_upsert_entries)

    synced = sync_graduation_to_catalog(candidates, config)

    assert len(synced) == 2
    assert captured["list_calls"] == 1
    assert captured["batch_sizes"] == [2]
    assert [candidate.catalog_entry_id for candidate in candidates] == [entry["id"] for entry in synced]


def test_scan_positive_import_candidates_reads_catalog_entry_and_builder_file(tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandbox"
    session_dir = sandbox_dir / "sess-1"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v4.py").write_text("# strategy\n", encoding="utf-8")

    catalog_path = tmp_path / "strategy_catalog.json"
    upsert_entry(
        {
            "id": "ema_cross|BTCUSDC|1h|hash123",
            "strategy_name": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "params_hash": "hash123",
            "category": "p2_positive_observed",
            "status": "active",
            "source": "saved_run",
            "tags": ["positive_import", "positive_return"],
            "last_metrics_snapshot": {
                "total_return_pct": 12.5,
                "profit_factor": 1.2,
                "sharpe_ratio": 1.1,
                "total_trades": 40,
            },
            "meta": {
                "builder_session_id": "sess-1",
                "builder_iteration": 4,
                "source_run_id": "run-123",
                "source_params": {"fast_period": 12, "slow_period": 26},
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "universe_mode": "exploratory",
                "universe_purpose": "builder_manual",
                "import_source_kind": "metadata_fallback",
            },
        },
        path=catalog_path,
    )

    candidates = scan_positive_import_candidates(
        GraduationConfig(sandbox_dir=sandbox_dir, catalog_path=catalog_path),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.session_id == "sess-1"
    assert candidate.best_iteration == 4
    assert candidate.strategy_name == "ema_cross"
    assert candidate.strategy_params == {"fast_period": 12, "slow_period": 26}
    assert candidate.source_run_id == "run-123"
    assert candidate.source_universe_mode == "exploratory"
    assert candidate.source_universe_purpose == "builder_manual"
    assert candidate.strategy_file.endswith("sess-1\\strategy_v4.py") or candidate.strategy_file.endswith(
        "sess-1/strategy_v4.py",
    )


def test_run_positive_import_graduation_updates_existing_catalog_entries(tmp_path: Path, monkeypatch) -> None:
    catalog_path = tmp_path / "strategy_catalog.json"
    upsert_entry(
        {
            "id": "ema_cross|BTCUSDC|1h|hash123",
            "strategy_name": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "params_hash": "hash123",
            "category": "p2_positive_observed",
            "status": "active",
            "source": "saved_run",
            "tags": ["positive_import", "positive_return"],
            "last_metrics_snapshot": {
                "total_return_pct": 8.0,
                "profit_factor": 1.15,
                "sharpe_ratio": 1.0,
                "total_trades": 35,
            },
            "meta": {
                "source_run_id": "run-123",
                "source_params": {"fast_period": 12},
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "import_source_kind": "metadata_fallback",
            },
        },
        path=catalog_path,
    )

    def _fake_p2(candidates, config=None, progress_callback=None):
        if progress_callback:
            progress_callback(
                phase="P3",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
        candidate = candidates[0]
        candidate.phase = "P3"
        candidate.decision = "WATCHLIST"
        candidate.p3_verdict = "PASSED"
        candidate.benchmark_consensus = {"consensus_passed": True}
        candidate.multi_ctx_results = {"passed_count": 2, "total_contexts": 6, "contexts": {}}
        if progress_callback:
            progress_callback(
                phase="P3",
                event="candidate_start",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P3",
                event="candidate_done",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P3",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [candidate]

    monkeypatch.setattr("catalog.graduation.run_multi_context_validation", _fake_p2)

    def _fake_positive_observed(candidates, source_mode, config=None):
        candidate = candidates[0]
        candidate.phase = "P2"
        candidate.decision = "WATCHLIST"
        candidate.p2_verdict = "PASSED"
        candidate.source_mode = source_mode
        return [candidate]

    monkeypatch.setattr("catalog.graduation.run_positive_observed_filter", _fake_positive_observed)

    def _fake_p3(candidates, config=None, progress_callback=None):
        if progress_callback:
            progress_callback(
                phase="P4",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
        candidate = candidates[0]
        candidate.sweep_robustness_pct = 44.0
        candidate.phase = "P4"
        candidate.decision = "WATCHLIST"
        candidate.p4_verdict = "PASSED"
        if progress_callback:
            progress_callback(
                phase="P4",
                event="candidate_start",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P4",
                event="candidate_done",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P4",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [candidate]

    monkeypatch.setattr("catalog.graduation.run_parameter_sensitivity", _fake_p3)

    def _fake_wfa(candidates, config=None, progress_callback=None):
        if progress_callback:
            progress_callback(
                phase="P5",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
        candidate = candidates[0]
        candidate.wfa_stability = 0.71
        candidate.wfa_avg_test_return_pct = 5.6
        candidate.phase = "P5"
        candidate.decision = "WATCHLIST"
        candidate.p5_verdict = "PASSED"
        if progress_callback:
            progress_callback(
                phase="P5",
                event="candidate_start",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P5",
                event="candidate_done",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P5",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [candidate]

    monkeypatch.setattr("catalog.graduation.run_wfa_validation", _fake_wfa)

    config = GraduationConfig(
        catalog_path=catalog_path,
        output_dir=tmp_path / "reports",
        sandbox_dir=tmp_path / "sandbox",
    )
    result = run_positive_import_graduation(config)
    catalog = read_catalog(catalog_path)

    assert result["stats"]["import_candidates"] == 1
    assert result["stats"]["p2_survivors"] == 1
    assert result["stats"]["p3_survivors"] == 1
    assert result["stats"]["p4_survivors"] == 1
    assert result["stats"]["p5_survivors"] == 1
    assert result["stats"]["catalog_synced"] == 1
    assert (config.output_dir / "positive_imports_graduation.json").exists()
    progress_payload = json.loads((config.output_dir / config.positive_progress_filename).read_text(encoding="utf-8"))
    assert progress_payload["status"] == "completed"
    assert progress_payload["current_phase"] == "P5"
    assert progress_payload["stats"]["p5_survivors"] == 1
    assert catalog["entries"][0]["category"] == "p5_wfa_candidate"
    assert "positive_processed" in catalog["entries"][0]["tags"]
    assert catalog["entries"][0]["meta"]["positive_pipeline_phase"] == "P5"


def test_run_full_graduation_writes_progress_state(tmp_path: Path, monkeypatch) -> None:
    candidate = GraduationCandidate(
        session_id="sandbox-1",
        session_dir=tmp_path / "sandbox" / "sandbox-1",
        strategy_name="ema_cross",
        source_mode="sandbox",
        best_return_pct=12.5,
    )

    def _fake_scan(_config):
        return [candidate]

    monkeypatch.setattr("catalog.graduation.scan_sandbox", _fake_scan)

    def _fake_positive_observed(candidates, source_mode, config=None):
        current = candidates[0]
        current.phase = "P2"
        current.decision = "WATCHLIST"
        current.p2_verdict = "PASSED"
        current.source_mode = source_mode
        return [current]

    monkeypatch.setattr("catalog.graduation.run_positive_observed_filter", _fake_positive_observed)

    def _fake_p3(candidates, config=None, progress_callback=None):
        current = candidates[0]
        current.phase = "P3"
        current.decision = "WATCHLIST"
        current.p3_verdict = "PASSED"
        if progress_callback:
            progress_callback(
                phase="P3",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P3",
                event="candidate_done",
                candidate=current,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P3",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [current]

    monkeypatch.setattr("catalog.graduation.run_multi_context_validation", _fake_p3)

    def _fake_p4(candidates, config=None, progress_callback=None):
        current = candidates[0]
        current.phase = "P4"
        current.decision = "WATCHLIST"
        current.p4_verdict = "PASSED"
        current.sweep_robustness_pct = 66.0
        if progress_callback:
            progress_callback(
                phase="P4",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P4",
                event="candidate_done",
                candidate=current,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P4",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [current]

    monkeypatch.setattr("catalog.graduation.run_parameter_sensitivity", _fake_p4)

    def _fake_p5(candidates, config=None, progress_callback=None):
        current = candidates[0]
        current.phase = "P5"
        current.decision = "WATCHLIST"
        current.p5_verdict = "PASSED"
        current.wfa_stability = 0.74
        if progress_callback:
            progress_callback(
                phase="P5",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P5",
                event="candidate_done",
                candidate=current,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P5",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [current]

    monkeypatch.setattr("catalog.graduation.run_wfa_validation", _fake_p5)

    def _fake_promote(candidates, _output_dir):
        current = candidates[0]
        current.phase = "P6"
        current.decision = "PROMOTED"
        current.p6_verdict = "PROMOTED"
        return [current]

    monkeypatch.setattr("catalog.graduation.promote_to_strategies", _fake_promote)
    monkeypatch.setattr("catalog.graduation.sync_graduation_to_catalog", lambda candidates, config=None: [{"id": "cat-1"}])

    config = GraduationConfig(
        output_dir=tmp_path / "reports",
        sandbox_dir=tmp_path / "sandbox",
        sync_catalog=True,
    )

    result = run_full_graduation(config)

    assert result["stats"]["p1_candidates"] == 1
    assert result["stats"]["p2_survivors"] == 1
    assert result["stats"]["p3_survivors"] == 1
    assert result["stats"]["p4_survivors"] == 1
    assert result["stats"]["p5_survivors"] == 1
    assert result["stats"]["p6_promoted"] == 1
    assert result["stats"]["catalog_synced"] == 1
    assert (config.output_dir / "graduation_full.json").exists()
    progress_payload = json.loads((config.output_dir / config.full_progress_filename).read_text(encoding="utf-8"))
    assert progress_payload["status"] == "completed"
    assert progress_payload["pipeline"] == "full_graduation"
    assert progress_payload["current_phase"] == "P6"
    assert progress_payload["stats"]["p6_promoted"] == 1
    assert progress_payload["stats"]["catalog_synced"] == 1
