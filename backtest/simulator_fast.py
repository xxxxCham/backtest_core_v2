"""
Backtest Core - Fast Trade Simulator (Numba-accelerated)
=======================================================

Version haute performance du simulateur de trades utilisant Numba JIT.
Jusqu'à 100x plus rapide que la version Python pure.

Usage:
    from backtest.simulator_fast import simulate_trades_fast

    trades_df = simulate_trades_fast(df, signals, params)
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Numba pour JIT compilation
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

from utils.log import get_logger

logger = get_logger(__name__)


# =============================================================================
# NUMBA-OPTIMIZED CORE (JIT-compiled)
# =============================================================================

if HAS_NUMBA:
    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False)
    def _simulate_trades_numba(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        signals: np.ndarray,
        leverage: float,
        k_sl: float,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
               np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
        """
        Cœur de simulation JIT-compilé.

        Retourne les arrays numpy des trades pour reconstruction DataFrame.
        """
        n_bars = len(closes)

        # Pré-allouer les arrays de sortie (max = n_bars/2 trades)
        max_trades = n_bars // 2 + 1
        entry_indices = np.zeros(max_trades, dtype=np.int64)
        exit_indices = np.zeros(max_trades, dtype=np.int64)
        sides = np.zeros(max_trades, dtype=np.int64)  # 1=long, -1=short
        entry_prices = np.zeros(max_trades, dtype=np.float64)
        exit_prices = np.zeros(max_trades, dtype=np.float64)
        pnls = np.zeros(max_trades, dtype=np.float64)
        returns_pct = np.zeros(max_trades, dtype=np.float64)
        exit_reasons = np.zeros(max_trades, dtype=np.int64)  # 0=signal, 1=sl, 2=end
        sizes = np.zeros(max_trades, dtype=np.float64)

        # État position
        position = 0
        entry_price = 0.0
        entry_idx = 0
        trade_count = 0

        # Constantes précalculées
        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001
        sl_pct = k_sl * 0.01

        for i in range(n_bars):
            close_price = closes[i]
            signal = signals[i]

            # === Entrée en position ===
            if position == 0 and signal != 0:
                position = int(signal)
                entry_price = close_price * (1.0 + slippage_factor * position)
                entry_idx = i

            # === En position: vérifier sortie ===
            elif position != 0:
                exit_condition = False
                exit_reason = 0

                # 1. Signal opposé
                if signal != 0 and signal != position:
                    exit_condition = True
                    exit_reason = 0  # signal_reverse

                # 2. Stop-loss (intrabar check avec high/low)
                elif position == 1:
                    sl_price = entry_price * (1.0 - sl_pct)
                    if lows[i] <= sl_price:
                        exit_condition = True
                        exit_reason = 1  # stop_loss
                elif position == -1:
                    sl_price = entry_price * (1.0 + sl_pct)
                    if highs[i] >= sl_price:
                        exit_condition = True
                        exit_reason = 1  # stop_loss

                # === Exécuter sortie ===
                if exit_condition:
                    exit_price = close_price * (1.0 - slippage_factor * position)

                    # PnL
                    if position == 1:
                        raw_return = (exit_price - entry_price) / entry_price
                    else:
                        raw_return = (entry_price - exit_price) / entry_price

                    net_return = raw_return - fees_factor
                    pnl = net_return * leverage * initial_capital
                    position_size = leverage * initial_capital / entry_price

                    # Enregistrer trade
                    entry_indices[trade_count] = entry_idx
                    exit_indices[trade_count] = i
                    sides[trade_count] = position
                    entry_prices[trade_count] = entry_price
                    exit_prices[trade_count] = exit_price
                    pnls[trade_count] = pnl
                    returns_pct[trade_count] = net_return * 100.0
                    exit_reasons[trade_count] = exit_reason
                    sizes[trade_count] = position_size
                    trade_count += 1

                    # Reset
                    position = 0
                    entry_price = 0.0

                    # Nouvelle position si signal présent
                    if signal != 0:
                        position = int(signal)
                        entry_price = close_price * (1.0 + slippage_factor * position)
                        entry_idx = i

        # === Trade final si position ouverte ===
        if position != 0:
            final_price = closes[-1] * (1.0 - slippage_factor * position)

            if position == 1:
                raw_return = (final_price - entry_price) / entry_price
            else:
                raw_return = (entry_price - final_price) / entry_price

            net_return = raw_return - fees_factor
            pnl = net_return * leverage * initial_capital
            position_size = leverage * initial_capital / entry_price

            entry_indices[trade_count] = entry_idx
            exit_indices[trade_count] = n_bars - 1
            sides[trade_count] = position
            entry_prices[trade_count] = entry_price
            exit_prices[trade_count] = final_price
            pnls[trade_count] = pnl
            returns_pct[trade_count] = net_return * 100.0
            exit_reasons[trade_count] = 2  # end_of_data
            sizes[trade_count] = position_size
            trade_count += 1

        return (
            entry_indices[:trade_count],
            exit_indices[:trade_count],
            sides[:trade_count],
            entry_prices[:trade_count],
            exit_prices[:trade_count],
            pnls[:trade_count],
            returns_pct[:trade_count],
            exit_reasons[:trade_count],
            sizes[:trade_count],
            trade_count
        )

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False)
    def _calculate_equity_numba(
        n_bars: int,
        entry_indices: np.ndarray,
        exit_indices: np.ndarray,
        pnls: np.ndarray,
        entry_prices: np.ndarray,
        sizes: np.ndarray,
        side_signs: np.ndarray,
        close_prices: np.ndarray,
        initial_capital: float,
    ) -> np.ndarray:
        """
        Calcule l'equity mark-to-market en O(n_bars + n_trades).

        Maintient une sémantique identique au moteur de référence:
        - capital réalisé crédité à la barre de sortie
        - P&L non réalisé des positions ouvertes sur l'intervalle [entry, exit)
        """
        capital_changes = np.zeros(n_bars, dtype=np.float64)
        long_size_delta = np.zeros(n_bars + 1, dtype=np.float64)
        short_size_delta = np.zeros(n_bars + 1, dtype=np.float64)
        long_entry_delta = np.zeros(n_bars + 1, dtype=np.float64)
        short_entry_delta = np.zeros(n_bars + 1, dtype=np.float64)

        for i in range(len(exit_indices)):
            entry_idx = entry_indices[i]
            exit_idx = exit_indices[i]

            if entry_idx < 0:
                entry_idx = 0
            elif entry_idx > n_bars:
                entry_idx = n_bars

            if exit_idx < 0:
                exit_idx = 0
            elif exit_idx > n_bars:
                exit_idx = n_bars

            if 0 <= exit_idx < n_bars:
                capital_changes[exit_idx] += pnls[i]

            if entry_idx >= exit_idx:
                continue

            size = sizes[i]
            entry_notional = entry_prices[i] * size

            if side_signs[i] >= 0:
                long_size_delta[entry_idx] += size
                long_size_delta[exit_idx] -= size
                long_entry_delta[entry_idx] += entry_notional
                long_entry_delta[exit_idx] -= entry_notional
            else:
                short_size_delta[entry_idx] += size
                short_size_delta[exit_idx] -= size
                short_entry_delta[entry_idx] += entry_notional
                short_entry_delta[exit_idx] -= entry_notional

        equity = np.empty(n_bars, dtype=np.float64)
        realized_pnl = 0.0
        active_long_size = 0.0
        active_short_size = 0.0
        active_long_entry = 0.0
        active_short_entry = 0.0

        for i in range(n_bars):
            realized_pnl += capital_changes[i]
            active_long_size += long_size_delta[i]
            active_short_size += short_size_delta[i]
            active_long_entry += long_entry_delta[i]
            active_short_entry += short_entry_delta[i]

            unrealized_pnl = (
                close_prices[i] * active_long_size
                - active_long_entry
                + active_short_entry
                - close_prices[i] * active_short_size
            )
            equity[i] = initial_capital + realized_pnl + unrealized_pnl

        return equity

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False)
    def _simulate_trades_numba_bb_levels(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        signals: np.ndarray,
        leverage: float,
        k_sl: float,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
        bb_stop_long: np.ndarray,
        bb_tp_long: np.ndarray,
        bb_stop_short: np.ndarray,
        bb_tp_short: np.ndarray,
        bb_pos_low: np.ndarray,
        bb_pos_high: np.ndarray,
        sl_level_arr: np.ndarray,
        tp_level_arr: np.ndarray,
        sl_level_param: float,
        tp_level_param: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
               np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
        """
        Kernel Numba JIT avec support BB-levels stop-loss/take-profit.

        Version 10-100× plus rapide que fallback Python grâce à JIT compilation.
        Gère dynamiquement les niveaux de SL/TP basés sur Bollinger Bands.
        """
        n_bars = len(closes)

        # Pré-allouer les arrays de sortie
        max_trades = n_bars // 2 + 1
        entry_indices = np.zeros(max_trades, dtype=np.int64)
        exit_indices = np.zeros(max_trades, dtype=np.int64)
        sides = np.zeros(max_trades, dtype=np.int64)
        entry_prices = np.zeros(max_trades, dtype=np.float64)
        exit_prices = np.zeros(max_trades, dtype=np.float64)
        pnls = np.zeros(max_trades, dtype=np.float64)
        returns_pct = np.zeros(max_trades, dtype=np.float64)
        exit_reasons = np.zeros(max_trades, dtype=np.int64)
        sizes = np.zeros(max_trades, dtype=np.float64)

        # État position
        position = 0
        entry_price = 0.0
        entry_idx = 0
        trade_count = 0

        # États BB levels
        stop_price = np.nan
        tp_price = np.nan
        stop_level = np.nan
        tp_level = np.nan
        use_bb_pos = False
        has_bb_stop = False
        has_bb_tp = False

        # Constantes précalculées
        slippage_factor = slippage_bps * 0.0001
        fees_factor = fees_bps * 2 * 0.0001
        sl_pct = k_sl * 0.01

        for i in range(n_bars):
            close_price = closes[i]
            signal = signals[i]

            # === ENTRÉE EN POSITION ===
            if position == 0 and signal != 0:
                position = int(signal)
                entry_price = close_price * (1.0 + slippage_factor * position)
                entry_idx = i

                # Initialiser BB levels pour cette position (logique inline)
                stop_price = np.nan
                tp_price = np.nan
                stop_level = np.nan
                tp_level = np.nan
                use_bb_pos = False
                has_bb_stop = False
                has_bb_tp = False

                if position == 1:
                    # LONG: utiliser bb_stop_long et bb_tp_long
                    stop_price = bb_stop_long[i]
                    has_bb_stop = not np.isnan(stop_price)
                    tp_price = bb_tp_long[i]
                    has_bb_tp = not np.isnan(tp_price)
                else:
                    # SHORT: utiliser bb_stop_short et bb_tp_short
                    stop_price = bb_stop_short[i]
                    has_bb_stop = not np.isnan(stop_price)
                    tp_price = bb_tp_short[i]
                    has_bb_tp = not np.isnan(tp_price)

                # Fallback sur bb_pos_low/high si pas de BB direct
                if not (has_bb_stop or has_bb_tp):
                    use_bb_pos = True
                    stop_level = sl_level_arr[i] if not np.isnan(sl_level_arr[i]) else sl_level_param
                    tp_level = tp_level_arr[i] if not np.isnan(tp_level_arr[i]) else tp_level_param
                    has_bb_stop = not np.isnan(stop_level)
                    has_bb_tp = not np.isnan(tp_level)

            # === EN POSITION: VÉRIFIER SORTIE ===
            elif position != 0:
                exit_condition = False
                exit_reason = 0
                sl_hit = False
                tp_hit = False

                # Check SL/TP basé sur BB levels ou price levels
                if use_bb_pos:
                    # Utiliser bb_pos_low/high comme indicateurs de position
                    if position == 1:
                        if has_bb_stop and bb_pos_low[i] <= stop_level:
                            sl_hit = True
                        if has_bb_tp and bb_pos_high[i] >= tp_level:
                            tp_hit = True
                    else:  # SHORT
                        if has_bb_stop and bb_pos_high[i] >= stop_level:
                            sl_hit = True
                        if has_bb_tp and bb_pos_low[i] <= tp_level:
                            tp_hit = True
                else:
                    # Utiliser price directement
                    if has_bb_stop:
                        if position == 1 and lows[i] <= stop_price:
                            sl_hit = True
                        elif position == -1 and highs[i] >= stop_price:
                            sl_hit = True
                    if has_bb_tp:
                        if position == 1 and highs[i] >= tp_price:
                            tp_hit = True
                        elif position == -1 and lows[i] <= tp_price:
                            tp_hit = True

                # Fallback SL classique (k_sl) si pas de BB stop
                if not sl_hit and not has_bb_stop:
                    if position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                        sl_hit = True
                    elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                        sl_hit = True

                # Déterminer raison sortie
                if sl_hit:
                    exit_condition = True
                    exit_reason = 1  # stop_loss
                elif tp_hit:
                    exit_condition = True
                    exit_reason = 3  # take_profit
                elif signal != 0 and signal != position:
                    exit_condition = True
                    exit_reason = 0  # signal_reverse

                # === EXÉCUTER SORTIE ===
                if exit_condition:
                    exit_price = close_price * (1.0 - slippage_factor * position)

                    # Calcul PnL
                    if position == 1:
                        raw_return = (exit_price - entry_price) / entry_price
                    else:
                        raw_return = (entry_price - exit_price) / entry_price

                    net_return = raw_return - fees_factor
                    pnl = net_return * leverage * initial_capital
                    position_size = leverage * initial_capital / entry_price

                    # Enregistrer trade
                    entry_indices[trade_count] = entry_idx
                    exit_indices[trade_count] = i
                    sides[trade_count] = position
                    entry_prices[trade_count] = entry_price
                    exit_prices[trade_count] = exit_price
                    pnls[trade_count] = pnl
                    returns_pct[trade_count] = net_return * 100.0
                    exit_reasons[trade_count] = exit_reason
                    sizes[trade_count] = position_size
                    trade_count += 1

                    # Reset position
                    position = 0
                    entry_price = 0.0
                    stop_price = np.nan
                    tp_price = np.nan
                    stop_level = np.nan
                    tp_level = np.nan
                    use_bb_pos = False
                    has_bb_stop = False
                    has_bb_tp = False

                    # Nouvelle position immédiate si signal présent
                    if signal != 0:
                        position = int(signal)
                        entry_price = close_price * (1.0 + slippage_factor * position)
                        entry_idx = i

                        # Réinitialiser BB levels
                        stop_price = np.nan
                        tp_price = np.nan
                        stop_level = np.nan
                        tp_level = np.nan
                        use_bb_pos = False
                        has_bb_stop = False
                        has_bb_tp = False

                        if position == 1:
                            stop_price = bb_stop_long[i]
                            has_bb_stop = not np.isnan(stop_price)
                            tp_price = bb_tp_long[i]
                            has_bb_tp = not np.isnan(tp_price)
                        else:
                            stop_price = bb_stop_short[i]
                            has_bb_stop = not np.isnan(stop_price)
                            tp_price = bb_tp_short[i]
                            has_bb_tp = not np.isnan(tp_price)

                        if not (has_bb_stop or has_bb_tp):
                            use_bb_pos = True
                            stop_level = sl_level_arr[i] if not np.isnan(sl_level_arr[i]) else sl_level_param
                            tp_level = tp_level_arr[i] if not np.isnan(tp_level_arr[i]) else tp_level_param
                            has_bb_stop = not np.isnan(stop_level)
                            has_bb_tp = not np.isnan(tp_level)

        # === TRADE FINAL SI POSITION OUVERTE ===
        if position != 0:
            final_price = closes[-1] * (1.0 - slippage_factor * position)

            if position == 1:
                raw_return = (final_price - entry_price) / entry_price
            else:
                raw_return = (entry_price - final_price) / entry_price

            net_return = raw_return - fees_factor
            pnl = net_return * leverage * initial_capital
            position_size = leverage * initial_capital / entry_price

            entry_indices[trade_count] = entry_idx
            exit_indices[trade_count] = n_bars - 1
            sides[trade_count] = position
            entry_prices[trade_count] = entry_price
            exit_prices[trade_count] = final_price
            pnls[trade_count] = pnl
            returns_pct[trade_count] = net_return * 100.0
            exit_reasons[trade_count] = 2  # end_of_data
            sizes[trade_count] = position_size
            trade_count += 1

        return (
            entry_indices[:trade_count],
            exit_indices[:trade_count],
            sides[:trade_count],
            entry_prices[:trade_count],
            exit_prices[:trade_count],
            pnls[:trade_count],
            returns_pct[:trade_count],
            exit_reasons[:trade_count],
            sizes[:trade_count],
            trade_count
        )


# =============================================================================
# NUMPY VECTORIZED FALLBACK (si Numba non disponible)
# =============================================================================

def _simulate_trades_numpy(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    signals: np.ndarray,
    leverage: float,
    k_sl: float,
    initial_capital: float,
    fees_bps: float,
    slippage_bps: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Version numpy pure (fallback si pas de Numba)."""
    n_bars = len(closes)

    # Pré-allouer
    max_trades = n_bars // 2 + 1
    entry_indices = np.zeros(max_trades, dtype=np.int64)
    exit_indices = np.zeros(max_trades, dtype=np.int64)
    sides = np.zeros(max_trades, dtype=np.int64)
    entry_prices = np.zeros(max_trades, dtype=np.float64)
    exit_prices = np.zeros(max_trades, dtype=np.float64)
    pnls = np.zeros(max_trades, dtype=np.float64)
    returns_pct = np.zeros(max_trades, dtype=np.float64)
    exit_reasons = np.zeros(max_trades, dtype=np.int64)
    sizes = np.zeros(max_trades, dtype=np.float64)

    position = 0
    entry_price = 0.0
    entry_idx = 0
    trade_count = 0

    slippage_factor = slippage_bps * 0.0001
    fees_factor = fees_bps * 2 * 0.0001
    sl_pct = k_sl * 0.01

    for i in range(n_bars):
        close_price = closes[i]
        signal = signals[i]

        if position == 0 and signal != 0:
            position = int(signal)
            entry_price = close_price * (1.0 + slippage_factor * position)
            entry_idx = i

        elif position != 0:
            exit_condition = False
            exit_reason = 0

            if signal != 0 and signal != position:
                exit_condition = True
                exit_reason = 0
            elif position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                exit_condition = True
                exit_reason = 1
            elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                exit_condition = True
                exit_reason = 1

            if exit_condition:
                exit_price = close_price * (1.0 - slippage_factor * position)

                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price

                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                position_size = leverage * initial_capital / entry_price

                entry_indices[trade_count] = entry_idx
                exit_indices[trade_count] = i
                sides[trade_count] = position
                entry_prices[trade_count] = entry_price
                exit_prices[trade_count] = exit_price
                pnls[trade_count] = pnl
                returns_pct[trade_count] = net_return * 100.0
                exit_reasons[trade_count] = exit_reason
                sizes[trade_count] = position_size
                trade_count += 1

                position = 0
                entry_price = 0.0

                if signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)
                    entry_idx = i

    # Trade final
    if position != 0:
        final_price = closes[-1] * (1.0 - slippage_factor * position)

        if position == 1:
            raw_return = (final_price - entry_price) / entry_price
        else:
            raw_return = (entry_price - final_price) / entry_price

        net_return = raw_return - fees_factor
        pnl = net_return * leverage * initial_capital
        position_size = leverage * initial_capital / entry_price

        entry_indices[trade_count] = entry_idx
        exit_indices[trade_count] = n_bars - 1
        sides[trade_count] = position
        entry_prices[trade_count] = entry_price
        exit_prices[trade_count] = final_price
        pnls[trade_count] = pnl
        returns_pct[trade_count] = net_return * 100.0
        exit_reasons[trade_count] = 2
        sizes[trade_count] = position_size
        trade_count += 1

    return (
        entry_indices[:trade_count],
        exit_indices[:trade_count],
        sides[:trade_count],
        entry_prices[:trade_count],
        exit_prices[:trade_count],
        pnls[:trade_count],
        returns_pct[:trade_count],
        exit_reasons[:trade_count],
        sizes[:trade_count],
        trade_count
    )


# =============================================================================
# PUBLIC API
# =============================================================================

EXIT_REASON_MAP = {0: "signal_reverse", 1: "stop_loss", 2: "end_of_data", 3: "take_profit"}


def _simulate_trades_numpy_bb_levels(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    signals: np.ndarray,
    leverage: float,
    k_sl: float,
    initial_capital: float,
    fees_bps: float,
    slippage_bps: float,
    bb_stop_long: Optional[np.ndarray],
    bb_tp_long: Optional[np.ndarray],
    bb_stop_short: Optional[np.ndarray],
    bb_tp_short: Optional[np.ndarray],
    bb_pos_low: Optional[np.ndarray],
    bb_pos_high: Optional[np.ndarray],
    sl_level_arr: Optional[np.ndarray],
    tp_level_arr: Optional[np.ndarray],
    sl_level_param: float,
    tp_level_param: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Fallback numpy loop with BB-level stop-loss/take-profit support."""
    n_bars = len(closes)

    max_trades = n_bars // 2 + 1
    entry_indices = np.zeros(max_trades, dtype=np.int64)
    exit_indices = np.zeros(max_trades, dtype=np.int64)
    sides = np.zeros(max_trades, dtype=np.int64)
    entry_prices = np.zeros(max_trades, dtype=np.float64)
    exit_prices = np.zeros(max_trades, dtype=np.float64)
    pnls = np.zeros(max_trades, dtype=np.float64)
    returns_pct = np.zeros(max_trades, dtype=np.float64)
    exit_reasons = np.zeros(max_trades, dtype=np.int64)
    sizes = np.zeros(max_trades, dtype=np.float64)

    position = 0
    entry_price = 0.0
    entry_idx = 0
    trade_count = 0

    stop_price = np.nan
    tp_price = np.nan
    stop_level = np.nan
    tp_level = np.nan
    use_bb_pos = False
    has_bb_stop = False
    has_bb_tp = False

    slippage_factor = slippage_bps * 0.0001
    fees_factor = fees_bps * 2 * 0.0001
    sl_pct = k_sl * 0.01

    def _init_trade_levels(bar_idx: int, pos: int) -> Tuple[float, float, float, float, bool, bool, bool]:
        stop_p = np.nan
        tp_p = np.nan
        stop_l = np.nan
        tp_l = np.nan
        use_pos = False
        has_stop = False
        has_tp = False

        if pos == 1:
            if bb_stop_long is not None:
                stop_p = bb_stop_long[bar_idx]
                has_stop = not np.isnan(stop_p)
            if bb_tp_long is not None:
                tp_p = bb_tp_long[bar_idx]
                has_tp = not np.isnan(tp_p)
        else:
            if bb_stop_short is not None:
                stop_p = bb_stop_short[bar_idx]
                has_stop = not np.isnan(stop_p)
            if bb_tp_short is not None:
                tp_p = bb_tp_short[bar_idx]
                has_tp = not np.isnan(tp_p)

        if not (has_stop or has_tp) and bb_pos_low is not None and bb_pos_high is not None:
            use_pos = True
            stop_l = sl_level_arr[bar_idx] if sl_level_arr is not None else sl_level_param
            tp_l = tp_level_arr[bar_idx] if tp_level_arr is not None else tp_level_param
            has_stop = not np.isnan(stop_l)
            has_tp = not np.isnan(tp_l)

        return stop_p, tp_p, stop_l, tp_l, use_pos, has_stop, has_tp

    for i in range(n_bars):
        close_price = closes[i]
        signal = signals[i]

        if position == 0 and signal != 0:
            position = int(signal)
            entry_price = close_price * (1.0 + slippage_factor * position)
            entry_idx = i
            stop_price, tp_price, stop_level, tp_level, use_bb_pos, has_bb_stop, has_bb_tp = _init_trade_levels(i, position)

        elif position != 0:
            exit_condition = False
            exit_reason = 0

            sl_hit = False
            tp_hit = False

            if use_bb_pos:
                if position == 1:
                    if has_bb_stop and bb_pos_low[i] <= stop_level:
                        sl_hit = True
                    if has_bb_tp and bb_pos_high[i] >= tp_level:
                        tp_hit = True
                else:
                    if has_bb_stop and bb_pos_high[i] >= stop_level:
                        sl_hit = True
                    if has_bb_tp and bb_pos_low[i] <= tp_level:
                        tp_hit = True
            else:
                if has_bb_stop:
                    if position == 1 and lows[i] <= stop_price:
                        sl_hit = True
                    elif position == -1 and highs[i] >= stop_price:
                        sl_hit = True
                if has_bb_tp:
                    if position == 1 and highs[i] >= tp_price:
                        tp_hit = True
                    elif position == -1 and lows[i] <= tp_price:
                        tp_hit = True

            if not sl_hit and not has_bb_stop:
                if position == 1 and lows[i] <= entry_price * (1.0 - sl_pct):
                    sl_hit = True
                elif position == -1 and highs[i] >= entry_price * (1.0 + sl_pct):
                    sl_hit = True

            if sl_hit:
                exit_condition = True
                exit_reason = 1
            elif tp_hit:
                exit_condition = True
                exit_reason = 3
            elif signal != 0 and signal != position:
                exit_condition = True
                exit_reason = 0

            if exit_condition:
                exit_price = close_price * (1.0 - slippage_factor * position)

                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price

                net_return = raw_return - fees_factor
                pnl = net_return * leverage * initial_capital
                position_size = leverage * initial_capital / entry_price

                entry_indices[trade_count] = entry_idx
                exit_indices[trade_count] = i
                sides[trade_count] = position
                entry_prices[trade_count] = entry_price
                exit_prices[trade_count] = exit_price
                pnls[trade_count] = pnl
                returns_pct[trade_count] = net_return * 100.0
                exit_reasons[trade_count] = exit_reason
                sizes[trade_count] = position_size
                trade_count += 1

                position = 0
                entry_price = 0.0
                stop_price = np.nan
                tp_price = np.nan
                stop_level = np.nan
                tp_level = np.nan
                use_bb_pos = False
                has_bb_stop = False
                has_bb_tp = False

                if signal != 0:
                    position = int(signal)
                    entry_price = close_price * (1.0 + slippage_factor * position)
                    entry_idx = i
                    stop_price, tp_price, stop_level, tp_level, use_bb_pos, has_bb_stop, has_bb_tp = _init_trade_levels(i, position)

    if position != 0:
        final_price = closes[-1] * (1.0 - slippage_factor * position)

        if position == 1:
            raw_return = (final_price - entry_price) / entry_price
        else:
            raw_return = (entry_price - final_price) / entry_price

        net_return = raw_return - fees_factor
        pnl = net_return * leverage * initial_capital
        position_size = leverage * initial_capital / entry_price

        entry_indices[trade_count] = entry_idx
        exit_indices[trade_count] = n_bars - 1
        sides[trade_count] = position
        entry_prices[trade_count] = entry_price
        exit_prices[trade_count] = final_price
        pnls[trade_count] = pnl
        returns_pct[trade_count] = net_return * 100.0
        exit_reasons[trade_count] = 2
        sizes[trade_count] = position_size
        trade_count += 1

    return (
        entry_indices[:trade_count],
        exit_indices[:trade_count],
        sides[:trade_count],
        entry_prices[:trade_count],
        exit_prices[:trade_count],
        pnls[:trade_count],
        returns_pct[:trade_count],
        exit_reasons[:trade_count],
        sizes[:trade_count],
        trade_count
    )


def simulate_trades_fast(
    df: pd.DataFrame,
    signals: pd.Series,
    params: Dict[str, Any],
) -> pd.DataFrame:
    """
    Simule l'exécution des trades avec optimisation Numba.

    10-100x plus rapide que simulate_trades() standard.

    Args:
        df: DataFrame OHLCV avec index datetime
        signals: Série de signaux (+1, -1, 0)
        params: Paramètres de trading

    Returns:
        DataFrame des trades
    """
    # Extraire paramètres
    leverage = float(params.get("leverage", 1))
    k_sl = float(params.get("k_sl", 1.5))
    initial_capital = float(params.get("initial_capital", 10000.0))
    fees_bps = float(params.get("fees_bps", 10.0))
    slippage_bps = float(params.get("slippage_bps", 5.0))

    # Convertir en arrays numpy (contiguous pour performance)
    closes = np.ascontiguousarray(df["close"].values, dtype=np.float64)
    highs = np.ascontiguousarray(df["high"].values, dtype=np.float64)
    lows = np.ascontiguousarray(df["low"].values, dtype=np.float64)
    signal_arr = np.ascontiguousarray(
        signals.values if hasattr(signals, "values") else signals,
        dtype=np.float64
    )

    bb_stop_long = (
        np.ascontiguousarray(df["bb_stop_long"].values, dtype=np.float64)
        if "bb_stop_long" in df.columns else None
    )
    bb_tp_long = (
        np.ascontiguousarray(df["bb_tp_long"].values, dtype=np.float64)
        if "bb_tp_long" in df.columns else None
    )
    bb_stop_short = (
        np.ascontiguousarray(df["bb_stop_short"].values, dtype=np.float64)
        if "bb_stop_short" in df.columns else None
    )
    bb_tp_short = (
        np.ascontiguousarray(df["bb_tp_short"].values, dtype=np.float64)
        if "bb_tp_short" in df.columns else None
    )
    bb_pos_low = (
        np.ascontiguousarray(df["bb_pos_low"].values, dtype=np.float64)
        if "bb_pos_low" in df.columns else None
    )
    bb_pos_high = (
        np.ascontiguousarray(df["bb_pos_high"].values, dtype=np.float64)
        if "bb_pos_high" in df.columns else None
    )
    sl_level_arr = (
        np.ascontiguousarray(df["sl_level"].values, dtype=np.float64)
        if "sl_level" in df.columns else None
    )
    tp_level_arr = (
        np.ascontiguousarray(df["tp_level"].values, dtype=np.float64)
        if "tp_level" in df.columns else None
    )
    sl_level_param = params.get("sl_level", np.nan)
    if sl_level_param is None:
        sl_level_param = np.nan
    sl_level_param = float(sl_level_param)
    tp_level_param = params.get("tp_level", np.nan)
    if tp_level_param is None:
        tp_level_param = np.nan
    tp_level_param = float(tp_level_param)

    use_bb_levels = any(
        arr is not None for arr in (
            bb_stop_long,
            bb_tp_long,
            bb_stop_short,
            bb_tp_short,
            bb_pos_low,
            bb_pos_high,
        )
    )

    # ========================================================================
    # DISPATCH OPTIMISÉ : Prioriser Numba JIT (10-100× plus rapide)
    # ========================================================================

    if use_bb_levels:
        # BB levels actifs → utiliser kernel spécialisé
        if HAS_NUMBA:
            # ✅ SOLUTION A : Kernel Numba JIT avec BB levels (RAPIDE)
            logger.debug("Backend: numba_bb_levels (JIT-compiled)")

            # ⚡ Performance: cache fallback NaN réutilisable (évite allocations GC)
            # Numba requiert arrays (pas None) → fallback NaN array si None
            n_bars = len(closes)

            # Cache thread-local pour éviter allocations répétées (gain mémoire + GC)
            if not hasattr(simulate_trades_fast, '_nan_cache') or len(simulate_trades_fast._nan_cache) != n_bars:
                simulate_trades_fast._nan_cache = np.full(n_bars, np.nan, dtype=np.float64)
            _nan_fallback = simulate_trades_fast._nan_cache

            bb_stop_long_arr = bb_stop_long if bb_stop_long is not None else _nan_fallback
            bb_tp_long_arr = bb_tp_long if bb_tp_long is not None else _nan_fallback
            bb_stop_short_arr = bb_stop_short if bb_stop_short is not None else _nan_fallback
            bb_tp_short_arr = bb_tp_short if bb_tp_short is not None else _nan_fallback
            bb_pos_low_arr = bb_pos_low if bb_pos_low is not None else _nan_fallback
            bb_pos_high_arr = bb_pos_high if bb_pos_high is not None else _nan_fallback
            sl_level_arr_safe = sl_level_arr if sl_level_arr is not None else _nan_fallback
            tp_level_arr_safe = tp_level_arr if tp_level_arr is not None else _nan_fallback

            result = _simulate_trades_numba_bb_levels(
                closes, highs, lows, signal_arr,
                leverage, k_sl, initial_capital, fees_bps, slippage_bps,
                bb_stop_long_arr, bb_tp_long_arr, bb_stop_short_arr, bb_tp_short_arr,
                bb_pos_low_arr, bb_pos_high_arr, sl_level_arr_safe, tp_level_arr_safe,
                sl_level_param, tp_level_param,
            )
        else:
            # ⚠️ FALLBACK : Boucle Python (LENT - seulement si Numba indisponible)
            logger.warning("Backend: numpy_bb_levels (Python loop - SLOW)")
            logger.warning("⚠️  Performance dégradée : installez numba pour accélération 10-100×")
            result = _simulate_trades_numpy_bb_levels(
                closes, highs, lows, signal_arr,
                leverage, k_sl, initial_capital, fees_bps, slippage_bps,
                bb_stop_long, bb_tp_long, bb_stop_short, bb_tp_short,
                bb_pos_low, bb_pos_high, sl_level_arr, tp_level_arr,
                sl_level_param, tp_level_param,
            )
    elif HAS_NUMBA:
        # ✅ Kernel Numba standard (sans BB levels)
        logger.debug("Backend: numba_standard (JIT-compiled)")
        result = _simulate_trades_numba(
            closes, highs, lows, signal_arr,
            leverage, k_sl, initial_capital, fees_bps, slippage_bps
        )
    else:
        # ⚠️ FALLBACK : NumPy pur (seulement si Numba indisponible)
        logger.debug("Backend: numpy_standard (Numba non disponible)")
        result = _simulate_trades_numpy(
            closes, highs, lows, signal_arr,
            leverage, k_sl, initial_capital, fees_bps, slippage_bps
        )

    (entry_indices, exit_indices, sides, entry_prices, exit_prices,
     pnls, returns_pct, exit_reasons, sizes, trade_count) = result

    if trade_count == 0:
        return pd.DataFrame(columns=[
            "entry_ts", "exit_ts", "pnl", "size", "price_entry", "price_exit",
            "side", "exit_reason", "return_pct", "leverage_used", "fees_paid"
        ])

    # Convertir timestamps
    timestamps = df.index.values
    fees_factor = fees_bps * 2 * 0.0001

    trades_df = pd.DataFrame({
        "entry_ts": pd.to_datetime(timestamps[entry_indices]),
        "exit_ts": pd.to_datetime(timestamps[exit_indices]),
        "pnl": pnls,
        "size": sizes,
        "price_entry": entry_prices,
        "price_exit": exit_prices,
        "side": np.where(sides == 1, "LONG", "SHORT"),
        "exit_reason": [EXIT_REASON_MAP.get(r, "unknown") for r in exit_reasons],
        "return_pct": returns_pct,
        "leverage_used": leverage,
        "fees_paid": sizes * entry_prices * fees_factor
    })

    logger.debug(f"Simulation fast terminée: {trade_count} trades")

    return trades_df


def calculate_equity_fast(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    initial_capital: float = 10000.0
) -> pd.Series:
    """
    Calcule la courbe d'équité avec mark-to-market.

    Args:
        df: DataFrame OHLCV (pour l'index)
        trades_df: DataFrame des trades
        initial_capital: Capital initial

    Returns:
        pd.Series de l'équité avec la même sémantique que calculate_equity_curve()
    """
    n_bars = len(df)

    if trades_df.empty:
        return pd.Series(initial_capital, index=df.index, dtype=np.float64)

    # Préparer les timestamps et harmoniser les timezones
    entry_ts = pd.to_datetime(trades_df["entry_ts"])
    exit_ts = pd.to_datetime(trades_df["exit_ts"])

    # Harmoniser les timezones avec df.index
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        if entry_ts.dt.tz is None:
            entry_ts = entry_ts.dt.tz_localize(df.index.tz)
        elif entry_ts.dt.tz != df.index.tz:
            entry_ts = entry_ts.dt.tz_convert(df.index.tz)

        if exit_ts.dt.tz is None:
            exit_ts = exit_ts.dt.tz_localize(df.index.tz)
        elif exit_ts.dt.tz != df.index.tz:
            exit_ts = exit_ts.dt.tz_convert(df.index.tz)

    # ═══════════════════════════════════════════════════════════════════════════
    # OPTIMISATION CRITIQUE: Utiliser get_indexer au lieu de dict comprehension
    # ═══════════════════════════════════════════════════════════════════════════
    # AVANT: ts_to_idx = {ts: i for i, ts in enumerate(df.index)}  # 116k itérations!
    # APRÈS: get_indexer natif pandas (100× plus rapide avec binary search)

    # Convertir en indices avec get_indexer (vectorisé, O(n log n))
    entry_indices = df.index.get_indexer(entry_ts, method=None)
    exit_indices = df.index.get_indexer(exit_ts, method=None)

    # Remplacer -1 (not found) par bornes valides
    entry_indices = np.where(entry_indices == -1, 0, entry_indices).astype(np.int64)
    exit_indices = np.where(exit_indices == -1, n_bars - 1, exit_indices).astype(np.int64)

    # Extraire données des trades
    pnls = trades_df["pnl"].values.astype(np.float64)
    entry_prices = trades_df["price_entry"].values.astype(np.float64)
    sizes = trades_df["size"].values.astype(np.float64)
    sides = trades_df.get("side", pd.Series(["LONG"] * len(trades_df))).values
    side_signs = np.where(sides == "SHORT", -1, 1).astype(np.int8)

    # Prix close pour mark-to-market
    close_prices = df['close'].values.astype(np.float64)

    if HAS_NUMBA:
        equity_arr = _calculate_equity_numba(
            n_bars,
            entry_indices,
            exit_indices,
            pnls,
            entry_prices,
            sizes,
            side_signs,
            close_prices,
            initial_capital
        )
    else:
        capital_changes = np.zeros(n_bars, dtype=np.float64)
        np.add.at(capital_changes, exit_indices, pnls)

        long_mask = side_signs >= 0
        short_mask = ~long_mask

        long_size_delta = np.zeros(n_bars + 1, dtype=np.float64)
        short_size_delta = np.zeros(n_bars + 1, dtype=np.float64)
        long_entry_delta = np.zeros(n_bars + 1, dtype=np.float64)
        short_entry_delta = np.zeros(n_bars + 1, dtype=np.float64)

        def _apply_open_trade_deltas(mask: np.ndarray, size_delta: np.ndarray, entry_delta: np.ndarray) -> None:
            if not np.any(mask):
                return
            valid_mask = mask & (entry_indices < exit_indices)
            if not np.any(valid_mask):
                return
            notionals = entry_prices[valid_mask] * sizes[valid_mask]
            np.add.at(size_delta, entry_indices[valid_mask], sizes[valid_mask])
            np.add.at(size_delta, exit_indices[valid_mask], -sizes[valid_mask])
            np.add.at(entry_delta, entry_indices[valid_mask], notionals)
            np.add.at(entry_delta, exit_indices[valid_mask], -notionals)

        _apply_open_trade_deltas(long_mask, long_size_delta, long_entry_delta)
        _apply_open_trade_deltas(short_mask, short_size_delta, short_entry_delta)

        realized = initial_capital + np.cumsum(capital_changes)
        active_long_size = np.cumsum(long_size_delta[:-1])
        active_short_size = np.cumsum(short_size_delta[:-1])
        active_long_entry = np.cumsum(long_entry_delta[:-1])
        active_short_entry = np.cumsum(short_entry_delta[:-1])
        unrealized = (
            close_prices * active_long_size
            - active_long_entry
            + active_short_entry
            - close_prices * active_short_size
        )
        equity_arr = realized + unrealized

    return pd.Series(equity_arr, index=df.index, dtype=np.float64)


def calculate_returns_fast(equity: pd.Series) -> pd.Series:
    """Calcul vectorisé des rendements."""
    equity_arr = equity.values
    returns = np.zeros_like(equity_arr)
    returns[1:] = (equity_arr[1:] - equity_arr[:-1]) / equity_arr[:-1]
    returns = np.nan_to_num(returns, 0.0)
    return pd.Series(returns, index=equity.index, dtype=np.float64)


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def simulate_batch(
    df: pd.DataFrame,
    signals_batch: List[pd.Series],
    params_batch: List[Dict[str, Any]],
    n_jobs: int = -1
) -> List[pd.DataFrame]:
    """
    Simule plusieurs backtests en parallèle.

    Args:
        df: DataFrame OHLCV partagé
        signals_batch: Liste de séries de signaux
        params_batch: Liste de paramètres
        n_jobs: Nombre de workers (-1 = tous les CPUs)

    Returns:
        Liste de DataFrames de trades
    """
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if n_jobs == -1:
        n_jobs = os.cpu_count() or 4

    results = [None] * len(signals_batch)

    def run_single(idx: int) -> Tuple[int, pd.DataFrame]:
        trades = simulate_trades_fast(df, signals_batch[idx], params_batch[idx])
        return idx, trades

    with ThreadPoolExecutor(max_workers=n_jobs) as executor:
        futures = [executor.submit(run_single, i) for i in range(len(signals_batch))]
        for future in as_completed(futures):
            idx, trades = future.result()
            results[idx] = trades

    return results


__all__ = [
    "simulate_trades_fast",
    "calculate_equity_fast",
    "calculate_returns_fast",
    "simulate_batch",
    "HAS_NUMBA"
]
