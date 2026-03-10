"""
Module-ID: backtest.walk_forward

Purpose: Pipeline Walk-Forward Analysis (WFA) standalone — split / run / aggregate.

Role in pipeline: validation (opt-in)

Key components: WalkForwardConfig, FoldResult, WalkForwardSummary, run_walk_forward

Inputs: DataFrame OHLCV, strategy name/params, WalkForwardConfig

Outputs: WalkForwardSummary (résumé global + folds détaillés + score stabilité)

Dependencies: backtest.engine, backtest.validation (WalkForwardValidator), numpy

Conventions:
  - opt-in uniquement (WFA off = zéro overhead)
  - pas de DataFrame.copy() — slices par indices
  - agrégation NumPy vectorisée
  - logs discrets (debug/info), désactivables

Read-if: Vous intégrez le WFA dans un pipeline, un CLI ou un test.

Skip-if: Vous ne touchez qu'à un indicateur ou une stratégie isolée.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.validation import WalkForwardValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardConfig:
    """Configuration immuable d'une WFA.

    Args:
        n_folds: Nombre de fenêtres glissantes.
        train_ratio: Ratio train/total (ex: 0.7 = 70% train, 30% test).
        embargo_pct: Embargo entre train et test (% du total).
        min_train_bars: Seuil minimum de barres pour le train.
        min_test_bars: Seuil minimum de barres pour le test.
        expanding: True = fenêtre expanding (anchored), False = rolling.

    Example:
        >>> cfg = WalkForwardConfig(n_folds=5, train_ratio=0.7)
    """

    n_folds: int = 5
    train_ratio: float = 0.7
    embargo_pct: float = 0.02
    min_train_bars: int = 100
    min_test_bars: int = 50
    expanding: bool = False


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------


@dataclass
class FoldResult:
    """Résultat d'un fold WFA unique.

    Contient les indices, tailles et métriques train/test.
    """

    fold_id: int

    # Indices (positions iloc dans le DataFrame original)
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    # Métriques — None si le fold a échoué
    train_metrics: Optional[Dict[str, Any]] = None
    test_metrics: Optional[Dict[str, Any]] = None

    # Timing
    execution_time_ms: float = 0.0

    @property
    def train_bars(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_bars(self) -> int:
        return self.test_end - self.test_start

    @property
    def is_valid(self) -> bool:
        return self.train_metrics is not None and self.test_metrics is not None

    @property
    def overfitting_ratio(self) -> float:
        """Ratio train_sharpe / test_sharpe. > 1.0 = overfitting probable."""
        if not self.is_valid:
            return float("nan")
        train_s = self.train_metrics.get("sharpe_ratio", 0)
        test_s = self.test_metrics.get("sharpe_ratio", 0)
        if abs(test_s) < 1e-9:
            return 999.0 if train_s > 0 else 1.0
        return train_s / test_s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_range": [self.train_start, self.train_end],
            "test_range": [self.test_start, self.test_end],
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "train_sharpe": (
                self.train_metrics.get("sharpe_ratio", 0) if self.train_metrics else None
            ),
            "test_sharpe": (
                self.test_metrics.get("sharpe_ratio", 0) if self.test_metrics else None
            ),
            "overfitting_ratio": (
                round(self.overfitting_ratio, 3) if self.is_valid else None
            ),
            "execution_time_ms": round(self.execution_time_ms, 1),
        }


@dataclass
class WalkForwardSummary:
    """Résultat complet d'une analyse Walk-Forward.

    Contient :
      - La config utilisée
      - Les résultats fold par fold
      - Les agrégats (moyennes, stabilité, verdict)
    """

    config: WalkForwardConfig
    folds: List[FoldResult] = field(default_factory=list)

    # Agrégats
    avg_train_sharpe: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_overfitting_ratio: float = 0.0
    degradation_pct: float = 0.0
    test_stability_std: float = 0.0

    # Verdict
    is_robust: bool = False
    confidence_score: float = 0.0
    n_valid_folds: int = 0

    # Timing
    total_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dict (JSON-friendly)."""
        return {
            "config": {
                "n_folds": self.config.n_folds,
                "train_ratio": self.config.train_ratio,
                "embargo_pct": self.config.embargo_pct,
                "expanding": self.config.expanding,
            },
            "n_valid_folds": self.n_valid_folds,
            "avg_train_sharpe": round(self.avg_train_sharpe, 4),
            "avg_test_sharpe": round(self.avg_test_sharpe, 4),
            "avg_overfitting_ratio": round(self.avg_overfitting_ratio, 3),
            "degradation_pct": round(self.degradation_pct, 2),
            "test_stability_std": round(self.test_stability_std, 4),
            "is_robust": self.is_robust,
            "confidence_score": round(self.confidence_score, 3),
            "total_time_ms": round(self.total_time_ms, 1),
            "folds": [f.to_dict() for f in self.folds],
        }

    def to_agent_metrics(self) -> Dict[str, Any]:
        """Convertit en format WalkForwardMetrics (compatibilité agents)."""
        return {
            "train_sharpe": float(self.avg_train_sharpe),
            "test_sharpe": float(self.avg_test_sharpe),
            "overfitting_ratio": float(self.avg_overfitting_ratio),
            "classic_ratio": float(self.avg_overfitting_ratio),
            "degradation_pct": float(self.degradation_pct),
            "test_stability_std": float(self.test_stability_std),
            "n_valid_folds": self.n_valid_folds,
        }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------


def _make_validator(cfg: WalkForwardConfig) -> WalkForwardValidator:
    """Instancie un WalkForwardValidator depuis une WalkForwardConfig."""
    test_pct = 1.0 - cfg.train_ratio
    return WalkForwardValidator(
        n_folds=cfg.n_folds,
        test_pct=test_pct,
        embargo_pct=cfg.embargo_pct,
        min_train_samples=cfg.min_train_bars,
        min_test_samples=cfg.min_test_bars,
        expanding=cfg.expanding,
    )


def _run_single_fold(
    df: pd.DataFrame,
    fold_vf: Any,  # ValidationFold from validation.py
    strategy_name: str,
    params: Dict[str, Any],
    initial_capital: float,
    config: Any,
) -> FoldResult:
    """Exécute un fold (train + test) et retourne le FoldResult.

    PERF: Pas de DataFrame.copy(). Le moteur ne mutate pas le df en entrée.
    """
    t0 = time.perf_counter()

    fold_result = FoldResult(
        fold_id=fold_vf.fold_id,
        train_start=fold_vf.train_start,
        train_end=fold_vf.train_end,
        test_start=fold_vf.test_start,
        test_end=fold_vf.test_end,
    )

    engine = BacktestEngine(initial_capital=initial_capital, config=config)

    try:
        # Slice sans .copy() — le moteur lit mais ne mute pas le DataFrame
        train_slice = df.iloc[fold_vf.train_start:fold_vf.train_end]
        test_slice = df.iloc[fold_vf.test_start:fold_vf.test_end]

        # Backtest train
        train_result = engine.run(
            df=train_slice,
            strategy=strategy_name,
            params=params,
            silent_mode=True,
            fast_metrics=True,
        )
        fold_result.train_metrics = dict(train_result.metrics)

        # Backtest test
        test_result = engine.run(
            df=test_slice,
            strategy=strategy_name,
            params=params,
            silent_mode=True,
            fast_metrics=True,
        )
        fold_result.test_metrics = dict(test_result.metrics)

    except Exception as e:
        logger.warning("fold_%d_failed error=%s", fold_vf.fold_id, e)

    fold_result.execution_time_ms = (time.perf_counter() - t0) * 1000
    return fold_result


def _aggregate(folds: List[FoldResult], cfg: WalkForwardConfig) -> WalkForwardSummary:
    """Agrège les résultats de tous les folds en un WalkForwardSummary.

    Utilise NumPy pour les calculs vectorisés.
    """
    valid = [f for f in folds if f.is_valid]
    n_valid = len(valid)

    if n_valid == 0:
        return WalkForwardSummary(
            config=cfg,
            folds=folds,
            n_valid_folds=0,
            avg_overfitting_ratio=999.0,
            degradation_pct=100.0,
        )

    train_sharpes = np.array(
        [f.train_metrics.get("sharpe_ratio", 0) for f in valid], dtype=np.float64
    )
    test_sharpes = np.array(
        [f.test_metrics.get("sharpe_ratio", 0) for f in valid], dtype=np.float64
    )

    avg_train = float(np.mean(train_sharpes))
    avg_test = float(np.mean(test_sharpes))
    std_test = float(np.std(test_sharpes))

    # Ratio classique
    if abs(avg_test) > 1e-9:
        classic_ratio = avg_train / avg_test
    else:
        classic_ratio = 999.0

    # Dégradation %
    if abs(avg_train) > 1e-9:
        degradation = max(0.0, (avg_train - avg_test) / abs(avg_train) * 100)
    else:
        degradation = 100.0

    # Pénalité stabilité → ratio robuste
    stability_penalty = std_test * 2.0
    robust_ratio = classic_ratio + stability_penalty

    # Score de confiance (0-1)
    conf_factors = []
    if avg_test > 0:
        conf_factors.append(min(avg_test / 2.0, 1.0))
    else:
        conf_factors.append(0.0)
    if std_test > 0:
        conf_factors.append(1.0 / (1.0 + std_test))
    if classic_ratio < 3.0:
        conf_factors.append(max(0.0, 1.0 - (classic_ratio - 1.0) / 2.0))
    else:
        conf_factors.append(0.0)

    confidence = float(np.mean(conf_factors)) if conf_factors else 0.0

    is_robust = avg_test > 0.5 and robust_ratio < 2.0 and confidence > 0.5

    return WalkForwardSummary(
        config=cfg,
        folds=folds,
        avg_train_sharpe=avg_train,
        avg_test_sharpe=avg_test,
        avg_overfitting_ratio=robust_ratio,
        degradation_pct=degradation,
        test_stability_std=std_test,
        is_robust=is_robust,
        confidence_score=confidence,
        n_valid_folds=n_valid,
        total_time_ms=sum(f.execution_time_ms for f in folds),
    )


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def run_walk_forward(
    df: pd.DataFrame,
    strategy_name: str,
    params: Dict[str, Any],
    *,
    config: Optional[WalkForwardConfig] = None,
    initial_capital: float = 10000.0,
    engine_config: Any = None,
) -> WalkForwardSummary:
    """Exécute une analyse Walk-Forward complète.

    Pipeline : split → run folds → aggregate.

    Args:
        df: DataFrame OHLCV (DatetimeIndex requis).
        strategy_name: Nom de la stratégie enregistrée.
        params: Paramètres de la stratégie.
        config: Configuration WFA (défauts raisonnables si None).
        initial_capital: Capital de départ.
        engine_config: Config moteur (fees/slippage).

    Returns:
        WalkForwardSummary avec folds détaillés et agrégats.

    Example:
        >>> from backtest.walk_forward import run_walk_forward, WalkForwardConfig
        >>> cfg = WalkForwardConfig(n_folds=5, train_ratio=0.7)
        >>> summary = run_walk_forward(df, "ema_cross", {"fast": 12, "slow": 26}, config=cfg)
        >>> print(summary.is_robust, summary.avg_test_sharpe)
    """
    cfg = config or WalkForwardConfig()

    logger.debug(
        "wfa_start strategy=%s n_folds=%d train_ratio=%.2f bars=%d",
        strategy_name, cfg.n_folds, cfg.train_ratio, len(df),
    )

    t_pipeline = time.perf_counter()

    # 1. SPLIT — délègue au WalkForwardValidator existant
    t0 = time.perf_counter()
    validator = _make_validator(cfg)
    validation_folds = validator.split(df)
    logger.debug(
        "wfa_split folds_generated=%d elapsed_ms=%.1f",
        len(validation_folds), (time.perf_counter() - t0) * 1000,
    )

    if not validation_folds:
        logger.warning("wfa_no_valid_folds bars=%d config=%s", len(df), cfg)
        return WalkForwardSummary(config=cfg, n_valid_folds=0)

    # 2. RUN — exécuter chaque fold séquentiellement
    t0 = time.perf_counter()
    fold_results: List[FoldResult] = []
    for vf in validation_folds:
        fr = _run_single_fold(
            df=df,
            fold_vf=vf,
            strategy_name=strategy_name,
            params=params,
            initial_capital=initial_capital,
            config=engine_config,
        )
        fold_results.append(fr)
        logger.debug(
            "wfa_fold_%d train_sharpe=%.3f test_sharpe=%.3f time_ms=%.1f",
            fr.fold_id,
            fr.train_metrics.get("sharpe_ratio", 0) if fr.train_metrics else 0,
            fr.test_metrics.get("sharpe_ratio", 0) if fr.test_metrics else 0,
            fr.execution_time_ms,
        )
    logger.debug(
        "wfa_folds_done elapsed_ms=%.1f", (time.perf_counter() - t0) * 1000
    )

    # 3. AGGREGATE — calcul des métriques globales
    t0 = time.perf_counter()
    summary = _aggregate(fold_results, cfg)
    summary.total_time_ms = (time.perf_counter() - t_pipeline) * 1000
    logger.debug(
        "wfa_aggregate elapsed_ms=%.1f", (time.perf_counter() - t0) * 1000
    )

    logger.info(
        "wfa_done n_valid=%d/%d avg_test_sharpe=%.3f robust=%s "
        "degradation=%.1f%% confidence=%.3f total_ms=%.0f",
        summary.n_valid_folds,
        len(validation_folds),
        summary.avg_test_sharpe,
        summary.is_robust,
        summary.degradation_pct,
        summary.confidence_score,
        summary.total_time_ms,
    )

    return summary


def check_wfa_feasibility(
    n_bars: int,
    config: Optional[WalkForwardConfig] = None,
) -> Tuple[bool, str]:
    """Vérifie si une WFA est réalisable sans charger les données.

    Garde-fou léger (pas de lecture DataFrame).

    Args:
        n_bars: Nombre de barres disponibles.
        config: Configuration WFA.

    Returns:
        (feasible, message)
    """
    cfg = config or WalkForwardConfig()
    min_bars_needed = cfg.n_folds * (cfg.min_train_bars + cfg.min_test_bars)

    if n_bars < min_bars_needed:
        return False, (
            f"Données insuffisantes: {n_bars} barres < "
            f"{min_bars_needed} minimum ({cfg.n_folds} folds × "
            f"({cfg.min_train_bars} train + {cfg.min_test_bars} test)). "
            f"WFA automatiquement désactivée."
        )
    return True, f"WFA réalisable: {n_bars} barres ≥ {min_bars_needed} minimum."


__all__ = [
    "FoldResult",
    "WalkForwardConfig",
    "WalkForwardSummary",
    "check_wfa_feasibility",
    "run_walk_forward",
]
