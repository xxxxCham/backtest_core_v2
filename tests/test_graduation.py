from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest.walk_forward import FoldResult, WalkForwardSummary
from catalog.graduation import (
    GraduationCandidate,
    GraduationConfig,
    _extract_numeric_params,
    _generate_neighborhood,
    import_positive_artifacts_to_catalog,
    run_positive_import_graduation,
    run_wfa_validation,
    save_graduation_report,
    scan_sandbox,
    scan_positive_import_candidates,
    sync_graduation_to_catalog,
)
from catalog.strategy_catalog import upsert_entry
from catalog.strategy_catalog import read_catalog
from utils.parameters import ParameterSpec


def _write_session(
    root: Path,
    session_id: str,
    *,
    status: str,
    iterations: list[dict],
    objective: str = "",
) -> None:
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("# stub\n", encoding="utf-8")
    payload = {
        "session_id": session_id,
        "status": status,
        "objective": objective,
        "iterations": iterations,
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


def test_scan_sandbox_uses_or_based_repechage(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"

    _write_session(
        sandbox,
        "success_candidate",
        status="success",
        objective='{"objective": "trend alpha"}',
        iterations=[
            {
                "iteration": 1,
                "continuous_score": 10.0,
                "return_pct": -5.0,
                "profit_factor": 0.8,
                "sharpe": 0.1,
                "trades": 10,
            }
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
            }
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
            }
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
            }
        ],
    )

    candidates = scan_sandbox(GraduationConfig(sandbox_dir=sandbox))

    assert [candidate.session_id for candidate in candidates] == [
        "score_candidate",
        "success_candidate",
        "pf_candidate",
    ]
    assert candidates[1].objective == "trend alpha"
    assert "status=success" in candidates[1].inclusion_reasons
    assert any(reason.startswith("score=") for reason in candidates[0].inclusion_reasons)
    assert any(reason.startswith("PF=") for reason in candidates[2].inclusion_reasons)


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
    assert "avg_test_return" in candidates[1].rejection_reason


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
                }
            }
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
            multi_ctx_results={"passed_count": 1, "total_contexts": 6},
        ),
        GraduationCandidate(
            session_id="cand_p3",
            session_dir=p3_dir,
            best_iteration=1,
            strategy_file="p3/strategy_v1.py",
            decision="REJECTED",
            phase="P4",
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
            phase="P5",
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
        "p3_watchlist",
        "p4_paper_candidate",
    ]
    assert all(candidate.catalog_entry_id for candidate in candidates)


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
            ]
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
    assert entry["category"] == "p1_builder_inbox"
    assert "positive_import" in entry["tags"]
    assert "positive_return" in entry["tags"]
    assert entry["meta"]["builder_session_id"] == "sess-positive"
    assert entry["meta"]["import_source_kind"] == "unified_overview"
    assert entry["meta"]["positive_return_pct"] == 12.5


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
            ]
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
            }
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
            }
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
            "category": "p1_builder_inbox",
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
    assert candidate.strategy_file.endswith("sess-1\\strategy_v4.py") or candidate.strategy_file.endswith("sess-1/strategy_v4.py")


def test_run_positive_import_graduation_updates_existing_catalog_entries(tmp_path: Path, monkeypatch) -> None:
    catalog_path = tmp_path / "strategy_catalog.json"
    upsert_entry(
        {
            "id": "ema_cross|BTCUSDC|1h|hash123",
            "strategy_name": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "params_hash": "hash123",
            "category": "p1_builder_inbox",
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
                phase="P2",
                event="phase_start",
                candidate=None,
                index=0,
                total=len(candidates),
                survivors=0,
                extra={},
            )
        candidate = candidates[0]
        candidate.phase = "P2"
        candidate.decision = "WATCHLIST"
        candidate.multi_ctx_results = {"passed_count": 2, "total_contexts": 6, "contexts": {}}
        if progress_callback:
            progress_callback(
                phase="P2",
                event="candidate_start",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=0,
                extra={},
            )
            progress_callback(
                phase="P2",
                event="candidate_done",
                candidate=candidate,
                index=1,
                total=len(candidates),
                survivors=1,
                extra={},
            )
            progress_callback(
                phase="P2",
                event="phase_end",
                candidate=None,
                index=len(candidates),
                total=len(candidates),
                survivors=1,
                extra={},
            )
        return [candidate]

    monkeypatch.setattr("catalog.graduation.run_multi_context_validation", _fake_p2)

    def _fake_p3(candidates, config=None, progress_callback=None):
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
        candidate.sweep_robustness_pct = 44.0
        candidate.phase = "P3"
        candidate.decision = "WATCHLIST"
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

    monkeypatch.setattr("catalog.graduation.run_parameter_sensitivity", _fake_p3)

    def _fake_wfa(candidates, config=None, progress_callback=None):
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
        candidate.wfa_stability = 0.71
        candidate.wfa_avg_test_return_pct = 5.6
        candidate.phase = "P4"
        candidate.decision = "WATCHLIST"
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
    assert result["stats"]["catalog_synced"] == 1
    assert (config.output_dir / "positive_imports_graduation.json").exists()
    progress_payload = json.loads((config.output_dir / config.positive_progress_filename).read_text(encoding="utf-8"))
    assert progress_payload["status"] == "completed"
    assert progress_payload["current_phase"] == "P4"
    assert progress_payload["stats"]["p4_survivors"] == 1
    assert catalog["entries"][0]["category"] == "p4_paper_candidate"
    assert "positive_processed" in catalog["entries"][0]["tags"]
    assert catalog["entries"][0]["meta"]["positive_pipeline_phase"] == "P4"
