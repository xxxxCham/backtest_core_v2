"""
Module-ID: backtest.execution

Purpose: Modéliser l'exécution réaliste (spread bid/ask, slippage, latence, impact marché).

Role in pipeline: execution

Key components: ExecutionModel, ExecutionConfig, SpreadCalculator, SlippageCalculator

Inputs: Prix OHLCV, volatilité, volume, modèle (IDEAL/FIXED/DYNAMIC/REALISTIC)

Outputs: Spread/slippage appliqués au prix d'exécution

Dependencies: numpy, pandas, utils.log, optionnel: backtest.execution_fast (Numba)

Conventions: Spread en bps; slippage en fractions; latence en ms; modèles IDEAL < FIXED < DYNAMIC < REALISTIC en réalisme; optimisation 50-100x via Numba si dispo.

Read-if: Configuration réalisme exécution, calcul spread/slippage, ou modification frais/latence.

Skip-if: Backtests académiques (IDEAL model suffisant).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)

# Import fonctions optimisées (Numba si disponible)
try:
    from backtest.execution_fast import (
        HAS_NUMBA,
        high_low_spread,
        roll_spread,
    )
    USE_FAST_EXECUTION = True
    logger.debug(f"Execution optimizations: Numba={'available' if HAS_NUMBA else 'unavailable'}")
except ImportError:
    USE_FAST_EXECUTION = False
    HAS_NUMBA = False
    logger.debug("Execution optimizations: disabled")


class ExecutionModel(Enum):
    """Modèles d'exécution disponibles."""
    IDEAL = "ideal"           # Exécution instantanée au prix demandé
    FIXED = "fixed"           # Spread/slippage fixes
    DYNAMIC = "dynamic"       # Spread/slippage dynamiques
    REALISTIC = "realistic"   # Modèle complet avec impact


@dataclass
class ExecutionConfig:
    """
    Configuration du modèle d'exécution.

    Attributes:
        model: Type de modèle d'exécution
        spread_bps: Spread fixe en basis points (pour FIXED)
        slippage_bps: Slippage fixe en basis points (pour FIXED)
        latency_ms: Latence d'exécution en millisecondes
        use_volatility_spread: Ajuster spread selon volatilité
        use_volume_slippage: Ajuster slippage selon volume
        market_impact_bps: Impact de marché par unité de taille
        min_spread_bps: Spread minimum
        max_spread_bps: Spread maximum
        volatility_window: Fenêtre pour calcul volatilité
        volume_window: Fenêtre pour calcul volume moyen
    """
    model: ExecutionModel = ExecutionModel.DYNAMIC

    # Paramètres fixes
    spread_bps: float = 5.0
    slippage_bps: float = 3.0
    latency_ms: float = 50.0

    # Paramètres dynamiques
    use_volatility_spread: bool = True
    use_volume_slippage: bool = True
    market_impact_bps: float = 0.0  # Désactivé par défaut

    # Bornes
    min_spread_bps: float = 1.0
    max_spread_bps: float = 50.0
    min_slippage_bps: float = 0.5
    max_slippage_bps: float = 30.0

    # Fenêtres de calcul
    volatility_window: int = 20
    volume_window: int = 20

    # Facteurs de scaling
    volatility_spread_factor: float = 2.0  # Multiplie la volatilité normalisée
    volume_slippage_factor: float = 1.5    # Impact du ratio de volume

    # Optional partial fills (only for REALISTIC)
    partial_fill_prob: float = 0.0
    partial_fill_min: float = 0.5
    partial_fill_max: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "model": self.model.value,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "latency_ms": self.latency_ms,
            "use_volatility_spread": self.use_volatility_spread,
            "use_volume_slippage": self.use_volume_slippage,
            "market_impact_bps": self.market_impact_bps,
            "min_spread_bps": self.min_spread_bps,
            "max_spread_bps": self.max_spread_bps,
            "partial_fill_prob": self.partial_fill_prob,
            "partial_fill_min": self.partial_fill_min,
            "partial_fill_max": self.partial_fill_max,
        }


@dataclass
class ExecutionResult:
    """
    Résultat d'une exécution.

    Attributes:
        executed_price: Prix d'exécution final
        requested_price: Prix demandé original
        spread_cost: Coût du spread en valeur absolue
        slippage_cost: Coût du slippage en valeur absolue
        market_impact: Impact de marché en valeur absolue
        latency_bars: Nombre de barres de latence appliquées
        total_cost_bps: Coût total en basis points
    """
    executed_price: float
    requested_price: float
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    market_impact: float = 0.0
    latency_bars: int = 0
    filled_size: float = 0.0
    fill_ratio: float = 1.0

    @property
    def total_cost(self) -> float:
        """Coût total d'exécution."""
        return self.spread_cost + self.slippage_cost + self.market_impact

    @property
    def total_cost_bps(self) -> float:
        """Coût total en basis points."""
        if self.requested_price == 0:
            return 0.0
        return (self.total_cost / self.requested_price) * 10000

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "executed_price": self.executed_price,
            "requested_price": self.requested_price,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "market_impact": self.market_impact,
            "latency_bars": self.latency_bars,
            "total_cost_bps": self.total_cost_bps,
            "filled_size": self.filled_size,
            "fill_ratio": self.fill_ratio,
        }


class ExecutionEngine:
    """
    Moteur d'exécution réaliste.

    Calcule les prix d'exécution en tenant compte du spread,
    slippage, latence et impact de marché.

    Example:
        >>> config = ExecutionConfig(model=ExecutionModel.DYNAMIC)
        >>> engine = ExecutionEngine(config)
        >>> engine.prepare(df)  # Précalcule volatilité, volume
        >>> result = engine.execute_order(price=100.0, side=1, bar_idx=50)
    """

    def __init__(self, config: Optional[ExecutionConfig] = None):
        """
        Initialise le moteur d'exécution.

        Args:
            config: Configuration d'exécution (défaut: ExecutionConfig())
        """
        self.config = config or ExecutionConfig()
        self._prepared = False

        # Données précalculées
        self._volatility: Optional[np.ndarray] = None
        self._normalized_volatility: Optional[np.ndarray] = None
        self._volume_ratio: Optional[np.ndarray] = None
        self._bar_duration_ms: float = 0.0

        logger.debug(f"ExecutionEngine initialisé: {self.config.model.value}")

    def prepare(self, df: pd.DataFrame) -> None:
        """
        Précalcule les métriques nécessaires à partir des données OHLCV.

        Args:
            df: DataFrame OHLCV avec colonnes 'close', 'high', 'low', 'volume'
        """
        n = len(df)

        if n < 2:
            logger.warning("Données insuffisantes pour prepare()")
            self._prepared = False
            return

        # Calculer la durée d'une barre en ms
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) >= 2:
            delta = (df.index[1] - df.index[0]).total_seconds() * 1000
            self._bar_duration_ms = delta
        else:
            self._bar_duration_ms = 60000  # Défaut: 1 minute

        closes = df["close"].values

        # === Volatilité (VECTORISÉ) ===
        if self.config.use_volatility_spread:
            returns = np.zeros(n)
            returns[1:] = np.diff(closes) / closes[:-1]

            window = self.config.volatility_window

            # Calcul vectorisé avec pandas rolling (100x plus rapide)
            returns_series = pd.Series(returns)
            volatility_series = returns_series.rolling(window=window, min_periods=window).std()
            self._volatility = volatility_series.bfill().values

            # Normaliser (0-1 scale basé sur percentiles)
            if np.max(self._volatility) > 0:
                # S'assurer que la tranche n'est pas vide
                start_idx = min(window, len(self._volatility) - 1)
                vol_slice = self._volatility[start_idx:]

                if len(vol_slice) > 0:
                    p10 = np.percentile(vol_slice, 10)
                    p90 = np.percentile(vol_slice, 90)
                    self._normalized_volatility = np.clip(
                        (self._volatility - p10) / (p90 - p10 + 1e-10),
                        0, 1
                    )
                else:
                    # Fenêtre trop grande, utiliser des valeurs par défaut
                    self._normalized_volatility = np.ones_like(self._volatility) * 0.5
            else:
                self._normalized_volatility = np.zeros(n)
        else:
            self._volatility = np.zeros(n)
            self._normalized_volatility = np.zeros(n)

        # === Volume ratio (VECTORISÉ) ===
        if self.config.use_volume_slippage and "volume" in df.columns:
            volumes = df["volume"].values
            window = self.config.volume_window

            # Calcul vectorisé avec pandas rolling (100x plus rapide)
            volumes_series = pd.Series(volumes)
            avg_volume = volumes_series.rolling(window=window, min_periods=window).mean()
            avg_volume = avg_volume.bfill().values

            # Éviter division par zéro
            avg_volume = np.where(avg_volume == 0, 1.0, avg_volume)

            # Ratio = volume_courant / volume_moyen
            # Faible volume = plus de slippage
            with np.errstate(divide='ignore', invalid='ignore'):
                volume_ratio = volumes / avg_volume
                # Inverser: faible volume = ratio > 1 = plus de slippage
                self._volume_ratio = np.where(volume_ratio > 0, 1.0 / volume_ratio, 1.0)

            # Limiter entre 0.5 et 3.0
            self._volume_ratio = np.clip(self._volume_ratio, 0.5, 3.0)
        else:
            self._volume_ratio = np.ones(n)

        self._prepared = True
        logger.debug(f"ExecutionEngine préparé: {n} barres")

    def _calculate_spread_bps(self, bar_idx: int) -> float:
        """Calcule le spread en BPS pour une barre donnée."""
        if self.config.model == ExecutionModel.IDEAL:
            return 0.0

        if self.config.model == ExecutionModel.FIXED:
            return self.config.spread_bps

        # Modèle dynamique
        base_spread = self.config.spread_bps

        if self.config.use_volatility_spread and self._normalized_volatility is not None:
            vol_factor = self._normalized_volatility[bar_idx]
            # Plus de volatilité = plus de spread
            spread_adjustment = vol_factor * self.config.volatility_spread_factor
            base_spread *= (1 + spread_adjustment)

        return np.clip(
            base_spread,
            self.config.min_spread_bps,
            self.config.max_spread_bps
        )

    def _calculate_slippage_bps(self, bar_idx: int, size: float = 1.0) -> float:
        """Calcule le slippage en BPS pour une barre donnée."""
        if self.config.model == ExecutionModel.IDEAL:
            return 0.0

        if self.config.model == ExecutionModel.FIXED:
            return self.config.slippage_bps

        # Modèle dynamique
        base_slippage = self.config.slippage_bps

        if self.config.use_volume_slippage and self._volume_ratio is not None:
            vol_ratio = self._volume_ratio[bar_idx]
            # Faible volume (ratio > 1) = plus de slippage
            base_slippage *= vol_ratio * self.config.volume_slippage_factor

        return np.clip(
            base_slippage,
            self.config.min_slippage_bps,
            self.config.max_slippage_bps
        )

    def _calculate_market_impact_bps(self, size: float, price: float) -> float:
        """Calcule l'impact de marché en BPS."""
        if self.config.market_impact_bps == 0:
            return 0.0

        # Impact proportionnel à la taille de l'ordre
        # Plus l'ordre est gros, plus l'impact est important
        return self.config.market_impact_bps * np.sqrt(size)

    def _calculate_latency_bars(self) -> int:
        """Calcule le nombre de barres de latence."""
        if self.config.latency_ms == 0 or self._bar_duration_ms == 0:
            return 0

        # Latence en nombre de barres (arrondi supérieur)
        return int(np.ceil(self.config.latency_ms / self._bar_duration_ms))

    def execute_order(
        self,
        price: float,
        side: int,
        bar_idx: int,
        size: float = 1.0
    ) -> ExecutionResult:
        """
        Simule l'exécution d'un ordre.

        Args:
            price: Prix demandé (mid-price)
            side: Direction (1 = achat/long, -1 = vente/short)
            bar_idx: Index de la barre courante
            size: Taille de l'ordre (pour impact de marché)

        Returns:
            ExecutionResult avec tous les détails d'exécution
        """
        if not self._prepared and self.config.model in (ExecutionModel.DYNAMIC, ExecutionModel.REALISTIC):
            logger.warning("ExecutionEngine non préparé - utilisation valeurs fixes")

        # Borner l'index
        if self._normalized_volatility is not None:
            bar_idx = min(bar_idx, len(self._normalized_volatility) - 1)
        bar_idx = max(0, bar_idx)

        size = abs(size)

        # Calculer les composantes
        spread_bps = self._calculate_spread_bps(bar_idx)
        slippage_bps = self._calculate_slippage_bps(bar_idx, size)
        impact_bps = self._calculate_market_impact_bps(size, price)
        latency_bars = self._calculate_latency_bars()

        # Convertir en coûts absolus
        spread_cost = price * (spread_bps / 10000) / 2  # Demi-spread
        slippage_cost = price * (slippage_bps / 10000)
        impact_cost = price * (impact_bps / 10000)

        # Prix d'exécution (ajusté selon direction)
        # Achat: prix + coûts, Vente: prix - coûts
        total_adjustment = spread_cost + slippage_cost + impact_cost
        executed_price = price + (side * total_adjustment)

        # Optional partial fills
        fill_ratio = 1.0
        filled_size = size
        if self.config.model == ExecutionModel.REALISTIC and self.config.partial_fill_prob > 0:
            if np.random.random() < self.config.partial_fill_prob:
                fill_ratio = np.random.uniform(
                    self.config.partial_fill_min,
                    self.config.partial_fill_max
                )
                filled_size = size * fill_ratio

        return ExecutionResult(
            executed_price=executed_price,
            requested_price=price,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            market_impact=impact_cost,
            latency_bars=latency_bars,
            filled_size=filled_size,
            fill_ratio=fill_ratio,
        )

    def get_bid_ask(self, mid_price: float, bar_idx: int) -> Tuple[float, float]:
        """
        Calcule les prix bid/ask à partir du mid-price.

        Args:
            mid_price: Prix médian
            bar_idx: Index de la barre

        Returns:
            Tuple (bid, ask)
        """
        spread_bps = self._calculate_spread_bps(bar_idx)
        half_spread = mid_price * (spread_bps / 10000) / 2

        bid = mid_price - half_spread
        ask = mid_price + half_spread

        return bid, ask

    def get_execution_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques d'exécution."""
        stats = {
            "model": self.config.model.value,
            "prepared": self._prepared,
            "bar_duration_ms": self._bar_duration_ms,
        }

        if self._volatility is not None:
            stats["avg_volatility"] = float(np.mean(self._volatility))
            stats["max_volatility"] = float(np.max(self._volatility))

        if self._volume_ratio is not None:
            stats["avg_volume_ratio"] = float(np.mean(self._volume_ratio))

        return stats


class SpreadCalculator:
    """
    Calculateur de spread bid/ask.

    Fournit plusieurs méthodes pour estimer le spread:
    - Fixe
    - Basé sur volatilité
    - Basé sur volume
    - High-Low estimator (Roll)
    """

    @staticmethod
    def fixed_spread(base_bps: float = 5.0) -> float:
        """Spread fixe en BPS."""
        return base_bps

    @staticmethod
    def volatility_spread(
        returns: np.ndarray,
        base_bps: float = 5.0,
        vol_factor: float = 2.0
    ) -> np.ndarray:
        """
        Spread basé sur la volatilité récente.

        Args:
            returns: Array des rendements
            base_bps: Spread de base
            vol_factor: Facteur multiplicateur de volatilité

        Returns:
            Array des spreads en BPS
        """
        vol = np.abs(returns) * 10000  # En BPS
        return np.maximum(base_bps, vol * vol_factor)

    @staticmethod
    def roll_spread(
        closes: np.ndarray,
        window: int = 20
    ) -> np.ndarray:
        """
        Estimateur de Roll pour le spread bid/ask.

        Basé sur l'autocovariance des rendements.
        Roll (1984): spread = 2 * sqrt(-cov(r_t, r_{t-1}))

        Args:
            closes: Array des prix de clôture
            window: Fenêtre de calcul

        Returns:
            Array des spreads estimés (en valeur, pas en BPS)

        Notes:
            Utilise implémentation optimisée (Numba si disponible, sinon pandas rolling)
        """
        returns = np.zeros(len(closes))
        returns[1:] = np.diff(closes) / closes[:-1]

        # Utiliser version optimisée si disponible
        if USE_FAST_EXECUTION:
            return roll_spread(closes, returns, window)

        # Fallback: pandas rolling (vectorisé, 50x plus rapide que boucle Python)
        returns_series = pd.Series(returns)
        returns_lag = returns_series.shift(1)
        cov = returns_series.rolling(window).cov(returns_lag).fillna(0).values

        spreads = np.zeros(len(closes))
        negative_cov = cov < 0
        spreads[negative_cov] = 2 * np.sqrt(-cov[negative_cov]) * closes[negative_cov]

        return spreads

    @staticmethod
    def high_low_spread(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray = None  # Pas utilisé mais gardé pour compatibilité API
    ) -> np.ndarray:
        """
        Estimateur Corwin-Schultz basé sur High-Low.

        Args:
            highs: Array des hauts
            lows: Array des bas
            closes: Array des clôtures (non utilisé, pour compatibilité)

        Returns:
            Array des spreads estimés en BPS

        Notes:
            Utilise implémentation optimisée (Numba si disponible, sinon boucle Python)
        """
        # Utiliser version optimisée si disponible (Numba JIT-compiled)
        if USE_FAST_EXECUTION and HAS_NUMBA:
            return high_low_spread(highs, lows)

        # Fallback: boucle Python (difficilement vectorisable à cause de max/min imbriqués)
        n = len(highs)
        spreads = np.zeros(n)
        sqrt_2 = np.sqrt(2.0)

        for i in range(2, n):
            # Beta = (ln(H_t/L_t))^2 + (ln(H_{t-1}/L_{t-1}))^2
            beta = (np.log(highs[i] / lows[i])) ** 2 + (np.log(highs[i-1] / lows[i-1])) ** 2

            # Gamma = (ln(max(H_t, H_{t-1}) / min(L_t, L_{t-1})))^2
            gamma = (np.log(max(highs[i], highs[i-1]) / min(lows[i], lows[i-1]))) ** 2

            # Alpha
            denom = 3.0 - 2.0 * sqrt_2
            if abs(denom) > 1e-10:
                alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)

                # Spread = 2 * (e^alpha - 1) / (1 + e^alpha)
                if alpha > -10:  # Éviter overflow
                    exp_alpha = np.exp(alpha)
                    spread_pct = 2 * (exp_alpha - 1) / (1 + exp_alpha)
                    spreads[i] = max(0, spread_pct * 10000)  # En BPS

        return spreads


class SlippageCalculator:
    """
    Calculateur de slippage.

    Fournit plusieurs modèles de slippage:
    - Fixe
    - Proportionnel au volume
    - Basé sur volatilité
    - Impact de marché (Almgren-Chriss)
    """

    @staticmethod
    def fixed_slippage(base_bps: float = 3.0) -> float:
        """Slippage fixe en BPS."""
        return base_bps

    @staticmethod
    def volume_slippage(
        order_size: float,
        avg_volume: float,
        base_bps: float = 3.0,
        impact_factor: float = 0.1
    ) -> float:
        """
        Slippage basé sur le ratio taille_ordre / volume_moyen.

        Args:
            order_size: Taille de l'ordre
            avg_volume: Volume moyen
            base_bps: Slippage de base
            impact_factor: Facteur d'impact

        Returns:
            Slippage en BPS
        """
        if avg_volume <= 0:
            return base_bps

        participation_rate = order_size / avg_volume
        return base_bps * (1 + impact_factor * participation_rate)

    @staticmethod
    def volatility_slippage(
        volatility: float,
        base_bps: float = 3.0,
        vol_multiplier: float = 100.0
    ) -> float:
        """
        Slippage basé sur la volatilité.

        Args:
            volatility: Volatilité (écart-type des rendements)
            base_bps: Slippage de base
            vol_multiplier: Multiplicateur de volatilité

        Returns:
            Slippage en BPS
        """
        return base_bps + volatility * vol_multiplier

    @staticmethod
    def almgren_chriss_impact(
        order_size: float,
        daily_volume: float,
        daily_volatility: float,
        eta: float = 0.1,
        gamma: float = 0.5
    ) -> float:
        """
        Modèle d'impact de marché Almgren-Chriss.

        Temporary impact = eta * sigma * (Q / V)^gamma

        Args:
            order_size: Taille de l'ordre (Q)
            daily_volume: Volume journalier (V)
            daily_volatility: Volatilité journalière (sigma)
            eta: Paramètre d'impact
            gamma: Exposant (généralement 0.5 pour sqrt)

        Returns:
            Impact temporaire en fraction de prix
        """
        if daily_volume <= 0:
            return 0.0

        return eta * daily_volatility * (order_size / daily_volume) ** gamma


def create_execution_engine(
    model: str = "dynamic",
    spread_bps: float = 5.0,
    slippage_bps: float = 3.0,
    latency_ms: float = 50.0,
    **kwargs
) -> ExecutionEngine:
    """
    Factory pour créer un ExecutionEngine configuré.

    Args:
        model: Type de modèle ('ideal', 'fixed', 'dynamic', 'realistic')
        spread_bps: Spread de base en BPS
        slippage_bps: Slippage de base en BPS
        latency_ms: Latence en millisecondes
        **kwargs: Paramètres additionnels pour ExecutionConfig

    Returns:
        ExecutionEngine configuré

    Example:
        >>> engine = create_execution_engine(model="dynamic", spread_bps=3.0)
        >>> engine.prepare(df)
        >>> result = engine.execute_order(price=100, side=1, bar_idx=50)
    """
    model_enum = ExecutionModel(model.lower())

    config = ExecutionConfig(
        model=model_enum,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        latency_ms=latency_ms,
        **kwargs
    )

    return ExecutionEngine(config)


__all__ = [
    "ExecutionModel",
    "ExecutionConfig",
    "ExecutionResult",
    "ExecutionEngine",
    "SpreadCalculator",
    "SlippageCalculator",
    "create_execution_engine",
]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur exécution réaliste
# - Conventions spread (bps), slippage (fractions), modèles (IDEAL...REALISTIC) explicitées
# - Read-if/Skip-if ajoutés pour tri rapide
