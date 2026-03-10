"""
Module-ID: catalog.gating

Purpose: Mini-backtest gating via compilation déterministe du proposal + BacktestEngine.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from backtest.engine import BacktestEngine
from catalog.models import GatingConfig, Variant

logger = logging.getLogger(__name__)


def _load_strategy_from_code(code: str, module_name: str = "gating_strategy"):
    """Charge dynamiquement une stratégie depuis du code Python généré."""
    # Écrire le code dans un fichier temporaire
    tmp_dir = Path(tempfile.mkdtemp(prefix="catalog_gating_"))
    module_path = tmp_dir / f"{module_name}.py"
    module_path.write_text(code, encoding="utf-8")

    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger le module depuis {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Chercher la classe de stratégie (BuilderGeneratedStrategy ou StrategyBase subclass)
    strategy_cls = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and attr_name != "StrategyBase"
            and hasattr(attr, "generate_signals")
        ):
            strategy_cls = attr
            break

    if strategy_cls is None:
        raise RuntimeError("Aucune classe de stratégie trouvée dans le code généré")

    return strategy_cls()


def run_gating(
    variant: Variant,
    df: pd.DataFrame,
    config: GatingConfig,
    engine: Optional[BacktestEngine] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Exécute un mini-backtest sur un variant pour gating.

    1. Compile variant.proposal → code Python via compile_proposal_to_code
    2. Charge la stratégie dynamiquement
    3. Exécute BacktestEngine.run(df, strategy, params, fast_metrics=True)
    4. Compare metrics aux seuils gating

    Args:
        variant: Variant à tester
        df: DataFrame OHLCV pour le backtest
        config: Configuration de gating (seuils)
        engine: BacktestEngine optionnel (créé si None)

    Returns:
        Tuple (passed, metrics_dict)
    """
    # Import lazy pour éviter la circularité
    from agents.strategy_builder import compile_proposal_to_code

    metrics: Dict[str, Any] = {
        "passed": False,
        "error": None,
        "total_trades": 0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
        "sharpe_ratio": 0.0,
        "total_return_pct": 0.0,
        "duration_ms": 0,
    }

    start_time = time.monotonic()

    try:
        # 1. Compiler le proposal en code Python
        code = compile_proposal_to_code(variant.proposal, variant=0)
        if not code:
            metrics["error"] = "Compilation returned empty code"
            return False, metrics

        # 2. Charger la stratégie
        module_name = f"gating_{variant.variant_id.replace('-', '_')}"
        strategy = _load_strategy_from_code(code, module_name)

        # 3. Exécuter le backtest
        if engine is None:
            engine = BacktestEngine(initial_capital=10000.0)

        result = engine.run(
            df=df,
            strategy=strategy,
            params=variant.proposal.get("default_params", {}),
            fast_metrics=True,
            silent_mode=True,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        metrics["duration_ms"] = elapsed_ms

        # 4. Extraire les métriques
        m = result.metrics
        metrics["total_trades"] = m.get("total_trades", 0)
        metrics["max_drawdown"] = abs(m.get("max_drawdown", 0))
        metrics["profit_factor"] = m.get("profit_factor", 0.0)
        metrics["sharpe_ratio"] = m.get("sharpe_ratio", 0.0)
        metrics["total_return_pct"] = m.get("total_return_pct", 0.0)

        # 5. Appliquer les seuils
        thresholds = config.thresholds
        passed = True
        reasons = []

        if metrics["total_trades"] < thresholds.get("min_trades", 20):
            passed = False
            reasons.append(
                f"trades={metrics['total_trades']} < min={thresholds.get('min_trades', 20)}"
            )

        if metrics["max_drawdown"] > thresholds.get("max_drawdown_pct", 40):
            passed = False
            reasons.append(
                f"drawdown={metrics['max_drawdown']:.1f}% > max={thresholds.get('max_drawdown_pct', 40)}%"
            )

        if metrics["profit_factor"] < thresholds.get("min_profit_factor", 1.05):
            passed = False
            reasons.append(
                f"pf={metrics['profit_factor']:.2f} < min={thresholds.get('min_profit_factor', 1.05)}"
            )

        metrics["passed"] = passed
        if reasons:
            metrics["rejection_reasons"] = reasons

        return passed, metrics

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        metrics["duration_ms"] = elapsed_ms
        metrics["error"] = f"{type(e).__name__}: {e}"
        logger.warning("Gating failed for %s: %s", variant.variant_id, e)
        return False, metrics


def run_gating_batch(
    variants: list[Variant],
    df: pd.DataFrame,
    config: GatingConfig,
) -> list[Tuple[Variant, bool, Dict[str, Any]]]:
    """
    Exécute le gating sur un batch de variants.

    Returns:
        Liste de (variant, passed, metrics) pour chaque variant.
    """
    engine = BacktestEngine(initial_capital=10000.0)
    results = []

    for variant in variants:
        passed, metrics = run_gating(variant, df, config, engine=engine)
        variant.gating_result = metrics
        results.append((variant, passed, metrics))

    return results
