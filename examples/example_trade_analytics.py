"""
Exemple d'utilisation des métriques enrichies (TradeAnalytics)

Montre comment utiliser le nouveau système d'analyse de plages pour :
1. Exécuter un backtest avec métriques enrichies
2. Analyser MFE/MAE, distribution PnL, efficacité TP/SL
3. Exporter les résultats pour analyse LLM
4. Identifier les plages de paramètres à optimiser

Usage:
    python examples/example_trade_analytics.py
"""

import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine import BacktestEngine
from backtest.report_generator import export_trade_analytics_json, generate_llm_prompt
from data.loader import load_ohlcv
from strategies.bollinger_atr_v3 import BollingerATRStrategyV3


def main():
    print("=" * 80)
    print("EXEMPLE : Métriques Enrichies de Trading")
    print("=" * 80)
    print()

    # 1. Charger les données
    print("📊 Chargement des données...")
    df = load_ohlcv("BTCUSDC", "30m", lookback_days=90)
    print(f"✓ {len(df)} barres chargées")
    print()

    # 2. Configurer les paramètres
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "k_tp": 2.5,  # TP à tester
        "k_sl": 1.5,  # SL à tester
        "leverage": 3,
        "entry_z": 2.0,
    }

    print("⚙️  Paramètres de test :")
    for key, value in params.items():
        print(f"  - {key}: {value}")
    print()

    # 3. Exécuter le backtest
    print("🚀 Exécution du backtest...")
    engine = BacktestEngine(initial_capital=10000.0)

    result = engine.run(
        df=df,
        strategy=BollingerATRStrategyV3(),
        params=params,
        symbol="BTCUSDC",
        timeframe="30m",
        silent_mode=False  # Activer les métriques enrichies
    )

    print(f"✓ Backtest terminé : {len(result.trades)} trades")
    print()

    # 4. Afficher les métriques standard
    print("📈 Métriques Standard :")
    metrics = result.metrics
    print(f"  - Total Return: {metrics.get('total_return_pct', 0):.2f}%")
    print(f"  - Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"  - Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
    print(f"  - Win Rate: {metrics.get('win_rate', 0):.1f}%")
    print(f"  - Profit Factor: {metrics.get('profit_factor', 0):.2f}")
    print()

    # 5. Vérifier si analytics disponible
    if "trade_analytics" in metrics and metrics["trade_analytics"]:
        print("✨ Métriques Enrichies disponibles !")
        print()

        # Ré-enrichir pour obtenir l'objet TradeAnalytics
        # (normalement déjà fait dans engine, mais on le refait pour l'exemple)
        from backtest.trade_analytics import PnLDistribution, TPSLBoundsAnalysis, TradeAnalytics, TradeExcursions

        analytics_dict = metrics["trade_analytics"]

        # Reconstruire les objets (simplifié)
        excursions = TradeExcursions(**analytics_dict["excursions"])
        pnl_dist = PnLDistribution(**analytics_dict["pnl_distribution"])
        tp_sl = TPSLBoundsAnalysis(**analytics_dict["tp_sl_bounds"])

        analytics = TradeAnalytics(
            excursions=excursions,
            pnl_distribution=pnl_dist,
            tp_sl_bounds=tp_sl,
            total_trades=analytics_dict["total_trades"],
            win_rate=analytics_dict["win_rate"],
            profit_factor=analytics_dict["profit_factor"],
            expectancy=analytics_dict["expectancy"],
        )

        # 6. Afficher le résumé LLM
        print(analytics.to_llm_summary())
        print()

        # 7. Exporter vers JSON
        output_dir = Path("backtest_results/analytics_example")
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "analytics.json"
        export_trade_analytics_json(
            analytics,
            json_path,
            include_metadata={
                "strategy": "BollingerATRStrategyV3",
                "symbol": "BTCUSDC",
                "timeframe": "30m",
                "params": params,
            }
        )
        print(f"💾 Métriques exportées : {json_path}")
        print()

        # 8. Générer prompt LLM
        prompt = generate_llm_prompt(
            analytics,
            params,
            context="Stratégie Bollinger ATR V3 sur BTCUSDC 30m - Recherche de plages optimales"
        )

        prompt_path = output_dir / "llm_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"📝 Prompt LLM généré : {prompt_path}")
        print()

        # 9. Recommandations automatiques
        print("🎯 RECOMMANDATIONS AUTOMATIQUES :")
        print()

        if excursions.pct_mfe_above_tp > 50:
            print("  ⚠️  >50% des trades dépassent le TP actuel")
            print(f"      → Augmenter k_tp de {params['k_tp']} à ~{params['k_tp'] * 1.3:.1f}")
            print()

        if excursions.pct_mae_below_sl < 30:
            print("  ⚠️  <30% des trades touchent le SL actuel")
            print(f"      → Réduire k_sl de {params['k_sl']} à ~{params['k_sl'] * 0.8:.1f}")
            print()

        if pnl_dist.pnl_skewness < -0.5:
            print("  ⚠️  Distribution négativement asymétrique")
            print("      → Stratégie fragile, risque de grosses pertes")
            print()

        if tp_sl.pct_sl_hit > 60:
            print("  ⚠️  >60% sorties sur SL")
            print("      → Stratégie défensive insuffisante")
            print("      → Revoir les conditions d'entrée")
            print()

        if excursions.avg_mfe_to_tp_ratio > 1.5:
            print("  ✅ Ratio MFE/TP > 1.5")
            print("      → Plage TP peut être augmentée sans risque")
            print()

        print("=" * 80)
        print("✨ Analyse terminée avec succès !")
        print("=" * 80)

    else:
        print("⚠️  Métriques enrichies non disponibles (mode silent activé ?)")
        print()


if __name__ == "__main__":
    main()
