"""Cross-engine robustness check for graduated strategies.

Rejoue les DÉCISIONS d'exécution du moteur projet (incl. stops/TP ATR via bb_levels)
dans un moteur de référence INDÉPENDANT (numpy pur), en faisant varier UNIQUEMENT
les conventions risquées :

  A) exit@close + additif      -> réplique fidèle du moteur projet (validation)
  B) exit@level + additif      -> SL/TP remplis au NIVEAU (réaliste), pas au close
  C) exit@level + composé      -> + réinvestissement (ruine possible)

Hypothèse testée : le moteur projet sort les SL/TP au close de la barre, pas au
niveau touché. Sur actif volatil (mèches), ça peut transformer une perte pleine
au stop en quasi-zéro -> inflation. exit@level mesure cet artefact.

Usage: python -m tools.cross_engine_validation
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent

SOURCES = [
    ("#1 SOL", "grad_20260423_050049_strat_gie_sur_solusdc_4h_exploiter_les_r.py", "SOLUSDC", "4h", "low_conf", 113.4),
    ("#2 ADA", "grad_20260429_091955_json_objective_capturer_des_mouvements_d.py", "ADAUSDC", "4h", "low_conf", 113.4),
    ("#3 ETH", "grad_20260429_210138_objective_filtrer_les_faux_signaux_de_m.py", "ETHUSDC", "1h", "low_conf", 304.1),
    ("#4 ORDI", "grad_20260520_173440_strat_gie_de_multi_factor_sur_ordiusdc_1.py", "ORDIUSDC", "15m", "STRICT", 1660.0),
    ("#5 ORDI", "grad_20260521_060228_volatility_breakout_sur_ordiusdc_15m_in.py", "ORDIUSDC", "15m", "STRICT", 124.7),
    ("#6 TAO", "grad_20260522_021658_objective_cette_strat_gie_de_regime_ada.py", "TAOUSDC", "1h", "low_conf", 34.3),
]

_BB_COLS = ("bb_stop_long", "bb_tp_long", "bb_stop_short", "bb_tp_short",
            "bb_pos_low", "bb_pos_high", "sl_level", "tp_level")


def load_strategy(path: Path):
    from strategies.base import StrategyBase
    spec = importlib.util.spec_from_file_location(f"grad_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return next(
        v() for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, StrategyBase) and v is not StrategyBase
    )


def compute_signals(eng, df, strat, final_params):
    """Retourne (signals_array, bb_arrays_dict) — même chemin que le moteur."""
    indicators = eng._calculate_indicators(df, strat, final_params)
    signals = strat.generate_signals(df, indicators, final_params)  # peut muter df
    sig = np.array(signals.values if hasattr(signals, "values") else signals, dtype=np.float64, copy=True)
    if "_tradable" in df.columns:
        sig[~df["_tradable"].values] = 0.0
    np.nan_to_num(sig, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    bb = {col: (np.asarray(df[col].values, dtype=np.float64) if col in df.columns else None) for col in _BB_COLS}
    return sig, bb


def ref_backtest(o, h, l, c, sig, bb, *, leverage, sl_pct, fee_rt, slip,
                 exit_fill="close", compound=False, init=10000.0):
    n = len(c)
    pos = 0
    entry = 0.0
    basis = 0.0
    realized = init
    stop_price = tp_price = stop_level = tp_level = np.nan
    use_bb_pos = has_stop = has_tp = False
    peak = init
    maxdd = 0.0
    n_trades = wins = n_sl = n_tp = n_sig = 0
    gross_w = gross_l = sum_ret = 0.0
    ruined = False

    bsl, btl = bb.get("bb_stop_long"), bb.get("bb_tp_long")
    bss, bts = bb.get("bb_stop_short"), bb.get("bb_tp_short")
    bpl, bph = bb.get("bb_pos_low"), bb.get("bb_pos_high")
    sla, tla = bb.get("sl_level"), bb.get("tp_level")

    def g(arr, i):
        return arr[i] if arr is not None else np.nan

    def init_levels(i, p):
        nonlocal stop_price, tp_price, stop_level, tp_level, use_bb_pos, has_stop, has_tp
        stop_price = tp_price = stop_level = tp_level = np.nan
        use_bb_pos = has_stop = has_tp = False
        if p == 1:
            stop_price = g(bsl, i); has_stop = not np.isnan(stop_price)
            tp_price = g(btl, i); has_tp = not np.isnan(tp_price)
        else:
            stop_price = g(bss, i); has_stop = not np.isnan(stop_price)
            tp_price = g(bts, i); has_tp = not np.isnan(tp_price)
        if not (has_stop or has_tp):
            use_bb_pos = True
            sv = g(sla, i); stop_level = sv
            tv = g(tla, i); tp_level = tv
            has_stop = not np.isnan(stop_level); has_tp = not np.isnan(tp_level)

    for i in range(n):
        cp = c[i]
        s = sig[i]
        if pos != 0 and entry > 0:
            eqi = realized + (cp - entry) / entry * pos * basis * leverage
        else:
            eqi = realized
        if eqi > peak:
            peak = eqi
        if peak > 0:
            dd = (eqi - peak) / peak * 100.0
            if dd < maxdd:
                maxdd = dd
        if ruined:
            continue

        if pos == 0 and s != 0 and cp > 0:
            pos = int(s); entry = cp * (1.0 + slip * pos)
            basis = realized if compound else init
            init_levels(i, pos)
            continue

        if pos != 0:
            sl_hit = tp_hit = False
            if use_bb_pos:
                if pos == 1:
                    if has_stop and g(bpl, i) <= stop_level: sl_hit = True
                    if has_tp and g(bph, i) >= tp_level: tp_hit = True
                else:
                    if has_stop and g(bph, i) >= stop_level: sl_hit = True
                    if has_tp and g(bpl, i) <= tp_level: tp_hit = True
            else:
                if has_stop and ((pos == 1 and l[i] <= stop_price) or (pos == -1 and h[i] >= stop_price)):
                    sl_hit = True
                if has_tp and ((pos == 1 and h[i] >= tp_price) or (pos == -1 and l[i] <= tp_price)):
                    tp_hit = True
            if not sl_hit and not has_stop:
                if (pos == 1 and l[i] <= entry * (1.0 - sl_pct)) or (pos == -1 and h[i] >= entry * (1.0 + sl_pct)):
                    sl_hit = True

            reason = -1
            if sl_hit: reason = 1
            elif tp_hit: reason = 3
            elif s != 0 and s != pos: reason = 0

            if reason >= 0:
                # prix de sortie : close (moteur) vs niveau réel (réaliste)
                base = cp
                if exit_fill == "level" and not use_bb_pos:
                    if reason == 1:
                        base = stop_price if has_stop else (entry * (1.0 - sl_pct) if pos == 1 else entry * (1.0 + sl_pct))
                    elif reason == 3 and has_tp:
                        base = tp_price
                exit_px = base * (1.0 - slip * pos)
                net = (exit_px - entry) / entry * pos - fee_rt
                realized += net * basis * leverage
                sum_ret += net; n_trades += 1
                if reason == 1: n_sl += 1
                elif reason == 3: n_tp += 1
                else: n_sig += 1
                if net > 0: wins += 1; gross_w += net
                else: gross_l += -net
                if compound and realized <= 0:
                    realized = 0.0; ruined = True
                pos = 0; entry = 0.0
                if not ruined and s != 0 and cp > 0:
                    pos = int(s); entry = cp * (1.0 + slip * pos)
                    basis = realized if compound else init
                    init_levels(i, pos)

    if pos != 0 and entry > 0:
        net = (c[-1] * (1.0 - slip * pos) - entry) / entry * pos - fee_rt
        realized += net * basis * leverage
        sum_ret += net; n_trades += 1
        if net > 0: wins += 1; gross_w += net
        else: gross_l += -net

    pf = (gross_w / gross_l) if gross_l > 1e-12 else None
    return {
        "total_return_pct": round((realized - init) / init * 100.0, 1),
        "n_trades": n_trades,
        "win_rate": round(wins / n_trades * 100.0, 1) if n_trades else 0.0,
        "avg_trade_pct": round(sum_ret / n_trades * 100.0, 3) if n_trades else 0.0,
        "profit_factor": round(pf, 2) if pf is not None else None,
        "max_drawdown_pct": round(maxdd, 1),
        "exits": {"sl": n_sl, "tp": n_tp, "signal": n_sig},
        "ruined": ruined,
    }


def main() -> None:
    from backtest.engine import BacktestEngine
    from data.loader import load_ohlcv

    results = []
    for label, fname, symbol, tf, tier, announced in SOURCES:
        row: dict[str, Any] = {"label": label, "symbol": symbol, "tf": tf, "tier": tier, "announced_return": announced}
        try:
            strat = load_strategy(_ROOT / "strategies" / "graduated" / fname)
            df = load_ohlcv(symbol, tf)
            eng = BacktestEngine(initial_capital=10000.0)
            fees_bps = float(eng.config.fees_bps); slip_bps = float(eng.config.slippage_bps)
            final_params = {"initial_capital": 10000.0, "fees_bps": fees_bps, "slippage_bps": slip_bps, **strat.default_params}
            res = eng.run(df, strat, params=dict(strat.default_params), symbol=symbol, timeframe=tf,
                          silent_mode=True, fast_metrics=False)
            m = res.metrics
            row["project"] = {
                "total_return_pct": round(float(m.get("total_return_pct", 0) or 0), 1),
                "sharpe": round(float(m.get("sharpe_ratio", 0) or 0), 2),
                "max_drawdown_pct": round(float(m.get("max_drawdown_pct", 0) or 0), 1),
                "win_rate": round(float(m.get("win_rate", 0) or 0), 1),
                "n_trades": int(m.get("total_trades", len(res.trades)) or 0),
            }
            sig, bb = compute_signals(eng, df, strat, final_params)
            row["bb_cols_present"] = sorted(k for k, v in bb.items() if v is not None)
            o = df["open"].values.astype(np.float64); h = df["high"].values.astype(np.float64)
            l = df["low"].values.astype(np.float64); c = df["close"].values.astype(np.float64)
            lev = float(strat.default_params.get("leverage", 1) or 1)
            sl_pct = float(final_params.get("k_sl", 1.5)) * 0.01
            common = dict(leverage=lev, sl_pct=sl_pct, fee_rt=fees_bps * 2 * 1e-4, slip=slip_bps * 1e-4)
            row["A_replica"] = ref_backtest(o, h, l, c, sig, bb, exit_fill="close", compound=False, **common)
            row["B_exit_level"] = ref_backtest(o, h, l, c, sig, bb, exit_fill="level", compound=False, **common)
            row["C_level_compound"] = ref_backtest(o, h, l, c, sig, bb, exit_fill="level", compound=True, **common)
        except Exception as e:  # noqa: BLE001
            import traceback
            row["error"] = f"{type(e).__name__}: {e}"; row["trace"] = traceback.format_exc()[-400:]
        results.append(row)

    out = _ROOT / "catalog" / "graduation_results" / "cross_engine_validation.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 116)
    print(f"{'STRAT':9}{'mkt':13}{'tier':9}{'PROJET':>9}{'A=repl':>9}{'B=level':>9}{'C=comp':>9}{'B_DD':>8}{'C_DD':>8}{'C_ruin':>7}{'SL/TP/sig (A)':>16}")
    print("-" * 116)
    for r in results:
        if "error" in r:
            print(f"{r['label']:9}{r['symbol']+'/'+r['tf']:13} ERROR: {r['error'][:60]}")
            continue
        p, A, B, C = r["project"], r["A_replica"], r["B_exit_level"], r["C_level_compound"]
        ex = A["exits"]
        exits_str = f"{ex['sl']}/{ex['tp']}/{ex['signal']}"
        print(f"{r['label']:9}{r['symbol']+'/'+r['tf']:13}{r['tier']:9}"
              f"{p['total_return_pct']:>8.0f}%{A['total_return_pct']:>8.0f}%{B['total_return_pct']:>8.0f}%"
              f"{C['total_return_pct']:>8.0f}%{B['max_drawdown_pct']:>7.0f}%{C['max_drawdown_pct']:>7.0f}%"
              f"{str(C['ruined']):>7}{exits_str:>16}")
    print("=" * 116)
    print("\nA doit ≈ PROJET (validation réplique). B isole l'artefact sortie-au-close. C ajoute la composition.")
    print(f"Détails: {out}")


if __name__ == "__main__":
    main()
