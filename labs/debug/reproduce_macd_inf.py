#!/usr/bin/env python3
"""
Test pour reproduire exactement le bug PnL = -inf du sweep MACD
"""

import itertools

import numpy as np

from backtest.engine import BacktestEngine
from data.loader import load_ohlcv
from strategies.macd_cross import MACDCrossStrategy


def reproduce_macd_inf_bug():
    """Reproduire le bug PnL = -inf en testant des combinaisons problématiques."""
    print("🔍 REPRODUCTION BUG MACD PnL = -inf")
    print("=" * 45)

    # Charger données
    df = load_ohlcv("BTCUSDC", "30m")
    if df.empty:
        print("❌ Pas de données BTCUSDC/30m")
        return

    # Prendre différentes tailles d'échantillon pour tester
    test_sizes = [50, 100, 200, 500]

    # Paramètres problématiques potentiels (tirés du ParameterSpec de macd_cross)
    fast_periods = [5, 10, 15, 25, 30]  # min_val=5, max_val=30
    slow_periods = [15, 20, 30, 40, 50]  # min_val=15, max_val=50
    signal_periods = [5, 10, 15, 20]      # min_val=5, max_val=20

    print(f"🧪 Test de {len(fast_periods) * len(slow_periods) * len(signal_periods)} combinaisons")

    bug_found = False
    strategy = MACDCrossStrategy()

    for size in test_sizes:
        if bug_found:
            break

        df_test = df.head(size)
        print(f"\n📊 Test avec {size} barres...")

        bug_combos = []

        for fast, slow, signal in itertools.product(fast_periods, slow_periods, signal_periods):
            # Vérifier contraintes logiques
            if fast >= slow:  # fast doit être < slow
                continue

            params = {
                "fast_period": fast,
                "slow_period": slow,
                "signal_period": signal,
                "leverage": 1
            }

            try:
                engine = BacktestEngine(initial_capital=10000.0)
                result = engine.run(
                    df=df_test,
                    strategy=strategy,
                    params=params,
                    symbol="BTCUSDC",
                    timeframe="30m",
                    silent_mode=True  # Éviter les logs
                )

                pnl = result.metrics.get("total_pnl", 0)

                # Vérifier si on a trouvé le bug
                if pnl == float('-inf') or pnl == float('inf') or np.isnan(pnl):
                    print(f"❌ BUG TROUVÉ! Params: {params}")
                    print(f"   PnL: {pnl}")
                    print(f"   Sharpe: {result.metrics.get('sharpe_ratio', 'N/A')}")
                    print(f"   Trades: {result.metrics.get('total_trades', 'N/A')}")
                    print(f"   Account ruiné: {result.metrics.get('account_ruined', 'N/A')}")

                    # Analyser l'équité
                    if hasattr(result, 'equity'):
                        print(f"   Équité min: ${result.equity.min():.2f}")
                        print(f"   Équité max: ${result.equity.max():.2f}")
                        print(f"   Équité finale: ${result.equity.iloc[-1]:.2f}")

                        # Chercher valeurs infinies dans equity
                        inf_count = np.isinf(result.equity).sum()
                        nan_count = np.isnan(result.equity).sum()
                        print(f"   Équité inf: {inf_count}/{len(result.equity)}")
                        print(f"   Équité NaN: {nan_count}/{len(result.equity)}")

                    bug_combos.append(params)
                    bug_found = True

                    if len(bug_combos) >= 3:  # Arrêter après 3 bugs trouvés
                        break

            except Exception as e:
                # Vérifier si l'exception contient "inf"
                if "inf" in str(e).lower():
                    print(f"❌ EXCEPTION INF! Params: {params}")
                    print(f"   Erreur: {e}")
                    bug_combos.append(params)
                    bug_found = True

        if bug_combos:
            print(f"\n🎯 {len(bug_combos)} combinaisons problématiques trouvées avec {size} barres")
            break

    if not bug_found:
        print("\n⚠️ Bug PnL = -inf non reproduit avec ces paramètres")
        print("Le problème pourrait venir de:")
        print("- Données spécifiques à certains tokens/timeframes")
        print("- Paramètres encore plus extrêmes")
        print("- Problème dans le calcul des métriques")
        print("- Race conditions en mode parallèle")

        # Tester avec des paramètres encore plus extrêmes
        print("\n🔬 Test avec paramètres extrêmes...")
        extreme_params = [
            {"fast_period": 29, "slow_period": 30, "signal_period": 5},   # Très proche
            {"fast_period": 5, "slow_period": 50, "signal_period": 20},   # Très écarté
            {"fast_period": 10, "slow_period": 15, "signal_period": 20},  # Signal > slow
        ]

        for params in extreme_params:
            try:
                engine = BacktestEngine(initial_capital=10000.0)
                result = engine.run(
                    df=df.head(100),
                    strategy=strategy,
                    params=params,
                    symbol="BTCUSDC",
                    timeframe="30m"
                )

                pnl = result.metrics.get("total_pnl", 0)
                print(f"Params {params}: PnL = {pnl}")

            except Exception as e:
                print(f"Params {params}: ERREUR - {e}")

    print("\n✅ Test terminé")

if __name__ == "__main__":
    reproduce_macd_inf_bug()
