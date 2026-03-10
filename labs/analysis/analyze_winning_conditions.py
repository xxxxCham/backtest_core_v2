"""
Analyse des conditions gagnantes vs perdantes d'une stratégie.

Objectif : Identifier QUAND la stratégie fonctionne pour construire des filtres.
"""
from pathlib import Path

import pandas as pd


def analyze_winning_conditions(
    trades_df: pd.DataFrame,
    market_data: pd.DataFrame,
    output_dir: str = "labs/analysis/results"
):
    """
    Analyse les trades gagnants vs perdants pour identifier des patterns.

    Args:
        trades_df: DataFrame avec colonnes [entry_time, exit_time, pnl, direction, ...]
        market_data: DataFrame OHLCV avec index datetime
        output_dir: Dossier de sortie
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Classifier trades
    trades_df['is_winner'] = trades_df['pnl'] > 0

    winning_trades = trades_df[trades_df['is_winner']]
    losing_trades = trades_df[~trades_df['is_winner']]

    print("="*80)
    print("ANALYSE DES CONDITIONS GAGNANTES")
    print("="*80)
    print(f"Total trades: {len(trades_df)}")
    print(f"  Gagnants: {len(winning_trades)} ({len(winning_trades)/len(trades_df)*100:.1f}%)")
    print(f"  Perdants: {len(losing_trades)} ({len(losing_trades)/len(trades_df)*100:.1f}%)")
    print()

    # === 1. ANALYSE PAR VOLATILITÉ ===
    print("1️⃣ ANALYSE PAR VOLATILITÉ")
    print("-" * 40)

    # Calculer ATR au moment de l'entrée
    market_data['atr_14'] = calculate_atr(market_data, period=14)

    # Joindre avec les trades
    for idx, trade in trades_df.iterrows():
        entry_time = trade['entry_time']
        if entry_time in market_data.index:
            trades_df.loc[idx, 'atr_at_entry'] = market_data.loc[entry_time, 'atr_14']

    # Comparer ATR moyen gagnants vs perdants
    atr_winners = trades_df[trades_df['is_winner']]['atr_at_entry'].mean()
    atr_losers = trades_df[~trades_df['is_winner']]['atr_at_entry'].mean()

    print(f"ATR moyen (gagnants): {atr_winners:.4f}")
    print(f"ATR moyen (perdants): {atr_losers:.4f}")
    print(f"Ratio: {atr_winners/atr_losers:.2f}x")
    print()

    # === 2. ANALYSE PAR TENDANCE ===
    print("2️⃣ ANALYSE PAR TENDANCE (SMA)")
    print("-" * 40)

    # Calculer SMA
    market_data['sma_50'] = market_data['close'].rolling(50).mean()
    market_data['above_sma'] = market_data['close'] > market_data['sma_50']

    # Joindre avec trades
    for idx, trade in trades_df.iterrows():
        entry_time = trade['entry_time']
        if entry_time in market_data.index:
            trades_df.loc[idx, 'above_sma'] = market_data.loc[entry_time, 'above_sma']

    # Comparer win rate selon position vs SMA
    above_sma = trades_df[trades_df["above_sma"]]
    below_sma = trades_df[~trades_df["above_sma"]]

    wr_above = above_sma['is_winner'].mean() * 100 if len(above_sma) > 0 else 0
    wr_below = below_sma['is_winner'].mean() * 100 if len(below_sma) > 0 else 0

    print(f"Win rate (prix > SMA50): {wr_above:.1f}% ({len(above_sma)} trades)")
    print(f"Win rate (prix < SMA50): {wr_below:.1f}% ({len(below_sma)} trades)")
    print()

    # === 3. ANALYSE PAR HEURE/JOUR ===
    print("3️⃣ ANALYSE TEMPORELLE")
    print("-" * 40)

    trades_df['entry_hour'] = pd.to_datetime(trades_df['entry_time']).dt.hour
    trades_df['entry_day'] = pd.to_datetime(trades_df['entry_time']).dt.dayofweek

    # Win rate par heure
    wr_by_hour = trades_df.groupby('entry_hour')['is_winner'].agg(['mean', 'count'])
    wr_by_hour['mean'] *= 100

    print("Win rate par heure (top 5):")
    top_hours = wr_by_hour[wr_by_hour['count'] >= 5].sort_values('mean', ascending=False).head()
    for hour, row in top_hours.iterrows():
        print(f"  {hour:02d}h: {row['mean']:.1f}% ({int(row['count'])} trades)")
    print()

    # === 4. RECOMMANDATIONS DE FILTRES ===
    print("4️⃣ RECOMMANDATIONS DE FILTRES")
    print("-" * 40)

    filters = []

    # Filtre volatilité
    if atr_winners > atr_losers * 1.2:
        atr_threshold = (atr_winners + atr_losers) / 2
        filters.append(f"✅ ATR > {atr_threshold:.4f} (favorise trades gagnants)")

    # Filtre tendance
    if abs(wr_above - wr_below) > 10:
        if wr_above > wr_below:
            filters.append("✅ Prix > SMA50 (favorise trades gagnants)")
        else:
            filters.append("✅ Prix < SMA50 (favorise trades gagnants)")

    # Filtre temporel
    best_hours = wr_by_hour[wr_by_hour['count'] >= 5].sort_values('mean', ascending=False).head(3)
    if len(best_hours) > 0:
        hours_list = ", ".join([f"{int(h):02d}h" for h in best_hours.index])
        filters.append(f"✅ Heures favorables: {hours_list}")

    if filters:
        print("Filtres suggérés :")
        for f in filters:
            print(f"  {f}")
    else:
        print("Aucun filtre évident détecté.")

    print()
    print("="*80)

    return {
        'trades_analyzed': trades_df,
        'filters': filters,
        'atr_winners': atr_winners,
        'atr_losers': atr_losers,
    }


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calcule Average True Range."""
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)

    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    return atr


# === EXEMPLE D'UTILISATION ===
if __name__ == "__main__":
    # Charger vos résultats de backtest
    # trades_df = pd.read_csv("path/to/trades.csv")
    # market_data = pd.read_parquet("path/to/AVAXUSDC_15m.parquet")

    # analyze_winning_conditions(trades_df, market_data)

    print("Script prêt. Importez vos données et lancez analyze_winning_conditions().")
