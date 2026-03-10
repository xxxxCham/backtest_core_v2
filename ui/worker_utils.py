"""
Utilitaires pour la gestion des workers et threads.

Fournit des fonctions pour l'exécution de backtests en parallèle
et la configuration des threads dans les processus workers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from ui.helpers import compute_period_days_from_df, safe_run_backtest


def run_backtest_multiprocess(args) -> Dict[str, Any]:
    """
    Wrapper picklable pour ProcessPoolExecutor.

    Args:
        args: tuple (param_combo, initial_capital, df, strategy_key, symbol, timeframe, debug_enabled)

    Returns:
        Dict avec résultats du backtest ou erreur
    """
    param_combo, initial_capital, df, strategy_key, symbol, timeframe, debug_enabled = args

    try:
        # Import local pour éviter les problèmes de pickling avec Streamlit
        from backtest.engine import BacktestEngine as _LocalBacktestEngine
        # Créer l'engine localement (pas picklable donc recréé dans chaque process)
        engine = _LocalBacktestEngine(initial_capital=initial_capital)
        period_days = compute_period_days_from_df(df)

        result_i, msg_i = safe_run_backtest(
            engine,
            df,
            strategy_key,
            param_combo,
            symbol,
            timeframe,
            silent_mode=not debug_enabled,
            fast_metrics=True,
        )

        params_native = {
            k: float(v) if hasattr(v, "item") else v for k, v in param_combo.items()
        }
        params_str = str(params_native)

        if result_i:
            m = result_i.metrics
            return {
                "params": params_str,
                "params_dict": param_combo,
                "total_pnl": m.get("total_pnl", 0.0),
                "theoretical_pnl": m.get("theoretical_pnl", 0.0),
                "sharpe": m.get("sharpe_ratio", 0.0),
                "max_dd": m.get("max_drawdown_pct", m.get("max_drawdown", 0.0)),
                "win_rate": m.get("win_rate", 0.0),
                "trades": m.get("total_trades", 0),
                "profit_factor": m.get("profit_factor", 0.0),
                "period_days": period_days,
            }
        return {
            "params": params_str,
            "params_dict": param_combo,
            "error": msg_i,
        }
    except Exception as exc:
        params_str = str(param_combo)
        return {
            "params": params_str,
            "params_dict": param_combo,
            "error": str(exc),
        }


def apply_thread_limit(thread_limit: int, label: str = "") -> None:
    """
    Applique des limites de threads pour contrôler l'utilisation CPU.

    Args:
        thread_limit: Nombre max de threads
        label: Label pour le logging (optionnel)
    """
    if thread_limit <= 0:
        return

    os.environ["BACKTEST_WORKER_THREADS"] = str(thread_limit)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
        "NUMBA_NUM_THREADS",
    ):
        os.environ[var] = str(thread_limit)

    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(thread_limit)
    except Exception:
        pass

    try:
        from numba import set_num_threads

        set_num_threads(thread_limit)
    except Exception:
        pass

    try:
        import torch
        torch.set_num_threads(thread_limit)
        torch.set_num_interop_threads(max(1, thread_limit // 2))
    except Exception:
        pass

    if label:
        logger = logging.getLogger(__name__)
        logger.info("Thread limit %s appliqué: %s", label, thread_limit)


def init_sweep_worker(thread_limit: int) -> None:
    """
    Initializer ProcessPoolExecutor - applique limites threads AVANT tout calcul.

    Args:
        thread_limit: Nombre max de threads pour ce worker
    """
    apply_thread_limit(thread_limit, label="worker")

    # Forcer avec threadpoolctl (plus efficace que les env vars seules)
    try:
        import threadpoolctl
        info_before = threadpoolctl.threadpool_info()
        threadpoolctl.threadpool_limits(limits=max(1, thread_limit), user_api="blas")
        info_after = threadpoolctl.threadpool_info()

        # Log pour debug
        import logging
        logger = logging.getLogger(__name__)
        num_threads_before = sum(pool.get("num_threads", 0) for pool in info_before)
        num_threads_after = sum(pool.get("num_threads", 0) for pool in info_after)
        logger.debug(f"Worker threads BLAS: {num_threads_before} → {num_threads_after}")
    except ImportError:
        pass  # threadpoolctl non installé - les env vars suffiront
