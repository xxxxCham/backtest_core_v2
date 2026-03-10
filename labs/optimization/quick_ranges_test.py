#!/usr/bin/env python3
"""
Test rapide des nouvelles plages théoriques bollinger_atr
"""

import time

import pandas as pd

from backtest.engine import BacktestEngine
from strategies.bollinger_atr import BollingerATRStrategy


def load_sample_data():
    """Charge les données d'exemple"""
    df = pd.read_csv("data/sample_data/ETHUSDT_1m_sample.csv")
    df['datetime'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('datetime')
    return df

def test_new_ranges():
    """Test des nouvelles plages théoriques"""

    print("🎯 TEST DES NOUVELLES PLAGES THÉORIQUES")
    print("=" * 50)

    # Test configurations
    test_configs = [
        {
            "name": "Standard Théorique",
            "params": {
                "bb_period": 20,
                "bb_std": 2.0,
                "entry_z": 2.0,
                "atr_period": 14,
                "atr_percentile": 30,
                "k_sl": 1.5,
                "leverage": 1
            }
        },
        {
            "name": "Conservateur",
            "params": {
                "bb_period": 25,
                "bb_std": 1.8,
                "entry_z": 2.2,
                "atr_period": 18,
                "atr_percentile": 25,
                "k_sl": 1.2,
                "leverage": 1
            }
        },
        {
            "name": "Agressif",
            "params": {
                "bb_period": 15,
                "bb_std": 2.4,
                "entry_z": 1.6,
                "atr_period": 10,
                "atr_percentile": 45,
                "k_sl": 2.2,
                "leverage": 1
            }
        }
    ]

    # Charger les données
    df = load_sample_data()
    print(f"📊 Données chargées: {len(df)} barres")

    strategy = BollingerATRStrategy()

    # Utiliser l'initialisation simple
    engine = BacktestEngine(initial_capital=10000)

    results = []

    for test_config in test_configs:
        print(f"\n🔸 {test_config['name']}:")

        params = test_config['params']
        for key, value in params.items():
            if key != 'leverage':
                print(f"   • {key:15} = {value}")

        engine = BacktestEngine(initial_capital=10000)

        try:
            start_time = time.time()
            result = engine.run(
                df=df,
                strategy=strategy,
                params=params,
                symbol="ETHUSDT",
                timeframe="1m",
                silent_mode=True
            )
            duration = time.time() - start_time

            metrics = result.metrics
            pnl = metrics['total_pnl']
            sharpe = metrics['sharpe_ratio']
            trades = metrics.get('total_trades', 0)
            win_rate = metrics.get('win_rate_pct', 0)
            ruined = metrics.get('account_ruined', False)
            max_dd = metrics.get('max_drawdown_pct', 0)

            print(f"   📊 PnL: ${pnl:.2f} | Sharpe: {sharpe:.2f} | Trades: {trades}")
            print(f"   📈 Win Rate: {win_rate:.1f}% | Max DD: {max_dd:.1f}% | Ruined: {ruined}")
            print(f"   ⏱️ Durée: {duration:.2f}s")

            results.append({
                'name': test_config['name'],
                'pnl': pnl,
                'sharpe': sharpe,
                'trades': trades,
                'win_rate': win_rate,
                'ruined': ruined,
                'max_dd': max_dd
            })

        except Exception as e:
            print(f"   ❌ Erreur: {e}")
            results.append({
                'name': test_config['name'],
                'pnl': float('-inf'),
                'sharpe': float('-inf'),
                'trades': 0,
                'win_rate': 0,
                'ruined': True,
                'max_dd': 100
            })

    # Résumé comparatif
    print("\n🔍 RÉSUMÉ COMPARATIF:")
    print("=" * 70)
    print(f"{'Config':<20} {'PnL':<12} {'Sharpe':<8} {'Trades':<7} {'Win%':<6} {'DD%':<6} {'Ruined'}")
    print("-" * 70)

    best_pnl = float('-inf')
    best_config = ""

    for result in results:
        ruined_mark = "❌" if result['ruined'] else "✅"
        print(f"{result['name']:<20} ${result['pnl']:>8.2f} {result['sharpe']:>6.2f}  {result['trades']:>5d}   {result['win_rate']:>4.1f}% {result['max_dd']:>5.1f}%   {ruined_mark}")

        if result['pnl'] > best_pnl:
            best_pnl = result['pnl']
            best_config = result['name']

    print("-" * 70)

    # Analyse
    negative_count = sum(1 for r in results if r['pnl'] < 0)
    ruined_count = sum(1 for r in results if r['ruined'])

    print("\n💡 ANALYSE:")
    print(f"   • Meilleur résultat  : {best_config} (${best_pnl:.2f})")
    print(f"   • Résultats négatifs : {negative_count}/{len(results)} ({negative_count/len(results)*100:.1f}%)")
    print(f"   • Comptes ruinés     : {ruined_count}/{len(results)} ({ruined_count/len(results)*100:.1f}%)")

    if negative_count == len(results):
        print("   ⚠️ PROBLÈME: Toutes les configurations sont négatives")
        print("   🔧 RECOMMANDATION: Réviser la logique de la stratégie")
    elif ruined_count > len(results) / 2:
        print("   ⚠️ PROBLÈME: Trop de comptes ruinés")
        print("   🔧 RECOMMANDATION: Réviser la gestion du risque")
    elif best_pnl > 0:
        print("   ✅ POSITIF: Au moins une configuration profitable")
        print("   🎯 RECOMMANDATION: Focus sur les paramètres du meilleur résultat")
    else:
        print("   ⚠️ NEUTRE: Aucun résultat vraiment positif")
        print("   🔧 RECOMMANDATION: Ajuster les plages ou revoir la stratégie")

if __name__ == "__main__":
    test_new_ranges()
