"""
Backtest Core - Sweep Numba Vectorisé
=====================================

Exécute des milliers de backtests en parallèle avec Numba prange.
Élimine l'overhead multiprocessing (pickle, IPC) pour ~10-50× speedup.

Performance attendue sur Ryzen 9950X (32 threads):
- ProcessPoolExecutor: ~2000-3000 bt/s (overhead IPC ~50%)
- Numba prange: ~10000-50000 bt/s (overhead ~0%)

Stratégies supportées:
- bollinger_atr, bollinger_atr_v2, bollinger_atr_v3
- ema_cross
- rsi_reversal
"""

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from performance.memory import get_available_ram_gb
from performance.parallel import get_recommended_chunk_size, get_recommended_worker_count

try:
    from numba import get_num_threads, njit, prange, set_num_threads
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    prange = range
    get_num_threads = None
    set_num_threads = None


logger = logging.getLogger(__name__)

NUMBA_SWEEP_PARAM_SPECS: Dict[str, Dict[str, float]] = {
    "bollinger_best_longe_3i": {
        "bb_period": 20.0,
        "bb_std": 2.1,
        "entry_level": 0.0,
        "sl_level": -0.5,
        "tp_level": 0.85,
        "leverage": 1.0,
    },
    "bollinger_best_short_3i": {
        "bb_period": 20.0,
        "bb_std": 2.1,
        "entry_level": 1.0,
        "sl_level": 1.5,
        "tp_level": 0.15,
        "leverage": 1.0,
    },
    "bollinger": {
        "bb_period": 20.0,
        "bb_std": 2.0,
        "entry_z": 2.0,
        "leverage": 1.0,
        "k_sl": 1.5,
    },
    "ema_cross": {
        "fast_period": 12.0,
        "slow_period": 26.0,
        "leverage": 1.0,
        "k_sl": 1.5,
    },
    "rsi_reversal": {
        "rsi_period": 14.0,
        "overbought": 70.0,
        "oversold": 30.0,
        "leverage": 1.0,
        "k_sl": 1.5,
    },
    "macd_cross": {
        "fast_period": 12.0,
        "slow_period": 26.0,
        "signal_period": 9.0,
        "leverage": 1.0,
        "k_sl": 1.5,
    },
}

NUMBA_SWEEP_THREAD_PROFILES: Dict[str, Dict[str, float]] = {
    "bollinger_best_longe_3i": {
        "cost_multiplier": 1.35,
        "to_4_threads": 220_000,
        "to_8_threads": 550_000,
        "to_16_threads": 3_000_000,
    },
    "bollinger_best_short_3i": {
        "cost_multiplier": 1.35,
        "to_4_threads": 220_000,
        "to_8_threads": 550_000,
        "to_16_threads": 3_000_000,
    },
    "bollinger": {
        "cost_multiplier": 1.00,
        "to_4_threads": 220_000,
        "to_8_threads": 500_000,
        "to_16_threads": 3_500_000,
    },
    "ema_cross": {
        "cost_multiplier": 0.90,
        "to_4_threads": 180_000,
        "to_8_threads": 450_000,
        "to_16_threads": 3_200_000,
    },
    "rsi_reversal": {
        "cost_multiplier": 0.85,
        "to_4_threads": 250_000,
        "to_8_threads": 1_000_000,
        "to_16_threads": 8_000_000,
    },
    "macd_cross": {
        "cost_multiplier": 1.20,
        "to_4_threads": 200_000,
        "to_8_threads": 550_000,
        "to_16_threads": 3_200_000,
    },
}

# ============================================================================
# Stratégies supportées par le sweep Numba
# ============================================================================
NUMBA_SUPPORTED_STRATEGIES = {
    'bollinger_atr', 'bollinger_atr_v2', 'bollinger_atr_v3',
    'ema_cross',
    'rsi_reversal',
    'macd_cross',
    'bollinger_best_longe_3i',
    'bollinger_best_short_3i',
}

NUMBA_SUPPORTED_METRICS = {
    "sharpe",
    "sharpe_ratio",
    "total_pnl",
    "total_return",
    "total_return_pct",
    "max_drawdown",
    "max_drawdown_pct",
    "win_rate",
    "win_rate_pct",
    "total_trades",
    "n_trades",
}


def normalize_numba_strategy_key(strategy_key: str) -> str:
    """Normalise une clé stratégie pour les heuristiques de sweep Numba."""
    return str(strategy_key or "").lower().replace("-", "_").replace(" ", "_")


def normalize_numba_metric_name(metric: Optional[str]) -> str:
    """Normalise les alias de métriques vers le contrat canonique Numba."""
    metric_key = str(metric or "sharpe_ratio").strip().lower()
    aliases = {
        "sharpe": "sharpe_ratio",
        "return": "total_return_pct",
        "total_return": "total_return_pct",
        "pnl": "total_pnl",
        "drawdown": "max_drawdown_pct",
        "max_drawdown": "max_drawdown_pct",
        "winrate": "win_rate_pct",
        "win_rate": "win_rate_pct",
        "trades": "total_trades",
        "n_trades": "total_trades",
    }
    return aliases.get(metric_key, metric_key)


def is_numba_supported(strategy_key: str) -> bool:
    """Vérifie si une stratégie supporte le sweep Numba."""
    return HAS_NUMBA and normalize_numba_strategy_key(strategy_key) in NUMBA_SUPPORTED_STRATEGIES


def is_numba_metric_supported(metric: Optional[str]) -> bool:
    """Vérifie si la métrique demandée est compatible avec le backend Numba."""
    if metric is None:
        return True
    return normalize_numba_metric_name(metric) in NUMBA_SUPPORTED_METRICS


def should_use_numba_backend(
    strategy_key: str,
    *,
    metric: Optional[str] = "sharpe_ratio",
    total_combos: Optional[int] = None,
) -> bool:
    """
    Décide si le sweep Numba doit être utilisé par défaut.

    Le but est de privilégier Numba partout où le contrat fonctionnel reste
    compatible; un fallback classique reste possible via variables d'environnement.
    """
    strategy_name = normalize_numba_strategy_key(strategy_key)
    metric_name = normalize_numba_metric_name(metric)

    if not is_numba_supported(strategy_name):
        return False
    if not is_numba_metric_supported(metric_name):
        return False

    prefer_env = os.getenv("BACKTEST_PREFER_NUMBA_SWEEP", "1").strip().lower()
    if prefer_env in {"0", "false", "no", "off"}:
        return False

    if total_combos is not None:
        try:
            min_combos = max(1, int(os.getenv("BACKTEST_NUMBA_SWEEP_MIN_COMBOS", "1")))
        except (TypeError, ValueError):
            min_combos = 1
        if total_combos < min_combos:
            return False

    return True


def numba_result_to_metrics(result: Dict[str, Any], initial_capital: float) -> Dict[str, Any]:
    """Normalise un résultat Numba vers le format métriques attendu par les autres couches."""
    total_pnl = float(result.get("total_pnl", 0.0))
    max_drawdown = -abs(float(result.get("max_drawdown", 0.0)))
    win_rate = float(result.get("win_rate", 0.0))
    sharpe_ratio = float(result.get("sharpe_ratio", 0.0))
    total_trades = int(result.get("total_trades", 0))

    total_return_pct = 0.0
    if initial_capital:
        total_return_pct = total_pnl / float(initial_capital) * 100.0

    return {
        "total_pnl": total_pnl,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown,
        "win_rate_pct": win_rate,
        "total_trades": total_trades,
        "total_return_pct": total_return_pct,
    }


def build_numba_sweep_result_item(
    result: Dict[str, Any],
    *,
    initial_capital: float,
    metric: Optional[str] = "sharpe_ratio",
) -> Dict[str, Any]:
    """Construit un item de sweep normalisé à partir d'un résultat brut Numba."""
    metric_key = normalize_numba_metric_name(metric)
    metrics = numba_result_to_metrics(result, initial_capital)
    params = result.get("params", {}) or {}
    return {
        "params": params,
        "metrics": metrics,
        "score": metrics.get(metric_key, 0),
    }


def run_numba_sweep_items_if_supported(
    *,
    df: pd.DataFrame,
    strategy_key: str,
    param_grid: List[Dict[str, Any]],
    metric: Optional[str] = "sharpe_ratio",
    initial_capital: float = 10000.0,
    fees_bps: float = 10.0,
    slippage_bps: float = 5.0,
    progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
    result_chunk_callback: Optional[
        Callable[[List[Dict[str, Any]], int, int, Optional[Dict[str, Any]]], None]
    ] = None,
    thread_override: Optional[int] = None,
    chunk_size_override: Optional[int] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    _param_arrays: Optional[Dict[str, np.ndarray]] = None,
    _ohlcv: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Exécute un sweep Numba si le backend est compatible et retourne des items normalisés.

    Chaque item suit le contrat:
    `{"params": {...}, "metrics": {...}, "score": ...}`.
    """
    strategy_name = normalize_numba_strategy_key(strategy_key)
    metric_key = normalize_numba_metric_name(metric)

    if not should_use_numba_backend(
        strategy_name,
        metric=metric_key,
        total_combos=len(param_grid),
    ):
        return None

    def normalized_chunk_callback(
        chunk_rows: List[Dict[str, Any]],
        completed: int,
        total: int,
        best_result: Optional[Dict[str, Any]],
    ) -> None:
        if result_chunk_callback is None:
            return
        chunk_items = [
            build_numba_sweep_result_item(
                row,
                initial_capital=initial_capital,
                metric=metric_key,
            )
            for row in chunk_rows
        ]
        best_item = None
        if best_result is not None:
            best_item = build_numba_sweep_result_item(
                best_result,
                initial_capital=initial_capital,
                metric=metric_key,
            )
        result_chunk_callback(chunk_items, completed, total, best_item)

    rows = run_numba_sweep(
        df=df,
        strategy_key=strategy_name,
        param_grid=param_grid,
        initial_capital=initial_capital,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        progress_callback=progress_callback,
        result_chunk_callback=normalized_chunk_callback if result_chunk_callback else None,
        thread_override=thread_override,
        chunk_size_override=chunk_size_override,
        should_stop=should_stop,
        _param_arrays=_param_arrays,
        _ohlcv=_ohlcv,
    )
    return [
        build_numba_sweep_result_item(
            row,
            initial_capital=initial_capital,
            metric=metric_key,
        )
        for row in rows
    ]


if HAS_NUMBA:
    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _calc_bollinger_signals(
        closes: np.ndarray,
        bb_period: int,
        bb_std: float,
        entry_z: float,
    ) -> np.ndarray:
        """Calcule signaux Bollinger pour UN set de params (appelé depuis prange)."""
        n = len(closes)
        signals = np.zeros(n, dtype=np.float64)

        for i in prange(bb_period, n):
            window = closes[i-bb_period+1:i+1]
            sma = 0.0
            for j in range(bb_period):
                sma += window[j]
            sma /= bb_period

            var = 0.0
            for j in range(bb_period):
                diff = window[j] - sma
                var += diff * diff
            std = np.sqrt(var / bb_period)

            if std > 1e-10:
                z_score = (closes[i] - sma) / std
                if z_score < -entry_z:
                    signals[i] = 1.0
                elif z_score > entry_z:
                    signals[i] = -1.0

        return signals

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_bollinger_full(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        # Paramètres sous forme de tableaux (1 valeur par combo)
        bb_periods: np.ndarray,
        bb_stds: np.ndarray,
        entry_zs: np.ndarray,
        leverages: np.ndarray,
        k_sls: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Sweep COMPLET en un seul kernel Numba parallèle.
        Calcule signaux + backtest pour chaque combo en parallèle.
        """
        n_combos = len(bb_periods)
        n_bars = len(closes)

        # Résultats
        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        # ⚡ PARALLÉLISATION sur les combinaisons
        for combo_idx in prange(n_combos):
            bb_period = int(bb_periods[combo_idx])
            _bb_std = bb_stds[combo_idx]
            entry_z = entry_zs[combo_idx]
            leverage = leverages[combo_idx]
            k_sl = k_sls[combo_idx]
            sl_pct = k_sl * 0.01

            # === Calcul signaux Bollinger inline ===
            signals = np.zeros(n_bars, dtype=np.float64)
            for i in range(bb_period, n_bars):
                sma = 0.0
                for j in range(bb_period):
                    sma += closes[i - bb_period + 1 + j]
                sma /= bb_period

                var = 0.0
                for j in range(bb_period):
                    diff = closes[i - bb_period + 1 + j] - sma
                    var += diff * diff
                std = np.sqrt(var / bb_period)

                if std > 1e-10:
                    z_score = (closes[i] - sma) / std
                    if z_score < -entry_z:
                        signals[i] = 1.0
                    elif z_score > entry_z:
                        signals[i] = -1.0

            # === Simulation backtest ===
            position = 0
            entry_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0

            for i in range(n_bars):
                close_price = closes[i]
                signal = signals[i]

                if position == 0 and signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)

                elif position != 0:
                    exit_now = False

                    if signal != 0 and signal != position:
                        exit_now = True
                    elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        exit_now = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor * position)

                        if position == 1:
                            raw_return = (exit_price - entry_price) / entry_price
                        else:
                            raw_return = (entry_price - exit_price) / entry_price

                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital

                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1

                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return

                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd

                        position = 0
                        entry_price = 0.0
                        if signal != 0:
                            position = int(signal)
                            entry_price = close_price * (1.0 + slippage_factor * position)

            # Clôturer position ouverte
            if position != 0:
                exit_price = closes[-1] * (1.0 - slippage_factor * position)
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            # Métriques finales
            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count

            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        std_ret = np.sqrt(variance)
                        sharpes[combo_idx] = mean_ret / std_ret * np.sqrt(252)

            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_backtest_core(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        signals_matrix: np.ndarray,  # (n_combos, n_bars) - signaux pré-calculés
        leverages: np.ndarray,       # (n_combos,)
        k_sls: np.ndarray,           # (n_combos,)
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Exécute N backtests en parallèle (Numba prange).

        Returns:
            total_pnls: (n_combos,) - PnL total par combo
            sharpes: (n_combos,) - Sharpe ratio simplifié
            max_dds: (n_combos,) - Max drawdown %
            win_rates: (n_combos,) - Win rate %
            n_trades: (n_combos,) - Nombre de trades
        """
        n_combos = signals_matrix.shape[0]
        n_bars = len(closes)

        # Résultats
        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        # Constantes
        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        # ⚡ PARALLÉLISATION sur les combinaisons
        for combo_idx in prange(n_combos):
            signals = signals_matrix[combo_idx]
            leverage = leverages[combo_idx]
            k_sl = k_sls[combo_idx]
            sl_pct = k_sl * 0.01

            # État
            position = 0
            entry_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0

            # Compteurs trades
            trade_count = 0
            winning_trades = 0

            # Pour Sharpe: stocker les returns
            returns_sum = 0.0
            returns_sq_sum = 0.0

            for i in range(n_bars):
                close_price = closes[i]
                signal = signals[i]

                # === Entrée ===
                if position == 0 and signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)

                # === En position ===
                elif position != 0:
                    exit_now = False

                    # Signal opposé
                    if signal != 0 and signal != position:
                        exit_now = True
                    # Stop-loss
                    elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        exit_now = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor * position)

                        if position == 1:
                            raw_return = (exit_price - entry_price) / entry_price
                        else:
                            raw_return = (entry_price - exit_price) / entry_price

                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital

                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1

                        # Pour Sharpe
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return

                        # Drawdown
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd

                        # Reset ou nouvelle position
                        position = 0
                        entry_price = 0.0
                        if signal != 0:
                            position = int(signal)
                            entry_price = close_price * (1.0 + slippage_factor * position)

            # Clôturer position ouverte
            if position != 0:
                exit_price = closes[-1] * (1.0 - slippage_factor * position)
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            # Métriques finales
            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count

            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0

                # Sharpe simplifié
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        std_ret = np.sqrt(variance)
                        sharpes[combo_idx] = mean_ret / std_ret * np.sqrt(252)

            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


def run_sweep_numba(
    df,
    param_grid: List[Dict[str, Any]],
    signal_generator,  # Fonction qui génère les signaux pour un set de params
    initial_capital: float = 10000.0,
    fees_bps: float = 10.0,
    slippage_bps: float = 5.0,
) -> List[Dict[str, Any]]:
    """
    Exécute un sweep complet avec Numba vectorisé.

    Args:
        df: DataFrame OHLCV
        param_grid: Liste de dicts de paramètres
        signal_generator: Fonction (df, params) -> np.ndarray de signaux
        initial_capital: Capital initial
        fees_bps: Frais en basis points
        slippage_bps: Slippage en basis points

    Returns:
        Liste de résultats (dict par combinaison)
    """
    if not HAS_NUMBA:
        raise ImportError("Numba requis pour sweep vectorisé")

    n_combos = len(param_grid)
    n_bars = len(df)

    # Extraire données OHLCV
    closes = df['close'].values.astype(np.float64)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)

    # Pré-calculer TOUS les signaux (peut être parallélisé aussi)
    print(f"📊 Pré-calcul des signaux pour {n_combos} combinaisons...")
    signals_matrix = np.zeros((n_combos, n_bars), dtype=np.float64)
    leverages = np.zeros(n_combos, dtype=np.float64)
    k_sls = np.zeros(n_combos, dtype=np.float64)

    for i, params in enumerate(param_grid):
        signals_matrix[i] = signal_generator(df, params)
        leverages[i] = params.get('leverage', 1.0)
        k_sls[i] = params.get('k_sl', 1.5)

    # ⚡ Exécuter TOUS les backtests en parallèle
    print(f"⚡ Exécution de {n_combos} backtests en parallèle (Numba)...")
    total_pnls, sharpes, max_dds, win_rates, n_trades = _sweep_backtest_core(
        closes, highs, lows,
        signals_matrix,
        leverages, k_sls,
        initial_capital, fees_bps, slippage_bps
    )

    # Reconstruire résultats
    results = []
    for i, params in enumerate(param_grid):
        results.append({
            'params': params,
            'total_pnl': float(total_pnls[i]),
            'sharpe_ratio': float(sharpes[i]),
            'max_drawdown': float(max_dds[i]),
            'win_rate': float(win_rates[i]),
            'total_trades': int(n_trades[i]),
        })

    return results


# ============================================================================
# Générateurs de signaux optimisés Numba
# ============================================================================

@njit(cache=True, nogil=True, fastmath=True, boundscheck=False)
def _ema_numba(data: np.ndarray, period: int) -> np.ndarray:
    """EMA optimisée Numba."""
    n = len(data)
    result = np.empty(n, dtype=np.float64)
    alpha = 2.0 / (period + 1)

    # Initialiser avec SMA
    result[0] = data[0]
    for i in range(1, min(period, n)):
        result[i] = data[:i+1].mean()

    # EMA
    for i in range(period, n):
        result[i] = alpha * data[i] + (1 - alpha) * result[i-1]

    return result


@njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
def _bollinger_signals_numba(
    closes: np.ndarray,
    bb_period: int,
    bb_std: float,
    entry_z: float = 2.0,
) -> np.ndarray:
    """Génère signaux Bollinger bands (Numba)."""
    n = len(closes)
    signals = np.zeros(n, dtype=np.float64)

    for i in prange(bb_period, n):
        window = closes[i-bb_period+1:i+1]
        sma = window.mean()
        std = window.std()

        if std > 0:
            z_score = (closes[i] - sma) / std

            # Long si sous la bande inférieure
            if z_score < -entry_z:
                signals[i] = 1.0
            # Short si au-dessus de la bande supérieure
            elif z_score > entry_z:
                signals[i] = -1.0

    return signals


@njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
def _ema_cross_signals_numba(
    closes: np.ndarray,
    fast_period: int,
    slow_period: int,
) -> np.ndarray:
    """Génère signaux EMA crossover (Numba)."""
    n = len(closes)
    signals = np.zeros(n, dtype=np.float64)

    fast_ema = _ema_numba(closes, fast_period)
    slow_ema = _ema_numba(closes, slow_period)

    for i in prange(slow_period, n):
        # Crossover haussier
        if fast_ema[i] > slow_ema[i] and fast_ema[i-1] <= slow_ema[i-1]:
            signals[i] = 1.0
        # Crossover baissier
        elif fast_ema[i] < slow_ema[i] and fast_ema[i-1] >= slow_ema[i-1]:
            signals[i] = -1.0

    return signals


def create_signal_generator(strategy_name: str):
    """Factory pour créer un générateur de signaux selon la stratégie."""

    def bollinger_generator(df, params):
        return _bollinger_signals_numba(
            df['close'].values.astype(np.float64),
            int(params.get('bb_period', 20)),
            float(params.get('bb_std', 2.0)),
            float(params.get('entry_z', 2.0)),
        )

    def ema_cross_generator(df, params):
        return _ema_cross_signals_numba(
            df['close'].values.astype(np.float64),
            int(params.get('fast_period', 12)),
            int(params.get('slow_period', 26)),
        )

    generators = {
        'bollinger_atr': bollinger_generator,
        'bollinger': bollinger_generator,
        'ema_cross': ema_cross_generator,
    }

    return generators.get(strategy_name, bollinger_generator)


def _resolve_numba_strategy_family(strategy_lower: str) -> str:
    """Normalise une stratégie supportée vers sa famille de sweep Numba."""
    if strategy_lower in {"bollinger_best_longe_3i", "bollinger_best_short_3i"}:
        return strategy_lower
    if "bollinger" in strategy_lower:
        return "bollinger"
    if "ema" in strategy_lower and "cross" in strategy_lower:
        return "ema_cross"
    if "rsi" in strategy_lower:
        return "rsi_reversal"
    if "macd" in strategy_lower:
        return "macd_cross"
    raise ValueError(f"Stratégie '{strategy_lower}' non supportée par Numba sweep")


def _get_numba_param_spec(strategy_lower: str) -> Dict[str, float]:
    return NUMBA_SWEEP_PARAM_SPECS[_resolve_numba_strategy_family(strategy_lower)]


def _get_numba_thread_profile(strategy_lower: str) -> Dict[str, float]:
    return NUMBA_SWEEP_THREAD_PROFILES[_resolve_numba_strategy_family(strategy_lower)]


def _estimate_numba_sweep_bytes_per_combo(strategy_lower: str) -> int:
    """Estime la mémoire linéaire par combinaison pour un kernel spécialisé."""
    param_arrays = len(_get_numba_param_spec(strategy_lower))

    result_arrays = 5
    return (param_arrays + result_arrays) * 8


def _get_numba_sweep_memory_budget_gb() -> float:
    """
    Retourne le budget RAM autorisé pour un sweep Numba.

    Défaut: utiliser le matériel disponible avec une large fenêtre DDR, plafonnée
    à 40 GB pour éviter de saturer inutilement le système.
    """
    available_gb = max(1.0, get_available_ram_gb())

    env_budget = os.getenv("BACKTEST_NUMBA_SWEEP_RAM_BUDGET_GB")
    if env_budget:
        try:
            requested = max(0.5, float(env_budget))
        except (TypeError, ValueError):
            requested = min(40.0, available_gb * 0.80)
    else:
        requested = min(40.0, available_gb * 0.80)

    return max(0.5, min(requested, available_gb * 0.90))


def _get_numba_chunk_size(
    strategy_lower: str,
    total_combos: int,
    n_bars: int,
    chunk_size_override: Optional[int] = None,
) -> int:
    """
    Détermine une taille de chunk adaptée au sweep Numba.

    On borne la taille par:
    - un plafond de calcul pour éviter des kernels monolithiques
    - un plafond mémoire basé sur le budget DDR disponible
    """
    if total_combos <= 0:
        return 0

    if chunk_size_override is not None:
        return max(1, min(int(chunk_size_override), total_combos))

    bytes_per_combo = _estimate_numba_sweep_bytes_per_combo(strategy_lower)
    budget_bytes = _get_numba_sweep_memory_budget_gb() * (1024 ** 3)
    static_bytes = n_bars * 3 * 8
    linear_total_bytes = static_bytes + (total_combos * bytes_per_combo)
    if linear_total_bytes <= budget_bytes * 0.70:
        return total_combos

    headroom_bytes = max(256 * 1024 * 1024, int(budget_bytes * 0.05))
    usable_bytes = max(1, int(budget_bytes - static_bytes - headroom_bytes))
    memory_bound = max(1, usable_bytes // max(1, bytes_per_combo))

    base_chunk = get_recommended_chunk_size(default=2048, total_tasks=total_combos)
    max_chunk = int(os.getenv("BACKTEST_NUMBA_SWEEP_MAX_CHUNK", "1000000"))
    min_chunk = int(os.getenv("BACKTEST_NUMBA_SWEEP_MIN_CHUNK", str(max(2048, base_chunk * 8))))

    if total_combos <= min_chunk:
        return total_combos

    chunk_size = min(total_combos, memory_bound, max_chunk)
    if chunk_size < min_chunk:
        return max(1, min(total_combos, chunk_size))
    return max(min_chunk, chunk_size)


def _get_numba_thread_count(
    strategy_lower: str,
    chunk_size: int,
    n_bars: int,
    thread_override: Optional[int] = None,
) -> int:
    """
    Détermine le nombre de threads Numba utile pour un chunk.

    Les kernels Numba du sweep parallélisent sur les combinaisons. Sur petits
    chunks, utiliser beaucoup de threads coûte plus qu'il ne rapporte.
    """
    if chunk_size <= 0:
        return 1

    if thread_override is not None:
        return max(1, int(thread_override))

    recommended = get_recommended_worker_count(max_cap=os.cpu_count() or 1)
    profile = _get_numba_thread_profile(strategy_lower)
    work_units = chunk_size * max(1, n_bars) * profile["cost_multiplier"]

    if chunk_size < 64 or work_units < profile["to_4_threads"]:
        return 1
    if chunk_size < 128 or work_units < profile["to_8_threads"]:
        return min(recommended, 4)
    if chunk_size < 512 or work_units < profile["to_16_threads"]:
        return min(recommended, 8)
    if chunk_size < 2048 or work_units < profile["to_16_threads"] * 4:
        return min(recommended, 16)
    return max(1, recommended)


@contextmanager
def _numba_thread_context(thread_count: int):
    """Applique temporairement un nombre de threads Numba."""
    if not HAS_NUMBA or set_num_threads is None or get_num_threads is None:
        yield 1
        return

    previous = get_num_threads()
    applied = max(1, int(thread_count))
    set_num_threads(applied)
    try:
        yield get_num_threads()
    finally:
        set_num_threads(previous)


def _extract_param_array(
    params_chunk: List[Dict[str, Any]],
    key: str,
    default: float,
) -> np.ndarray:
    return np.fromiter(
        (float(params.get(key, default)) for params in params_chunk),
        dtype=np.float64,
        count=len(params_chunk),
    )


def extract_strategy_params(
    strategy_key: str,
    param_grid: List[Dict[str, Any]],
) -> Dict[str, np.ndarray]:
    """
    Pré-extrait tous les paramètres d'une grille en arrays numpy.

    Le hot path des gros sweeps ne doit pas reboucler sur `dict.get(...)`
    entre chaque chunk si la grille est déjà matérialisée.
    """
    strategy_lower = strategy_key.lower()
    param_spec = _get_numba_param_spec(strategy_lower)
    return {
        key: _extract_param_array(param_grid, key, default)
        for key, default in param_spec.items()
    }


def _slice_param_arrays(
    param_arrays: Dict[str, np.ndarray],
    start: int,
    end: int,
) -> Dict[str, np.ndarray]:
    return {key: values[start:end] for key, values in param_arrays.items()}


def _run_numba_kernel_chunk(
    strategy_lower: str,
    params_chunk: List[Dict[str, Any]],
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    initial_capital: float,
    fees_bps: float,
    slippage_bps: float,
    param_arrays_chunk: Optional[Dict[str, np.ndarray]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Exécute un chunk de sweep sur le kernel spécialisé correspondant."""
    param_spec = _get_numba_param_spec(strategy_lower)
    arrays = param_arrays_chunk or {
        key: _extract_param_array(params_chunk, key, default)
        for key, default in param_spec.items()
    }

    if strategy_lower == "bollinger_best_longe_3i":
        return _sweep_boll_level_long(
            closes,
            highs,
            lows,
            arrays["bb_period"],
            arrays["bb_std"],
            arrays["entry_level"],
            arrays["sl_level"],
            arrays["tp_level"],
            arrays["leverage"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    if strategy_lower == "bollinger_best_short_3i":
        return _sweep_boll_level_short(
            closes,
            highs,
            lows,
            arrays["bb_period"],
            arrays["bb_std"],
            arrays["entry_level"],
            arrays["sl_level"],
            arrays["tp_level"],
            arrays["leverage"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    if "bollinger" in strategy_lower:
        return _sweep_bollinger_full(
            closes,
            highs,
            lows,
            arrays["bb_period"],
            arrays["bb_std"],
            arrays["entry_z"],
            arrays["leverage"],
            arrays["k_sl"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    if "ema" in strategy_lower and "cross" in strategy_lower:
        return _sweep_ema_cross_full(
            closes,
            highs,
            lows,
            arrays["fast_period"],
            arrays["slow_period"],
            arrays["leverage"],
            arrays["k_sl"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    if "rsi" in strategy_lower:
        return _sweep_rsi_reversal_full(
            closes,
            highs,
            lows,
            arrays["rsi_period"],
            arrays["overbought"],
            arrays["oversold"],
            arrays["leverage"],
            arrays["k_sl"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    if "macd" in strategy_lower:
        return _sweep_macd_cross_full(
            closes,
            highs,
            lows,
            arrays["fast_period"],
            arrays["slow_period"],
            arrays["signal_period"],
            arrays["leverage"],
            arrays["k_sl"],
            initial_capital,
            fees_bps,
            slippage_bps,
        )

    raise ValueError(f"Stratégie '{strategy_lower}' non supportée par Numba sweep")


def _build_results_chunk(
    params_chunk: List[Dict[str, Any]],
    pnls: np.ndarray,
    sharpes: np.ndarray,
    max_dds: np.ndarray,
    win_rates: np.ndarray,
    n_trades: np.ndarray,
) -> List[Dict[str, Any]]:
    return [
        {
            "params": params_chunk[i],
            "total_pnl": float(pnls[i]),
            "sharpe_ratio": float(sharpes[i]),
            "max_drawdown": float(max_dds[i]),
            "win_rate": float(win_rates[i]),
            "total_trades": int(n_trades[i]),
        }
        for i in range(len(params_chunk))
    ]


def _make_best_result_dict(
    params_chunk: List[Dict[str, Any]],
    pnls: np.ndarray,
    sharpes: np.ndarray,
    max_dds: np.ndarray,
    win_rates: np.ndarray,
    n_trades: np.ndarray,
    best_idx: int,
) -> Dict[str, Any]:
    return {
        "params": params_chunk[best_idx],
        "total_pnl": float(pnls[best_idx]),
        "sharpe_ratio": float(sharpes[best_idx]),
        "max_drawdown": float(max_dds[best_idx]),
        "win_rate": float(win_rates[best_idx]),
        "total_trades": int(n_trades[best_idx]),
    }


# ============================================================================
# Benchmark
# ============================================================================


def _build_benchmark_ohlcv(n_bars: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.015, n_bars)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000, 10_000, n_bars),
        }
    )


def _build_benchmark_param_grid(strategy_key: str, n_combos: int) -> List[Dict[str, float]]:
    strategy_lower = strategy_key.lower()
    strategy_family = _resolve_numba_strategy_family(strategy_lower)
    combos: List[Dict[str, float]] = []

    if strategy_family == "ema_cross":
        for fast in range(5, 81):
            for slow in range(max(fast + 2, 20), 261, 2):
                for leverage in (1.0, 2.0):
                    for k_sl in (1.0, 1.5, 2.0):
                        combos.append(
                            {
                                "fast_period": float(fast),
                                "slow_period": float(slow),
                                "leverage": leverage,
                                "k_sl": k_sl,
                            }
                        )
                        if len(combos) >= n_combos:
                            return combos

    if strategy_family == "macd_cross":
        for fast in range(6, 41, 2):
            for slow in range(max(fast + 4, 24), 121, 2):
                for signal in range(5, 31, 2):
                    for leverage in (1.0, 2.0):
                        combos.append(
                            {
                                "fast_period": float(fast),
                                "slow_period": float(slow),
                                "signal_period": float(signal),
                                "leverage": leverage,
                                "k_sl": 1.5,
                            }
                        )
                        if len(combos) >= n_combos:
                            return combos

    if strategy_family == "rsi_reversal":
        for rsi_period in range(6, 40):
            for overbought in range(60, 91, 3):
                for oversold in range(10, 41, 3):
                    if oversold >= overbought:
                        continue
                    for leverage in (1.0, 2.0):
                        combos.append(
                            {
                                "rsi_period": float(rsi_period),
                                "overbought": float(overbought),
                                "oversold": float(oversold),
                                "leverage": leverage,
                                "k_sl": 1.5,
                            }
                        )
                        if len(combos) >= n_combos:
                            return combos

    if strategy_family in {"bollinger", "bollinger_best_longe_3i", "bollinger_best_short_3i"}:
        if "best_" in strategy_family:
            for bb_period in range(10, 90, 2):
                for bb_std in np.arange(0.8, 4.3, 0.2):
                    for entry in np.arange(-0.3, 1.7, 0.1):
                        combos.append(
                            {
                                "bb_period": float(bb_period),
                                "bb_std": float(bb_std),
                                "entry_level": float(entry if "long" in strategy_family else max(1.0, entry)),
                                "sl_level": float(-0.8 if "long" in strategy_family else 1.4),
                                "tp_level": float(0.9 if "long" in strategy_family else 0.2),
                                "leverage": 1.0,
                            }
                        )
                        if len(combos) >= n_combos:
                            return combos
        else:
            for bb_period in range(10, 90, 2):
                for bb_std in np.arange(1.0, 4.6, 0.2):
                    for entry_z in np.arange(1.0, 3.6, 0.2):
                        combos.append(
                            {
                                "bb_period": float(bb_period),
                                "bb_std": float(bb_std),
                                "entry_z": float(entry_z),
                                "leverage": 1.0,
                                "k_sl": 1.5,
                            }
                        )
                        if len(combos) >= n_combos:
                            return combos

    raise ValueError(f"Impossible de générer une grille benchmark pour '{strategy_key}'")


def benchmark_numba_strategy_profiles(
    strategy_keys: Optional[List[str]] = None,
    combo_sizes: Tuple[int, ...] = (128, 1024, 8192),
    n_bars: int = 5000,
    thread_candidates: Optional[Tuple[Optional[int], ...]] = None,
) -> List[Dict[str, Any]]:
    """
    Benchmark reproductible des profils adaptatifs Numba par stratégie.

    Utilisé pour fixer les seuils de threads sur CPU-only sans dépendre de l'UI.
    """
    if strategy_keys is None:
        strategy_keys = ["ema_cross", "macd_cross", "rsi_reversal", "bollinger_atr"]
    if thread_candidates is None:
        thread_candidates = (1, 4, 8, 16, None)

    rows: List[Dict[str, Any]] = []

    for idx, strategy_key in enumerate(strategy_keys):
        df = _build_benchmark_ohlcv(n_bars=n_bars, seed=42 + idx)
        max_combos = max(combo_sizes)
        param_grid = _build_benchmark_param_grid(strategy_key, max_combos)
        param_arrays = extract_strategy_params(strategy_key, param_grid)
        ohlcv = (
            np.asarray(df["close"].values, dtype=np.float64),
            np.asarray(df["high"].values, dtype=np.float64),
            np.asarray(df["low"].values, dtype=np.float64),
        )

        # Warmup JIT par stratégie pour éviter de polluer la mesure.
        run_numba_sweep(
            df=df,
            strategy_key=strategy_key,
            param_grid=param_grid[:8],
            return_arrays=True,
            thread_override=1,
            chunk_size_override=8,
            _param_arrays=_slice_param_arrays(param_arrays, 0, 8),
            _ohlcv=ohlcv,
        )

        for combo_size in combo_sizes:
            combo_grid = param_grid[:combo_size]
            combo_arrays = _slice_param_arrays(param_arrays, 0, combo_size)

            for thread_candidate in thread_candidates:
                start = time.perf_counter()
                run_numba_sweep(
                    df=df,
                    strategy_key=strategy_key,
                    param_grid=combo_grid,
                    return_arrays=True,
                    thread_override=thread_candidate,
                    chunk_size_override=combo_size,
                    _param_arrays=combo_arrays,
                    _ohlcv=ohlcv,
                )
                elapsed = time.perf_counter() - start
                rows.append(
                    {
                        "strategy": strategy_key,
                        "combo_size": combo_size,
                        "n_bars": n_bars,
                        "thread_mode": "adaptive" if thread_candidate is None else str(thread_candidate),
                        "throughput": combo_size / max(elapsed, 1e-9),
                        "elapsed": elapsed,
                    }
                )

    return rows


def benchmark_sweep_numba(n_combos: int = 1000, n_bars: int = 10000):
    """Benchmark du sweep Numba vs ProcessPoolExecutor."""
    import time

    print(f"\n{'='*60}")
    print(f"BENCHMARK SWEEP NUMBA - {n_combos} combinaisons × {n_bars} barres")
    print(f"{'='*60}\n")

    # Générer données
    np.random.seed(42)
    close = 100 * np.exp(np.cumsum(np.random.randn(n_bars) * 0.02))
    closes = close.astype(np.float64)
    highs = (close * 1.01).astype(np.float64)
    lows = (close * 0.99).astype(np.float64)

    # Générer grille comme tableaux
    bb_periods_list = []
    bb_stds_list = []
    entry_zs_list = []
    leverages_list = []
    k_sls_list = []

    for bb_period in range(10, 60, 2):
        for bb_std in [1.0, 1.5, 2.0, 2.5, 3.0]:
            for entry_z in [1.0, 1.5, 2.0, 2.5, 3.0]:
                bb_periods_list.append(bb_period)
                bb_stds_list.append(bb_std)
                entry_zs_list.append(entry_z)
                leverages_list.append(2.0)
                k_sls_list.append(1.5)
                if len(bb_periods_list) >= n_combos:
                    break
            if len(bb_periods_list) >= n_combos:
                break
        if len(bb_periods_list) >= n_combos:
            break

    bb_periods = np.array(bb_periods_list, dtype=np.float64)
    bb_stds = np.array(bb_stds_list, dtype=np.float64)
    entry_zs = np.array(entry_zs_list, dtype=np.float64)
    leverages = np.array(leverages_list, dtype=np.float64)
    k_sls = np.array(k_sls_list, dtype=np.float64)

    actual_combos = len(bb_periods)
    print(f"Grille: {actual_combos} combinaisons")

    # Warm-up JIT (première compilation)
    print("Warm-up Numba JIT (première compilation)...")
    _ = _sweep_bollinger_full(
        closes[:100], highs[:100], lows[:100],
        bb_periods[:5], bb_stds[:5], entry_zs[:5],
        leverages[:5], k_sls[:5],
        10000.0, 10.0, 5.0
    )
    print("  JIT compilé ✓")

    # Exécuter sweep complet
    print(f"\n⚡ Exécution sweep COMPLET ({actual_combos} combos × {n_bars} bars)...")
    start = time.perf_counter()
    total_pnls, sharpes, max_dds, win_rates, n_trades = _sweep_bollinger_full(
        closes, highs, lows,
        bb_periods, bb_stds, entry_zs,
        leverages, k_sls,
        10000.0, 10.0, 5.0
    )
    total_time = time.perf_counter() - start

    print(f"\n{'='*60}")
    print("RÉSULTATS")
    print(f"{'='*60}")
    print(f"  Temps total: {total_time:.3f}s")
    print("")
    print(f"  ⚡ Throughput: {actual_combos/total_time:,.0f} backtests/seconde")
    print(f"  ⚡ Temps/bt:   {total_time/actual_combos*1000:.3f} ms")
    print(f"{'='*60}")

    # Stats résultats
    print("\nStats résultats:")
    print(f"  Best PnL:    ${np.max(total_pnls):,.2f}")
    print(f"  Worst PnL:   ${np.min(total_pnls):,.2f}")
    print(f"  Best Sharpe: {np.max(sharpes):.2f}")
    print(f"  Avg trades:  {np.mean(n_trades):.0f}")

    return {
        'n_combos': actual_combos,
        'total_time': total_time,
        'throughput': actual_combos / total_time,
    }


# ============================================================================
# KERNELS EMA CROSS & RSI REVERSAL
# ============================================================================

if HAS_NUMBA:
    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_ema_cross_full(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        fast_periods: np.ndarray,
        slow_periods: np.ndarray,
        leverages: np.ndarray,
        k_sls: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Sweep EMA Cross en Numba parallèle."""
        n_combos = len(fast_periods)
        n_bars = len(closes)

        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        for combo_idx in prange(n_combos):
            fast_p = int(fast_periods[combo_idx])
            slow_p = int(slow_periods[combo_idx])
            leverage = leverages[combo_idx]
            k_sl = k_sls[combo_idx]
            sl_pct = k_sl * 0.01

            # Calcul EMA fast
            alpha_fast = 2.0 / (fast_p + 1)
            fast_ema = np.zeros(n_bars, dtype=np.float64)
            fast_ema[0] = closes[0]
            for i in range(1, n_bars):
                fast_ema[i] = alpha_fast * closes[i] + (1 - alpha_fast) * fast_ema[i-1]

            # Calcul EMA slow
            alpha_slow = 2.0 / (slow_p + 1)
            slow_ema = np.zeros(n_bars, dtype=np.float64)
            slow_ema[0] = closes[0]
            for i in range(1, n_bars):
                slow_ema[i] = alpha_slow * closes[i] + (1 - alpha_slow) * slow_ema[i-1]

            # Signaux crossover
            signals = np.zeros(n_bars, dtype=np.float64)
            for i in range(slow_p, n_bars):
                if fast_ema[i] > slow_ema[i] and fast_ema[i-1] <= slow_ema[i-1]:
                    signals[i] = 1.0
                elif fast_ema[i] < slow_ema[i] and fast_ema[i-1] >= slow_ema[i-1]:
                    signals[i] = -1.0

            # Simulation identique
            position = 0
            entry_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0

            for i in range(n_bars):
                close_price = closes[i]
                signal = signals[i]

                if position == 0 and signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)
                elif position != 0:
                    exit_now = False
                    if signal != 0 and signal != position:
                        exit_now = True
                    elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        exit_now = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor * position)
                        if position == 1:
                            raw_return = (exit_price - entry_price) / entry_price
                        else:
                            raw_return = (entry_price - exit_price) / entry_price
                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital
                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd
                        position = 0
                        entry_price = 0.0
                        if signal != 0:
                            position = int(signal)
                            entry_price = close_price * (1.0 + slippage_factor * position)

            # Clôture finale
            if position != 0:
                exit_price = closes[-1] * (1.0 - slippage_factor * position)
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count
            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        sharpes[combo_idx] = (mean_ret / np.sqrt(variance)) * np.sqrt(252)
            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_rsi_reversal_full(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        rsi_periods: np.ndarray,
        overboughts: np.ndarray,
        oversolds: np.ndarray,
        leverages: np.ndarray,
        k_sls: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Sweep RSI Reversal en Numba parallèle."""
        n_combos = len(rsi_periods)
        n_bars = len(closes)

        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        for combo_idx in prange(n_combos):
            rsi_p = int(rsi_periods[combo_idx])
            overbought = overboughts[combo_idx]
            oversold = oversolds[combo_idx]
            leverage = leverages[combo_idx]
            k_sl = k_sls[combo_idx]
            sl_pct = k_sl * 0.01

            # Calcul RSI
            rsi = np.zeros(n_bars, dtype=np.float64)
            avg_gain = 0.0
            avg_loss = 0.0

            # Première période
            for i in range(1, rsi_p + 1):
                diff = closes[i] - closes[i-1]
                if diff > 0:
                    avg_gain += diff
                else:
                    avg_loss -= diff
            avg_gain /= rsi_p
            avg_loss /= rsi_p

            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi[rsi_p] = 100.0 - (100.0 / (1.0 + rs))
            else:
                rsi[rsi_p] = 100.0

            # Smoothed RSI
            for i in range(rsi_p + 1, n_bars):
                diff = closes[i] - closes[i-1]
                gain = max(0.0, diff)
                loss = max(0.0, -diff)
                avg_gain = (avg_gain * (rsi_p - 1) + gain) / rsi_p
                avg_loss = (avg_loss * (rsi_p - 1) + loss) / rsi_p
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi[i] = 100.0 - (100.0 / (1.0 + rs))
                else:
                    rsi[i] = 100.0

            # Signaux reversal
            signals = np.zeros(n_bars, dtype=np.float64)
            for i in range(rsi_p + 1, n_bars):
                if rsi[i-1] <= oversold and rsi[i] > oversold:
                    signals[i] = 1.0  # Long quand RSI sort de survente
                elif rsi[i-1] >= overbought and rsi[i] < overbought:
                    signals[i] = -1.0  # Short quand RSI sort de surachat

            # Simulation (identique)
            position = 0
            entry_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0

            for i in range(n_bars):
                close_price = closes[i]
                signal = signals[i]

                if position == 0 and signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)
                elif position != 0:
                    exit_now = False
                    if signal != 0 and signal != position:
                        exit_now = True
                    elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        exit_now = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor * position)
                        if position == 1:
                            raw_return = (exit_price - entry_price) / entry_price
                        else:
                            raw_return = (entry_price - exit_price) / entry_price
                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital
                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd
                        position = 0
                        entry_price = 0.0
                        if signal != 0:
                            position = int(signal)
                            entry_price = close_price * (1.0 + slippage_factor * position)

            if position != 0:
                exit_price = closes[-1] * (1.0 - slippage_factor * position)
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count
            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        sharpes[combo_idx] = (mean_ret / np.sqrt(variance)) * np.sqrt(252)
            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


    # ================================================================
    # MACD CROSS — croisement MACD / Signal line
    # ================================================================

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_macd_cross_full(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        fast_periods: np.ndarray,
        slow_periods: np.ndarray,
        signal_periods: np.ndarray,
        leverages: np.ndarray,
        k_sls: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Sweep MACD Cross en Numba parallèle."""
        n_combos = len(fast_periods)
        n_bars = len(closes)

        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        for combo_idx in prange(n_combos):
            fast_p = int(fast_periods[combo_idx])
            slow_p = int(slow_periods[combo_idx])
            sig_p = int(signal_periods[combo_idx])
            leverage = leverages[combo_idx]
            k_sl = k_sls[combo_idx]
            sl_pct = k_sl * 0.01

            # --- Calcul EMA rapide ---
            ema_fast = np.zeros(n_bars, dtype=np.float64)
            alpha_f = 2.0 / (fast_p + 1)
            ema_fast[0] = closes[0]
            for i in range(1, n_bars):
                ema_fast[i] = alpha_f * closes[i] + (1.0 - alpha_f) * ema_fast[i - 1]

            # --- Calcul EMA lente ---
            ema_slow = np.zeros(n_bars, dtype=np.float64)
            alpha_s = 2.0 / (slow_p + 1)
            ema_slow[0] = closes[0]
            for i in range(1, n_bars):
                ema_slow[i] = alpha_s * closes[i] + (1.0 - alpha_s) * ema_slow[i - 1]

            # --- MACD line ---
            macd_line = np.zeros(n_bars, dtype=np.float64)
            for i in range(n_bars):
                macd_line[i] = ema_fast[i] - ema_slow[i]

            # --- Signal line (EMA du MACD) ---
            signal_line = np.zeros(n_bars, dtype=np.float64)
            alpha_sig = 2.0 / (sig_p + 1)
            signal_line[0] = macd_line[0]
            for i in range(1, n_bars):
                signal_line[i] = alpha_sig * macd_line[i] + (1.0 - alpha_sig) * signal_line[i - 1]

            # --- Signaux crossover ---
            warmup = slow_p + sig_p
            signals = np.zeros(n_bars, dtype=np.float64)
            for i in range(warmup, n_bars):
                prev_above = macd_line[i - 1] > signal_line[i - 1]
                curr_above = macd_line[i] > signal_line[i]
                if curr_above and not prev_above:
                    signals[i] = 1.0   # golden cross
                elif not curr_above and prev_above:
                    signals[i] = -1.0  # death cross

            # --- Simulation ---
            position = 0
            entry_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0

            for i in range(n_bars):
                close_price = closes[i]
                signal = signals[i]

                if position == 0 and signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)
                elif position != 0:
                    exit_now = False
                    if signal != 0 and signal != position:
                        exit_now = True
                    elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        exit_now = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor * position)
                        if position == 1:
                            raw_return = (exit_price - entry_price) / entry_price
                        else:
                            raw_return = (entry_price - exit_price) / entry_price
                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital
                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd
                        position = 0
                        entry_price = 0.0
                        if signal != 0:
                            position = int(signal)
                            entry_price = close_price * (1.0 + slippage_factor * position)

            # Clôture finale
            if position != 0:
                exit_price = closes[-1] * (1.0 - slippage_factor * position)
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count
            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        sharpes[combo_idx] = (mean_ret / np.sqrt(variance)) * np.sqrt(252)
            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


    # ================================================================
    # BOLLINGER BEST LONG 3i — entry/SL/TP sur échelle Bollinger
    # ================================================================

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_boll_level_long(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        bb_periods: np.ndarray,
        bb_stds: np.ndarray,
        entry_levels: np.ndarray,
        sl_levels: np.ndarray,
        tp_levels: np.ndarray,
        leverages: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Sweep Bollinger level-based LONG en Numba parallèle."""
        n_combos = len(bb_periods)
        n_bars = len(closes)

        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        for combo_idx in prange(n_combos):
            bb_p = int(bb_periods[combo_idx])
            bb_s = bb_stds[combo_idx]
            entry_lv = entry_levels[combo_idx]
            sl_lv = sl_levels[combo_idx]
            tp_lv = tp_levels[combo_idx]
            leverage = leverages[combo_idx]

            # --- Simulation avec Bollinger inline ---
            position = 0
            entry_price = 0.0
            stop_price = 0.0
            tp_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0
            prev_signal = 0.0

            for i in range(bb_p, n_bars):
                # Calcul Bollinger inline
                sma = 0.0
                for j in range(bb_p):
                    sma += closes[i - bb_p + 1 + j]
                sma /= bb_p
                var = 0.0
                for j in range(bb_p):
                    diff = closes[i - bb_p + 1 + j] - sma
                    var += diff * diff
                std = np.sqrt(var / bb_p)
                upper = sma + bb_s * std
                lower = sma - bb_s * std
                total_dist = upper - lower

                if total_dist < 1e-10:
                    continue

                # Price levels
                entry_pl = lower + entry_lv * total_dist
                sl_pl = lower + sl_lv * total_dist
                tp_pl = lower + tp_lv * total_dist

                close_price = closes[i]

                # Signal : LONG quand close <= entry_price_level (et pas déjà en position)
                signal = 1.0 if close_price <= entry_pl else 0.0
                # Déduplique (seulement sur changement)
                if signal == prev_signal:
                    signal = 0.0
                else:
                    prev_signal = signal if signal != 0.0 else prev_signal

                if position == 0 and signal == 1.0:
                    position = 1
                    entry_price = close_price * (1.0 + slippage_factor)
                    stop_price = sl_pl
                    tp_price = tp_pl
                elif position == 1:
                    exit_now = False
                    if lows[i] <= stop_price:
                        exit_now = True
                    elif highs[i] >= tp_price:
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 - slippage_factor)
                        raw_return = (exit_price - entry_price) / entry_price
                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital
                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd
                        position = 0
                        entry_price = 0.0

            # Clôture finale
            if position == 1:
                exit_price = closes[-1] * (1.0 - slippage_factor)
                raw_return = (exit_price - entry_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count
            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        sharpes[combo_idx] = (mean_ret / np.sqrt(variance)) * np.sqrt(252)
            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


    # ================================================================
    # BOLLINGER BEST SHORT 3i — miroir SHORT
    # ================================================================

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def _sweep_boll_level_short(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        bb_periods: np.ndarray,
        bb_stds: np.ndarray,
        entry_levels: np.ndarray,
        sl_levels: np.ndarray,
        tp_levels: np.ndarray,
        leverages: np.ndarray,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Sweep Bollinger level-based SHORT en Numba parallèle."""
        n_combos = len(bb_periods)
        n_bars = len(closes)

        total_pnls = np.zeros(n_combos, dtype=np.float64)
        sharpes = np.zeros(n_combos, dtype=np.float64)
        max_dds = np.zeros(n_combos, dtype=np.float64)
        win_rates = np.zeros(n_combos, dtype=np.float64)
        n_trades_out = np.zeros(n_combos, dtype=np.int64)

        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001

        for combo_idx in prange(n_combos):
            bb_p = int(bb_periods[combo_idx])
            bb_s = bb_stds[combo_idx]
            entry_lv = entry_levels[combo_idx]
            sl_lv = sl_levels[combo_idx]
            tp_lv = tp_levels[combo_idx]
            leverage = leverages[combo_idx]

            position = 0
            entry_price = 0.0
            stop_price = 0.0
            tp_price = 0.0
            equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0
            trade_count = 0
            winning_trades = 0
            returns_sum = 0.0
            returns_sq_sum = 0.0
            prev_signal = 0.0

            for i in range(bb_p, n_bars):
                # Calcul Bollinger inline
                sma = 0.0
                for j in range(bb_p):
                    sma += closes[i - bb_p + 1 + j]
                sma /= bb_p
                var = 0.0
                for j in range(bb_p):
                    diff = closes[i - bb_p + 1 + j] - sma
                    var += diff * diff
                std = np.sqrt(var / bb_p)
                upper = sma + bb_s * std
                lower = sma - bb_s * std
                total_dist = upper - lower

                if total_dist < 1e-10:
                    continue

                entry_pl = lower + entry_lv * total_dist   # ~upper band
                sl_pl = lower + sl_lv * total_dist         # au-dessus upper
                tp_pl = lower + tp_lv * total_dist         # vers lower

                close_price = closes[i]

                # Signal : SHORT quand close >= entry_price_level
                signal = -1.0 if close_price >= entry_pl else 0.0
                if signal == prev_signal:
                    signal = 0.0
                else:
                    prev_signal = signal if signal != 0.0 else prev_signal

                if position == 0 and signal == -1.0:
                    position = -1
                    entry_price = close_price * (1.0 - slippage_factor)
                    stop_price = sl_pl
                    tp_price = tp_pl
                elif position == -1:
                    exit_now = False
                    if highs[i] >= stop_price:
                        exit_now = True
                    elif lows[i] <= tp_price:
                        exit_now = True

                    if exit_now:
                        exit_price = close_price * (1.0 + slippage_factor)
                        raw_return = (entry_price - exit_price) / entry_price
                        net_return = raw_return - fees_factor
                        pnl = net_return * leverage * initial_capital
                        equity += pnl
                        trade_count += 1
                        if pnl > 0:
                            winning_trades += 1
                        returns_sum += net_return
                        returns_sq_sum += net_return * net_return
                        if equity > peak_equity:
                            peak_equity = equity
                        dd = (peak_equity - equity) / peak_equity * 100.0
                        if dd > max_dd:
                            max_dd = dd
                        position = 0
                        entry_price = 0.0

            # Clôture finale
            if position == -1:
                exit_price = closes[-1] * (1.0 + slippage_factor)
                raw_return = (entry_price - exit_price) / entry_price
                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                equity += pnl
                trade_count += 1
                if pnl > 0:
                    winning_trades += 1
                returns_sum += net_return
                returns_sq_sum += net_return * net_return

            total_pnls[combo_idx] = equity - initial_capital
            n_trades_out[combo_idx] = trade_count
            if trade_count > 0:
                win_rates[combo_idx] = (winning_trades / trade_count) * 100.0
                mean_ret = returns_sum / trade_count
                if trade_count > 1:
                    variance = (returns_sq_sum / trade_count) - (mean_ret * mean_ret)
                    if variance > 0:
                        sharpes[combo_idx] = (mean_ret / np.sqrt(variance)) * np.sqrt(252)
            max_dds[combo_idx] = max_dd

        return total_pnls, sharpes, max_dds, win_rates, n_trades_out


# ============================================================================
# FONCTION D'INTÉGRATION UI
# ============================================================================

def run_numba_sweep(
    df: pd.DataFrame,
    strategy_key: str,
    param_grid: List[Dict[str, Any]],
    initial_capital: float = 10000.0,
    fees_bps: float = 10.0,
    slippage_bps: float = 5.0,
    progress_callback: Optional[Callable[[int, int, Dict], None]] = None,
    result_chunk_callback: Optional[
        Callable[[List[Dict[str, Any]], int, int, Optional[Dict[str, Any]]], None]
    ] = None,
    return_arrays: bool = False,
    thread_override: Optional[int] = None,
    chunk_size_override: Optional[int] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    _param_arrays: Optional[Dict[str, np.ndarray]] = None,
    _ohlcv: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None,
) -> "Union[List[Dict[str, Any]], Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]":
    """
    Exécute un sweep Numba depuis l'UI.

    Args:
        df: DataFrame OHLCV avec colonnes 'close', 'high', 'low'
        strategy_key: Nom de la stratégie
        param_grid: Liste de dicts de paramètres
        initial_capital: Capital initial
        fees_bps: Frais en basis points
        slippage_bps: Slippage en basis points
        progress_callback: Optionnel, (completed, total, best_result) -> None
        result_chunk_callback: Optionnel, appelé après chaque chunk avec
                              (chunk_results, completed, total, best_result).
        return_arrays: Si True, retourne (pnls, sharpes, max_dds, win_rates, n_trades)
                       sans construire de dicts Python (10× moins de RAM).
        thread_override: Forcer un nombre de threads Numba (benchmark / debug).
        chunk_size_override: Forcer une taille de chunk en combinaisons.
        should_stop: Callback coopératif vérifié entre chunks.
        _param_arrays: Arrays pré-extraits alignés sur `param_grid` (hot path gros sweeps).
        _ohlcv: Tuple optionnel `(closes, highs, lows)` déjà matérialisé.

    Returns:
        Si return_arrays=False: Liste de résultats [{params, total_pnl, ...}, ...]
        Si return_arrays=True: Tuple (pnls, sharpes, max_dds, win_rates, n_trades) np.ndarray
    """
    if not HAS_NUMBA:
        raise ImportError("Numba non disponible")

    n_combos = len(param_grid)
    n_bars = len(df)
    if n_combos == 0:
        if return_arrays:
            empty_f = np.array([], dtype=np.float64)
            empty_i = np.array([], dtype=np.int64)
            return empty_f, empty_f.copy(), empty_f.copy(), empty_f.copy(), empty_i
        return []

    strategy_lower = strategy_key.lower()
    chunk_size = _get_numba_chunk_size(
        strategy_lower=strategy_lower,
        total_combos=n_combos,
        n_bars=n_bars,
        chunk_size_override=chunk_size_override,
    )
    threads = _get_numba_thread_count(
        strategy_lower=strategy_lower,
        chunk_size=chunk_size,
        n_bars=n_bars,
        thread_override=thread_override,
    )
    budget_gb = _get_numba_sweep_memory_budget_gb()
    bytes_per_combo = _estimate_numba_sweep_bytes_per_combo(strategy_lower)
    mem_estimate_mb = ((n_combos * bytes_per_combo) + (n_bars * 3 * 8)) / (1024 * 1024)
    emit_console = progress_callback is not None or not return_arrays

    logger.info(
        "[NUMBA] Sweep %s: %s combos × %s bars | est=%.1f MB | chunk=%s | threads=%s | budget=%.1f GB",
        strategy_lower,
        f"{n_combos:,}",
        f"{n_bars:,}",
        mem_estimate_mb,
        f"{chunk_size:,}",
        threads,
        budget_gb,
    )
    if emit_console:
        print(
            f"[NUMBA] Sweep {strategy_lower}: {n_combos:,} combos × {n_bars:,} bars | "
            f"chunk={chunk_size:,} | threads={threads} | est={mem_estimate_mb:.1f} MB",
            flush=True,
        )

    if _ohlcv is None:
        closes = np.asarray(df["close"].values, dtype=np.float64)
        highs = np.asarray(df["high"].values, dtype=np.float64)
        lows = np.asarray(df["low"].values, dtype=np.float64)
    else:
        closes = np.asarray(_ohlcv[0], dtype=np.float64)
        highs = np.asarray(_ohlcv[1], dtype=np.float64)
        lows = np.asarray(_ohlcv[2], dtype=np.float64)

    param_arrays = _param_arrays or extract_strategy_params(strategy_key, param_grid)
    for key, values in param_arrays.items():
        if len(values) != n_combos:
            raise ValueError(
                f"_param_arrays['{key}'] a une longueur {len(values)} != {n_combos}"
            )

    all_pnls = np.empty(n_combos, dtype=np.float64)
    all_sharpes = np.empty(n_combos, dtype=np.float64)
    all_max_dds = np.empty(n_combos, dtype=np.float64)
    all_win_rates = np.empty(n_combos, dtype=np.float64)
    all_n_trades = np.empty(n_combos, dtype=np.int64)
    results: List[Dict[str, Any]] = []
    best_result: Optional[Dict[str, Any]] = None
    best_pnl = float("-inf")
    completed = 0

    start_time = time.perf_counter()
    kernel_elapsed = 0.0
    build_elapsed = 0.0

    with _numba_thread_context(threads) as applied_threads:
        logger.info("[NUMBA] Threads appliqués: %s", applied_threads)

        for chunk_start in range(0, n_combos, chunk_size):
            if should_stop is not None and should_stop():
                logger.info("[NUMBA] Stop demandé après %s/%s combinaisons", completed, n_combos)
                break
            chunk_end = min(chunk_start + chunk_size, n_combos)
            param_arrays_chunk = _slice_param_arrays(param_arrays, chunk_start, chunk_end)
            needs_python_chunk = (not return_arrays) or progress_callback is not None
            params_chunk = (
                param_grid[chunk_start:chunk_end]
                if needs_python_chunk
                else []
            )

            t_kernel = time.perf_counter()
            pnls, sharpes, max_dds, win_rates, n_trades = _run_numba_kernel_chunk(
                strategy_lower=strategy_lower,
                params_chunk=params_chunk,
                closes=closes,
                highs=highs,
                lows=lows,
                initial_capital=initial_capital,
                fees_bps=fees_bps,
                slippage_bps=slippage_bps,
                param_arrays_chunk=param_arrays_chunk,
            )
            kernel_elapsed += time.perf_counter() - t_kernel

            all_pnls[chunk_start:chunk_end] = pnls
            all_sharpes[chunk_start:chunk_end] = sharpes
            all_max_dds[chunk_start:chunk_end] = max_dds
            all_win_rates[chunk_start:chunk_end] = win_rates
            all_n_trades[chunk_start:chunk_end] = n_trades

            local_best_idx = int(np.argmax(pnls))
            local_best_pnl = float(pnls[local_best_idx])
            if progress_callback is not None or result_chunk_callback is not None:
                local_best_result = _make_best_result_dict(
                    param_grid[chunk_start:chunk_end],
                    pnls,
                    sharpes,
                    max_dds,
                    win_rates,
                    n_trades,
                    local_best_idx,
                )
                if local_best_pnl > best_pnl or best_result is None:
                    best_pnl = local_best_pnl
                    best_result = local_best_result

            completed = chunk_end

            if not return_arrays:
                t_build = time.perf_counter()
                chunk_results = _build_results_chunk(
                    params_chunk=params_chunk,
                    pnls=pnls,
                    sharpes=sharpes,
                    max_dds=max_dds,
                    win_rates=win_rates,
                    n_trades=n_trades,
                )
                results.extend(chunk_results)
                build_elapsed += time.perf_counter() - t_build
                if result_chunk_callback is not None:
                    result_chunk_callback(chunk_results, completed, n_combos, best_result)

            if progress_callback and best_result is not None:
                progress_callback(completed, n_combos, best_result)

            if emit_console and (completed == n_combos or completed % max(chunk_size, 100000) == 0):
                elapsed = time.perf_counter() - start_time
                throughput = completed / elapsed if elapsed > 0 else 0.0
                print(
                    f"[NUMBA] Progression: {completed:,}/{n_combos:,} "
                    f"({completed / n_combos * 100:.1f}%) | {throughput:,.0f} bt/s",
                    flush=True,
                )

    total_time = time.perf_counter() - start_time

    if return_arrays:
        logger.info(
            "[NUMBA] Arrays: %s combos en %.2fs (%.0f bt/s)",
            f"{completed:,}",
            total_time,
            completed / max(total_time, 1e-9),
        )
        return (
            all_pnls[:completed],
            all_sharpes[:completed],
            all_max_dds[:completed],
            all_win_rates[:completed],
            all_n_trades[:completed],
        )

    if emit_console:
        print(
            f"⚡ Numba sweep TOTAL: {completed:,} combos en {total_time:.2f}s "
            f"({completed / max(total_time, 1e-9):,.0f} bt/s)",
            flush=True,
        )
        print(
            f"  • Kernel Numba: {kernel_elapsed:.2f}s ({completed / max(kernel_elapsed, 1e-9):,.0f} bt/s)",
            flush=True,
        )
        print(f"  • Construction: {build_elapsed:.2f}s", flush=True)

    return results


if __name__ == "__main__":
    benchmark_sweep_numba(n_combos=1000, n_bars=10000)
