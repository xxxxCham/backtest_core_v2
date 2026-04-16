# ruff: noqa
# mypy: ignore-errors
# pyright: reportPrivateUsage=false, reportGeneralTypeIssues=false, reportArgumentType=false, reportAssignmentType=false, reportRedeclaration=false, reportUnusedVariable=false, reportUnusedImport=false, reportUnusedParameter=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportUndefinedVariable=false, reportIncompatibleVariableOverride=false

"""
Tests pour le Strategy Builder (agents/strategy_builder.py).

Couvre :
- Validation du code généré (syntaxe, sécurité, structure)
- Création de session (ID, dossier)
- Extraction JSON/Python depuis réponses LLM
- Chargement dynamique de stratégie
"""

import concurrent.futures
import json
import shutil
import textwrap
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

import agents.builder_candidate_executor as builder_candidate_executor_module
import agents.strategy_builder as strategy_builder_module
from agents.builder_feedback import (
    CodeFeedbackSection,
    IterationPhaseFeedback,
    ProposalFeedbackSection,
)
from agents.indicator_context import (
    INDICATOR_SELECTION_REFERENCE,
    build_indicator_selection_guide,
    get_indicator_builder_access_example,
    get_indicator_builder_stable_alias_map,
    rank_indicator_selection,
)
from agents.llm_client import LLMConfig, LLMMessage, LLMProvider
from agents.strategy_builder import (
    GENERATED_CLASS_NAME,
    SANDBOX_ROOT,
    BuilderIteration,
    BuilderSession,
    StrategyBuilder,
    _apply_signal_direction_constraint,
    _build_deterministic_fallback_code,
    _build_deterministic_strategy_code,
    _extract_default_params_signature,
    _extract_generate_signals_logic_block,
    _extract_json_from_response,
    _extract_python_from_response,
    _infer_direction_constraint_from_objective,
    _is_accept_candidate,
    _is_interpreter_shutdown_runtime_error,
    _policy_change_type_override,
    _postprocess_llm_logic_block,
    _proposal_changes_indicator_set_in_params_mode,
    _proposal_has_meaningful_param_delta,
    _ranking_sharpe,
    _sanitize_proposal_payload,
    _select_best_branch_candidate,
    _select_session_recovery_anchor,
    _should_enable_stagnation_branching,
    _should_trip_logic_stagnation_circuit,
    _validate_llm_logic_block,
    compute_continuous_builder_score,
    generate_llm_objective,
    generate_llm_objective_from_seed,
    recommend_market_context,
    sanitize_objective_text,
)
from agents.builder_code_repair import _repair_code
from agents.builder_code_validation import validate_generated_code
from agents.thought_stream import ThoughtStream
from config.market_selection import evaluate_market_dataset, filter_market_universe
from strategies.base import StrategyBase

# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def valid_strategy_code():
    """Code Python valide d'une stratégie générée."""
    return textwrap.dedent(f"""\
        from typing import Any, Dict, List
        import numpy as np
        import pandas as pd
        from strategies.base import StrategyBase
        from utils.parameters import ParameterSpec

        class {GENERATED_CLASS_NAME}(StrategyBase):
            \"\"\"Stratégie générée par le builder.\"\"\"

            def __init__(self):
                super().__init__(name="TestBuilder")

            @property
            def required_indicators(self) -> List[str]:
                return ["rsi", "atr"]

            @property
            def default_params(self) -> Dict[str, Any]:
                return {{"rsi_period": 14, "atr_period": 14}}

            @property
            def parameter_specs(self) -> Dict[str, ParameterSpec]:
                return {{
                    "rsi_period": ParameterSpec(
                        name="rsi_period", min_val=5, max_val=30,
                        default=14, param_type="int",
                    ),
                }}

            def generate_signals(
                self, df: pd.DataFrame,
                indicators: Dict[str, Any],
                params: Dict[str, Any],
            ) -> pd.Series:
                n = len(df)
                signals = pd.Series(0.0, index=df.index, dtype=np.float64)
                rsi = indicators.get("rsi")
                if rsi is not None:
                    signals[rsi < 30] = 1.0
                    signals[rsi > 70] = -1.0
                return signals
    """)


@pytest.fixture
def sample_ohlcv():
    """DataFrame OHLCV minimal pour tests."""
    n = 200
    np.random.seed(42)
    close = np.cumsum(np.random.randn(n)) + 100
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.5,
        "high": close + abs(np.random.randn(n)),
        "low": close - abs(np.random.randn(n)),
        "close": close,
        "volume": np.random.randint(100, 10000, n).astype(float),
    })


def _make_market_df(
    *,
    n_bars: int = 1600,
    start: str = "2025-01-01",
    freq: str = "1h",
    price_scale: float = 100.0,
    volatility_sigma: float = 0.01,
    volume: float = 5000.0,
    tradable_ratio: float = 1.0,
) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    index = pd.date_range(start, periods=n_bars, freq=freq, tz="UTC")
    returns = rng.normal(0.0, volatility_sigma, n_bars)
    close = price_scale * np.exp(np.cumsum(returns))
    open_ = close * (1.0 + rng.normal(0.0, max(volatility_sigma / 2.0, 0.001), n_bars))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n_bars, volume, dtype=float),
        },
        index=index,
    )
    tradable = np.ones(n_bars, dtype=bool)
    inactive = int(round(n_bars * max(0.0, min(1.0, 1.0 - tradable_ratio))))
    if inactive > 0:
        tradable[:inactive] = False
    df["_tradable"] = tradable
    return df


def test_emit_completed_backtest_forwards_raw_result_to_callback():
    saved = []
    builder = StrategyBuilder(
        llm_client=SimpleNamespace(),
        backtest_completed_callback=lambda raw_result: saved.append(raw_result),
    )
    raw_result = SimpleNamespace(meta={})
    wrapped_result = SimpleNamespace(run_result=raw_result)
    session = SimpleNamespace(session_id="sess-1", objective="test objective")

    builder._emit_completed_backtest(
        wrapped_result,
        session=session,
        iteration_num=3,
    )

    assert saved == [raw_result]
    assert raw_result.meta["builder_session_id"] == "sess-1"
    assert raw_result.meta["builder_iteration"] == 3
    assert raw_result.meta["builder_objective"] == "test objective"


def _valid_builder_proposal_payload() -> str:
    return json.dumps(
        {
            "strategy_name": "runtime_ablation_probe",
            "hypothesis": "Probe payload for ablation tests",
            "change_type": "logic",
            "used_indicators": ["rsi", "atr"],
            "entry_long_logic": "rsi < 30",
            "entry_short_logic": "rsi > 70",
            "exit_logic": "rsi crosses 50",
            "risk_management": "ATR stop and ATR take-profit",
            "default_params": {"rsi_period": 14, "atr_period": 14},
            "parameter_specs": {
                "rsi_period": {"min": 5, "max": 30, "default": 14, "type": "int"}
            },
        }
    )


def test_precheck_signal_counts_handles_nameerror(sample_ohlcv):
    class _BrokenStrategy(StrategyBase):
        def __init__(self):
            super().__init__(name="broken_precheck")

        @property
        def required_indicators(self):
            return ["rsi"]

        @property
        def default_params(self):
            return {}

        @property
        def parameter_specs(self):
            return {}

        def generate_signals(self, df, indicators, params):
            signals = pd.Series(0.0, index=df.index, dtype=np.float64)
            signals[missing_filter] = 1.0  # noqa: F821 - intentional NameError path under test
            return signals

    builder = StrategyBuilder(llm_client=SimpleNamespace())

    probe = builder._precheck_signal_counts(
        _BrokenStrategy,
        sample_ohlcv,
        params={},
    )

    assert probe["ok"] is False
    assert "NameError" in probe["error"]
    assert "missing_filter" in probe["error"]


def test_ask_proposal_skips_runtime_context_blocks_when_ablated(monkeypatch, tmp_path):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr", "ema"]
    builder.ablation.disable("indicator_ranking")
    builder.ablation.disable("iteration_history")
    builder.ablation.disable("diagnostic_context")

    session = BuilderSession(
        session_id="proposal_ablation_test",
        objective="Tester l'ablation proposal",
        session_dir=tmp_path / "proposal_ablation_test",
        available_indicators=list(builder.available_indicators),
        max_iterations=3,
        symbol="BTCUSDC",
        timeframe="1h",
        n_bars=500,
    )
    session.direction_constraint = "long_short"
    last_iteration = BuilderIteration(
        iteration=1,
        hypothesis="Ancienne hypothèse",
        used_indicators=["rsi", "ema"],
        analysis="Ancienne analyse",
        diagnostic_detail={"actions": ["tighten risk"], "donts": ["repeat same logic"]},
        phase_feedback={"backtest": {"mode": "single"}},
        backtest_result=SimpleNamespace(
            metrics={
                "sharpe_ratio": 0.4,
                "sortino_ratio": 0.6,
                "calmar_ratio": 0.2,
                "total_return_pct": 5.0,
                "max_drawdown_pct": -12.0,
                "volatility_annual": 0.2,
                "win_rate_pct": 42.0,
                "total_trades": 18,
                "profit_factor": 1.1,
                "expectancy": 0.05,
                "avg_win": 2.0,
                "avg_loss": -1.2,
                "risk_reward_ratio": 1.6,
            }
        ),
    )
    session.iterations = [last_iteration]

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        strategy_builder_module,
        "rank_indicator_selection",
        lambda *args, **kwargs: pytest.fail("indicator_ranking should be skipped when ablated"),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "render_prompt",
        lambda template, context: captured.setdefault("context", dict(context)) or "prompt",
    )
    builder._chat_llm = lambda **kwargs: SimpleNamespace(content=_valid_builder_proposal_payload())

    proposal, feedback = builder._ask_proposal(session, last_iteration)

    assert proposal["strategy_name"] == "runtime_ablation_probe"
    assert feedback["final_valid"] is True
    context = captured["context"]
    assert isinstance(context, dict)
    assert context["available_indicators"] == ["rsi", "atr", "ema"]
    assert "diagnostic" not in context
    assert "iteration_history" not in context


def test_ask_code_skips_runtime_context_blocks_when_ablated(monkeypatch, tmp_path):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr", "ema"]
    builder.ablation.disable("indicator_ranking")
    builder.ablation.disable("diagnostic_context")

    session = BuilderSession(
        session_id="code_ablation_test",
        objective="Tester l'ablation code",
        session_dir=tmp_path / "code_ablation_test",
        available_indicators=list(builder.available_indicators),
        max_iterations=3,
        symbol="BTCUSDC",
        timeframe="1h",
        n_bars=500,
    )
    session.direction_constraint = "long_short"
    proposal = json.loads(_valid_builder_proposal_payload())
    last_iteration = BuilderIteration(
        iteration=1,
        diagnostic_detail={"actions": ["tighten risk"], "donts": ["repeat same logic"]},
        code="# previous code",
        backtest_result=SimpleNamespace(metrics={"sharpe_ratio": 0.5}),
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        strategy_builder_module,
        "rank_indicator_selection",
        lambda *args, **kwargs: pytest.fail("indicator_ranking should be skipped when ablated"),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "render_prompt",
        lambda template, context: captured.setdefault("context", dict(context)) or "prompt",
    )
    builder._chat_llm = lambda **kwargs: SimpleNamespace(
        content="```python\nsignals[:] = 0.0\n```"
    )

    code, feedback = builder._ask_code(session, proposal, last_iteration)

    assert "signals[:] = 0.0" in code
    assert feedback["final_valid"] is True
    context = captured["context"]
    assert isinstance(context, dict)
    assert context["available_indicators"] == ["rsi", "atr", "ema"]
    assert context["diagnostic_actions"] == []
    assert context["diagnostic_donts"] == []


def test_builder_run_uses_rule_based_analysis_when_llm_analysis_ablated(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]
    builder.ablation.disable("llm_analysis")

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_llm_analysis_ablated_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        json.loads(_valid_builder_proposal_payload()),
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._ask_pre_reflection = lambda *args, **kwargs: ""
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics={
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.1,
            "max_drawdown_pct": -8.0,
            "total_trades": 28,
            "win_rate_pct": 0.41,
            "profit_factor": 1.35,
            "expectancy": 0.12,
        },
        meta={},
    )
    builder._ask_analysis = lambda *args, **kwargs: pytest.fail(
        "llm_analysis should not be called when ablated"
    )

    session = builder.run(
        objective="Tester l'analyse rule-based",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert session.iterations[0].analysis.startswith("[rule-based]")


def test_chat_llm_uses_phase_specific_client_for_analysis():
    class _FakeClient:
        def __init__(self, name: str):
            self.name = name
            self.calls: list[dict[str, object]] = []
            self.config = LLMConfig(
                provider=LLMProvider.OLLAMA,
                model=name,
                ollama_host=f"http://{name}.local:11434",
            )

        def chat(
            self,
            messages,
            json_mode=False,
            temperature=None,
            max_tokens=None,
        ):
            self.calls.append(
                {
                    "messages": messages,
                    "json_mode": json_mode,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
            return SimpleNamespace(content=f"{self.name}-response")

    default_client = _FakeClient("builder")
    critic_client = _FakeClient("critic")
    builder = StrategyBuilder(
        llm_client=default_client,
        phase_llm_clients={"analysis": critic_client},
    )

    response = builder._chat_llm(
        [LLMMessage(role="user", content="analyse cette iteration")],
        phase="analysis",
    )

    assert response.content == "critic-response"
    assert len(critic_client.calls) == 1
    assert len(default_client.calls) == 0


def test_chat_llm_extends_timeout_for_vision_models(monkeypatch):
    captured: dict[str, int] = {}

    class _FakeClient:
        def __init__(self):
            self.config = LLMConfig(
                provider=LLMProvider.OLLAMA,
                model="qwen3-vl:32b",
                ollama_host="http://127.0.0.1:11434",
            )

        def chat(self, messages, json_mode=False, temperature=None, max_tokens=None):
            return SimpleNamespace(content="ok")

    class _Future:
        def result(self, timeout=None):
            captured["timeout"] = int(timeout or 0)
            return SimpleNamespace(content="ok")

    class _Pool:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn):
            return _Future()

        def shutdown(self, wait=True):  # noqa: ARG002
            pass

    monkeypatch.setattr(
        strategy_builder_module,
        "_new_streamlit_aware_thread_pool",
        lambda max_workers=1: _Pool(),
    )

    builder = StrategyBuilder(llm_client=_FakeClient())
    response = builder._chat_llm(
        [LLMMessage(role="user", content="propose une stratégie")],
        phase="proposal",
    )

    assert response.content == "ok"
    assert captured["timeout"] >= 300


def test_validate_builder_dataset_exploitability_rejects_high_untradable_ratio(sample_ohlcv):
    df = pd.concat([sample_ohlcv.copy(), sample_ohlcv.copy()])
    df["_tradable"] = True
    df.loc[df.index[:320], "_tradable"] = False

    ok, reason = strategy_builder_module.validate_builder_dataset_exploitability(
        df,
        symbol="UNKNOWN",
        timeframe="1h",
    )

    assert ok is False
    assert "tradable ratio" in reason.lower()


def test_filter_market_universe_differs_between_canonical_and_exploratory():
    good_df = _make_market_df()

    def loader(symbol, timeframe):
        del symbol, timeframe
        return good_df.copy()

    canonical = filter_market_universe(
        symbols=["DOGEUSDC", "BTCUSDC"],
        timeframes=["1h"],
        universe_mode="canonical",
        purpose="builder",
        strategy_type="trend",
        data_loader=loader,
    )
    exploratory = filter_market_universe(
        symbols=["DOGEUSDC", "BTCUSDC"],
        timeframes=["1h"],
        universe_mode="exploratory",
        purpose="builder",
        strategy_type="trend",
        data_loader=loader,
    )

    assert canonical["symbols"] == ["BTCUSDC"]
    assert any(
        item["symbol"] == "DOGEUSDC"
        and "outside canonical universe" in " | ".join(item.get("exclusion_reasons", []))
        for item in canonical["excluded_pairs"]
    )
    assert set(exploratory["symbols"]) == {"DOGEUSDC", "BTCUSDC"}


def test_evaluate_market_dataset_accepts_missing_market_cap_with_good_local_metrics():
    result = evaluate_market_dataset(
        _make_market_df(),
        symbol="BTCUSDC",
        timeframe="1h",
        universe_mode="canonical",
        purpose="builder",
        strategy_type="trend",
        token_profile={
            "volatility": "medium",
            "liquidity": "high",
            "strategies": ["trend"],
            "market_cap": None,
        },
    )

    assert result["accepted"] is True
    assert result["local_metrics"]["market_cap"] == 0.0
    assert result["local_metrics"]["market_cap_used"] is False


def test_evaluate_market_dataset_prioritizes_dollar_volume_over_raw_volume():
    low_price_high_volume_df = _make_market_df(price_scale=0.01, volume=50_000.0)

    result = evaluate_market_dataset(
        low_price_high_volume_df,
        symbol="BTCUSDC",
        timeframe="1h",
        universe_mode="canonical",
        purpose="builder",
        strategy_type="trend",
        token_profile={
            "volatility": "medium",
            "liquidity": "high",
            "strategies": ["trend"],
        },
    )

    assert result["accepted"] is False
    assert result["local_metrics"]["median_volume"] > 1000.0
    assert result["local_metrics"]["median_dollar_volume"] < 250000.0
    assert any(
        "median dollar volume insufficient" in reason
        for reason in result["exclusion_reasons"]
    )


def test_evaluate_market_dataset_volatility_depends_on_strategy_type():
    volatile_df = _make_market_df(volatility_sigma=0.08, volume=20_000.0)

    trend_result = evaluate_market_dataset(
        volatile_df,
        symbol="BTCUSDC",
        timeframe="1h",
        universe_mode="canonical",
        purpose="builder",
        strategy_type="trend",
        token_profile={
            "volatility": "high",
            "liquidity": "high",
            "strategies": ["trend", "breakout"],
        },
    )
    breakout_result = evaluate_market_dataset(
        volatile_df,
        symbol="BTCUSDC",
        timeframe="1h",
        universe_mode="canonical",
        purpose="builder",
        strategy_type="breakout",
        token_profile={
            "volatility": "high",
            "liquidity": "high",
            "strategies": ["trend", "breakout"],
        },
    )

    assert trend_result["accepted"] is False
    assert breakout_result["accepted"] is True
    assert trend_result["local_metrics"]["volatility_bucket"] == "high"
    assert breakout_result["local_metrics"]["volatility_bucket"] == "high"


def test_evaluate_market_dataset_rejects_sparse_weekly_in_canonical_mode():
    weekly_df = _make_market_df(
        n_bars=350,
        freq="1W",
        volume=25_000.0,
    )

    result = evaluate_market_dataset(
        weekly_df,
        symbol="BTCUSDC",
        timeframe="1w",
        universe_mode="canonical",
        purpose="builder",
        strategy_type="breakout",
        token_profile={
            "volatility": "high",
            "liquidity": "high",
            "strategies": ["breakout", "trend"],
        },
    )

    assert result["accepted"] is False
    assert result["applied_criteria"]["timeframe_specific_min_segment_bars"] == 400
    assert any(
        "continuous segment insufficient" in reason
        for reason in result["exclusion_reasons"]
    )


def test_extract_default_params_signature_reads_generated_literal(valid_strategy_code):
    defaults = _extract_default_params_signature(valid_strategy_code)

    assert defaults["rsi_period"] == 14
    assert defaults["atr_period"] == 14


def test_proposal_has_no_meaningful_param_delta_when_defaults_are_identical(valid_strategy_code):
    proposal = {
        "default_params": {"rsi_period": 14, "atr_period": 14},
    }

    assert _proposal_has_meaningful_param_delta(valid_strategy_code, proposal) is False


def test_proposal_detects_indicator_shift_in_params_mode(valid_strategy_code):
    proposal = {
        "used_indicators": ["bollinger", "adx"],
    }

    assert _proposal_changes_indicator_set_in_params_mode(valid_strategy_code, proposal) is True


def test_build_builder_sweep_plan_uses_parameter_specs_ranges():
    proposal = {
        "change_type": "logic",
        "default_params": {
            "rsi_period": 14,
            "stop_atr_mult": 1.5,
            "leverage": 1,
        },
        "parameter_specs": {
            "rsi_period": {
                "min": 5,
                "max": 30,
                "default": 14,
                "type": "int",
                "step": 1,
            },
            "stop_atr_mult": {
                "min": 1.0,
                "max": 2.0,
                "default": 1.5,
                "type": "float",
                "step": 0.2,
            },
            "leverage": {
                "min": 1,
                "max": 2,
                "default": 1,
                "type": "int",
                "step": 1,
            },
        },
    }

    plan = strategy_builder_module._build_builder_sweep_plan(proposal)

    assert plan["enabled"] is True
    assert plan["param_names"] == ["rsi_period", "stop_atr_mult"]
    assert plan["parameter_values"]["rsi_period"] == [14, 13, 15]
    assert plan["parameter_values"]["stop_atr_mult"] == [1.5, 1.3, 1.7]
    assert len(plan["param_grid"]) == 9
    assert all(item["leverage"] == 1 for item in plan["param_grid"])


def test_builder_run_emits_progress_events(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    progress_events = []
    builder = StrategyBuilder(
        llm_client=SimpleNamespace(),
        progress_callback=lambda payload: progress_events.append(payload),
    )
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_progress_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "strategy_name": "builder_progress_test_strategy",
            "hypothesis": "RSI reversal simple",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "entry_long_logic": "rsi < 30",
            "entry_short_logic": "rsi > 70",
            "exit_logic": "rsi crosses 50",
            "risk_management": "atr stop",
            "default_params": {"rsi_period": 14, "atr_period": 14},
            "parameter_specs": {},
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._ask_pre_reflection = lambda *args, **kwargs: ""
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics={
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.1,
            "max_drawdown_pct": -8.0,
            "total_trades": 28,
            "win_rate_pct": 41.0,
            "profit_factor": 1.35,
            "expectancy": 0.12,
        },
        meta={},
    )
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "accept")

    session = builder.run(
        objective="Tester la progression Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert [event["event"] for event in progress_events] == [
        "session_start",
        "iteration_start",
        "phase_start",
        "proposal_candidate",
        "proposal_selected",
        "phase_done",
        "phase_start",
        "phase_start",
        "phase_done",
        "phase_start",
        "phase_done",
        "phase_start",
        "phase_done",
        "phase_done",
        "diagnostic",
        "phase_start",
        "analysis",
        "iteration_done",
        "session_done",
    ]
    assert [event.get("phase") for event in progress_events if event["event"] == "phase_start"] == [
        "proposal",
        "code",
        "save_and_load",
        "precheck",
        "backtest",
        "analysis",
    ]
    assert any(
        event["event"] == "phase_done"
        and event.get("phase") == "backtest"
        and event.get("payload", {}).get("sharpe") == 1.42
        for event in progress_events
    )
    proposal_selected = next(
        event for event in progress_events if event["event"] == "proposal_selected"
    )
    assert proposal_selected["selected_branch_label"] == "main"
    assert proposal_selected["payload"]["proposal"]["hypothesis"] == "RSI reversal simple"
    assert all("timestamp" in event and "payload" in event for event in progress_events)
    assert {
        event["branch_label"]
        for event in progress_events
        if event["event"] in {"phase_start", "phase_done"}
        and event.get("phase") in {"save_and_load", "precheck", "backtest"}
    } == {"main"}
    assert session.best_sharpe == pytest.approx(1.42)
    assert not any(event["event"] == "iteration_error" for event in progress_events)


def test_builder_run_emits_branch_candidates_and_selected_branch(monkeypatch, tmp_path, sample_ohlcv):
    import agents.builder_loop as builder_loop_module

    progress_events = []
    builder = StrategyBuilder(
        llm_client=SimpleNamespace(),
        progress_callback=lambda payload: progress_events.append(payload),
    )
    builder.available_indicators = ["rsi", "atr", "ema"]
    builder.ablation.is_enabled = lambda key: key in {"stagnation_branching", "llm_analysis"}

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_branch_progress_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        builder_loop_module,
        "_should_enable_stagnation_branching",
        lambda last_iteration: True,
    )
    monkeypatch.setattr(
        builder_loop_module,
        "_build_stagnation_branch_specs",
        lambda previous_indicators: [
            {"label": "keep", "directive": "keep"},
            {"label": "add_one", "directive": "add_one"},
        ],
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._persist_session_strategy_code = lambda *args, **kwargs: None

    def _ask_proposal(session, last_iteration, branch_directive=None):
        label = str(branch_directive or "main")
        suffix = "base" if label == "main" else label
        indicators = ["rsi", "atr"] if label != "add_one" else ["rsi", "atr", "ema"]
        return (
            {
                "strategy_name": f"branch_{suffix}",
                "hypothesis": f"Hypothese {suffix}",
                "used_indicators": indicators,
                "change_type": "logic",
                "entry_long_logic": "rsi < 30",
                "entry_short_logic": "rsi > 70",
                "exit_logic": "rsi crosses 50",
                "risk_management": "atr stop",
                "default_params": {"rsi_period": 14, "atr_period": 14},
                "parameter_specs": {},
            },
            {"phase": "proposal", "branch": suffix, "final_valid": True},
        )

    def _execute_candidate(
        *,
        session,
        proposal,
        proposal_feedback,
        last_iteration,
        iteration_num,
        data,
        initial_capital,
        fallback_count,
        branch_label,
    ):
        del session, last_iteration, data, initial_capital
        builder._emit_progress(
            "phase_start",
            iteration=iteration_num,
            phase="save_and_load",
            branch_label=branch_label,
            detail="chargement branche",
        )
        builder._emit_progress(
            "phase_done",
            iteration=iteration_num,
            phase="save_and_load",
            branch_label=branch_label,
            detail="strategie chargee",
        )
        builder._emit_progress(
            "phase_start",
            iteration=iteration_num,
            phase="backtest",
            branch_label=branch_label,
            detail="simulation branche",
        )
        metrics = {
            "total_return_pct": 7.5 if branch_label == "keep" else 14.0,
            "sharpe_ratio": 0.85 if branch_label == "keep" else 1.33,
            "sortino_ratio": 1.2 if branch_label == "keep" else 1.8,
            "calmar_ratio": 0.7 if branch_label == "keep" else 1.1,
            "max_drawdown_pct": -9.0 if branch_label == "keep" else -5.0,
            "total_trades": 22 if branch_label == "keep" else 31,
            "win_rate_pct": 39.0 if branch_label == "keep" else 46.0,
            "profit_factor": 1.12 if branch_label == "keep" else 1.38,
            "expectancy": 0.08 if branch_label == "keep" else 0.14,
        }
        builder._emit_progress(
            "phase_done",
            iteration=iteration_num,
            phase="backtest",
            branch_label=branch_label,
            sharpe=metrics["sharpe_ratio"],
            total_return_pct=metrics["total_return_pct"],
        )
        outcome = {
            "branch_label": branch_label,
            "proposal": proposal,
            "proposal_feedback": proposal_feedback,
            "code_feedback": {"phase": "code", "source": "llm"},
            "precheck_feedback": {},
            "pre_reflection_feedback": {},
            "backtest_feedback": {"mode": "single"},
            "code": f"# {branch_label}\nsignals[:] = 0.0",
            "bt_result": SimpleNamespace(metrics=metrics, meta={}),
            "metrics": metrics,
            "sharpe": metrics["sharpe_ratio"],
            "rank_score": metrics["sharpe_ratio"],
            "is_fallback": False,
            "target_sharpe": 1.0,
        }
        return outcome, fallback_count

    builder._ask_proposal = _ask_proposal
    builder._execute_proposal_candidate = _execute_candidate
    builder._ask_analysis = lambda *args, **kwargs: ("Branche add_one retenue", "accept")

    session = builder.run(
        objective="Tester le branching Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    candidate_events = [
        event for event in progress_events if event["event"] == "proposal_candidate"
    ]
    assert [event["branch_label"] for event in candidate_events] == ["keep", "add_one"]
    selected_event = next(
        event for event in progress_events if event["event"] == "proposal_selected"
    )
    assert selected_event["selected_branch_label"] == "add_one"
    assert selected_event["payload"]["proposal"]["hypothesis"] == "Hypothese add_one"
    phase_branch_events = [
        event
        for event in progress_events
        if event["event"] in {"phase_start", "phase_done"}
        and event.get("phase") in {"save_and_load", "backtest"}
    ]
    assert {event["branch_label"] for event in phase_branch_events} == {"keep", "add_one"}
    assert all(event["branch_label"] for event in phase_branch_events)


def test_thought_stream_keeps_current_session_and_archives_previous(tmp_path):
    stream_path = tmp_path / "_live_thoughts.md"
    archive_dir = tmp_path / "_live_thoughts_archives"

    first_stream = ThoughtStream(
        "session_one",
        "Objectif terminal 1",
        "mock-model",
        path=stream_path,
        archive_dir=archive_dir,
    )
    first_stream.consume(
        {
            "event": "session_start",
            "timestamp": "2026-04-10T10:00:00Z",
            "session_id": "session_one",
            "payload": {"symbol": "BTCUSDC", "timeframe": "1h"},
        }
    )
    first_stream.consume(
        {
            "event": "proposal_selected",
            "timestamp": "2026-04-10T10:00:10Z",
            "session_id": "session_one",
            "selected_branch_label": "add_one",
            "message": "Branche retenue | branche `add_one` - Hypothese session one",
            "payload": {
                "proposal": {
                    "hypothesis": "Hypothese session one",
                    "used_indicators": ["rsi", "ema"],
                }
            },
        }
    )
    first_stream.consume(
        {
            "event": "session_done",
            "timestamp": "2026-04-10T10:01:00Z",
            "session_id": "session_one",
            "status": "success",
            "payload": {"total_iterations": 1, "best_sharpe": 1.11},
        }
    )

    first_archive = archive_dir / "session_one.md"
    assert first_archive.exists()
    assert "session_one" in first_archive.read_text(encoding="utf-8")

    second_stream = ThoughtStream(
        "session_two",
        "Objectif terminal 2",
        "mock-model",
        path=stream_path,
        archive_dir=archive_dir,
    )
    second_stream.consume(
        {
            "event": "session_start",
            "timestamp": "2026-04-10T11:00:00Z",
            "session_id": "session_two",
            "payload": {"symbol": "ETHUSDC", "timeframe": "30m"},
        }
    )
    second_stream.consume(
        {
            "event": "session_done",
            "timestamp": "2026-04-10T11:01:00Z",
            "session_id": "session_two",
            "status": "failed",
            "payload": {"total_iterations": 2, "best_sharpe": 0.0},
        }
    )

    rendered = stream_path.read_text(encoding="utf-8")
    assert "session_two" in rendered
    assert "session_one" not in rendered
    assert (archive_dir / "session_two.md").exists()
    assert "Hypothese session one" in first_archive.read_text(encoding="utf-8")


def test_builder_relays_llm_stream_chunks_to_thought_stream(tmp_path):
    stream_path = tmp_path / "_live_thoughts.md"
    archive_dir = tmp_path / "_live_thoughts_archives"
    thought_stream = ThoughtStream(
        "session_stream",
        "Objectif stream",
        "mock-model",
        path=stream_path,
        archive_dir=archive_dir,
    )
    thought_stream.consume(
        {
            "event": "session_start",
            "timestamp": "2026-04-10T12:00:00Z",
            "session_id": "session_stream",
            "payload": {"symbol": "BTCUSDC", "timeframe": "1h"},
        }
    )

    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder._active_thought_stream = thought_stream

    # Envoyer assez de chars pour d\u00e9passer le seuil de batch (80 chars)
    chunk_a = '"strategy_name": "RSI mean-reversion avec confirmation Bollinger", '
    chunk_b = '"used_indicators": ["rsi", "bollinger"], "hypothesis": "test"'
    builder._emit_stream_chunk("proposal", chunk_a)
    builder._emit_stream_chunk("proposal", chunk_b)
    # Flush explicite du buffer r\u00e9siduel
    thought_stream.flush_stream()

    rendered = stream_path.read_text(encoding="utf-8")
    assert "[STREAM]" in rendered
    assert "Proposition" in rendered
    assert "verbatim masque dans le flux canonique" in rendered
    assert "strategy_name" not in rendered


def test_thought_stream_backtest_phase_done_renders_trade_metrics(tmp_path):
    stream_path = tmp_path / "_live_thoughts.md"
    archive_dir = tmp_path / "_live_thoughts_archives"
    thought_stream = ThoughtStream(
        "session_metrics",
        "Objectif metrics",
        "mock-model",
        path=stream_path,
        archive_dir=archive_dir,
    )
    thought_stream.consume(
        {
            "event": "session_start",
            "timestamp": "2026-04-15T12:00:00Z",
            "session_id": "session_metrics",
            "payload": {"symbol": "BTCUSDC", "timeframe": "1h"},
        }
    )
    thought_stream.consume(
        {
            "event": "phase_done",
            "timestamp": "2026-04-15T12:00:30Z",
            "session_id": "session_metrics",
            "phase": "backtest",
            "status": "ok",
            "message": "resume backtest courant",
            "payload": {
                "detail": "resume backtest courant",
                "sharpe": 1.234,
                "total_return_pct": 12.5,
                "total_pnl": 1250.0,
                "total_trades": 42,
                "win_rate_pct": 38.1,
                "profit_factor": 1.27,
                "max_drawdown_pct": -8.5,
            },
        }
    )

    rendered = stream_path.read_text(encoding="utf-8")
    assert "RESULTATS : Sharpe 1.234 | Return +12.50% | PnL $+1,250.00" in rendered
    assert "TRADES    : Trades 42 | Win rate 38.1% | PF 1.27 | Max DD 8.50%" in rendered


def test_thought_stream_ignores_late_chunks_after_session_done(tmp_path):
    stream_path = tmp_path / "_live_thoughts.md"
    archive_dir = tmp_path / "_live_thoughts_archives"
    thought_stream = ThoughtStream(
        "session_closed",
        "Objectif clos",
        "mock-model",
        path=stream_path,
        archive_dir=archive_dir,
    )
    thought_stream.consume(
        {
            "event": "session_start",
            "timestamp": "2026-04-10T12:05:00Z",
            "session_id": "session_closed",
            "payload": {"symbol": "BTCUSDC", "timeframe": "1h"},
        }
    )
    thought_stream.consume(
        {
            "event": "session_done",
            "timestamp": "2026-04-10T12:06:00Z",
            "session_id": "session_closed",
            "status": "failed",
            "payload": {"total_iterations": 1, "best_sharpe": 0.0},
        }
    )
    before = stream_path.read_text(encoding="utf-8")

    thought_stream.stream_chunk("proposal", "late chunk should be ignored")
    thought_stream.flush_stream()

    after = stream_path.read_text(encoding="utf-8")
    assert after == before
    assert "late chunk should be ignored" not in after


def test_chat_llm_timeout_aborts_active_streams(monkeypatch):
    abort_calls = {"count": 0}

    class _TimeoutFuture:
        def result(self, timeout=None):
            del timeout
            raise concurrent.futures.TimeoutError()

    class _TimeoutPool:
        def submit(self, fn, *args, **kwargs):
            del fn, args, kwargs
            return _TimeoutFuture()

        def shutdown(self, wait=False):
            del wait
            return None

    class _AbortableClient:
        def __init__(self):
            self.config = LLMConfig(
                provider=LLMProvider.OLLAMA,
                model="gemma4:31b",
                ollama_host="http://127.0.0.1:11434",
            )

        def abort_current_stream(self):
            abort_calls["count"] += 1
            return True

        def chat(self, messages, json_mode=False, temperature=None, max_tokens=None):
            del messages, json_mode, temperature, max_tokens
            return SimpleNamespace(content="should_not_be_used")

    monkeypatch.setattr(
        strategy_builder_module,
        "_new_streamlit_aware_thread_pool",
        lambda max_workers=1: _TimeoutPool(),
    )

    builder = StrategyBuilder(llm_client=_AbortableClient())
    response = builder._chat_llm(
        [LLMMessage(role="user", content="génère une stratégie")],
        phase="code",
    )

    assert response.content == ""
    assert abort_calls["count"] == 1


def test_builder_persists_runtime_checkpoint_on_save_and_load_failure(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_runtime_checkpoint_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "strategy_name": "builder_checkpoint_test",
            "hypothesis": "RSI reversal simple",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "entry_long_logic": "rsi < 30",
            "entry_short_logic": "rsi > 70",
            "exit_logic": "rsi crosses 50",
            "risk_management": "atr stop",
            "default_params": {"rsi_period": 14, "atr_period": 14},
            "parameter_specs": {},
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True, "source": "llm"},
    )

    def _raise_save_and_load(session, code, iteration_num):
        raise RuntimeError("boom load")

    builder._save_and_load = _raise_save_and_load
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "stop")

    session = builder.run(
        objective="Tester checkpoint runtime Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.iterations
    iteration = session.iterations[0]
    assert iteration.error == "RuntimeError: boom load"
    assert iteration.phase_feedback["execution"]["failure_stage"] == "save_and_load"
    checkpoint_path = session.session_dir / "runtime_checkpoint.json"
    assert checkpoint_path.exists()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["iteration"] == 1
    assert payload["stage"] == "save_and_load"
    assert payload["status"] == "error"
    assert payload["error"] == "RuntimeError: boom load"
    assert payload["code_feedback"]["source"] == "llm"
    assert payload["events"][-1]["stage"] == "save_and_load"


def test_builder_run_uses_sweep_and_rewrites_code_defaults(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_sweep_defaults_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "strategy_name": "builder_rsi_atr_sweep",
            "hypothesis": "RSI + ATR with local sweep",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "entry_long_logic": "rsi < 30 AND atr > 0",
            "entry_short_logic": "rsi > 70 AND atr > 0",
            "exit_logic": "rsi crosses above 50 OR rsi crosses below 50",
            "risk_management": "ATR-based stop and take-profit",
            "default_params": {"rsi_period": 14, "atr_period": 14},
            "parameter_specs": {
                "rsi_period": {
                    "min": 10,
                    "max": 20,
                    "default": 14,
                    "type": "int",
                    "step": 1,
                },
                "atr_period": {
                    "min": 10,
                    "max": 20,
                    "default": 14,
                    "type": "int",
                    "step": 1,
                },
            },
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._ask_pre_reflection = lambda *args, **kwargs: ""

    def _fake_run_backtest(*args, **kwargs):
        params = dict(args[2])
        rsi_period = int(params.get("rsi_period", 14))
        atr_period = int(params.get("atr_period", 14))
        sharpe = 2.0 - (abs(rsi_period - 15) * 0.1) - (abs(atr_period - 13) * 0.1)
        return SimpleNamespace(
            metrics={
                "total_return_pct": 10.0 + sharpe,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sharpe + 0.2,
                "calmar_ratio": sharpe,
                "max_drawdown_pct": -8.0,
                "total_trades": 28,
                "win_rate_pct": 41.0,
                "profit_factor": 1.35,
                "expectancy": 0.12,
            },
            meta={},
            run_result=SimpleNamespace(meta={}),
        )

    builder._run_backtest = _fake_run_backtest
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "accept")

    session = builder.run(
        objective="Tester le sweep Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    iteration = session.iterations[0]
    backtest_feedback = iteration.phase_feedback["backtest"]

    assert backtest_feedback["mode"] == "sweep"
    assert backtest_feedback["sweep_total_tested"] == 9
    assert backtest_feedback["params_used"]["rsi_period"] == 15
    assert backtest_feedback["params_used"]["atr_period"] == 13
    assert (
        _extract_default_params_signature(iteration.code)["rsi_period"] == 15
    )
    assert (
        _extract_default_params_signature(iteration.code)["atr_period"] == 13
    )


def test_retry_runtime_timeout_ignores_reasoning_floor():
    llm_client = SimpleNamespace(config=SimpleNamespace(model="deepseek-r1:14b"))

    main_code_timeout = strategy_builder_module._resolve_builder_phase_timeout(
        "code",
        180,
        llm_client,
    )
    retry_timeout = strategy_builder_module._resolve_builder_phase_timeout(
        "retry_code_runtime",
        90,
        llm_client,
    )

    assert main_code_timeout >= 420
    assert retry_timeout == 90


def test_builder_run_fallback_accept_tracks_best_sharpe(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_fallback_accept_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {},
        {"phase": "proposal", "final_valid": False},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._ask_pre_reflection = lambda *args, **kwargs: ""
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics={
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.1,
            "max_drawdown_pct": -8.0,
            "total_trades": 28,
            "win_rate_pct": 41.0,
            "profit_factor": 1.35,
            "expectancy": 0.12,
        },
        meta={},
    )
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "accept")

    session = builder.run(
        objective="Tester la progression Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert session.best_sharpe == pytest.approx(1.42)
    assert session.best_iteration is not None
    assert session.best_iteration.is_fallback is True


def test_builder_run_ignores_pre_reflection_timeout(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_pre_reflection_timeout_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    class _TimeoutFuture:
        def result(self, timeout=None):
            raise concurrent.futures.TimeoutError()

    class _TimeoutPool:
        def submit(self, fn, *args, **kwargs):
            return _TimeoutFuture()

        def shutdown(self, wait=False):
            return None

    monkeypatch.setattr(
        strategy_builder_module,
        "_new_streamlit_aware_thread_pool",
        lambda max_workers=1: _TimeoutPool(),
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "hypothesis": "RSI reversal simple",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "default_params": {"rsi_period": 14, "atr_period": 14},
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics={
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.1,
            "max_drawdown_pct": -8.0,
            "total_trades": 28,
            "win_rate_pct": 41.0,
            "profit_factor": 1.35,
            "expectancy": 0.12,
        },
        meta={},
    )
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "accept")

    session = builder.run(
        objective="Tester le timeout pre-reflection",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert session.iterations[0].phase_feedback.get("pre_reflection", {}).get("timeout") is True


def test_builder_run_skips_pre_reflection_when_ablated(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]
    builder.ablation.disable("pre_reflection")

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_pre_reflection_ablated_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_new_streamlit_aware_thread_pool",
        lambda max_workers=1: pytest.fail("pre_reflection pool should not be created when ablated"),
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "hypothesis": "RSI reversal simple",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "default_params": {"rsi_period": 14, "atr_period": 14},
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 0.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics={
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.1,
            "max_drawdown_pct": -8.0,
            "total_trades": 28,
            "win_rate_pct": 41.0,
            "profit_factor": 1.35,
            "expectancy": 0.12,
        },
        meta={},
    )
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse stable", "accept")

    session = builder.run(
        objective="Tester la désactivation pre-reflection",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert "pre_reflection" not in session.iterations[0].phase_feedback


def test_candidate_executor_skips_runtime_fix_when_ablated(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.ablation.disable("runtime_fix")
    builder._retry_code_runtime_fix = lambda **kwargs: pytest.fail(
        "runtime_fix should not be called when ablated"
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._run_backtest_with_optional_sweep = lambda *args, **kwargs: (
        SimpleNamespace(
            metrics={
                "total_return_pct": 11.0,
                "sharpe_ratio": 1.1,
                "sortino_ratio": 1.5,
                "calmar_ratio": 1.0,
                "max_drawdown_pct": -9.0,
                "total_trades": 24,
                "win_rate_pct": 40.0,
                "profit_factor": 1.2,
                "expectancy": 0.09,
            },
            meta={},
        ),
        {"mode": "single", "params_used": {"rsi_period": 14}},
    )

    session = BuilderSession(
        session_id="candidate_runtime_fix_off",
        objective="test",
        session_dir=tmp_path / "candidate_runtime_fix_off",
        symbol="BTCUSDC",
        timeframe="1h",
    )
    proposal = json.loads(_valid_builder_proposal_payload())
    context = builder_candidate_executor_module.CandidateExecutionContext(
        session=session,
        proposal=proposal,
        proposal_feedback={},
        last_iteration=None,
        iteration_num=1,
        data=sample_ohlcv,
        initial_capital=10000.0,
        fallback_count=0,
    )
    executor = builder_candidate_executor_module.BuilderCandidateExecutorV2(
        builder,
        context,
    )

    monkeypatch.setattr(
        builder_candidate_executor_module,
        "_repair_code",
        lambda code, req_inds, enable_indicator_binding: code,
    )
    monkeypatch.setattr(
        builder_candidate_executor_module,
        "validate_generated_code",
        lambda code: (True, ""),
    )

    code, bt_result = executor._recover_runtime_failure(
        "signals[:] = 0.0",
        RuntimeError("boom"),
    )

    assert "GeneratedStrategy" in code
    assert bt_result.metrics["sharpe_ratio"] == 1.1
    assert executor.code_feedback["source"] == "deterministic_fallback"
    assert executor.backtest_feedback["runtime_fix_fallback_deterministic_used"] is True


def test_candidate_executor_skips_code_repair_when_ablated(monkeypatch, tmp_path, sample_ohlcv):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.ablation.disable("code_repair")

    session = BuilderSession(
        session_id="candidate_no_repair",
        objective="test",
        session_dir=tmp_path / "candidate_no_repair",
    )
    context = builder_candidate_executor_module.CandidateExecutionContext(
        session=session,
        proposal={"used_indicators": ["rsi"]},
        proposal_feedback={},
        last_iteration=None,
        iteration_num=1,
        data=sample_ohlcv,
        initial_capital=10000.0,
        fallback_count=0,
    )
    executor = builder_candidate_executor_module.BuilderCandidateExecutorV2(
        builder,
        context,
    )

    monkeypatch.setattr(
        builder_candidate_executor_module,
        "_repair_code",
        lambda *args, **kwargs: pytest.fail("code_repair should not be called when ablated"),
    )
    monkeypatch.setattr(
        builder_candidate_executor_module,
        "validate_generated_code",
        lambda code: (True, ""),
    )

    code = executor._validate_candidate_code("signals[:] = 0.0")

    assert code == "signals[:] = 0.0"


def test_candidate_executor_passes_indicator_binding_flag_to_repair(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.ablation.disable("indicator_binding")

    session = BuilderSession(
        session_id="candidate_indicator_binding_off",
        objective="test",
        session_dir=tmp_path / "candidate_indicator_binding_off",
    )
    context = builder_candidate_executor_module.CandidateExecutionContext(
        session=session,
        proposal={"used_indicators": ["rsi"]},
        proposal_feedback={},
        last_iteration=None,
        iteration_num=1,
        data=sample_ohlcv,
        initial_capital=10000.0,
        fallback_count=0,
    )
    executor = builder_candidate_executor_module.BuilderCandidateExecutorV2(
        builder,
        context,
    )
    recorded_flags: list[bool] = []

    monkeypatch.setattr(
        builder_candidate_executor_module,
        "_repair_code",
        lambda code, req_inds, enable_indicator_binding: (
            recorded_flags.append(bool(enable_indicator_binding)) or code
        ),
    )
    monkeypatch.setattr(
        builder_candidate_executor_module,
        "validate_generated_code",
        lambda code: (True, ""),
    )

    code = executor._validate_candidate_code("signals[:] = 0.0")

    assert code == "signals[:] = 0.0"
    assert recorded_flags == [False]


def test_builder_overrides_params_when_no_real_param_delta(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr", "bollinger", "adx"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_params_no_delta_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None

    proposals = iter(
        [
            (
                {
                    "hypothesis": "Base RSI/ATR",
                    "used_indicators": ["rsi", "atr"],
                    "change_type": "logic",
                    "default_params": {
                        "rsi_period": 14,
                        "atr_period": 14,
                        "leverage": 1,
                        "stop_atr_mult": 1.5,
                        "tp_atr_mult": 3.0,
                        "warmup": 50,
                    },
                },
                {"phase": "proposal", "final_valid": True},
            ),
            (
                {
                    "hypothesis": "Je prétends tuner les paramètres mais je change les indicateurs",
                    "used_indicators": ["bollinger", "adx"],
                    "change_type": "params",
                    "default_params": {
                        "rsi_period": 14,
                        "atr_period": 14,
                        "leverage": 1,
                        "stop_atr_mult": 1.5,
                        "tp_atr_mult": 3.0,
                        "warmup": 50,
                    },
                },
                {"phase": "proposal", "final_valid": True},
            ),
        ]
    )
    builder._ask_proposal = lambda session, last_iteration: next(proposals)

    code_calls = []

    def _ask_code(session, proposal, last_iteration):
        code_calls.append(proposal.get("change_type"))
        return "signals[:] = 0.0", {"phase": "code", "final_valid": True}

    builder._ask_code = _ask_code
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "total_signals": 2,
        "long_signals": 1,
        "short_signals": 1,
    }
    builder._ask_pre_reflection = lambda *args, **kwargs: ""

    metric_stream = iter(
        [
            {
                "total_return_pct": 5.0,
                "sharpe_ratio": 0.4,
                "sortino_ratio": 0.5,
                "calmar_ratio": 0.3,
                "max_drawdown_pct": -20.0,
                "total_trades": 20,
                "win_rate_pct": 45.0,
                "profit_factor": 1.1,
                "expectancy": 0.1,
            },
            {
                "total_return_pct": 6.0,
                "sharpe_ratio": 0.6,
                "sortino_ratio": 0.7,
                "calmar_ratio": 0.4,
                "max_drawdown_pct": -18.0,
                "total_trades": 22,
                "win_rate_pct": 47.0,
                "profit_factor": 1.2,
                "expectancy": 0.12,
            },
        ]
    )
    builder._run_backtest = lambda *args, **kwargs: SimpleNamespace(
        metrics=next(metric_stream),
        meta={},
    )

    analysis_calls = iter([
        ("continuer", "continue"),
        ("accepter", "accept"),
    ])
    builder._ask_analysis = lambda *args, **kwargs: next(analysis_calls)

    session = builder.run(
        objective="Tester override params-only",
        data=sample_ohlcv,
        max_iterations=2,
        target_sharpe=0.5,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert session.status == "success"
    assert code_calls == ["logic", "logic"]
    assert session.iterations[1].change_type == "logic"
    assert (
        "indicator_set_changed"
        in session.iterations[1]
        .phase_feedback["proposal"]["change_type_overridden"]["reason"]
    )
    assert (
        session.iterations[1]
        .phase_feedback["proposal"]["change_type_overridden"]["reason"]
        != ""
    )
    assert session.iterations[1].phase_feedback["code"].get("source") != "params_patch"


def test_infer_direction_constraint_from_objective_detects_buy_only():
    objective = (
        "Generate buy signals on BTCUSDC 4h timeframe. "
        "Only execute buy orders."
    )
    assert _infer_direction_constraint_from_objective(objective) == "long_only"


def test_sanitize_proposal_payload_clears_short_logic_for_long_only():
    proposal = {
        "strategy_name": "mean_reversion_test",
        "hypothesis": "RSI oversold bounce",
        "change_type": "logic",
        "used_indicators": ["rsi", "atr"],
        "entry_long_logic": "rsi crosses above 30",
        "entry_short_logic": "rsi crosses below 70",
        "exit_logic": "close crosses above ema",
        "risk_management": "ATR-based stop/take-profit",
        "default_params": {"rsi_period": 14},
        "parameter_specs": {
            "rsi_period": {"min": 5, "max": 30, "default": 14, "type": "int"}
        },
    }

    cleaned = _sanitize_proposal_payload(
        proposal,
        available_indicators=["rsi", "atr", "ema"],
        objective="Generate buy signals on BTCUSDC 4h timeframe. Only execute buy orders.",
    )

    assert cleaned["direction_constraint"] == "long_only"
    assert cleaned["entry_long_logic"] == "rsi crosses above 30"
    assert cleaned["entry_short_logic"] == ""


def test_sanitize_proposal_payload_drops_pathological_param_names():
    proposal = {
        "strategy_name": "pathological_params",
        "hypothesis": "Test sanitation",
        "change_type": "params",
        "used_indicators": ["rsi", "atr"],
        "entry_long_logic": "rsi < 30",
        "entry_short_logic": "rsi > 70",
        "default_params": {
            "rsi_period": 14,
            "distance_to_force_index_weight_volume_weight_volume_weight_volume_weight": 1.0,
        },
        "parameter_specs": {
            "rsi_period": {"min": 5, "max": 30, "default": 14, "type": "int"},
            "distance_to_force_index_weight_volume_weight_volume_weight_volume_weight": {
                "min": 0.1,
                "max": 3.0,
                "default": 1.0,
                "type": "float",
            },
        },
    }

    cleaned = _sanitize_proposal_payload(
        proposal,
        available_indicators=["rsi", "atr"],
        objective="Test params",
    )

    assert "rsi_period" in cleaned["default_params"]
    assert "distance_to_force_index_weight_volume_weight_volume_weight_volume_weight" not in cleaned["default_params"]
    assert "distance_to_force_index_weight_volume_weight_volume_weight_volume_weight" not in cleaned["parameter_specs"]


def test_builder_iteration_phase_feedback_coerces_to_typed_mapping():
    iteration = BuilderIteration(
        iteration=1,
        phase_feedback={
            "proposal": {
                "phase": "proposal",
                "final_valid": True,
                "lm_signature": "custom-model-trace",
            }
        },
    )

    assert isinstance(iteration.phase_feedback, IterationPhaseFeedback)
    assert isinstance(iteration.phase_feedback, dict)
    assert isinstance(iteration.phase_feedback["proposal"], ProposalFeedbackSection)
    assert iteration.phase_feedback["proposal"]["phase"] == "proposal"
    assert iteration.phase_feedback["proposal"].extras == {
        "lm_signature": "custom-model-trace"
    }

    iteration.phase_feedback["code"] = {
        "source": "llm",
        "provider_hint": "reasoning-pass",
    }

    assert isinstance(iteration.phase_feedback["code"], CodeFeedbackSection)
    assert iteration.phase_feedback["code"].extras == {
        "provider_hint": "reasoning-pass"
    }


def test_sanitize_proposal_payload_canonicalizes_common_indicator_aliases():
    proposal = {
        "strategy_name": "alias_cleanup",
        "hypothesis": "Nettoyer les alias Builder",
        "change_type": "logic",
        "used_indicators": ["bull_score", "pivot", "klt", "rsci", "atr"],
        "entry_long_logic": "bull_score > 0.6",
        "entry_short_logic": "",
        "exit_logic": "pivot break",
        "risk_management": "ATR stop/take-profit",
        "default_params": {"atr_period": 14},
        "parameter_specs": {},
    }

    cleaned = _sanitize_proposal_payload(
        proposal,
        available_indicators=["directional_bias", "pivot_points", "keltner", "rsi", "atr"],
        objective="Breakout avec filtres directionnels",
    )

    assert cleaned["used_indicators"] == [
        "directional_bias",
        "pivot_points",
        "keltner",
        "rsi",
        "atr",
    ]


def test_apply_signal_direction_constraint_removes_forbidden_side():
    signals = pd.Series([1.0, -1.0, 0.0, -1.0, 1.0], dtype=np.float64)
    constrained = _apply_signal_direction_constraint(signals, "long_only")
    assert constrained.tolist() == [1.0, 0.0, 0.0, 0.0, 1.0]


def test_builder_run_skips_backtest_for_pathological_signal_density(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
    valid_strategy_code,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    builder.available_indicators = ["rsi", "atr"]

    monkeypatch.setattr(
        StrategyBuilder,
        "create_session_id",
        staticmethod(lambda objective: "builder_signal_density_test"),
    )
    monkeypatch.setattr(
        StrategyBuilder,
        "get_session_dir",
        staticmethod(lambda session_id: tmp_path / session_id),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_validate_builder_dataset_exploitability",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        strategy_builder_module,
        "_build_deterministic_strategy_code",
        lambda proposal, logic_block: valid_strategy_code,
    )

    builder._save_session_summary = lambda session: None
    builder._safe_save_session_summary = lambda session: None
    builder._ask_proposal = lambda session, last_iteration: (
        {
            "hypothesis": "Deduplication des signaux manquante",
            "used_indicators": ["rsi", "atr"],
            "change_type": "logic",
            "default_params": {"rsi_period": 14, "atr_period": 14},
        },
        {"phase": "proposal", "final_valid": True},
    )
    builder._ask_code = lambda session, proposal, last_iteration: (
        "signals[:] = 1.0",
        {"phase": "code", "final_valid": True},
    )
    builder._save_and_load = lambda session, code, iteration_num: object
    builder._auto_fix_required_indicators = lambda strategy_cls, code: strategy_cls
    builder._precheck_signal_counts = lambda *args, **kwargs: {
        "ok": True,
        "bar_count": 1000,
        "total_signals": 950,
        "long_signals": 500,
        "short_signals": 450,
        "signal_density": 0.95,
        "transition_signals": 120,
        "transition_density": 0.12,
        "repeated_same_signals": 830,
        "repeated_same_ratio": 0.8736842105,
    }

    backtest_called = {"value": False}

    def _unexpected_backtest(*args, **kwargs):
        backtest_called["value"] = True
        raise AssertionError("_run_backtest should not be called")

    builder._run_backtest = _unexpected_backtest
    builder._ask_analysis = lambda *args, **kwargs: ("Analyse overtrading", "stop")

    session = builder.run(
        objective="Tester le skip precheck Builder",
        data=sample_ohlcv,
        max_iterations=1,
        target_sharpe=1.0,
        symbol="BTCUSDC",
        timeframe="1h",
    )

    assert backtest_called["value"] is False
    assert session.iterations[0].diagnostic_category == "overtrading"
    assert session.iterations[0].backtest_result.metrics["total_trades"] == 950
    assert session.iterations[0].phase_feedback["precheck"]["backtest_skipped"] is True
    assert (
        session.iterations[0].phase_feedback["precheck"]["pathological_signal_density"]
        is True
    )
    assert (
        session.iterations[0].phase_feedback["precheck"]["skip_reason"]
        == "pathological_signal_density"
    )


# ─── Tests validate_generated_code ───────────────────────────────────────

class TestValidateCode:
    """Tests de la fonction validate_generated_code."""

    def test_valid_code(self, valid_strategy_code):
        is_valid, msg = validate_generated_code(valid_strategy_code)
        assert is_valid, f"Code devrait être valide: {msg}"

    def test_syntax_error(self):
        code = "class Foo(\n  def bar(self):\n    pass"
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "syntaxe" in msg.lower() or "syntax" in msg.lower()

    def test_missing_class(self):
        code = textwrap.dedent("""\
            import numpy as np
            class WrongName:
                def generate_signals(self, df, indicators, params):
                    pass
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert GENERATED_CLASS_NAME in msg

    def test_missing_generate_signals(self):
        code = textwrap.dedent(f"""\
            class {GENERATED_CLASS_NAME}:
                def some_other_method(self):
                    pass
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "generate_signals" in msg

    def test_reject_nameerror_df_not_defined(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, data, indicators, params):
                    signals = pd.Series(0.0, index=data.index)
                    close = df["close"].values
                    signals[close > 0] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "nameerror" in msg.lower()
        assert "df" in msg.lower()

    def test_reject_nameerror_warmup_not_defined(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals.iloc[:warmup] = 0.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "nameerror" in msg.lower()
        assert "warmup" in msg.lower()

    def test_reject_two_dimensional_signal_indexing(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{"leverage": 1, "warmup": 5}}

                def generate_signals(self, df, indicators, params):
                    rsi = np.nan_to_num(indicators["rsi"])
                    long_mask = rsi < 30
                    signals = pd.Series(0.0, index=df.index, dtype=np.float64)
                    signals.loc[long_mask, "long"] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "signals" in msg.lower()
        assert "series" in msg.lower() or "1d" in msg.lower()

    def test_dangerous_os_system(self):
        code = textwrap.dedent(f"""\
            import os
            class {GENERATED_CLASS_NAME}:
                def generate_signals(self, df, indicators, params):
                    os.system("rm -rf /")
                    return df["close"] * 0
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "dangereux" in msg.lower() or "dangerous" in msg.lower()

    def test_dangerous_subprocess(self):
        code = textwrap.dedent(f"""\
            import subprocess
            class {GENERATED_CLASS_NAME}:
                def generate_signals(self, df, indicators, params):
                    subprocess.run(["ls"])
                    return df["close"] * 0
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid

    def test_dangerous_eval(self):
        code = textwrap.dedent(f"""\
            class {GENERATED_CLASS_NAME}:
                def generate_signals(self, df, indicators, params):
                    return eval("df['close']")
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid

    def test_reject_iloc_on_indicator_array(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    for i in range(len(df)):
                        if indicators["rsi"].iloc[i] < 30:
                            signals.iloc[i] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        # May be rejected for iloc or for-range (both are banned patterns)
        assert "iloc" in msg.lower() or "range" in msg.lower()

    def test_reject_unknown_indicator_alias(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi", "bollinger_upper"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    upper = indicators.get("bollinger_upper")
                    rsi = indicators["rsi"]
                    if upper is not None:
                        signals[(rsi > 70) & (df["close"].values > upper)] = -1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "indicateur" in msg.lower() or "inconnu" in msg.lower()

    def test_reject_array_indicator_subkey_access(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["ema"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    ema_21 = np.nan_to_num(indicators["ema"]["ema_21"])
                    signals[df["close"].values > ema_21] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "ndarray" in msg.lower() or "ema" in msg.lower()

    def test_reject_dict_indicator_direct_comparison(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["adx"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    adx = indicators["adx"]
                    signals[adx > 25] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "dict" in msg.lower() and "adx" in msg.lower()

    def test_reject_direct_indicator_subscript_comparison(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["adx"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    adx_filter = indicators["adx"] > 25
                    signals[adx_filter] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "dict" in msg.lower() and "adx" in msg.lower()

    def test_reject_direct_indicator_subscript_method_call(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["adx"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    if indicators["adx"].upper():
                        signals[df["close"].values > 0] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "indicator dict" in msg.lower() or "dict" in msg.lower()

    def test_reject_unknown_supertrend_subkey(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["supertrend"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    st = indicators["supertrend"]
                    upper = np.nan_to_num(st["upper"])
                    signals[df["close"].values > upper] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "supertrend" in msg.lower() and "sous-cl" in msg.lower()

    def test_reject_dict_indicator_any_method(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["adx"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    adx = indicators["adx"]
                    if adx.any():
                        signals.iloc[:10] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "indicator dict" in msg.lower() or "dict" in msg.lower()

    def test_reject_overwrite_np_alias(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    np = 1
                    signals = pd.Series(0.0, index=df.index)
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "alias réservé `np`".lower() in msg.lower()

    def test_reject_bare_registered_indicator_name_without_alias(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["coppock_curve"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[coppock_curve > 0] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "coppock_curve" in msg
        assert "variable nue" in msg.lower()

    def test_reject_undefined_local_variable_in_generate_signals(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["bollinger"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    bb = indicators["bollinger"]
                    lower = np.nan_to_num(bb["lower"])
                    close = df["close"].values
                    long_entry = (close <= lower) & bb_upper_trend_up
                    signals[long_entry] = 1.0
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "nameerror" in msg.lower()
        assert "bb_upper_trend_up" in msg

    def test_reject_ellipsis_placeholder_in_generate_signals(self):
        code = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    ...
                    return signals
        """)
        is_valid, msg = validate_generated_code(code)
        assert not is_valid
        assert "placeholder" in msg.lower()
        assert "..." in msg


# ─── Tests extraction LLM ─────────────────────────────────────────────────

class TestExtractResponse:
    """Tests des helpers d'extraction de réponse LLM."""

    def test_extract_json_from_code_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = _extract_json_from_response(text)
        assert result == {"key": "value"}

    def test_extract_json_bare(self):
        text = '{"strategy_name": "test"}'
        result = _extract_json_from_response(text)
        assert result["strategy_name"] == "test"

    def test_extract_json_embedded_in_text(self):
        text = 'Here is the result: {"hypothesis": "test RSI"} and done.'
        result = _extract_json_from_response(text)
        assert result["hypothesis"] == "test RSI"

    def test_extract_json_invalid(self):
        text = "No JSON here, just text."
        result = _extract_json_from_response(text)
        assert result == {}

    def test_extract_python_from_code_block(self):
        text = 'Sure:\n```python\nimport numpy as np\nprint("hello")\n```'
        result = _extract_python_from_response(text)
        assert "import numpy" in result
        assert "print" in result

    def test_extract_python_fallback(self):
        text = "import pandas as pd\ndf = pd.DataFrame()"
        result = _extract_python_from_response(text)
        assert "import pandas" in result

    def test_extract_python_strips_prose_and_numbered_markers(self):
        text = textwrap.dedent("""\
            Here is the corrected code:
            1. import numpy as np
            2. from strategies.base import StrategyBase

            Note: keep only this code.
        """)

        result = _extract_python_from_response(text)

        assert result.startswith("import numpy as np")
        assert "from strategies.base import StrategyBase" in result
        assert "Here is the corrected code" not in result
        assert "Note:" not in result

    def test_extract_python_returns_empty_for_traceback_only_response(self):
        text = textwrap.dedent("""\
            Traceback (most recent call last):
              File "<unknown>", line 7
                TypeError: unsupported operand type(s) for -: 'dict' and 'dict'
            TypeError: unsupported operand type(s) for -: 'dict' and 'dict'
        """)

        result = _extract_python_from_response(text)

        assert result == ""

    def test_extract_generate_signals_logic_block_returns_empty_on_indented_logic_snippet(self):
        raw = textwrap.dedent("""\
            Here is the logic:

                n = len(df)
                signals[close > ema_fast] = 1.0
                return signals
        """)

        result = _extract_generate_signals_logic_block(raw)

        assert result == ""

    def test_extract_generate_signals_logic_block_recovers_from_noisy_indented_class_code(self):
        raw = textwrap.dedent(f"""\
            Here is the corrected code:

                class {GENERATED_CLASS_NAME}(StrategyBase):
                    def generate_signals(self, df, indicators, params):
                        n = len(df)
                        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
                        signals[close > ema_fast] = 1.0
                        return signals
        """)

        result = _extract_generate_signals_logic_block(raw)

        assert "signals[close > ema_fast] = 1.0" in result
        assert "return signals" not in result


class TestLogicBlockValidation:
    def test_llm_logic_allows_boolean_constants_outside_signals(self):
        logic = textwrap.dedent("""\
            long_prev = np.roll(long_mask, 1)
            long_prev[:1] = False
            long_entry = long_mask & (~long_prev)
            signals[long_entry] = 1.0
        """)
        ok, err = _validate_llm_logic_block(logic)
        assert ok, err

    def test_llm_logic_rejects_true_false_in_signal_assignments(self):
        logic = "signals[long_mask] = True"
        ok, err = _validate_llm_logic_block(logic)
        assert not ok
        assert "true/false" in err.lower()

    def test_llm_logic_rejects_signals_loc_assignments(self):
        logic = "signals.loc[long_mask] = 1.0"
        ok, err = _validate_llm_logic_block(logic)
        assert not ok
        assert "signals" in err.lower()

    def test_llm_logic_rejects_pipe_joined_indicator_subkeys(self):
        logic = "upper = np.nan_to_num(indicators['bollinger']['upper|middle|lower'])"
        ok, err = _validate_llm_logic_block(logic)
        assert not ok
        assert "sous-cles" in err.lower() or "sous-cl" in err.lower()

    def test_llm_logic_rejects_crosses_helper_names(self):
        logic = "long_entry = crosses_above_price(close, ema_fast)"
        ok, err = _validate_llm_logic_block(logic)
        assert not ok
        assert "crosses_" in err.lower()

    def test_postprocess_llm_logic_rewrites_signals_loc_and_indicator_alias_access(self):
        logic = textwrap.dedent("""\
            signals.loc[long_mask] = 1
            has_position = signals.notnull()
            plus = indicators['plus_di']
            stop_mult = indicators['stop_atr_mult']
        """)

        fixed = _postprocess_llm_logic_block(logic, ["adx", "atr"])

        assert "signals[long_mask] = 1.0" in fixed
        assert "(signals != 0.0)" in fixed
        assert "indicators['adx']['plus_di']" in fixed
        assert "params.get('stop_atr_mult', 1.5)" in fixed

    def test_postprocess_llm_logic_rewrites_cross_helper_calls(self):
        logic = "long_mask = crosses_above(close, ema_fast)"

        fixed = _postprocess_llm_logic_block(logic, ["ema"])

        assert "crosses_above" not in fixed
        assert "(close > ema_fast)" in fixed
        assert "np.roll(close, 1) <= np.roll(ema_fast, 1)" in fixed

    def test_postprocess_llm_logic_rewrites_same_slice_vector_comparison(self):
        logic = "long_mask = close[warmup:] > ema_fast[warmup:]"

        fixed = _postprocess_llm_logic_block(logic, ["ema"])

        assert "close[warmup:]" not in fixed
        assert "ema_fast[warmup:]" not in fixed
        assert "long_mask = close > ema_fast" in fixed

    def test_postprocess_llm_logic_rewrites_and_keyword_on_mask_assignment(self):
        logic = "long_mask = (close > ema_fast) and (adx_val > 20)"

        fixed = _postprocess_llm_logic_block(logic, ["ema", "adx"])

        assert " and " not in fixed
        assert "long_mask = (((close > ema_fast)) & ((adx_val > 20)))" in fixed

    def test_postprocess_llm_logic_rewrites_truncated_signal_mask_assignment(self):
        logic = "signals[long_mask[1:]] = 1"

        fixed = _postprocess_llm_logic_block(logic, ["ema"])

        assert "signals[long_mask[1:]]" not in fixed
        assert "signals[long_mask] = 1.0" in fixed


class TestCodeRepair:
    def test_deterministic_builder_injects_indicator_binding_block(self):
        proposal = {
            "strategy_name": "BindingTest",
            "used_indicators": ["rsi", "bollinger"],
            "default_params": {},
        }

        code = _build_deterministic_strategy_code(
            proposal,
            "signals[(rsi < 30) & (lower > 0)] = 1.0",
        )

        assert "rsi = np.nan_to_num(indicators['rsi'])" in code
        assert 'bb = indicators["bollinger"]' in code
        assert 'lower = np.nan_to_num(bb["lower"])' in code
        assert "bollinger_data = bb" in code
        assert "bollinger_lower = lower" in code

    def test_repair_normalizes_indicator_key_case(self):
        raw = "x = indicators['SMA']\ny = indicators.get('ADX', None)\n"
        repaired = _repair_code(raw)
        assert "indicators['sma']" in repaired
        assert "indicators.get('adx'" in repaired

    def test_repair_rewrites_dict_dot_notation(self):
        raw = "x = donchian.upper\ny = adx.adx\n"
        repaired = _repair_code(raw)
        assert "indicators['donchian']['upper']" in repaired
        assert "indicators['adx']['adx']" in repaired

    def test_repair_rewrites_indicators_close_to_df_close(self):
        raw = "price = indicators['close']\nsl = indicators.get('bb_stop_long', np.nan)\n"
        repaired = _repair_code(raw)
        assert "df['close']" in repaired
        assert "df['bb_stop_long']" in repaired

    def test_repair_injects_bare_indicator_alias_in_generate_signals(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["coppock_curve"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[coppock_curve > 0] = 1.0
                    return signals
        """)
        repaired = _repair_code(raw)
        assert "coppock_curve = np.nan_to_num(indicators['coppock_curve'])" in repaired

    def test_repair_normalizes_legacy_base_strategy_import(self):
        raw = textwrap.dedent(f"""\
            import numpy as np
            import pandas as pd
            from strategies.base_strategy import BaseStrategy

            class {GENERATED_CLASS_NAME}(BaseStrategy):
                required_indicators = ["ema_fast"]
                default_params = {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[indicators["ema_fast"] > 0] = 1.0
                    return signals
        """)
        repaired = _repair_code(raw)
        assert "from strategies.base import StrategyBase" in repaired
        assert f"class {GENERATED_CLASS_NAME}(StrategyBase):" in repaired

    def test_repair_rewrites_signals_loc_2d_long_short_assignments(self):
        raw = textwrap.dedent(f"""\
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                required_indicators = ["ema_fast"]
                default_params = {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    long_mask = indicators["ema_fast"] > 0
                    short_mask = indicators["ema_fast"] < 0
                    signals.loc[long_mask, "long"] = 1.0
                    signals.loc[short_mask, "short"] = 1.0
                    return signals
        """)
        repaired = _repair_code(raw)
        assert "signals.loc[" not in repaired
        assert "signals[long_mask] = 1.0" in repaired
        assert "signals[short_mask] = -1.0" in repaired

    def test_repair_rewrites_safe_dict_indicator_direct_comparison(self):
        raw = "if indicators['adx'] > 25:\n    signals[mask] = 1.0\n"
        repaired = _repair_code(raw)
        assert "indicators['adx'] > 25" not in repaired
        assert "indicators['adx']['adx']" in repaired

    def test_repair_injects_binding_block_from_required_indicators(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi", "bollinger"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[(rsi < 30) & (lower > 0)] = 1.0
                    return signals
        """)
        repaired = _repair_code(raw, ["rsi", "bollinger"])
        assert "rsi = np.nan_to_num(indicators['rsi'])" in repaired
        assert "bb = indicators['bollinger']" in repaired
        assert 'lower = np.nan_to_num(bb["lower"])' in repaired
        assert "bollinger_data = bb" in repaired
        assert "bollinger_lower = lower" in repaired

    def test_repair_injects_directional_bias_subkeys(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["directional_bias"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[bull_score > bear_score] = 1.0
                    return signals
        """)

        repaired = _repair_code(raw, ["directional_bias"])

        assert 'bias = indicators["directional_bias"]' in repaired or "bias = indicators['directional_bias']" in repaired
        assert 'bull_score = np.nan_to_num(bias["bull_score"])' in repaired
        assert 'bear_score = np.nan_to_num(bias["bear_score"])' in repaired

    def test_repair_does_not_inject_aliases_before_existing_indicator_extraction(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi", "bollinger", "atr"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    rsi = np.nan_to_num(indicators['rsi'])
                    bb = indicators['bollinger']
                    upper = np.nan_to_num(bb["upper"])
                    middle = np.nan_to_num(bb["middle"])
                    lower = np.nan_to_num(bb["lower"])
                    atr = np.nan_to_num(indicators['atr'])
                    signals[(rsi < 30) & (lower > 0)] = 1.0
                    return signals
        """)

        repaired = _repair_code(raw, ["rsi", "bollinger", "atr"])

        assert "rsi_arr = rsi" not in repaired
        assert "rsi_data = rsi" not in repaired
        assert "bollinger_upper = upper" not in repaired
        assert repaired.count("rsi = np.nan_to_num(indicators['rsi'])") == 1

    def test_repair_injects_price_and_array_aliases_for_common_nameerrors(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["rsi"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    signals[(price > 0) & (rsi_arr > 50)] = 1.0
                    return signals
        """)

        repaired = _repair_code(raw, ["rsi"])

        assert "close = np.nan_to_num(df['close'].values.astype(np.float64))" in repaired
        assert "price = close" in repaired
        assert "rsi_arr = rsi" in repaired

    def test_repair_rewrites_invalid_indicator_and_param_access_aliases(self):
        raw = (
            "x = indicators['plus_di']\n"
            "y = indicators.get('aroon_down')\n"
            "z = indicators['stop_atr_mult']\n"
        )

        repaired = _repair_code(raw)

        assert "indicators['adx']['plus_di']" in repaired
        assert "indicators['aroon']['aroon_down']" in repaired
        assert "params.get('stop_atr_mult', 1.5)" in repaired

    def test_repair_rewrites_semantic_bollinger_aliases(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["momentum", "bollinger"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    momentum = np.nan_to_num(indicators['momentum'])
                    signals[momentum > higher_bollinger] = 1.0
                    return signals
        """)

        repaired = _repair_code(raw, ["momentum", "bollinger"])

        assert "higher_bollinger" not in repaired
        assert "indicators['bollinger']['upper']" in repaired

    def test_repair_injects_bare_param_aliases_used_in_generate_signals(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["atr", "aroon", "bollinger"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    atr = np.nan_to_num(indicators['atr'])
                    close = np.nan_to_num(df['close'].values.astype(np.float64))
                    signals[
                        (indicators['aroon']['aroon_up'] > 75)
                        & (indicators['aroon']['aroon_down'] < 25)
                        & (close > indicators['bollinger']['upper'])
                        & (atr > 1.5 * atr_period)
                    ] = 1.0
                    return signals
        """)

        repaired = _repair_code(raw, ["atr", "aroon", "bollinger"])

        assert "atr_period = params.get('atr_period', 14)" in repaired

    def test_repair_salvages_complex_ast_noise_and_unmatched_parenthesis(self):
        raw = textwrap.dedent(f"""\
            Here is the corrected code:
            ```python
            1. from typing import Any, Dict, List
            2. import numpy as np
            3. import pandas as pd
            4. from strategies.base import StrategyBase

            5. class {GENERATED_CLASS_NAME}(StrategyBase):
            6.     @property
            7.     def required_indicators(self) -> List[str]:
            8.         return ["rsi"]

            9.     @property
            10.     def default_params(self) -> Dict[str, Any]:
            11.         return {{}}

            12.     def generate_signals(self, df, indicators, params):
            13.         signals = pd.Series(0.0, index=df.index)
            14.         signals[rsi_arr > 50] = 1.0))
            15.         return signals
            ```
            Explanation: removed for runtime.
        """)

        repaired = _repair_code(raw, ["rsi"])
        is_valid, msg = validate_generated_code(repaired)

        assert is_valid, msg
        assert "from typing import Any, Dict, List" in repaired
        assert "Explanation:" not in repaired
        assert "rsi_arr = rsi" in repaired

    def test_repair_code_does_not_crash_on_runtime_traceback_text(self):
        raw = "TypeError: unsupported operand type(s) for -: 'dict' and 'dict'"

        repaired = _repair_code(raw, ["amplitude_hunter"])
        is_valid, msg = validate_generated_code(repaired)

        assert isinstance(repaired, str)
        assert not is_valid
        assert "Classe" in msg or "syntaxe" in msg.lower()

    def test_validate_generated_code_rejects_direct_nan_to_num_on_amplitude_hunter_dict(self):
        raw = textwrap.dedent(f"""\
            from typing import Any, Dict, List
            import numpy as np
            import pandas as pd
            from strategies.base import StrategyBase

            class {GENERATED_CLASS_NAME}(StrategyBase):
                @property
                def required_indicators(self) -> List[str]:
                    return ["amplitude_hunter"]

                @property
                def default_params(self) -> Dict[str, Any]:
                    return {{}}

                def generate_signals(self, df, indicators, params):
                    signals = pd.Series(0.0, index=df.index)
                    amp = np.nan_to_num(indicators["amplitude_hunter"])
                    signals[amp > 0] = 1.0
                    return signals
        """)

        is_valid, msg = validate_generated_code(raw)

        assert not is_valid
        assert "amplitude_hunter" in msg

    def test_auto_fix_required_indicators_recovers_missing_runtime_dependencies(self):
        builder = StrategyBuilder(llm_client=SimpleNamespace())

        class _Strategy:
            @property
            def required_indicators(self):
                return ["rsi"]

        code = textwrap.dedent(f"""\
            class {GENERATED_CLASS_NAME}:
                @property
                def required_indicators(self):
                    return ["rsi"]

                def generate_signals(self, df, indicators, params):
                    adx_d = indicators['adx']
                    dc = indicators['donchian']
                    return indicators['rsi']
        """)

        patched = builder._auto_fix_required_indicators(_Strategy, code)
        required = patched().required_indicators

        assert "rsi" in required
        assert "adx" in required
        assert "donchian" in required

    def test_indicator_stable_alias_map_exposes_preferred_names(self):
        alias_map = get_indicator_builder_stable_alias_map("bollinger")
        assert alias_map["bb"] == "bollinger_data"
        assert alias_map["lower"] == "bollinger_lower"

    def test_indicator_selection_guide_mentions_preferred_stable_aliases(self):
        guide = build_indicator_selection_guide(["bollinger"])
        joined = "\n".join(guide)
        assert "Preferred stable aliases:" in joined
        assert "bb->bollinger_data" in joined
        assert "lower->bollinger_lower" in joined


class _DummyLLMClient:
    def __init__(self, response: str):
        self._response = response

    def chat(self, messages, max_tokens=0, json_mode=False):  # noqa: ANN001
        return self._response


class TestMarketRecommendation:
    def test_recommend_market_context_valid(self):
        llm = _DummyLLMClient(
            '{"symbol":"DOGEUSDC","timeframe":"5m","confidence":0.82,"reason":"Scalp court terme."}',
        )
        result = recommend_market_context(
            llm,
            objective="Scalp de continuation agressif",
            candidate_symbols=["BTCUSDC", "DOGEUSDC"],
            candidate_timeframes=["5m", "15m"],
            default_symbol="BTCUSDC",
            default_timeframe="15m",
        )
        assert result["source"] == "llm"
        assert result["symbol"] == "DOGEUSDC"
        assert result["timeframe"] == "5m"
        assert float(result["confidence"]) > 0.8

    def test_recommend_market_context_out_of_universe_fallback(self):
        llm = _DummyLLMClient(
            '{"symbol":"ETHUSDC","timeframe":"1m","confidence":0.9,"reason":"Test"}',
        )
        result = recommend_market_context(
            llm,
            objective="Scalp",
            candidate_symbols=["BTCUSDC", "DOGEUSDC"],
            candidate_timeframes=["5m", "15m"],
            default_symbol="BTCUSDC",
            default_timeframe="15m",
        )
        assert result["source"] == "fallback_out_of_universe"
        assert result["symbol"] == "BTCUSDC"
        assert result["timeframe"] == "15m"

    def test_recommend_market_context_invalid_json_fallback(self):
        llm = _DummyLLMClient("pas de json ici")
        result = recommend_market_context(
            llm,
            objective="Scalp",
            candidate_symbols=["BTCUSDC"],
            candidate_timeframes=["5m"],
            default_symbol="BTCUSDC",
            default_timeframe="5m",
        )
        assert result["source"] == "fallback_invalid_json"
        assert result["symbol"] == "BTCUSDC"
        assert result["timeframe"] == "5m"


class TestObjectiveGenerationIndicatorSanitization:
    def test_generate_llm_objective_preserves_explicit_indicator_block_without_padding(self):
        llm = _DummyLLMClient(
            (
                "Breakout sur ADAUSDC 1w. "
                "Indicateurs : DONCHIAN + PSAR + ATR. "
                "Entrées : cassure validée par psar. "
                "Sorties : invalidation de cassure. "
                "Risk management : stop ATR."
            )
        )
        objective = generate_llm_objective(
            llm,
            symbol=["ADAUSDC"],
            timeframe=["1w"],
            available_indicators=["donchian", "psar", "atr", "rsi", "bollinger", "adx"],
        )

        lower = objective.lower()
        assert "donchian" in lower
        assert "psar" in lower
        assert "atr" in lower
        assert "bollinger" not in lower
        assert "adx" not in lower

    def test_generate_llm_objective_sanitizes_unavailable_indicator(self):
        llm = _DummyLLMClient(
            (
                "Momentum sur BTCUSDC 1h. "
                "Indicateurs : FEAR_GREED + ONCHAIN_SMOOTHING + ATR. "
                "Entrées : confirmation momentum. "
                "Sorties : signal inverse. "
                "Risk management : stop ATR."
            )
        )
        objective = generate_llm_objective(
            llm,
            symbol=["BTCUSDC"],
            timeframe=["1h"],
            available_indicators=["ema", "rsi", "atr", "onchain_smoothing"],
        )
        lower = objective.lower()
        assert "fear_greed" not in lower
        assert "onchain_smoothing" in lower
        assert "atr" in lower

    def test_generate_llm_objective_auto_market_keeps_placeholders_and_sanitizes(self):
        llm = _DummyLLMClient(
            (
                "Contrarian sur BTCUSDC 1m. "
                "Indicateurs : FEAR_GREED + RSI + ATR. "
                "Entrées : rebond. Sorties : invalidation."
            )
        )
        objective = generate_llm_objective(
            llm,
            symbol=None,
            timeframe=None,
            available_indicators=["rsi", "atr", "ema"],
        )
        lower = objective.lower()
        assert "{symbol}" in objective
        assert "{timeframe}" in objective
        assert "fear_greed" not in lower

    def test_generate_llm_objective_accepts_structured_json_payload(self):
        llm = _DummyLLMClient(
            json.dumps(
                {
                    "objective": (
                        "[Compression breakout] sur BTCUSDC 1h. "
                        "Indicateurs : EMA + ADX + ATR. "
                        "Entrées : cassure valide après compression. "
                        "Sorties : retour dans le range. "
                        "Risk management : stop ATR."
                    ),
                    "style": "Compression breakout",
                    "symbol": "BTCUSDC",
                    "timeframe": "1h",
                    "used_indicators": ["ema", "adx", "atr"],
                    "entry_logic": "cassure valide après compression",
                    "exit_logic": "retour dans le range",
                    "risk_management": "stop ATR",
                    "hypothesis": "la compression précède souvent une impulsion",
                }
            )
        )
        objective = generate_llm_objective(
            llm,
            symbol=["BTCUSDC"],
            timeframe=["1h"],
            available_indicators=["ema", "adx", "atr", "rsi"],
        )
        assert objective.startswith("[Compression breakout]")
        assert "EMA" in objective
        assert "ADX" in objective
        assert "ATR" in objective

    def test_generate_llm_objective_from_seed_keeps_placeholders_and_sanitizes(self):
        llm = _DummyLLMClient(
            (
                "Breakout adaptatif sur BTCUSDC 5m. "
                "Indicateurs : FEAR_GREED + DONCHIAN + ATR. "
                "Entrées : cassure confirmée. "
                "Sorties : invalidation. "
                "Risk management : stop ATR."
            )
        )
        objective = generate_llm_objective_from_seed(
            llm,
            seed_objective=(
                "Strategie de Breakout sur {symbol} {timeframe}. "
                "Indicateurs : DONCHIAN + ADX + ATR. "
                "Entree long sur cassure du range avec confirmation ADX."
            ),
            symbol=None,
            timeframe=None,
            available_indicators=["donchian", "adx", "atr", "ema"],
        )
        lower = objective.lower()
        assert "{symbol}" in objective
        assert "{timeframe}" in objective
        assert "fear_greed" not in lower

    def test_generate_llm_objective_from_seed_accepts_structured_json_payload(self):
        llm = _DummyLLMClient(
            json.dumps(
                {
                    "objective": (
                        "[Retournement filtre] sur {symbol} {timeframe}. "
                        "Indicateurs : RSI + EMA + ATR. "
                        "Entrées : excès suivi d'un retour sur EMA. "
                        "Sorties : invalidation du rebond. "
                        "Risk management : stop ATR."
                    ),
                    "style": "Retournement filtre",
                    "symbol": "{symbol}",
                    "timeframe": "{timeframe}",
                    "used_indicators": ["rsi", "ema", "atr"],
                    "entry_logic": "excès puis retour sur EMA",
                    "exit_logic": "invalidation du rebond",
                    "risk_management": "stop ATR",
                    "hypothesis": "les excès se résorbent mieux avec filtre directionnel",
                }
            )
        )
        objective = generate_llm_objective_from_seed(
            llm,
            seed_objective=(
                "Strategie de Mean Reversion sur {symbol} {timeframe}. "
                "Indicateurs : RSI + EMA + ATR."
            ),
            symbol=None,
            timeframe=None,
            available_indicators=["ema", "rsi", "atr"],
        )
        assert objective.startswith("[Retournement filtre]")
        assert "{symbol}" in objective
        assert "{timeframe}" in objective

    def test_generate_llm_objective_canonicalizes_indicator_aliases(self):
        llm = _DummyLLMClient(
            (
                "Breakout sur BTCUSDC 1h. "
                "Indicateurs : PIVOT + KLT + BULL_SCORE + ATR. "
                "Entrées : cassure confirmée. Sorties : invalidation."
            )
        )
        objective = generate_llm_objective(
            llm,
            symbol=["BTCUSDC"],
            timeframe=["1h"],
            available_indicators=["pivot_points", "keltner", "directional_bias", "atr", "rsi"],
        )
        lower = objective.lower()
        assert "pivot_points" in lower
        assert "keltner" in lower
        assert "directional_bias" in lower
        assert " bull_score " not in f" {lower} "
        assert " klt " not in f" {lower} "


# ─── Tests session ─────────────────────────────────────────────────────────

class TestSession:
    """Tests de gestion de session."""

    def test_create_session_id(self):
        sid = StrategyBuilder.create_session_id("Trend BTC 30m Bollinger")
        assert "trend_btc_30m_bollinger" in sid
        # Contient un timestamp
        assert "_" in sid
        parts = sid.split("_")
        assert len(parts) >= 3

    def test_get_session_dir(self):
        sdir = StrategyBuilder.get_session_dir("test_session_123")
        assert sdir == SANDBOX_ROOT / "test_session_123"

    def test_builder_session_defaults(self):
        session = BuilderSession(
            session_id="test",
            objective="Trend following",
            session_dir=Path("/tmp/test"),
        )
        assert session.status == "running"
        assert session.best_sharpe == float("-inf")
        assert session.iterations == []

    def test_builder_iteration_defaults(self):
        it = BuilderIteration(iteration=1)
        assert it.hypothesis == ""
        assert it.error is None
        assert it.decision == ""


class TestObjectiveSanitizer:
    """Tests du nettoyage d'objectif Builder."""

    def test_preserve_clean_objective(self):
        objective = (
            "Scalp de continuation sur DOGEUSDC 5m. "
            "Indicateurs: EMA + RSI + Bollinger. "
            "Entrées pullback EMA21. Sorties ATR."
        )
        assert sanitize_objective_text(objective) == objective

    def test_strip_orphan_think_tags(self):
        raw = "</think> Breakout propre sur BTCUSDC 1h. <think>"
        cleaned = sanitize_objective_text(raw)
        assert cleaned == "Breakout propre sur BTCUSDC 1h."

    def test_strip_prompt_instruction_leakage_and_keep_objective_core(self):
        raw = (
            "Évite la redondance et la formulation trop technique. "
            "Exemple de format correct : [Style] sur EOSUSDC 15m. "
            "Indicateurs : AMPLITUDE_HUNTER + CHAIKIN_OSCILLATOR + DIRECTIONAL_BIAS + ATR. "
            "Entrées : amplitude_hunter > 0.5. Sorties : invalidation. "
            "Risk management : stop ATR."
        )
        cleaned = sanitize_objective_text(raw)
        assert cleaned.startswith("[Style] sur EOSUSDC 15m.")
        assert "Évite la redondance" not in cleaned
        assert "Exemple de format correct" not in cleaned

    def test_generate_llm_objective_falls_back_when_prompt_leakage_is_pure_meta(self):
        llm = _DummyLLMClient(
            "Tu dois inclure au least 3 indicateurs et au moins 1 filtre de regime. "
            "Okay, let's dive into this. First, I need to figure out the trading strategy objective."
        )
        objective = generate_llm_objective(
            llm,
            symbol=["BTCUSDC"],
            timeframe=["1h"],
            available_indicators=["ema", "rsi", "atr"],
        )
        assert objective.startswith("Stratégie de ")
        assert "Okay, let's dive" not in objective
        assert "Tu dois inclure" not in objective

    def test_extract_objective_from_contaminated_logs(self):
        raw = textwrap.dedent("""\
            19:24:49 | INFO | agents.ollama_manager | démarrage
            19:25:00 | INFO | backtest.agents.strategy_builder | strategy_builder_start session=abc objective='19:24:49 | INFO | noise
            19:25:00 | INFO | backtest.agents.strategy_builder | strategy_builder_start session=prev objective='[Scalp de continuation / micro-retournement] sur [crypto liquide] [5m ou 15m].
            Indicateurs : [EMA 9/21/50] + [RSI 14] + [Bandes de Bollinger 20,2].' indicators=31
            Traceback (most recent call last):
              File "D:\\backtest_core_v2\\agents\\strategy_builder.py", line 1
            ' indicators=31
        """)
        cleaned = sanitize_objective_text(raw)
        assert cleaned.startswith("[Scalp de continuation / micro-retournement]")
        assert "strategy_builder_start" not in cleaned
        assert "| INFO |" not in cleaned

    def test_drop_pipe_warning_and_traceback_blob(self):
        raw = textwrap.dedent("""\
            | WARNING | data.loader | Plus gros gap : 2019-05-15 02:30:00+00:00 → 2019-05-15 13:00:00+00:00 (20 barres)
            ────────────────────────── Traceback (most recent call last) ───────────────────────────
            C:\\Program Files\\Python312\\Lib\\site-packages\\streamlit\\runtime\\scriptrunner\\exec_code.py
            StreamlitAPIException: st.session_state.builder_objective_input cannot be modified
        """)
        cleaned = sanitize_objective_text(raw)
        assert cleaned == ""


class TestSessionRecovery:
    def test_select_session_recovery_anchor_prefers_best_iteration(self):
        session = BuilderSession(
            session_id="recovery_anchor",
            objective="test",
            session_dir=Path("/tmp/recovery_anchor"),
        )
        stable_best = BuilderIteration(
            iteration=1,
            backtest_result=SimpleNamespace(metrics={"sharpe_ratio": 1.2}),
        )
        stable_fallback = BuilderIteration(
            iteration=2,
            backtest_result=SimpleNamespace(metrics={"sharpe_ratio": 0.4}),
            is_fallback=True,
        )
        broken = BuilderIteration(iteration=3, error="boom")
        session.iterations = [stable_best, stable_fallback, broken]
        session.best_iteration = stable_best

        anchor, source = _select_session_recovery_anchor(session, broken)

        assert anchor is stable_best
        assert source == "best_iteration"

    def test_attempt_session_auto_reset_records_recovery_event(self, tmp_path):
        builder = StrategyBuilder.__new__(StrategyBuilder)
        checkpoint_calls: list[int] = []

        session = BuilderSession(
            session_id="recovery_reset",
            objective="test",
            session_dir=tmp_path / "recovery_reset",
        )
        stable_best = BuilderIteration(
            iteration=1,
            backtest_result=SimpleNamespace(metrics={"sharpe_ratio": 1.1}),
        )
        session.iterations = [stable_best]
        session.best_iteration = stable_best

        with unittest.mock.patch(
            "agents.builder_session_io.save_session_summary",
            side_effect=lambda s: checkpoint_calls.append(s.auto_reset_count),
        ):
            ok, anchor, consecutive_failures, fallback_count, event = (
                builder._attempt_session_auto_reset(
                    session,
                    iteration_num=3,
                    trigger="consecutive_failures",
                    reason="3 erreurs",
                    last_iteration=None,
                    consecutive_failures=3,
                    fallback_count=1,
                )
            )

        assert ok is True
        assert anchor is stable_best
        assert consecutive_failures == 0
        assert fallback_count == 0
        assert event["anchor_source"] == "best_iteration"
        assert session.auto_reset_count == 1
        assert session.recovery_events[0]["trigger"] == "consecutive_failures"
        assert checkpoint_calls == [1]


class TestBuilderRobustnessGate:
    """Tests des garde-fous robustesse pour acceptance/ranking."""

    def test_ranking_penalizes_ruined_metrics(self):
        metrics = {
            "sharpe_ratio": 1.8,
            "total_return_pct": -35000.0,
            "max_drawdown_pct": -100.0,
            "total_trades": 1200,
        }
        assert _ranking_sharpe(metrics) <= -90.0

    def test_ranking_penalizes_no_trades(self):
        metrics = {
            "sharpe_ratio": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "total_trades": 0,
        }
        assert _ranking_sharpe(metrics) <= -5.0

    def test_accept_candidate_requires_robustness(self):
        metrics = {
            "sharpe_ratio": 1.2,
            "total_return_pct": 10.0,
            "max_drawdown_pct": -30.0,
            "total_trades": 40,
        }
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is True
        assert reason == "ok"

    def test_accept_candidate_rejects_ruined(self):
        metrics = {
            "sharpe_ratio": 1.5,
            "total_return_pct": -200.0,
            "max_drawdown_pct": -99.0,
            "total_trades": 60,
        }
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is False
        assert reason == "ruined_metrics"

    def test_policy_change_type_overrides_to_logic_on_ruined_no_trades_cycle(self):
        session = BuilderSession(
            session_id="test",
            objective="test",
            session_dir=Path("/tmp/test_policy_logic"),
        )
        it1 = BuilderIteration(
            iteration=1,
            diagnostic_category="ruined",
            diagnostic_detail={"severity": "critical"},
        )
        it2 = BuilderIteration(
            iteration=2,
            diagnostic_category="no_trades",
            diagnostic_detail={"severity": "critical"},
        )
        session.iterations = [it1, it2]

        override = _policy_change_type_override(session=session, last_iteration=it2)
        assert override == "logic"

    def test_policy_change_type_overrides_to_params_near_target(self):
        session = BuilderSession(
            session_id="test",
            objective="test",
            session_dir=Path("/tmp/test_policy_params"),
        )
        it1 = BuilderIteration(
            iteration=1,
            diagnostic_category="approaching_target",
            diagnostic_detail={"severity": "info"},
        )
        session.iterations = [it1]

        override = _policy_change_type_override(session=session, last_iteration=it1)
        assert override == "params"


class TestDeterministicFallbackCode:
    """Vérifie le fallback de code déterministe en dernier recours."""

    def test_deterministic_fallback_is_valid_python(self):
        proposal = {
            "strategy_name": "Fallback Test",
            "used_indicators": ["rsi", "bollinger", "adx"],
            "default_params": {"rsi_period": 14, "stop_atr_mult": 1.5},
        }
        code = _build_deterministic_fallback_code(proposal)
        is_valid, msg = validate_generated_code(code)
        assert is_valid, msg

    def test_deterministic_fallback_conservative_logic(self):
        proposal = {"strategy_name": "Fallback Test", "used_indicators": ["rsi"]}
        code = _build_deterministic_fallback_code(proposal)
        assert "rsi_oversold" in code
        assert "rsi_overbought" in code
        assert "bollinger" in code

    def test_deterministic_fallback_breakout_variant_for_donchian_adx(self):
        proposal = {
            "strategy_name": "Fallback Breakout",
            "used_indicators": ["donchian", "adx", "atr"],
        }
        code = _build_deterministic_fallback_code(proposal)
        assert "dc_upper" in code
        assert "dc_lower" in code
        assert "adx_threshold" in code


def test_deterministic_proposal_fallback_prioritizes_explicit_objective_indicators():
    fallback = strategy_builder_module._build_deterministic_proposal_fallback(
        objective="Breakout sur ADAUSDC 1w. Indicateurs : DONCHIAN + PSAR + ATR.",
        available_indicators=["donchian", "psar", "atr", "rsi", "bollinger", "adx"],
    )

    assert fallback["used_indicators"] == ["donchian", "psar", "atr"]
    assert fallback["indicator_override_reason"] == ""


def test_candidate_executor_falls_back_when_code_uses_indicator_outside_proposal(
    monkeypatch,
    tmp_path,
    sample_ohlcv,
):
    builder = StrategyBuilder(llm_client=SimpleNamespace())
    session = BuilderSession(
        session_id="candidate_indicator_contract",
        objective="Breakout avec RSI uniquement",
        session_dir=tmp_path / "candidate_indicator_contract",
    )
    context = builder_candidate_executor_module.CandidateExecutionContext(
        session=session,
        proposal={
            "strategy_name": "indicator_contract",
            "used_indicators": ["rsi"],
            "default_params": {"warmup": 5},
            "parameter_specs": {},
        },
        proposal_feedback={},
        last_iteration=None,
        iteration_num=1,
        data=sample_ohlcv,
        initial_capital=10000.0,
        fallback_count=0,
    )
    executor = builder_candidate_executor_module.BuilderCandidateExecutorV2(
        builder,
        context,
    )

    monkeypatch.setattr(
        builder_candidate_executor_module,
        "_repair_code",
        lambda code, req_inds, enable_indicator_binding: code,
    )
    monkeypatch.setattr(
        builder_candidate_executor_module,
        "validate_generated_code",
        lambda code: (True, ""),
    )
    monkeypatch.setattr(
        builder,
        "_retry_code_simple",
        lambda proposal: (
            "```python\n"
            "adx = np.nan_to_num(indicators['adx']['adx'])\n"
            "signals[:] = (adx > 20).astype(float)\n"
            "```"
        ),
    )
    monkeypatch.setattr(executor, "_next_fallback_code", lambda: "fallback_code")

    proposal = {
        "strategy_name": "indicator_contract",
        "used_indicators": ["rsi"],
        "default_params": {"warmup": 5},
        "parameter_specs": {},
    }
    drifting_code = _build_deterministic_strategy_code(
        proposal,
        "adx = np.nan_to_num(indicators['adx']['adx'])\n"
        "signals[:] = (adx > 20).astype(float)\n",
    )

    code = executor._validate_candidate_code(drifting_code)

    assert code == "fallback_code"
    assert executor.code_feedback["fallback_deterministic_used"] is True
    assert executor.code_feedback["indicator_contract_status"] == "retry"
    assert executor.code_feedback["indicator_contract_violation"]["unexpected"] == ["adx"]
    assert executor.code_feedback["indicator_contract_retry_violation"]["unexpected"] == ["adx"]


class TestGracefulInterpreterShutdown:
    def test_interpreter_shutdown_runtime_error_is_detected(self):
        exc = RuntimeError("cannot schedule new futures after interpreter shutdown")
        assert _is_interpreter_shutdown_runtime_error(exc) is True

    def test_chat_llm_requalifies_interpreter_shutdown_as_keyboard_interrupt(self, monkeypatch):
        builder = StrategyBuilder.__new__(StrategyBuilder)
        builder.stream_callback = None
        builder._active_thought_stream = None
        builder.phase_llm_clients = {}
        builder.llm = SimpleNamespace(config=SimpleNamespace(ollama_host=None))
        builder.llm_topology_config = SimpleNamespace(
            resolve_builder_phase_route=lambda phase, fallback_host=None: SimpleNamespace(ollama_host=None)
        )

        class _BrokenPool:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn):
                raise RuntimeError("cannot schedule new futures after interpreter shutdown")

            def shutdown(self, wait=True):  # noqa: ARG002
                pass

        monkeypatch.setattr(strategy_builder_module, "_new_streamlit_aware_thread_pool", lambda max_workers=1: _BrokenPool())

        with pytest.raises(KeyboardInterrupt):
            builder._chat_llm(
                messages=[LLMMessage(role="user", content="ping")],
                phase="code",
            )


# ─── Tests chargement dynamique ──────────────────────────────────────────

class TestDynamicLoad:
    """Tests du chargement dynamique de stratégie."""

    def test_save_and_load(self, valid_strategy_code, tmp_path):
        """Vérifie que le code valide peut être chargé dynamiquement."""
        builder = StrategyBuilder.__new__(StrategyBuilder)
        builder.available_indicators = ["rsi", "atr"]

        session = BuilderSession(
            session_id="test_dynamic",
            objective="Test",
            session_dir=tmp_path / "test_dynamic",
        )
        session.session_dir.mkdir(parents=True, exist_ok=True)

        cls = builder._save_and_load(session, valid_strategy_code, 1)
        assert cls.__name__ == GENERATED_CLASS_NAME

        # Instancier et vérifier les propriétés
        instance = cls()
        assert "rsi" in instance.required_indicators
        assert "rsi_period" in instance.default_params

    def test_save_creates_versioned_copy(self, valid_strategy_code, tmp_path):
        builder = StrategyBuilder.__new__(StrategyBuilder)
        builder.available_indicators = ["rsi", "atr"]

        session = BuilderSession(
            session_id="test_versioned",
            objective="Test",
            session_dir=tmp_path / "test_versioned",
        )
        session.session_dir.mkdir(parents=True, exist_ok=True)

        builder._save_and_load(session, valid_strategy_code, 3)

        assert (session.session_dir / "strategy.py").exists()
        assert (session.session_dir / "strategy_v3.py").exists()


# ─── Tests indicateurs disponibles ───────────────────────────────────────

class TestIndicators:
    """Vérifie que le builder voit bien le registry."""

    def test_available_indicators_not_empty(self):
        from indicators.registry import list_indicators
        indicators = list_indicators()
        assert len(indicators) > 10
        assert "bollinger" in indicators
        assert "atr" in indicators
        assert "rsi" in indicators
        assert "ema" in indicators

    def test_builder_gets_indicators(self):
        # On ne peut pas instancier le builder sans LLM, mais on peut
        # vérifier la liste statiquement
        from indicators.registry import list_indicators
        assert "macd" in list_indicators()
        assert "supertrend" in list_indicators()
        assert "fva" in list_indicators()
        assert "fvg" in list_indicators()
        assert "swing" in list_indicators()
        assert "smart_legs" in list_indicators()
        assert "directional_bias" in list_indicators()
        assert "markov_switching" in list_indicators()

    @pytest.mark.parametrize(
        ("name", "params", "result_type"),
        [
            ("wma", {"period": 14}, "array"),
            ("hma", {"period": 20}, "array"),
            ("tma", {"period": 20}, "array"),
            ("cmo", {"period": 14}, "array"),
            ("tsi", {"long_period": 25, "short_period": 13}, "array"),
            ("kst", {}, "array"),
            ("ultimate_oscillator", {}, "array"),
            ("fisher_transform", {"period": 10}, "dict"),
            ("kvo", {}, "dict"),
            ("cmf", {"period": 20}, "array"),
            ("chaikin_oscillator", {}, "array"),
            ("eom", {"period": 14}, "array"),
            ("elder_ray", {"period": 13}, "dict"),
            ("force_index", {"period": 13}, "array"),
            ("dpo", {"period": 20}, "array"),
            ("coppock_curve", {}, "array"),
            ("mass_index", {}, "array"),
            ("fva", {}, "array"),
            ("fvg", {}, "dict"),
            ("swing", {}, "dict"),
            ("smart_legs", {}, "dict"),
            ("directional_bias", {}, "dict"),
            ("amplitude_hunter", {"period": 20}, "dict"),
            ("markov_switching", {}, "dict"),
        ],
    )
    def test_new_registry_indicators_calculate(self, sample_ohlcv, name, params, result_type):
        from indicators.registry import calculate_indicator, list_indicators

        assert name in list_indicators()

        result = calculate_indicator(name, sample_ohlcv, params)

        if result_type == "dict":
            assert isinstance(result, dict)
            assert result
            for values in result.values():
                assert len(np.asarray(values)) == len(sample_ohlcv)
            return

        assert isinstance(result, np.ndarray)
        assert len(result) == len(sample_ohlcv)


# ─── Tests templates ──────────────────────────────────────────────────────

class TestTemplates:
    """Vérifie que les templates Jinja2 sont accessibles et rendables."""

    def test_rank_indicator_selection_is_deterministic_for_session(self):
        ordered_a = rank_indicator_selection(
            ["rsi", "donchian", "adx", "bollinger", "atr"],
            objective="Breakout trend following on BTC",
            diagnostic={"category": "poor_performance", "summary": "Breakout logic still weak"},
            previous_indicators=["rsi", "atr"],
            session_seed="session-123",
            prefer_diversity=True,
        )
        ordered_b = rank_indicator_selection(
            ["rsi", "donchian", "adx", "bollinger", "atr"],
            objective="Breakout trend following on BTC",
            diagnostic={"category": "poor_performance", "summary": "Breakout logic still weak"},
            previous_indicators=["rsi", "atr"],
            session_seed="session-123",
            prefer_diversity=True,
        )

        assert ordered_a == ordered_b

    def test_rank_indicator_selection_prefers_relevant_indicators(self):
        ordered = rank_indicator_selection(
            ["rsi", "donchian", "adx", "bollinger", "atr"],
            objective="Build a breakout trend-following strategy with volatility filter",
            diagnostic={"category": "no_trades", "summary": "Breakout setup needs clearer trend confirmation"},
            previous_indicators=["rsi", "atr"],
            session_seed="session-breakout",
            prefer_diversity=True,
        )

        assert ordered.index("donchian") < ordered.index("rsi")
        assert ordered.index("adx") < ordered.index("rsi")

    def test_rank_indicator_selection_keeps_all_indicators(self):
        available = ["rsi", "donchian", "adx", "bollinger", "atr", "markov_switching"]
        ordered = rank_indicator_selection(
            available,
            objective="Range reversion with volatility filter",
            diagnostic={"category": "poor_performance", "summary": "Previous mix was noisy"},
            previous_indicators=["rsi", "atr"],
            session_seed="session-all-indicators",
            prefer_diversity=True,
        )

        assert set(ordered) == set(available)
        assert len(ordered) == len(available)

    def test_rank_indicator_selection_does_not_bury_relevant_previous_indicator(self):
        ordered = rank_indicator_selection(
            ["rsi", "donchian", "adx", "bollinger", "atr"],
            objective="Build a breakout trend-following strategy with volatility filter",
            diagnostic={"category": "poor_performance", "summary": "Need stronger breakout confirmation"},
            previous_indicators=["donchian", "atr"],
            session_seed="session-relevant-previous",
            prefer_diversity=True,
        )

        assert ordered.index("donchian") < ordered.index("rsi")

    def test_rank_indicator_selection_demotes_previous_indicator_when_diversity_is_requested(self):
        ordered_stable = rank_indicator_selection(
            ["rsi", "mfi", "roc", "atr"],
            objective="",
            diagnostic={},
            previous_indicators=["rsi"],
            session_seed="seed-1",
            prefer_diversity=False,
        )
        ordered_diverse = rank_indicator_selection(
            ["rsi", "mfi", "roc", "atr"],
            objective="",
            diagnostic={},
            previous_indicators=["rsi"],
            session_seed="seed-1",
            prefer_diversity=True,
        )

        assert ordered_diverse.index("rsi") > ordered_stable.index("rsi")
        assert ordered_diverse != ordered_stable

    def test_indicator_selection_guide_expands_abbreviations(self):
        guide = build_indicator_selection_guide(["rsi", "macd", "markov_switching"])

        assert any("Relative Strength Index" in line for line in guide)
        assert any("Moving Average Convergence Divergence" in line for line in guide)
        assert any("probabilistic regime detector" in line.lower() for line in guide)
        assert any('indicators["rsi"]' in line for line in guide)
        assert any('indicators["macd"]' in line for line in guide)

    def test_indicator_builder_access_example_handles_dict_indicator(self):
        example = get_indicator_builder_access_example("bollinger")

        assert 'indicators["bollinger"]' in example
        assert 'np.nan_to_num' in example
        assert 'upper' in example

    def test_indicator_builder_access_example_handles_amplitude_hunter_dict(self):
        example = get_indicator_builder_access_example("amplitude_hunter")
        alias_map = get_indicator_builder_stable_alias_map("amplitude_hunter")

        assert 'indicators["amplitude_hunter"]' in example
        assert 'range_pct' in example
        assert 'score' in example
        assert alias_map["score"] == "amplitude_hunter_score"

    def test_indicator_reference_stores_builder_access_examples(self):
        assert 'builder_access' in INDICATOR_SELECTION_REFERENCE["rsi"]
        assert 'builder_access' in INDICATOR_SELECTION_REFERENCE["bollinger"]
        assert 'indicators["rsi"]' in INDICATOR_SELECTION_REFERENCE["rsi"]["builder_access"]
        assert 'indicators["bollinger"]' in INDICATOR_SELECTION_REFERENCE["bollinger"]["builder_access"]

    def test_proposal_template_renders(self):
        from utils.template import render_prompt
        context = {
            "objective": "Trend following BTC",
            "available_indicators": ["rsi", "bollinger", "atr", "markov_switching", "directional_bias"],
            "available_indicator_guide": build_indicator_selection_guide(
                ["rsi", "bollinger", "atr", "markov_switching", "directional_bias"]
            ),
            "iteration": 1,
            "max_iterations": 5,
        }
        result = render_prompt("strategy_builder_proposal.jinja2", context)
        assert "Trend following BTC" in result
        assert "rsi" in result
        assert "ITERATION 1" in result
        assert "limited parameter sweep" in result
        assert "INDICATOR QUICK GUIDE" in result
        assert "session-stable and lightly re-ranked" in result
        assert "Relative Strength Index" in result
        assert 'indicators["rsi"]' in result
        assert "REGIME FILTER GUIDANCE" in result
        assert "markov_switching" in result
        assert "directional_bias" in result
        assert "1 to 5 indicators" in result

    def test_proposal_template_locks_explicit_objective_indicators_and_drops_canonical_example(self):
        from utils.template import render_prompt

        context = {
            "objective": "Breakout ADAUSDC avec DONCHIAN + PSAR + ATR",
            "available_indicators": ["donchian", "psar", "atr", "rsi", "bollinger", "adx"],
            "available_indicator_guide": build_indicator_selection_guide(
                ["donchian", "psar", "atr", "rsi", "bollinger", "adx"]
            ),
            "objective_indicators": ["donchian", "psar", "atr"],
            "indicator_lock_mode": "semi_open",
            "iteration": 1,
            "max_iterations": 6,
        }

        result = render_prompt("strategy_builder_proposal.jinja2", context)

        assert "OBJECTIVE INDICATOR CONTRACT" in result
        assert "donchian, psar, atr" in result
        assert '"used_indicators": ["rsi", "bollinger", "atr"]' not in result
        assert '"used_indicators": ["donchian", "psar", "atr"]' in result
        assert "indicator_override_reason" in result

    def test_proposal_template_explicitly_allows_indicator_add_remove_replace_on_stagnation(self):
        from utils.template import render_prompt

        context = {
            "objective": "Breakout ETH",
            "available_indicators": ["rsi", "bollinger", "atr", "adx"],
            "available_indicator_guide": build_indicator_selection_guide(
                ["rsi", "bollinger", "atr", "adx"]
            ),
            "iteration": 4,
            "max_iterations": 10,
            "diagnostic": {
                "category": "poor_performance",
                "severity": "high",
                "change_type": "logic",
                "summary": "Signals remain noisy and the previous setup stagnated.",
            },
            "previous_indicators": ["rsi", "atr"],
            "should_consider_indicator_expansion": True,
        }

        result = render_prompt("strategy_builder_proposal.jinja2", context)

        assert "remove one noisy indicator" in result
        assert "replace one indicator" in result
        assert "add one new indicator" in result
        assert "small but real change in the indicator set" in result

    def test_proposal_template_renders_branch_directive(self):
        from utils.template import render_prompt

        context = {
            "objective": "Breakout ETH",
            "available_indicators": ["rsi", "bollinger", "atr"],
            "available_indicator_guide": build_indicator_selection_guide(
                ["rsi", "bollinger", "atr"]
            ),
            "iteration": 5,
            "max_iterations": 10,
            "branch_directive": "STAGNATION BRANCH: ADD_ONE. Add exactly one new indicator.",
        }

        result = render_prompt("strategy_builder_proposal.jinja2", context)

        assert "BRANCH DIRECTIVE" in result
        assert "STAGNATION BRANCH: ADD_ONE" in result

    def test_should_enable_stagnation_branching_requires_identical_metrics(self):
        last_iteration = BuilderIteration(iteration=1)
        last_iteration.phase_feedback = {
            "stagnation": {"identical_metrics": True},
            "diagnostic": {"category": "needs_work"},
        }

        assert _should_enable_stagnation_branching(last_iteration) is True

        last_iteration.phase_feedback = {
            "stagnation": {"identical_metrics": False},
            "diagnostic": {"category": "needs_work"},
        }

        assert _should_enable_stagnation_branching(last_iteration) is False

    def test_select_best_branch_candidate_prefers_non_fallback_and_additive_branch_on_tie(self):
        keep_result = {
            "branch_label": "keep",
            "bt_result": SimpleNamespace(metrics={"sharpe_ratio": 1.2}),
            "rank_score": 10.0,
            "is_fallback": False,
        }
        add_result = {
            "branch_label": "add_one",
            "bt_result": SimpleNamespace(metrics={"sharpe_ratio": 1.2}),
            "rank_score": 10.0,
            "is_fallback": False,
        }

        selected = _select_best_branch_candidate([keep_result, add_result])

        assert selected["branch_label"] == "add_one"

    def test_select_best_branch_candidate_uses_raw_metrics_before_rank_score(self):
        keep_result = {
            "branch_label": "keep",
            "bt_result": SimpleNamespace(
                metrics={
                    "sharpe_ratio": 0.8,
                    "total_return_pct": 4.0,
                    "max_drawdown_pct": -12.0,
                    "profit_factor": 1.10,
                    "total_trades": 30,
                    "win_rate_pct": 42.0,
                }
            ),
            "metrics": {
                "sharpe_ratio": 0.8,
                "total_return_pct": 4.0,
                "max_drawdown_pct": -12.0,
                "profit_factor": 1.10,
                "total_trades": 30,
                "win_rate_pct": 42.0,
            },
            "rank_score": 50.0,
            "target_sharpe": 1.0,
            "is_fallback": False,
        }
        add_result = {
            "branch_label": "add_one",
            "bt_result": SimpleNamespace(
                metrics={
                    "sharpe_ratio": 1.3,
                    "total_return_pct": 12.0,
                    "max_drawdown_pct": -8.0,
                    "profit_factor": 1.30,
                    "total_trades": 44,
                    "win_rate_pct": 47.0,
                }
            ),
            "metrics": {
                "sharpe_ratio": 1.3,
                "total_return_pct": 12.0,
                "max_drawdown_pct": -8.0,
                "profit_factor": 1.30,
                "total_trades": 44,
                "win_rate_pct": 47.0,
            },
            "rank_score": -20.0,
            "target_sharpe": 1.0,
            "is_fallback": False,
        }

        selected = _select_best_branch_candidate([keep_result, add_result])

        assert selected["branch_label"] == "add_one"

    def test_should_trip_logic_stagnation_circuit_after_two_identical_logic_iterations(self):
        last_iteration = BuilderIteration(iteration=4, change_type="logic")
        last_iteration.phase_feedback = {"stagnation": {"identical_metrics": True}}

        iteration = BuilderIteration(iteration=5, change_type="both")
        iteration.phase_feedback = {"stagnation": {"identical_metrics": True}}

        assert _should_trip_logic_stagnation_circuit(last_iteration, iteration) is True

        iteration.change_type = "params"
        assert _should_trip_logic_stagnation_circuit(last_iteration, iteration) is False

    def test_code_template_renders(self):
        from utils.template import render_prompt
        context = {
            "objective": "Mean reversion ETH",
            "proposal": {
                "strategy_name": "test_strat",
                "used_indicators": ["rsi", "bollinger"],
                "entry_long_logic": "RSI < 30",
                "entry_short_logic": "RSI > 70",
                "exit_logic": "RSI crosses 50",
                "risk_management": "ATR stop",
                "default_params": {"rsi_period": 14},
            },
            "available_indicators": ["rsi", "bollinger", "atr"],
            "available_indicator_guide": build_indicator_selection_guide(
                ["rsi", "bollinger", "atr"]
            ),
            "class_name": GENERATED_CLASS_NAME,
        }
        result = render_prompt("strategy_builder_code.jinja2", context)
        assert GENERATED_CLASS_NAME in result
        assert "Mean reversion ETH" in result
        assert "rsi, bollinger" in result
        assert "feed a limited Builder sweep" in result
        assert "INDICATOR QUICK GUIDE" in result
        assert "session-stable and lightly re-ranked" in result
        assert "Average True Range" in result
        assert 'indicators["bollinger"]' in result


class TestMarketRecommendationDiversity:
    def test_recommend_market_context_diversity_overrides_repeated_pair(self):
        llm = _DummyLLMClient(
            '{"symbol":"0GUSDC","timeframe":"1h","confidence":0.92,"reason":"objectif explicite"}',
        )
        result = recommend_market_context(
            llm,
            objective="Breakout Donchian sur 0GUSDC 1h",
            candidate_symbols=["0GUSDC", "BTCUSDC"],
            candidate_timeframes=["1h", "15m"],
            default_symbol="BTCUSDC",
            default_timeframe="15m",
            recent_markets=[("0GUSDC", "1h"), ("BTCUSDC", "1h"), ("0GUSDC", "15m")],
        )
        assert result["symbol"] == "BTCUSDC"
        assert result["timeframe"] == "15m"
        assert str(result["source"]).endswith("diversity_override")



    def test_recommend_market_context_rotates_when_all_pairs_recent(self):
        llm = _DummyLLMClient(
            '{"symbol":"0GUSDC","timeframe":"1h","confidence":0.90,"reason":"focus"}',
        )
        result = recommend_market_context(
            llm,
            objective="Breakout 0GUSDC 1h",
            candidate_symbols=["0GUSDC", "BTCUSDC"],
            candidate_timeframes=["1h"],
            default_symbol="0GUSDC",
            default_timeframe="1h",
            recent_markets=[("0GUSDC", "1h"), ("BTCUSDC", "1h")],
        )
        assert result["symbol"] == "BTCUSDC"
        assert result["timeframe"] == "1h"
        assert str(result["source"]).endswith("diversity_override")
class TestBuilderRobustnessProfitFactor:
    def test_accept_candidate_rejects_low_profit_factor(self):
        metrics = {
            "sharpe_ratio": 1.3,
            "total_return_pct": 12.0,
            "max_drawdown_pct": -18.0,
            "total_trades": 45,
            "profit_factor": 1.01,
        }
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is False
        assert reason == "profit_factor_too_low"

    def test_accept_candidate_allows_small_drawdown_excess_when_quality_high(self):
        metrics = {
            "sharpe_ratio": 1.55,
            "total_return_pct": 19.0,
            "max_drawdown_pct": 36.0,  # +1% au-dessus du seuil nominal
            "total_trades": 62,
            "profit_factor": 1.24,
            "win_rate_pct": 39.0,
        }
        score = compute_continuous_builder_score(metrics, target_sharpe=1.0)["score"]
        assert score > 45.0
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is True
        assert reason == "ok"

    def test_accept_candidate_ignores_low_continuous_score_when_hard_metrics_are_valid(self):
        metrics = {
            "sharpe_ratio": 1.0,
            "total_return_pct": 0.2,
            "max_drawdown_pct": 35.0,
            "total_trades": 20,
            "profit_factor": 1.05,
            "win_rate_pct": 20.0,
        }
        score = compute_continuous_builder_score(metrics, target_sharpe=1.0)["score"]
        assert score < 35.0
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is True
        assert reason == "ok"

    def test_accept_candidate_rejects_extreme_drawdown(self):
        metrics = {
            "sharpe_ratio": 1.8,
            "total_return_pct": 35.0,
            "max_drawdown_pct": 70.0,
            "total_trades": 88,
            "profit_factor": 1.3,
            "win_rate_pct": 41.0,
        }
        ok, reason = _is_accept_candidate(metrics, target_sharpe=1.0)
        assert ok is False
        assert reason == "drawdown_extreme"


class TestBuilderSummaryLeaderboard:
    def test_save_session_summary_writes_leaderboard_files(self):
        builder = StrategyBuilder.__new__(StrategyBuilder)
        session_dir = Path(".tmp") / f"summary_test_{uuid4().hex[:8]}"
        session = BuilderSession(
            session_id="summary_test",
            objective="Test leaderboard export",
            session_dir=session_dir,
            target_sharpe=1.0,
            symbol="ETHUSDC",
            timeframe="4h",
            n_bars=240,
            date_range_start="2026-01-01 00:00:00",
            date_range_end="2026-02-10 00:00:00",
            initial_capital=25000.0,
        )
        session.session_dir.mkdir(parents=True, exist_ok=True)

        bt_good = SimpleNamespace(
            metrics={
                "sharpe_ratio": 1.4,
                "total_pnl": 3750.0,
                "total_return_pct": 15.0,
                "max_drawdown_pct": 30.0,
                "profit_factor": 1.2,
                "win_rate_pct": 38.0,
                "total_trades": 55,
            },
            meta={"params": {"x": 1}},
        )
        bt_mid = SimpleNamespace(
            metrics={
                "sharpe_ratio": 0.9,
                "total_pnl": 1250.0,
                "total_return_pct": 5.0,
                "max_drawdown_pct": 26.0,
                "profit_factor": 1.08,
                "win_rate_pct": 34.0,
                "total_trades": 43,
            },
            meta={"params": {"x": 2}},
        )

        it1 = BuilderIteration(
            iteration=1,
            backtest_result=bt_mid,
            decision="continue",
            phase_feedback={
                "backtest": {
                    "runtime_error": "ValueError: test runtime",
                    "runtime_traceback_tail": "Traceback line 1\nTraceback line 2",
                }
            },
        )
        it2 = BuilderIteration(iteration=2, backtest_result=bt_good, decision="accept")
        session.iterations = [it1, it2]
        session.best_iteration = it2
        session.best_sharpe = 1.4
        session.best_score = compute_continuous_builder_score(
            bt_good.metrics,
            target_sharpe=1.0,
        )["score"]
        session.status = "success"
        session.builder_execution_mode = "expert_multi_role"
        session.orchestration_mode = "multi_llm"
        session.instrumentation_enabled = True
        session.instrumentation_summary = {
            "iterations": 2,
            "fallback_rate": 0.5,
            "repair_rate": 0.5,
            "blockers": [{"kind": "precheck", "count": 1}],
            "helpers": [{"kind": "runtime_fix", "count": 1}],
            "restriction_events": {"precheck": 1, "runtime_fix": 1},
        }
        session.ablation_config = {"code_repair": True, "precheck": False}
        session.pipeline_traces_path = "pipeline_traces.json"
        session.restriction_events = {"precheck": 1, "runtime_fix": 1}
        session.multi_llm_profile = "brain"
        session.multi_llm_role_overrides = {"builder_llm": ["qwen3:30b"]}
        session.multi_llm_assignments = [{"role": "builder_llm", "resolved_model": "qwen3:30b"}]
        session.auto_reset_count = 1
        session.recovery_events = [
            {
                "iteration": 2,
                "trigger": "consecutive_failures",
                "reason": "test",
            }
        ]

        try:
            builder._save_session_summary(session)

            summary_path = session.session_dir / "session_summary.json"
            csv_path = session.session_dir / "leaderboard_builder.csv"
            md_path = session.session_dir / "leaderboard_builder.md"

            assert summary_path.exists()
            assert csv_path.exists()
            assert md_path.exists()

            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            assert "leaderboard" in payload
            assert len(payload["leaderboard"]) == 2
            assert payload["leaderboard"][0]["iteration"] == 2
            assert payload["leaderboard"][0]["total_pnl"] == 3750.0
            assert payload["auto_reset_count"] == 1
            assert payload["recovery_events"][0]["trigger"] == "consecutive_failures"
            assert payload["symbol"] == "ETHUSDC"
            assert payload["timeframe"] == "4h"
            assert payload["n_bars"] == 240
            assert payload["date_range_start"] == "2026-01-01 00:00:00"
            assert payload["date_range_end"] == "2026-02-10 00:00:00"
            assert payload["initial_capital"] == 25000.0
            assert payload["last_runtime_error"] == "ValueError: test runtime"
            assert payload["last_runtime_error_iteration"] == 1
            assert payload["last_runtime_traceback_tail"] == "Traceback line 1\nTraceback line 2"
            assert payload["builder_execution_mode"] == "expert_multi_role"
            assert payload["orchestration_mode"] == "multi_llm"
            assert payload["instrumentation_enabled"] is True
            assert payload["instrumentation_summary"]["fallback_rate"] == 0.5
            assert payload["ablation_config"]["precheck"] is False
            assert payload["pipeline_traces_path"] == "pipeline_traces.json"
            assert payload["restriction_events"]["runtime_fix"] == 1
            assert payload["multi_llm_profile"] == "brain"
            assert payload["multi_llm_role_overrides"]["builder_llm"] == ["qwen3:30b"]
        finally:
            shutil.rmtree(session_dir, ignore_errors=True)

# ─── Tests refactor scoring souple ──────────────────────────────────────────



class TestRefactorCheckpoints:
    """Tests de validation du refactor checkpoints souples."""

    def test_positive_progress_gate_checkpoints_updated(self):
        """Vérifie que les checkpoints sont bien à {6: 1, 9: 2}."""
        from agents.strategy_builder import POSITIVE_PROGRESS_GATE_CHECKPOINTS
        assert POSITIVE_PROGRESS_GATE_CHECKPOINTS == {6: 1, 9: 2}

    def test_min_successful_iterations_updated(self):
        """Vérifie que MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP = 5."""
        from agents.strategy_builder import MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP
        assert MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP == 5

    def test_count_positive_iterations_with_fallback_quota(self):
        """Vérifie que les fallbacks positifs comptent avec quota."""
        from types import SimpleNamespace

        from agents.strategy_builder import (
            MAX_POSITIVE_FALLBACK_COUNT,
            BuilderIteration,
            _count_positive_iterations,
        )

        # Scénario : 2 fallbacks positifs + 1 LLM positif
        iterations = [
            BuilderIteration(
                iteration=1,
                is_fallback=True,
                backtest_result=SimpleNamespace(
                    metrics={"total_return_pct": 5.0, "total_trades": 25}
                ),
            ),
            BuilderIteration(
                iteration=2,
                is_fallback=True,
                backtest_result=SimpleNamespace(
                    metrics={"total_return_pct": 3.0, "total_trades": 22}
                ),
            ),
            BuilderIteration(
                iteration=3,
                is_fallback=False,
                backtest_result=SimpleNamespace(
                    metrics={"total_return_pct": 8.0, "total_trades": 30}
                ),
            ),
        ]

        count = _count_positive_iterations(iterations)
        # 1 fallback (quota max 1) + 1 LLM = 2 positifs
        assert count == 2
        assert MAX_POSITIVE_FALLBACK_COUNT == 1


def test_compute_session_generation_stats_returns_correct_rates():
    """compute_session_generation_stats retourne les bons compteurs et taux."""
    from agents.builder_state import BuilderSession, BuilderIteration, compute_session_generation_stats

    session = BuilderSession(session_id="gen-stats-test", objective="test", session_dir=Path("/tmp"))
    session.iterations = [
        BuilderIteration(iteration=1, is_fallback=False),
        BuilderIteration(iteration=2, is_fallback=True),
        BuilderIteration(iteration=3, is_fallback=False),
        BuilderIteration(iteration=4, is_fallback=False),
        BuilderIteration(iteration=5, is_fallback=True),
    ]
    stats = compute_session_generation_stats(session)
    assert stats["total"] == 5
    assert stats["canonical"] == 3
    assert stats["deterministic"] == 2
    assert abs(stats["canonical_rate"] - 0.6) < 1e-9


def test_compute_session_generation_stats_empty_session():
    """compute_session_generation_stats retourne 0 pour une session vide."""
    from agents.builder_state import BuilderSession, compute_session_generation_stats

    session = BuilderSession(session_id="empty-gen", objective="test", session_dir=Path("/tmp"))
    session.iterations = []
    stats = compute_session_generation_stats(session)
    assert stats["total"] == 0
    assert stats["canonical_rate"] == 0.0


def test_builder_session_has_model_name_field():
    """BuilderSession expose un champ model_name."""
    from agents.builder_state import BuilderSession

    session = BuilderSession(session_id="model-name-test", objective="test", session_dir=Path("/tmp"))
    assert session.model_name == ""
    session.model_name = "gemma4:26b"
    assert session.model_name == "gemma4:26b"

