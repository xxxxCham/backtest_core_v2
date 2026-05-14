"""Tests unitaires de agents.simple_builder.

Aucun appel Ollama reel : le LLMClient est mocke avec une reponse pre-ecrite.
Aucun lancement Streamlit : pipeline pur en memoire.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.llm_client import LLMClient, LLMConfig, LLMProvider, LLMResponse
from agents.simple_builder import (
    DEFAULT_ACCEPT_CRITERIA,
    DslCompileError,
    IndicatorNotFoundError,
    JsonValidationError,
    SimpleBuilder,
    _normalize_atom,
    check_indicators_against_registry,
    compile_strategy_from_proposal,
    decide,
    diagnose,
    validate_proposal_schema,
)
# Import side-effect: register all indicators
import indicators.registry as _registry  # noqa: F401


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def synthetic_ohlcv() -> pd.DataFrame:
    """Random-walk OHLCV de 800 barres, deterministe."""
    rng = np.random.default_rng(42)
    n = 800
    drift = rng.normal(loc=0.0005, scale=0.012, size=n)
    close = 100.0 * np.exp(np.cumsum(drift))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(1000, 5000, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    }, index=idx)


@pytest.fixture
def valid_proposal() -> dict[str, Any]:
    return {
        "strategy_name": "rsi_mean_reversion_test",
        "indicators": [
            {"alias": "rsi14", "name": "rsi", "params": {"period": 14}},
            {"alias": "ema50", "name": "ema", "params": {"period": 50}},
        ],
        "entry_long": ["all", [
            ["lt", "rsi14", 30],
            ["gt", "close", "ema50"],
        ]],
        "exit_long": ["any", [
            ["gt", "rsi14", 70],
        ]],
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    }


class _CannedLLM(LLMClient):
    """Faux LLM client : retourne une reponse JSON pre-ecrite."""

    def __init__(self, payloads: list[Any]):
        super().__init__(LLMConfig(provider=LLMProvider.OLLAMA, model="canned"))
        self._payloads = list(payloads)
        self._calls = 0

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        self._calls += 1
        if not self._payloads:
            raise AssertionError("CannedLLM exhausted")
        payload = self._payloads.pop(0)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(
            content=content,
            model="canned",
            provider=LLMProvider.OLLAMA,
        )

    def is_available(self) -> bool:
        return True


# =============================================================================
# validate_proposal_schema
# =============================================================================


def test_validate_proposal_accepts_minimal_valid(valid_proposal):
    assert validate_proposal_schema(valid_proposal) is valid_proposal


def test_validate_proposal_rejects_non_dict():
    with pytest.raises(JsonValidationError, match="non-dict"):
        validate_proposal_schema("not a dict")


def test_validate_proposal_rejects_missing_keys():
    with pytest.raises(JsonValidationError, match="cles requises manquantes"):
        validate_proposal_schema({"strategy_name": "x", "indicators": []})


def test_validate_proposal_rejects_unknown_keys(valid_proposal):
    p = dict(valid_proposal)
    p["unknown_field"] = 42
    with pytest.raises(JsonValidationError, match="cles inconnues"):
        validate_proposal_schema(p)


def test_validate_proposal_rejects_empty_indicators(valid_proposal):
    p = dict(valid_proposal)
    p["indicators"] = []
    with pytest.raises(JsonValidationError, match="indicators"):
        validate_proposal_schema(p)


def test_validate_proposal_rejects_duplicate_alias(valid_proposal):
    p = dict(valid_proposal)
    p["indicators"] = [
        {"alias": "x", "name": "rsi"},
        {"alias": "x", "name": "ema"},
    ]
    with pytest.raises(JsonValidationError, match="duplique"):
        validate_proposal_schema(p)


def test_validate_proposal_rejects_bad_stop_loss(valid_proposal):
    p = dict(valid_proposal)
    p["stop_loss_pct"] = 0.0
    with pytest.raises(JsonValidationError, match="stop_loss_pct"):
        validate_proposal_schema(p)


# =============================================================================
# check_indicators_against_registry
# =============================================================================


def test_check_indicators_accepts_known(valid_proposal):
    check_indicators_against_registry(valid_proposal)  # ne leve rien


def test_check_indicators_rejects_unknown(valid_proposal):
    p = dict(valid_proposal)
    p["indicators"] = [
        {"alias": "z", "name": "definitely_not_an_indicator", "params": {}},
    ]
    with pytest.raises(IndicatorNotFoundError, match="definitely_not_an_indicator"):
        check_indicators_against_registry(p)


# =============================================================================
# DSL compiler
# =============================================================================


def test_compile_strategy_builds_concrete(valid_proposal):
    strat = compile_strategy_from_proposal(valid_proposal)
    assert strat.name == "rsi_mean_reversion_test"
    assert "rsi" in strat.required_indicators
    assert "ema" in strat.required_indicators


def test_dsl_rejects_unknown_alias(valid_proposal, synthetic_ohlcv):
    p = dict(valid_proposal)
    p["entry_long"] = ["all", [["lt", "unknown_alias", 30]]]
    strat = compile_strategy_from_proposal(p)
    with pytest.raises(DslCompileError, match="alias inconnu"):
        strat.generate_signals(synthetic_ohlcv, indicators={}, params={})


def test_dsl_rejects_unknown_op(valid_proposal, synthetic_ohlcv):
    p = dict(valid_proposal)
    p["entry_long"] = ["xor", [["lt", "rsi14", 30]]]
    strat = compile_strategy_from_proposal(p)
    with pytest.raises(DslCompileError, match="operateur DSL inconnu"):
        strat.generate_signals(synthetic_ohlcv, indicators={}, params={})


def test_dsl_supports_crosses_above(synthetic_ohlcv):
    proposal = {
        "strategy_name": "crosses_test",
        "indicators": [
            {"alias": "fast", "name": "ema", "params": {"period": 10}},
            {"alias": "slow", "name": "ema", "params": {"period": 30}},
        ],
        "entry_long": ["all", [["crosses_above", "fast", "slow"]]],
        "exit_long": ["all", [["crosses_below", "fast", "slow"]]],
    }
    validate_proposal_schema(proposal)
    check_indicators_against_registry(proposal)
    strat = compile_strategy_from_proposal(proposal)
    signals = strat.generate_signals(synthetic_ohlcv, indicators={}, params={})
    # Avec ema diff. on doit avoir au moins quelques croisements
    assert int((signals == 1).sum()) >= 1
    assert int((signals == -1).sum()) >= 1


def test_dsl_signals_have_same_index(valid_proposal, synthetic_ohlcv):
    strat = compile_strategy_from_proposal(valid_proposal)
    signals = strat.generate_signals(synthetic_ohlcv, indicators={}, params={})
    assert list(signals.index) == list(synthetic_ohlcv.index)
    assert signals.dtype.kind in ("i", "u")


# =============================================================================
# diagnose / decide
# =============================================================================


def test_diagnose_passing_case():
    metrics = {
        "n_trades": 50, "total_return_pct": 12.0, "sharpe_ratio": 1.2,
        "max_drawdown_pct": 15.0, "profit_factor": 1.4,
    }
    diag = diagnose(metrics, DEFAULT_ACCEPT_CRITERIA)
    assert diag["passed"] is True
    assert diag["failed_checks"] == []


def test_diagnose_failing_case_lists_failures():
    metrics = {
        "n_trades": 5, "total_return_pct": 1.0, "sharpe_ratio": 0.1,
        "max_drawdown_pct": 50.0, "profit_factor": 0.9,
    }
    diag = diagnose(metrics, DEFAULT_ACCEPT_CRITERIA)
    assert diag["passed"] is False
    assert "min_trades" in diag["failed_checks"]
    assert "max_drawdown_pct" in diag["failed_checks"]
    assert "min_profit_factor" in diag["failed_checks"]


def test_decide_accepts_when_passed():
    diag = {"passed": True, "failed_checks": []}
    status, _ = decide(diag, iteration=1, max_iterations=5)
    assert status == "accepted"


def test_decide_stops_on_last_iteration_when_failed():
    diag = {"passed": False, "failed_checks": ["min_trades"]}
    status, _ = decide(diag, iteration=5, max_iterations=5)
    assert status == "stop"


def test_decide_rejects_mid_session():
    diag = {"passed": False, "failed_checks": ["min_trades"]}
    status, _ = decide(diag, iteration=2, max_iterations=5)
    assert status == "rejected"


# =============================================================================
# Pipeline complet
# =============================================================================


def test_full_pipeline_accept_or_stop_no_crash(
    valid_proposal, synthetic_ohlcv, tmp_path,
):
    """Le pipeline doit tourner end-to-end sans crash, peu importe le verdict."""
    llm = _CannedLLM([valid_proposal])
    builder = SimpleBuilder(
        llm_client=llm,
        max_iterations=1,
        sessions_dir=tmp_path,
        initial_capital=10000.0,
    )
    session = builder.build(
        objective="Test deterministe",
        data=synthetic_ohlcv,
        symbol="TEST",
        timeframe="1h",
    )
    assert session.session_id
    assert session.iterations, "au moins une iteration doit etre enregistree"
    assert session.final_status in {"accepted", "stopped", "exhausted"}
    # NDJSON ecrit
    files = list(tmp_path.glob("*.ndjson"))
    assert files, "fichier de log NDJSON attendu"
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert any('"event": "session_start"' in line for line in lines)
    assert any('"event": "session_end"' in line for line in lines)


def test_pipeline_handles_invalid_json_with_one_retry(
    valid_proposal, synthetic_ohlcv, tmp_path,
):
    """1ere reponse cassee, 2eme valide -> le retry contractuel sauve l'iter."""
    llm = _CannedLLM([
        "this is not json at all, just plain text",  # 1ere : invalide
        valid_proposal,                                # 2eme : valide
    ])
    builder = SimpleBuilder(
        llm_client=llm, max_iterations=1, sessions_dir=tmp_path,
        retry_on_invalid_json=1,
    )
    session = builder.build(
        objective="retry test", data=synthetic_ohlcv,
        symbol="TEST", timeframe="1h",
    )
    assert session.iterations
    # Le proposal recuere par retry doit etre celui valide
    assert session.iterations[0].phase_reached not in ("init", "propose(attempt=1)")


def test_pipeline_fails_explicitly_on_unknown_indicator(
    synthetic_ohlcv, tmp_path,
):
    """Si LLM produit un indicateur inconnu, l'iteration doit echouer typee, pas planter."""
    bad = {
        "strategy_name": "bad",
        "indicators": [{"alias": "x", "name": "definitely_unknown"}],
        "entry_long": ["all", [["gt", "close", 0]]],
        "exit_long": ["all", [["lt", "close", 1e9]]],
    }
    llm = _CannedLLM([bad])
    builder = SimpleBuilder(
        llm_client=llm, max_iterations=1, sessions_dir=tmp_path,
        retry_on_invalid_json=0,
    )
    session = builder.build(
        objective="bad test", data=synthetic_ohlcv,
        symbol="TEST", timeframe="1h",
    )
    assert session.iterations[0].status == "failed"
    assert session.iterations[0].error_code == "ERR_INDICATOR_UNKNOWN"


def test_pipeline_fails_explicitly_on_invalid_schema(synthetic_ohlcv, tmp_path):
    """Si le JSON manque des cles requises, echec type sans retry suffisant."""
    bad = {"strategy_name": "x"}  # incomplet
    llm = _CannedLLM([bad, bad])  # meme reponse au retry
    builder = SimpleBuilder(
        llm_client=llm, max_iterations=1, sessions_dir=tmp_path,
        retry_on_invalid_json=1,
    )
    session = builder.build(
        objective="schema test", data=synthetic_ohlcv,
        symbol="TEST", timeframe="1h",
    )
    assert session.iterations[0].status == "failed"
    assert session.iterations[0].error_code == "ERR_JSON_SCHEMA"


# =============================================================================
# _normalize_atom : tolérance aux formes LLM hors-spec
# =============================================================================


def _make_series_map(**kwargs: int) -> dict:
    """Cree un dict d'alias -> Series fictive (valeurs constantes)."""
    return {k: pd.Series([float(v)] * 10) for k, v in kwargs.items()}


def test_normalize_atom_passthrough_string():
    assert _normalize_atom("rsi14", series_by_alias=_make_series_map(rsi14=0)) == "rsi14"


def test_normalize_atom_passthrough_number():
    assert _normalize_atom(30, series_by_alias={}) == 30


def test_normalize_atom_list_alias_value_token():
    """['rsi14', 'value'] doit etre resolu en 'rsi14'."""
    aliases = _make_series_map(rsi14=0)
    result = _normalize_atom(["rsi14", "value"], series_by_alias=aliases)
    assert result == "rsi14"


def test_normalize_atom_list_alias_output_token():
    """['ema50', 'output'] doit etre resolu en 'ema50'."""
    aliases = _make_series_map(ema50=0)
    result = _normalize_atom(["ema50", "output"], series_by_alias=aliases)
    assert result == "ema50"


def test_normalize_atom_list_multi_output_dotted():
    """['bb', 'upper'] doit etre resolu en 'bb.upper' si alias existe."""
    aliases = _make_series_map(**{"bb.upper": 0, "bb.middle": 0, "bb.lower": 0})
    result = _normalize_atom(["bb", "upper"], series_by_alias=aliases)
    assert result == "bb.upper"


def test_normalize_atom_list_unknown_stays_list():
    """Liste non reconnue retourne la liste -> _resolve_atom levera l'erreur."""
    aliases = _make_series_map(rsi14=0)
    atom = ["outputs", 0, "rsi14"]
    result = _normalize_atom(atom, series_by_alias=aliases)
    assert result == atom  # inchange, pas normalise en silence


def test_normalize_atom_dict_ref():
    """{'$ref': 'rsi14'} -> 'rsi14'."""
    result = _normalize_atom({"$ref": "rsi14"}, series_by_alias={})
    assert result == "rsi14"


def test_normalize_atom_dict_alias_key():
    """{'alias': 'ema50', 'name': 'ema'} -> 'ema50'."""
    result = _normalize_atom({"alias": "ema50", "name": "ema"}, series_by_alias={})
    assert result == "ema50"


def test_dsl_tolerates_alias_value_list_form(synthetic_ohlcv):
    """['rsi14', 'value'] dans une expression DSL doit etre compile sans erreur."""
    proposal = {
        "strategy_name": "tolerance_test",
        "indicators": [
            {"alias": "rsi14", "name": "rsi", "params": {"period": 14}},
            {"alias": "ema50", "name": "ema", "params": {"period": 50}},
        ],
        # Forme erronee que le LLM produit : ["rsi14", "value"] au lieu de "rsi14"
        "entry_long": ["all", [["lt", ["rsi14", "value"], 30]]],
        "exit_long": ["any", [["gt", ["rsi14", "value"], 70]]],
    }
    strat = compile_strategy_from_proposal(proposal)
    signals = strat.generate_signals(synthetic_ohlcv, indicators={}, params={})
    assert signals.dtype.kind in ("i", "u")


def test_dsl_rejects_outputs_index_form(synthetic_ohlcv):
    """['outputs', 0, 'rsi14'] doit lever DslCompileError (non normalisable)."""
    proposal = {
        "strategy_name": "bad_outputs_form",
        "indicators": [
            {"alias": "rsi14", "name": "rsi", "params": {"period": 14}},
        ],
        "entry_long": ["all", [["lt", ["outputs", 0, "rsi14"], 30]]],
        "exit_long": ["any", [["gt", "rsi14", 70]]],
    }
    strat = compile_strategy_from_proposal(proposal)
    with pytest.raises(DslCompileError):
        strat.generate_signals(synthetic_ohlcv, indicators={}, params={})
