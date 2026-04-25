from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from agents.autonomous_strategist import AutonomousStrategist, IterationDecision
from agents.backtest_executor import BacktestExecutor, BacktestRequest
from agents.base_agent import AgentContext
from agents.builder_objectives import generate_random_objective
from agents.critic import CriticAgent


def _sample_ohlcv() -> pd.DataFrame:
    n = 120
    close = np.linspace(100.0, 120.0, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
    )


def _metrics_payload() -> dict[str, float]:
    return {
        "sharpe_ratio": 1.0,
        "sortino_ratio": 1.1,
        "total_return": 0.10,
        "max_drawdown": -0.12,
        "win_rate": 0.55,
        "profit_factor": 1.25,
        "total_trades": 24,
    }


def test_generate_random_objective_handles_market_lists_without_nameerror() -> None:
    objective = generate_random_objective(
        symbol=["BTCUSDC", "ETHUSDC"],
        timeframe=["15m", "1h"],
        available_indicators=["ema", "macd", "bollinger", "rsi", "atr", "stochastic"],
    )

    assert any(symbol in objective for symbol in ("BTCUSDC", "ETHUSDC"))
    assert any(timeframe in objective for timeframe in ("15m", "1h"))


def test_autonomous_strategist_stops_on_partial_next_parameters() -> None:
    data = _sample_ohlcv()
    calls: list[dict[str, float]] = []

    def _backtest_fn(strategy_name: str, params: dict, df: pd.DataFrame) -> dict[str, float]:
        calls.append(dict(params))
        return _metrics_payload()

    executor = BacktestExecutor(
        backtest_fn=_backtest_fn,
        strategy_name="ema_cross",
        data=data,
    )
    strategist = AutonomousStrategist(SimpleNamespace(), unload_llm_during_backtest=False)
    strategist._get_llm_decision = lambda context, session: IterationDecision(
        action="continue",
        confidence=0.9,
        next_hypothesis="partial params",
        next_parameters={"fast": 12},
        reasoning="only one param proposed",
    )

    session = strategist.optimize(
        executor=executor,
        initial_params={"fast": 12, "slow": 26},
        param_bounds={"fast": (5, 20), "slow": (10, 50)},
        max_iterations=2,
    )

    assert session.final_status == "no_improvement"
    assert "Missing parameters" in session.final_reasoning
    assert len(calls) == 1


def test_autonomous_strategist_enforces_time_budget_when_iterations_unbounded() -> None:
    data = _sample_ohlcv()
    calls: list[dict[str, float]] = []

    def _backtest_fn(strategy_name: str, params: dict, df: pd.DataFrame) -> dict[str, float]:
        calls.append(dict(params))
        return _metrics_payload()

    executor = BacktestExecutor(
        backtest_fn=_backtest_fn,
        strategy_name="ema_cross",
        data=data,
    )
    strategist = AutonomousStrategist(SimpleNamespace(), unload_llm_during_backtest=False)

    def _unexpected_decision(*args, **kwargs):
        raise AssertionError("_get_llm_decision should not be called after timeout")

    strategist._get_llm_decision = _unexpected_decision

    session = strategist.optimize(
        executor=executor,
        initial_params={"fast": 12, "slow": 26},
        param_bounds={"fast": (5, 20), "slow": (10, 50)},
        max_iterations=0,
        max_time_seconds=1e-9,
    )

    assert session.final_status == "timeout"
    assert "Time budget exceeded" in session.final_reasoning
    assert len(calls) == 1


def test_gpu_unload_failure_falls_back_to_direct_backtest_execution() -> None:
    strategist = AutonomousStrategist(SimpleNamespace(), unload_llm_during_backtest=True)

    class _FailingManager:
        def unload(self, _context):
            raise RuntimeError("GPU unavailable")

        def reload(self, _state):
            raise AssertionError("reload should not be called when unload fails")

    strategist._gpu_manager = _FailingManager()

    sentinel = object()
    run_calls: list[BacktestRequest] = []

    class _Executor:
        def run(self, request: BacktestRequest):
            run_calls.append(request)
            return sentinel

    result = strategist._run_backtest_with_gpu_optimization(
        _Executor(),
        BacktestRequest(parameters={"fast": 12}),
    )

    assert result is sentinel
    assert len(run_calls) == 1


def test_critic_execute_fails_on_invalid_pydantic_payload() -> None:
    critic = CriticAgent(SimpleNamespace())
    critic._build_critique_prompt = lambda context: "prompt"

    class _Response:
        content = '{"overall_assessment":"bad"}'
        total_tokens = 12

        @staticmethod
        def parse_json():
            return {"overall_assessment": "bad"}

    critic._call_llm = lambda *args, **kwargs: _Response()

    result = critic.execute(
        AgentContext(
            strategy_name="ema_cross",
            strategist_proposals=[{"id": 1, "hypothesis": "test"}],
        ),
    )

    assert result.success is False
    assert result.errors
    assert "Structure critique invalide" in result.errors[0]
