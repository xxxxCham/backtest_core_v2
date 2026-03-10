"""
Module-ID: backtest.simulator

Purpose: Simuler l'exécution des trades et le calcul des courbes d'équité/rendement.

Role in pipeline: execution

Key components: Trade, simulate_trades, calculate_equity_curve, calculate_returns

Inputs: Signaux (1/-1/0), DataFrame OHLCV, paramètres d'exécution (spread, slippage, levier)

Outputs: Trade list, equity curve array, returns array

Dependencies: numpy, pandas, utils.log

Conventions: Trade.side = 'LONG'|'SHORT'; pnl en devise de base; return_pct en fractions [0,1] ou pourcentages.

Read-if: Optimisation simulation ou modification de la mécanique des trades.

Skip-if: Vous ne touchez qu'aux stratégies/indicateurs.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd

from utils.log import get_logger

# Import optionnel de tqdm pour barres de progression
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    def tqdm(iterable, **kwargs):
        return iterable

logger = get_logger(__name__)


@dataclass
class Trade:
    """
    Représentation d'un trade exécuté.
    """
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    side: Literal["LONG", "SHORT"]
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    return_pct: float
    exit_reason: str
    leverage: float = 1.0
    fees_paid: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "side": self.side,
            "price_entry": self.entry_price,
            "price_exit": self.exit_price,
            "size": self.size,
            "pnl": self.pnl,
            "return_pct": self.return_pct,
            "exit_reason": self.exit_reason,
            "leverage_used": self.leverage,
            "fees_paid": self.fees_paid
        }


def simulate_trades(
    df: pd.DataFrame,
    signals: pd.Series,
    params: Dict[str, Any],
    execution_engine: Optional[Any] = None,
    show_progress: bool = False
) -> pd.DataFrame:
    """
    Simule l'exécution des trades basée sur les signaux.

    Features:
    - Gestion des positions (une seule à la fois)
    - Stop-loss configurable
    - Calcul des frais et slippage (fixe ou dynamique)
    - Exécution réaliste optionnelle (spread/slippage dynamique)
    - Sortie en fin de données si position ouverte

    Args:
        df: DataFrame OHLCV avec index datetime
        signals: Série de signaux (+1, -1, 0)
        params: Paramètres de trading:
            - leverage: Levier (défaut: 3)
            - k_sl: Multiplicateur stop-loss % (défaut: 1.5)
            - initial_capital: Capital initial (défaut: 10000)
            - fees_bps: Frais en bps (défaut: 10)
            - slippage_bps: Slippage en bps (défaut: 5)
            - execution_model: Modèle d'exécution ('fixed', 'dynamic', 'realistic')
        execution_engine: ExecutionEngine optionnel pour exécution réaliste
        show_progress: Afficher une barre de progression (défaut: False)

    Returns:
        DataFrame des trades avec colonnes:
        entry_ts, exit_ts, pnl, size, price_entry, price_exit, side, exit_reason, etc.
    """
    logger.debug("Début simulation des trades")

    trades: List[Trade] = []

    # État de position
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    entry_time: Optional[pd.Timestamp] = None
    position_size = 0.0
    exit_pending_reason: Optional[str] = None

    # Paramètres avec défauts
    leverage = params.get("leverage", 1)
    k_sl = params.get("k_sl", 1.5)  # Stop loss en %
    initial_capital = params.get("initial_capital", 10000.0)
    fees_bps = params.get("fees_bps", 10.0)
    slippage_bps = params.get("slippage_bps", 5.0)

    # Mode d'exécution
    use_realistic_execution = execution_engine is not None
    if use_realistic_execution:
        execution_engine.prepare(df)
        logger.debug("Mode exécution réaliste activé")

    # Convertir en arrays pour performance
    timestamps = df.index.values
    closes = df["close"].values
    lows = df["low"].values if "low" in df.columns else closes.copy()
    highs = df["high"].values if "high" in df.columns else closes.copy()
    signal_values = signals.values if hasattr(signals, "values") else signals

    bb_stop_long = df["bb_stop_long"].values if "bb_stop_long" in df.columns else None
    bb_tp_long = df["bb_tp_long"].values if "bb_tp_long" in df.columns else None
    bb_stop_short = df["bb_stop_short"].values if "bb_stop_short" in df.columns else None
    bb_tp_short = df["bb_tp_short"].values if "bb_tp_short" in df.columns else None
    bb_pos_low = df["bb_pos_low"].values if "bb_pos_low" in df.columns else None
    bb_pos_high = df["bb_pos_high"].values if "bb_pos_high" in df.columns else None
    sl_level_arr = df["sl_level"].values if "sl_level" in df.columns else None
    tp_level_arr = df["tp_level"].values if "tp_level" in df.columns else None
    sl_level_param = params.get("sl_level", np.nan)
    if sl_level_param is None:
        sl_level_param = np.nan
    sl_level_param = float(sl_level_param)
    tp_level_param = params.get("tp_level", np.nan)
    if tp_level_param is None:
        tp_level_param = np.nan
    tp_level_param = float(tp_level_param)

    stop_price = np.nan
    tp_price = np.nan
    stop_level = np.nan
    tp_level = np.nan
    use_bb_pos = False
    has_bb_stop = False
    has_bb_tp = False

    n_bars = len(closes)

    # Tracking des coûts d'exécution
    total_spread_cost = 0.0
    total_slippage_cost = 0.0

    # Barre de progression optionnelle
    bar_iterator = tqdm(
        range(n_bars),
        desc="Simulating trades",
        unit="bar",
        disable=not (show_progress and TQDM_AVAILABLE),
        leave=False
    ) if show_progress else range(n_bars)

    def _init_trade_levels(bar_idx: int, pos: int) -> None:
        nonlocal stop_price, tp_price, stop_level, tp_level, use_bb_pos, has_bb_stop, has_bb_tp
        stop_price = np.nan
        tp_price = np.nan
        stop_level = np.nan
        tp_level = np.nan
        use_bb_pos = False
        has_bb_stop = False
        has_bb_tp = False

        if pos == 1:
            if bb_stop_long is not None:
                stop_price = float(bb_stop_long[bar_idx])
                has_bb_stop = not np.isnan(stop_price)
            if bb_tp_long is not None:
                tp_price = float(bb_tp_long[bar_idx])
                has_bb_tp = not np.isnan(tp_price)
        else:
            if bb_stop_short is not None:
                stop_price = float(bb_stop_short[bar_idx])
                has_bb_stop = not np.isnan(stop_price)
            if bb_tp_short is not None:
                tp_price = float(bb_tp_short[bar_idx])
                has_bb_tp = not np.isnan(tp_price)

        if not (has_bb_stop or has_bb_tp) and bb_pos_low is not None and bb_pos_high is not None:
            use_bb_pos = True
            stop_level = float(sl_level_arr[bar_idx]) if sl_level_arr is not None else sl_level_param
            tp_level = float(tp_level_arr[bar_idx]) if tp_level_arr is not None else tp_level_param
            has_bb_stop = not np.isnan(stop_level)
            has_bb_tp = not np.isnan(tp_level)

    for i in bar_iterator:
        timestamp = pd.Timestamp(timestamps[i])
        close_price = closes[i]
        signal = signal_values[i]

        # === Entrée en position ===
        if position == 0 and signal != 0:
            position = int(signal)
            requested_size = leverage * initial_capital / close_price

            # Calcul du prix d'entrée
            if use_realistic_execution:
                exec_result = execution_engine.execute_order(
                    price=close_price,
                    side=position,
                    bar_idx=i,
                    size=requested_size
                )
                entry_price = exec_result.executed_price
                filled_size = getattr(exec_result, "filled_size", requested_size)
                if filled_size <= 0:
                    position = 0
                    continue
                position_size = filled_size
                total_spread_cost += exec_result.spread_cost
                total_slippage_cost += exec_result.slippage_cost
            else:
                # Mode simple: slippage fixe
                slip_factor = 1 + (slippage_bps * 0.0001 * position)
                entry_price = close_price * slip_factor
                position_size = leverage * initial_capital / entry_price

            entry_time = timestamp
            exit_pending_reason = None
            _init_trade_levels(i, position)

            logger.debug(f"Entrée {'LONG' if position == 1 else 'SHORT'} @ {entry_price:.2f}")

        # === En position: vérifier sortie ===
        elif position != 0:
            exit_condition = False
            exit_reason = ""

            # 1. Exit pending (partial fill)
            if exit_pending_reason is not None:
                exit_condition = True
                exit_reason = exit_pending_reason
            else:
                use_bb_levels = use_bb_pos or has_bb_stop or has_bb_tp

                if use_bb_levels:
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
                        if position == 1 and lows[i] <= entry_price * (1 - k_sl * 0.01):
                            sl_hit = True
                        elif position == -1 and highs[i] >= entry_price * (1 + k_sl * 0.01):
                            sl_hit = True

                    if sl_hit:
                        exit_condition = True
                        exit_reason = "stop_loss"
                    elif tp_hit:
                        exit_condition = True
                        exit_reason = "take_profit"
                    elif signal != 0 and signal != position:
                        exit_condition = True
                        exit_reason = "signal_reverse"
                else:
                    if signal != 0 and signal != position:
                        exit_condition = True
                        exit_reason = "signal_reverse"

                    if position == 1:
                        sl_price = entry_price * (1 - k_sl * 0.01)
                        if lows[i] <= sl_price:
                            exit_condition = True
                            exit_reason = "stop_loss"
                    elif position == -1:
                        sl_price = entry_price * (1 + k_sl * 0.01)
                        if highs[i] >= sl_price:
                            exit_condition = True
                            exit_reason = "stop_loss"

            # === Exécuter sortie ===
            if exit_condition:
                # Calcul du prix de sortie
                if use_realistic_execution:
                    exec_result = execution_engine.execute_order(
                        price=close_price,
                        side=-position,  # Direction opposée pour la sortie
                        bar_idx=i,
                        size=position_size
                    )
                    exit_price = exec_result.executed_price
                    filled_size = getattr(exec_result, "filled_size", position_size)
                    total_spread_cost += exec_result.spread_cost
                    total_slippage_cost += exec_result.slippage_cost
                else:
                    # Mode simple: slippage fixe
                    slip_factor = 1 - (slippage_bps * 0.0001 * position)
                    exit_price = close_price * slip_factor
                    filled_size = position_size

                if filled_size <= 0:
                    exit_pending_reason = exit_reason or "exit_pending"
                    continue

                trade_size = min(filled_size, position_size)

                # Calcul PnL
                if position == 1:
                    raw_return = (exit_price - entry_price) / entry_price
                else:
                    raw_return = (entry_price - exit_price) / entry_price

                # Frais (aller-retour)
                total_fees_pct = fees_bps * 2 * 0.0001
                net_return = raw_return - total_fees_pct

                # PnL avec taille de position
                trade_notional = trade_size * entry_price
                pnl = net_return * trade_notional

                # Frais payés
                fees_paid = trade_size * entry_price * total_fees_pct

                exit_reason_used = exit_reason
                if trade_size < position_size:
                    exit_reason_used = f"{exit_reason}_partial"

                trade = Trade(
                    entry_ts=entry_time,
                    exit_ts=timestamp,
                    side="LONG" if position == 1 else "SHORT",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=trade_size,
                    pnl=pnl,
                    return_pct=net_return * 100,
                    exit_reason=exit_reason_used,
                    leverage=leverage,
                    fees_paid=fees_paid
                )
                trades.append(trade)

                logger.debug(f"Sortie {trade.side} @ {exit_price:.2f}, PnL: ${pnl:.2f}")

                position_size -= trade_size
                if position_size <= 0:
                    # Reset position
                    position = 0
                    entry_price = 0.0
                    entry_time = None
                    exit_pending_reason = None
                    stop_price = np.nan
                    tp_price = np.nan
                    stop_level = np.nan
                    tp_level = np.nan
                    use_bb_pos = False
                    has_bb_stop = False
                    has_bb_tp = False

                    # Nouvelle position si signal présent
                    if signal != 0:
                        position = int(signal)
                        requested_size = leverage * initial_capital / close_price
                        if use_realistic_execution:
                            exec_result = execution_engine.execute_order(
                                price=close_price,
                                side=position,
                                bar_idx=i,
                                size=requested_size
                            )
                            entry_price = exec_result.executed_price
                            filled_size = getattr(exec_result, "filled_size", requested_size)
                            if filled_size <= 0:
                                position = 0
                                continue
                            position_size = filled_size
                            total_spread_cost += exec_result.spread_cost
                            total_slippage_cost += exec_result.slippage_cost
                        else:
                            entry_price = close_price * (1 + slippage_bps * 0.0001 * position)
                            position_size = leverage * initial_capital / entry_price
                        entry_time = timestamp
                        _init_trade_levels(i, position)
                else:
                    exit_pending_reason = exit_reason

    # === Trade final si position ouverte ===
    if position != 0 and entry_time is not None:
        if use_realistic_execution:
            exec_result = execution_engine.execute_order(
                price=closes[-1],
                side=-position,
                bar_idx=n_bars - 1,
                size=position_size
            )
            final_price = exec_result.executed_price
            total_spread_cost += exec_result.spread_cost
            total_slippage_cost += exec_result.slippage_cost
        else:
            final_price = closes[-1] * (1 - slippage_bps * 0.0001 * position)

        final_time = pd.Timestamp(timestamps[-1])

        if position == 1:
            raw_return = (final_price - entry_price) / entry_price
        else:
            raw_return = (entry_price - final_price) / entry_price

        total_fees_pct = fees_bps * 2 * 0.0001
        net_return = raw_return - total_fees_pct
        trade_notional = position_size * entry_price
        pnl = net_return * trade_notional

        trade = Trade(
            entry_ts=entry_time,
            exit_ts=final_time,
            side="LONG" if position == 1 else "SHORT",
            entry_price=entry_price,
            exit_price=final_price,
            size=position_size,
            pnl=pnl,
            return_pct=net_return * 100,
            exit_reason="end_of_data",
            leverage=leverage,
            fees_paid=position_size * entry_price * total_fees_pct
        )
        trades.append(trade)

    # Construire DataFrame
    if trades:
        trades_df = pd.DataFrame([t.to_dict() for t in trades])
    else:
        # DataFrame vide avec colonnes requises
        trades_df = pd.DataFrame(columns=[
            "entry_ts", "exit_ts", "pnl", "size", "price_entry", "price_exit",
            "side", "exit_reason", "return_pct", "leverage_used", "fees_paid"
        ])

    logger.info(f"Simulation terminée: {len(trades)} trades")

    return trades_df


def calculate_equity_curve(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    initial_capital: float = 10000.0,
    run_id: Optional[str] = None  # Pour logging structuré
) -> pd.Series:
    """
    Calcule la courbe d'équité avec mark-to-market.

    IMPORTANT: Inclut le P&L non réalisé des positions ouvertes.

    Args:
        df: DataFrame OHLCV (pour l'index temporel)
        trades_df: DataFrame des trades
        initial_capital: Capital initial

    Returns:
        pd.Series de l'équité avec mark-to-market
    """
    # EQUITY_SERIES_META - Log métadonnées courbe equity
    if run_id:
        freq_str = "unknown"
        if hasattr(df.index, 'freq') and df.index.freq is not None:
            freq_str = str(df.index.freq)
        elif isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
            freq_str = pd.infer_freq(df.index) or "unknown"

        logger.info(
            f"EQUITY_SERIES_META run_id={run_id} "
            f"index_type={type(df.index).__name__} freq={freq_str} "
            f"n_points={len(df)} initial_capital={initial_capital} currency=USD"
        )

    equity = pd.Series(initial_capital, index=df.index, dtype=np.float64)

    if trades_df.empty:
        if run_id:
            logger.info(
                f"EQUITY_COMPLETE run_id={run_id} len={len(equity)} "
                f"min={equity.min():.2f} max={equity.max():.2f} "
                f"final={equity.iloc[-1]:.2f} pnl=0.00 note=no_trades"
            )
        return equity

    # Harmoniser les timezones
    entry_ts_series = pd.to_datetime(trades_df["entry_ts"])
    exit_ts_series = pd.to_datetime(trades_df["exit_ts"])

    if hasattr(df.index, 'tz') and df.index.tz is not None:
        if entry_ts_series.dt.tz is None:
            entry_ts_series = entry_ts_series.dt.tz_localize(df.index.tz)
        elif entry_ts_series.dt.tz != df.index.tz:
            entry_ts_series = entry_ts_series.dt.tz_convert(df.index.tz)

        if exit_ts_series.dt.tz is None:
            exit_ts_series = exit_ts_series.dt.tz_localize(df.index.tz)
        elif exit_ts_series.dt.tz != df.index.tz:
            exit_ts_series = exit_ts_series.dt.tz_convert(df.index.tz)

    # Capital réalisé
    realized_capital = initial_capital

    # Parcourir chaque barre pour calculer equity avec mark-to-market
    for bar_idx, bar_time in enumerate(df.index):
        current_price = df['close'].iloc[bar_idx]

        # Trades fermés à cette barre
        closed_trades = trades_df[exit_ts_series <= bar_time]
        if not closed_trades.empty:
            realized_capital = initial_capital + closed_trades['pnl'].sum()

        # Positions ouvertes
        open_trades = trades_df[
            (entry_ts_series <= bar_time) & (exit_ts_series > bar_time)
        ]

        unrealized_pnl = 0.0
        if not open_trades.empty:
            for _, trade in open_trades.iterrows():
                entry_price = trade['price_entry']
                size = trade['size']
                side = trade.get('side', 'LONG')

                if side == 'LONG':
                    unrealized_pnl += (current_price - entry_price) * size
                else:  # SHORT
                    unrealized_pnl += (entry_price - current_price) * size

        equity.iloc[bar_idx] = realized_capital + unrealized_pnl

    # Logs détaillés avant return
    if run_id:
        # Détection jumps anormaux
        jumps = equity.pct_change().abs()
        if len(jumps) > 1:
            threshold = jumps.mean() + 3 * jumps.std()
            abnormal_jumps = jumps[jumps > threshold].dropna()

            if not abnormal_jumps.empty:
                logger.warning(
                    f"EQUITY_JUMPS run_id={run_id} n_jumps={len(abnormal_jumps)} "
                    f"max_jump={abnormal_jumps.max():.4f} "
                    f"jump_steps={abnormal_jumps.index.tolist()[:10]}"
                )

        # Drawdown analysis
        from backtest.performance import drawdown_series, max_drawdown
        dd_series = drawdown_series(equity)
        max_dd = max_drawdown(equity)

        dd_start = None
        if not dd_series.empty and dd_series.min() < 0:
            dd_start = str(dd_series.idxmin())

        logger.info(
            f"EQUITY_DD run_id={run_id} max_dd_pct={max_dd * 100:.2f} "
            f"dd_start={dd_start}"
        )

        # Réconciliation ledger
        if not trades_df.empty:
            equity_final = equity.iloc[-1]
            pnl_total = trades_df['pnl'].sum()
            equity_expected = initial_capital + pnl_total
            delta = abs(equity_final - equity_expected)

            if delta > 0.01:  # epsilon = 1 cent
                fees_total = trades_df.get('fees', pd.Series([0])).sum()
                logger.error(
                    f"EQUITY_RECONCILE_FAIL run_id={run_id} "
                    f"equity_final={equity_final:.2f} equity_expected={equity_expected:.2f} "
                    f"delta={delta:.2f} initial_capital={initial_capital:.2f} "
                    f"pnl_total={pnl_total:.2f} fees_total={fees_total:.2f}"
                )

        # Log final
        logger.info(
            f"EQUITY_COMPLETE run_id={run_id} len={len(equity)} "
            f"min={equity.min():.2f} max={equity.max():.2f} "
            f"final={equity.iloc[-1]:.2f} pnl={equity.iloc[-1] - initial_capital:.2f}"
        )

    return equity


def calculate_returns(equity: pd.Series) -> pd.Series:
    """
    Calcule les rendements périodiques à partir de la courbe d'équité.
    """
    returns = equity.pct_change().fillna(0)
    return returns


__all__ = ["simulate_trades", "Trade", "calculate_equity_curve", "calculate_returns"]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur l'exécution/simulation
# - Conventions Trade.side et return_pct explicitées pour éviter ambiguïtés
# - Read-if/Skip-if ajoutés pour guider la lecture
