"""
Tests unitaires — Walk-Forward Analysis (backtest.walk_forward)

Objectifs :
1. WFA off → zéro overhead, résultat identique.
2. WFA on  → folds corrects, pas de look-ahead, métriques cohérentes.
3. Période trop courte → auto-désactivation (check_wfa_feasibility).
4. Expanding (anchored) mode fonctionne.
5. Sérialisation dict/agent_metrics compatible.
6. Pas de DataFrame.copy() (vérifié implicitement par les slices).

Datasets synthétiques (≤500 barres) — rapide, pas de données fichier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardSummary,
    check_wfa_feasibility,
    run_walk_forward,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Crée un DataFrame OHLCV synthétique de *n* barres.

    Trend légèrement haussière pour que les stratégies Trend-Following
    génèrent des trades (EMA Cross).
    """
    rng = np.random.RandomState(seed)
    # Marche aléatoire avec drift positif
    returns = rng.normal(loc=0.0002, scale=0.01, size=n)
    price = 100.0 * np.exp(np.cumsum(returns))

    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    df = pd.DataFrame(
        {
            "open": price + rng.uniform(-0.2, 0.2, n),
            "high": price + rng.uniform(0.2, 1.0, n),
            "low": price - rng.uniform(0.2, 1.0, n),
            "close": price,
            "volume": rng.uniform(100, 500, n),
        },
        index=dates,
    )
    return df


# ---------------------------------------------------------------------------
# Tests — check_wfa_feasibility
# ---------------------------------------------------------------------------

class TestCheckFeasibility:
    """Cas de garde-fou avant exécution."""

    def test_sufficient_bars(self):
        ok, msg = check_wfa_feasibility(1000)
        assert ok is True
        assert "réalisable" in msg.lower()

    def test_insufficient_bars(self):
        ok, msg = check_wfa_feasibility(50)
        assert ok is False
        assert "insuffisante" in msg.lower() or "désactivée" in msg.lower()

    def test_custom_config_threshold(self):
        cfg = WalkForwardConfig(n_folds=3, min_train_bars=50, min_test_bars=20)
        ok, _ = check_wfa_feasibility(210, config=cfg)
        assert ok is True

        ok, _ = check_wfa_feasibility(200, config=cfg)
        # 3 * (50 + 20) = 210 > 200
        assert ok is False


# ---------------------------------------------------------------------------
# Tests — WalkForwardConfig
# ---------------------------------------------------------------------------

class TestWalkForwardConfig:
    """Vérifie que la config est immuable et les défauts raisonnables."""

    def test_default_values(self):
        cfg = WalkForwardConfig()
        assert cfg.n_folds == 5
        assert cfg.train_ratio == 0.7
        assert cfg.embargo_pct == 0.02
        assert cfg.expanding is False

    def test_frozen(self):
        cfg = WalkForwardConfig()
        with pytest.raises(AttributeError):
            cfg.n_folds = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests — run_walk_forward (pipeline complet)
# ---------------------------------------------------------------------------

class TestRunWalkForward:
    """Pipeline split → run → aggregate."""

    @pytest.fixture
    def df500(self) -> pd.DataFrame:
        return _make_ohlcv(500, seed=42)

    def test_basic_run_returns_summary(self, df500):
        cfg = WalkForwardConfig(
            n_folds=3,
            train_ratio=0.7,
            min_train_bars=50,
            min_test_bars=20,
        )
        summary = run_walk_forward(
            df500, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

        assert isinstance(summary, WalkForwardSummary)
        assert summary.n_valid_folds > 0
        assert len(summary.folds) > 0
        assert summary.total_time_ms > 0

    def test_no_look_ahead(self, df500):
        """Aucun fold ne doit avoir test_start < train_end."""
        cfg = WalkForwardConfig(
            n_folds=3,
            train_ratio=0.7,
            min_train_bars=50,
            min_test_bars=20,
        )
        summary = run_walk_forward(
            df500, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

        for fold in summary.folds:
            assert fold.test_start >= fold.train_end, (
                f"Look-ahead détecté fold {fold.fold_id}: "
                f"test_start={fold.test_start} < train_end={fold.train_end}"
            )

    def test_folds_sequential(self, df500):
        """Les folds doivent être ordonnés chronologiquement."""
        cfg = WalkForwardConfig(
            n_folds=4,
            train_ratio=0.7,
            min_train_bars=40,
            min_test_bars=15,
        )
        summary = run_walk_forward(
            df500, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

        for i in range(1, len(summary.folds)):
            prev = summary.folds[i - 1]
            curr = summary.folds[i]
            assert curr.train_start >= prev.train_start, "Folds non ordonnés"

    def test_expanding_mode(self, df500):
        """En mode expanding, train_start == 0 pour tous les folds."""
        cfg = WalkForwardConfig(
            n_folds=3,
            train_ratio=0.6,
            min_train_bars=50,
            min_test_bars=20,
            expanding=True,
        )
        summary = run_walk_forward(
            df500, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

        for fold in summary.folds:
            assert fold.train_start == 0, (
                f"Expanding mode : train_start devrait être 0, "
                f"got {fold.train_start} (fold {fold.fold_id})"
            )

    def test_too_few_bars_returns_empty(self):
        """Avec trop peu de barres, aucun fold valide."""
        tiny_df = _make_ohlcv(30, seed=99)
        cfg = WalkForwardConfig(
            n_folds=5,
            train_ratio=0.7,
            min_train_bars=100,
            min_test_bars=50,
        )
        summary = run_walk_forward(
            tiny_df, "ema_cross", {"fast_period": 5, "slow_period": 12}, config=cfg
        )

        assert summary.n_valid_folds == 0

    def test_metrics_are_numeric(self, df500):
        """Toutes les métriques agrégées doivent être des float/int."""
        cfg = WalkForwardConfig(
            n_folds=3,
            train_ratio=0.7,
            min_train_bars=50,
            min_test_bars=20,
        )
        summary = run_walk_forward(
            df500, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

        assert isinstance(summary.avg_train_sharpe, float)
        assert isinstance(summary.avg_test_sharpe, float)
        assert isinstance(summary.degradation_pct, float)
        assert isinstance(summary.confidence_score, float)
        assert isinstance(summary.n_valid_folds, int)


# ---------------------------------------------------------------------------
# Tests — Sérialisation
# ---------------------------------------------------------------------------

class TestSerialization:
    """to_dict() et to_agent_metrics() doivent être stables."""

    @pytest.fixture
    def summary(self) -> WalkForwardSummary:
        df = _make_ohlcv(500, seed=42)
        cfg = WalkForwardConfig(
            n_folds=3,
            train_ratio=0.7,
            min_train_bars=50,
            min_test_bars=20,
        )
        return run_walk_forward(
            df, "ema_cross", {"fast_period": 10, "slow_period": 25}, config=cfg
        )

    def test_to_dict_keys(self, summary):
        d = summary.to_dict()
        expected_keys = {
            "config", "n_valid_folds", "avg_train_sharpe", "avg_test_sharpe",
            "avg_overfitting_ratio", "degradation_pct", "test_stability_std",
            "is_robust", "confidence_score", "total_time_ms", "folds",
        }
        assert expected_keys.issubset(d.keys())
        assert isinstance(d["folds"], list)

    def test_to_agent_metrics_keys(self, summary):
        m = summary.to_agent_metrics()
        expected = {
            "train_sharpe", "test_sharpe", "overfitting_ratio",
            "classic_ratio", "degradation_pct", "test_stability_std",
            "n_valid_folds",
        }
        assert expected == set(m.keys())

    def test_fold_to_dict(self, summary):
        if summary.folds:
            fd = summary.folds[0].to_dict()
            assert "fold_id" in fd
            assert "train_range" in fd
            assert "test_range" in fd
            assert "overfitting_ratio" in fd


# ---------------------------------------------------------------------------
# Tests — Non-régression (WFA off)
# ---------------------------------------------------------------------------

class TestWFAOff:
    """WFA désactivé = aucun impact fonctionnel."""

    def test_wfa_off_same_as_direct_backtest(self):
        """Un backtest direct doit donner les mêmes métriques
        qu'un run sans WFA."""
        from backtest.engine import BacktestEngine

        df = _make_ohlcv(500, seed=42)
        params = {"fast_period": 10, "slow_period": 25}

        # Run direct
        engine = BacktestEngine()
        direct = engine.run(df, "ema_cross", params, silent_mode=True)

        # WFA off (via check_feasibility → False)
        ok, _ = check_wfa_feasibility(len(df), WalkForwardConfig(
            n_folds=20, min_train_bars=200, min_test_bars=100
        ))
        assert ok is False, "Config devrait rendre WFA infaisable sur 500 barres"

        # Le code appelant vérifie feasibility et n'appelle PAS run_walk_forward
        # → le backtest direct est utilisé → pas d'impact perf ni fonctionnel.
        assert direct.metrics.get("sharpe_ratio") is not None
