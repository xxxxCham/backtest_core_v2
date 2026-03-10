"""
Module-ID: data.sample_data.generate_sample

Purpose: Générateur données d'exemple synthétiques pour tests unitaires.

Role in pipeline: test data

Key components: generate_sample_btcusdt(), generate_sample_multi_token(), export parquet

Inputs: Output path, nombre barres

Outputs: Fichier parquet OHLCV avec données réalistes

Dependencies: numpy, pandas, pathlib

Conventions: Seed=42 pour reproductibilité; colonnes [open, high, low, close, volume]

Read-if: Générer données test ou démo.

Skip-if: Vous utiliser vos données réelles.
"""

from pathlib import Path

import numpy as np
import pandas as pd


def generate_sample_btcusdt(output_path: Path = None):
    """Génère des données synthétiques similaires à BTCUSDT."""
    np.random.seed(42)

    n_bars = 10000

    # Prix initial type BTC
    start_price = 42000.0
    volatility = 0.001  # ~0.1% par minute
    trend = 0.00001     # Légère tendance haussière

    # Générer les rendements
    returns = np.random.normal(trend, volatility, n_bars)

    # Ajouter quelques mouvements plus importants (fat tails)
    outliers = np.random.choice(n_bars, size=int(n_bars * 0.01), replace=False)
    returns[outliers] *= np.random.uniform(3, 8, len(outliers))

    # Construire les prix
    prices = start_price * np.exp(np.cumsum(returns))

    # Construire OHLCV
    df = pd.DataFrame()

    # Close prices
    df["close"] = prices

    # Open = previous close + noise
    df["open"] = df["close"].shift(1).fillna(start_price)

    # High/Low avec spread réaliste
    spread = np.random.uniform(0.0005, 0.002, n_bars) * prices
    df["high"] = np.maximum(df["open"], df["close"]) + spread
    df["low"] = np.minimum(df["open"], df["close"]) - spread

    # Volume (style crypto avec périodes actives)
    base_volume = np.random.exponential(50, n_bars)
    volatility_volume = np.abs(returns) * 5000  # Plus de volume sur gros mouvements
    df["volume"] = base_volume + volatility_volume

    # Index datetime
    start = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    df.index = pd.date_range(start=start, periods=n_bars, freq="1min")
    df.index.name = "timestamp"

    # Arrondir les valeurs
    df["open"] = df["open"].round(2)
    df["high"] = df["high"].round(2)
    df["low"] = df["low"].round(2)
    df["close"] = df["close"].round(2)
    df["volume"] = df["volume"].round(4)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path)
        print(f"✅ Données générées: {output_path} ({len(df)} lignes)")

    return df


def generate_sample_ethusdt(output_path: Path = None):
    """Génère des données synthétiques similaires à ETHUSDT."""
    np.random.seed(123)

    n_bars = 10000
    start_price = 2200.0
    volatility = 0.0015  # ETH plus volatile que BTC
    trend = 0.00002

    returns = np.random.normal(trend, volatility, n_bars)
    prices = start_price * np.exp(np.cumsum(returns))

    df = pd.DataFrame()
    df["close"] = prices
    df["open"] = df["close"].shift(1).fillna(start_price)
    spread = np.random.uniform(0.0005, 0.003, n_bars) * prices
    df["high"] = np.maximum(df["open"], df["close"]) + spread
    df["low"] = np.minimum(df["open"], df["close"]) - spread
    df["volume"] = np.random.exponential(200, n_bars)

    start = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    df.index = pd.date_range(start=start, periods=n_bars, freq="1min")
    df.index.name = "timestamp"

    df = df.round(2)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path)
        print(f"✅ Données générées: {output_path} ({len(df)} lignes)")

    return df


if __name__ == "__main__":
    data_dir = Path(__file__).parent

    print("Génération des données d'exemple...")
    print("=" * 40)

    generate_sample_btcusdt(data_dir / "BTCUSDT_1m_sample.csv")
    generate_sample_ethusdt(data_dir / "ETHUSDT_1m_sample.csv")

    print("\n✅ Terminé!")
