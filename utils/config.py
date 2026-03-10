"""
Module-ID: utils.config

Purpose: Configuration centralisée du moteur (data_dir, frais, slippage, etc.).

Role in pipeline: core

Key components: Config (dataclass), singleton pattern, env var override

Inputs: Fichier config, variables d'environnement

Outputs: Config dict accessible globalement

Dependencies: dataclasses, pathlib, json

Conventions: BPS pour frais/slippage; data_dir obligatoire; env vars override config file.

Read-if: Modification params config, defaults, ou env var parsing.

Skip-if: Vous appelez juste Config.get_instance().
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _default_data_dir() -> Path:
    """
    Résout un data_dir portable:
    BACKTEST_DATA_DIR > BACKTEST_CORE_DATA_DIR > TRADX_DATA_ROOT > ./data/sample_data
    """
    for key in ("BACKTEST_DATA_DIR", "BACKTEST_CORE_DATA_DIR", "TRADX_DATA_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return Path.cwd() / "data" / "sample_data"


@dataclass
class Config:
    """
    Configuration globale du moteur de backtest.

    Attributes:
        data_dir: Répertoire des données OHLCV
        initial_capital: Capital de départ
        default_leverage: Levier par défaut
        fees_bps: Frais en points de base (10 = 0.1%)
        slippage_bps: Slippage en points de base
        seed: Seed pour reproductibilité
    """

    # Chemins
    data_dir: Path = field(default_factory=_default_data_dir)
    # Modèles LLM: configurés via D:\models\models.json (voir utils.model_loader)

    # Capital & Trading
    initial_capital: float = 10_000.0
    default_leverage: float = 1.0
    fees_bps: float = 10.0  # 0.1%
    slippage_bps: float = 5.0  # 0.05%

    # Déterminisme
    seed: int = 42

    # Granularité des paramètres (pour limiter les combinaisons)
    granularity: float = 0.5  # 0=fin, 1=grossier
    max_values_per_param: int = 4  # Plafond combinatoire

    # Méta
    _instance: Optional["Config"] = field(default=None, repr=False)

    @classmethod
    def get_instance(cls) -> "Config":
        """Singleton pour configuration globale."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Charge la configuration depuis un fichier JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "data_dir": str(self.data_dir),
            "initial_capital": self.initial_capital,
            "default_leverage": self.default_leverage,
            "fees_bps": self.fees_bps,
            "slippage_bps": self.slippage_bps,
            "seed": self.seed,
            "granularity": self.granularity,
            "max_values_per_param": self.max_values_per_param,
        }

    def save(self, path: Path) -> None:
        """Sauvegarde la configuration dans un fichier JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


# Configuration par défaut des Safe Ranges (inspiré de ThreadX)
SAFE_RANGES_PRESET = {
    "bollinger": {
        "period": {"min": 10, "max": 50, "default": 20},
        "std_dev": {"min": 1.5, "max": 3.0, "default": 2.0}
    },
    "atr": {
        "period": {"min": 7, "max": 21, "default": 14}
    },
    "rsi": {
        "period": {"min": 7, "max": 21, "default": 14},
        "overbought": {"min": 65, "max": 80, "default": 70},
        "oversold": {"min": 20, "max": 35, "default": 30}
    },
    "ema": {
        "fast_period": {"min": 5, "max": 20, "default": 12},
        "slow_period": {"min": 15, "max": 50, "default": 26}
    },
    "strategy": {
        "entry_z": {"min": 1.5, "max": 3.0, "default": 2.0},
        "k_sl": {"min": 1.0, "max": 3.0, "default": 1.5},
        "leverage": {"min": 1, "max": 10, "default": 1}
    }
}


def parameter_values(
    min_val: float,
    max_val: float,
    granularity: float = 0.5,
    max_values: int = 4,
) -> list[float]:
    """
    Génère les valeurs de paramètre selon la granularité.

    Logique inspirée de ThreadX pour limiter l'explosion combinatoire:
    - granularity=0: maximum de valeurs (finesse maximale)
    - granularity=1: une seule valeur médiane
    - max_values: plafond absolu (défaut=4)

    Args:
        min_val: Valeur minimale
        max_val: Valeur maximale
        granularity: Coefficient de granularité [0, 1]
        max_values: Nombre maximum de valeurs retournées

    Returns:
        Liste de valeurs échantillonnées
    """
    import numpy as np

    if min_val >= max_val:
        return [min_val]

    # Nombre de valeurs souhaité (inversement proportionnel à granularity)
    base_steps = max(2, int(10 * (1 - granularity)))

    # Réduire si plage étroite (<5% de variation)
    range_pct = (max_val - min_val) / max(abs(min_val), 1e-10)
    if range_pct < 0.05:
        base_steps = max(2, int(base_steps * 0.3))

    # Appliquer le plafond
    n_values = min(base_steps, max_values)

    # Générer les valeurs
    if n_values <= 1:
        return [(min_val + max_val) / 2]

    values = np.linspace(min_val, max_val, n_values)
    return [round(v, 4) for v in values]


__all__ = ["Config", "SAFE_RANGES_PRESET", "parameter_values"]
