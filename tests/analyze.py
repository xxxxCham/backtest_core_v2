#!/usr/bin/env python
"""
CLI pour analyser rapidement les résultats de backtests
Usage: python analyze.py [options]
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.analyze_results import extract_all_results
from tools.generate_html_report import generate_html_report


def main():
    parser = argparse.ArgumentParser(
        description='📊 Analyse des résultats de backtests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python analyze.py                    # Analyse complète console
  python analyze.py --html             # Générer rapport HTML
  python analyze.py --csv              # Exporter CSV uniquement
  python analyze.py --strategy ema     # Filtrer par stratégie
  python analyze.py --profitable       # Voir uniquement configs profitables
  python analyze.py --top 10           # Afficher top 10 uniquement
        """
    )

    parser.add_argument('--html', action='store_true',
                       help='Générer un rapport HTML interactif')
    parser.add_argument('--csv', action='store_true',
                       help='Exporter CSV uniquement (pas d\'analyse console)')
    parser.add_argument('--strategy', type=str,
                       help='Filtrer par nom de stratégie')
    parser.add_argument('--symbol', type=str,
                       help='Filtrer par symbole')
    parser.add_argument('--timeframe', type=str,
                       help='Filtrer par timeframe')
    parser.add_argument('--profitable', action='store_true',
                       help='Afficher uniquement les configurations profitables')
    parser.add_argument('--top', type=int, default=None,
                       help='Nombre de meilleures configs à afficher')
    parser.add_argument('--min-pnl', type=float,
                       help='PnL minimum pour filtrage')
    parser.add_argument('--min-sharpe', type=float,
                       help='Sharpe ratio minimum pour filtrage')

    args = parser.parse_args()

    # Extraire les résultats
    print("🔍 Chargement des résultats...")
    results = extract_all_results()

    if not results:
        print("❌ Aucun résultat trouvé dans backtest_results/")
        return 1

    # Appliquer les filtres
    filtered = results

    if args.strategy:
        filtered = [r for r in filtered if args.strategy.lower() in r['strategy'].lower()]
        print(f"🎯 Filtre stratégie: {args.strategy} ({len(filtered)} résultats)")

    if args.symbol:
        filtered = [r for r in filtered if args.symbol.upper() == r['symbol'].upper()]
        print(f"💰 Filtre symbole: {args.symbol} ({len(filtered)} résultats)")

    if args.timeframe:
        filtered = [r for r in filtered if args.timeframe == r['tf']]
        print(f"⏰ Filtre timeframe: {args.timeframe} ({len(filtered)} résultats)")

    if args.profitable:
        filtered = [r for r in filtered if r['pnl'] > 0]
        print(f"💚 Filtre profitable uniquement ({len(filtered)} résultats)")

    if args.min_pnl:
        filtered = [r for r in filtered if r['pnl'] >= args.min_pnl]
        print(f"💵 Filtre PnL >= ${args.min_pnl} ({len(filtered)} résultats)")

    if args.min_sharpe:
        filtered = [r for r in filtered if r['sharpe'] >= args.min_sharpe]
        print(f"📈 Filtre Sharpe >= {args.min_sharpe} ({len(filtered)} résultats)")

    if not filtered:
        print("⚠️  Aucun résultat après filtrage")
        return 1

    # Top N
    if args.top:
        filtered = sorted(filtered, key=lambda x: x['pnl'], reverse=True)[:args.top]
        print(f"🏆 Top {args.top} configurations")

    # Export CSV uniquement
    if args.csv:
        output = f'analysis_filtered_{len(filtered)}_configs.csv'

        # Créer export data
        import pandas as pd
        export_data = []
        for r in sorted(filtered, key=lambda x: x['pnl'], reverse=True):
            row = {
                'rank': len(export_data) + 1,
                'strategy': r['strategy'],
                'symbol': r['symbol'],
                'timeframe': r['tf'],
                'pnl': r['pnl'],
                'return_pct': r['return_pct'],
                'sharpe': r['sharpe'],
                'win_rate': r['win_rate'],
                'trades': r['trades'],
                'profit_factor': r['profit_factor'],
                'run_id': r['run_id'],
            }
            for k, v in r['params'].items():
                row[f'param_{k}'] = v
            export_data.append(row)

        df = pd.DataFrame(export_data)
        df.to_csv(output, index=False)
        print(f"\n✅ {len(filtered)} configs exportées vers: {output}")
        return 0

    # Génération HTML
    if args.html:
        output = 'analysis_report_filtered.html' if len(filtered) < len(results) else 'analysis_report.html'
        generate_html_report(filtered, output)
        return 0

    # Analyse console complète
    print(f"\n{'='*120}")
    print(f"📊 ANALYSE DE {len(filtered)} CONFIGURATIONS")
    print(f"{'='*120}\n")

    # Affichage simplifié
    sorted_results = sorted(filtered, key=lambda x: x['pnl'], reverse=True)

    print(f"{'Rang':<6} {'Stratégie':<20} {'Symbole':<12} {'TF':<6} {'PnL':>15} {'Return%':>10} {'Sharpe':>7} {'Trades':>7} {'WinRate':>8}")
    print("-" * 120)

    for i, r in enumerate(sorted_results[:50], 1):  # Max 50 lignes
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅" if i <= 10 else ""
        pnl_emoji = "💚" if r['pnl'] > 0 else "💔"
        print(f"{emoji:<2}{i:<4} {r['strategy']:<20} {r['symbol']:<12} {r['tf']:<6} {pnl_emoji}${r['pnl']:>12,.2f} {r['return_pct']:>9.2f}% {r['sharpe']:>7.2f} {r['trades']:>7} {r['win_rate']:>7.1f}%")

        # Afficher les paramètres pour le top 3
        if i <= 3 and r['params']:
            params_str = ', '.join([f"{k}={v}" for k, v in sorted(r['params'].items())])
            print(f"       📋 {params_str}\n")

    if len(sorted_results) > 50:
        print(f"\n... et {len(sorted_results) - 50} autres configurations")

    # Stats rapides
    profitable = sum(1 for r in filtered if r['pnl'] > 0)
    total_pnl = sum(r['pnl'] for r in filtered)
    avg_pnl = total_pnl / len(filtered)

    print(f"\n{'='*120}")
    print("📊 STATISTIQUES")
    print(f"{'='*120}")
    print(f"Total configs: {len(filtered)}")
    print(f"Profitables: {profitable} ({100*profitable/len(filtered):.1f}%)")
    print(f"PnL total: ${total_pnl:,.2f}")
    print(f"PnL moyen: ${avg_pnl:,.2f}")
    print(f"Meilleur: ${max(r['pnl'] for r in filtered):,.2f}")
    print(f"Pire: ${min(r['pnl'] for r in filtered):,.2f}")

    print("\n💡 Astuce: Utilisez --html pour un rapport interactif")
    print("💡 Astuce: Utilisez --csv pour export Excel")

    return 0


if __name__ == '__main__':
    sys.exit(main())
