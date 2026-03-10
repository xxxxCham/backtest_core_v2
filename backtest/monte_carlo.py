"""
Module-ID: backtest.monte_carlo

Purpose: Échantillonnage intelligent de l'espace des paramètres (random/LHS/Sobol) pour optimisation plus rapide.

Role in pipeline: optimization

Key components: SamplingMethod, ParameterSpace, sample_parameters, MonteCarlo

Inputs: param_space Dict, n_samples, méthode (RANDOM/LATIN_HYPERCUBE/SOBOL)

Outputs: Échantillons (liste de dicts de paramètres)

Dependencies: numpy, optionnel: scipy.stats (LHS)

Conventions: Paramètres en fractions [0,1] puis redimensionnés; log_scale si demandé; échantillonnage uniforme sur l'espace.

Read-if: Optimisation via Monte Carlo au lieu de sweep exhaustif, ou échantillonnage intelligent.

Skip-if: Vous utilisez sweep/optuna/pareto au lieu d'échantillonnage aléatoire.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from utils.log import get_logger

logger = get_logger(__name__)


class SamplingMethod(Enum):
    """Méthodes d'échantillonnage disponibles."""
    RANDOM = "random"
    LATIN_HYPERCUBE = "latin_hypercube"
    SOBOL = "sobol"


@dataclass
class ParameterSpace:
    """
    Définition de l'espace des paramètres à échantillonner.

    Attributes:
        name: Nom du paramètre
        min_val: Valeur minimale
        max_val: Valeur maximale
        param_type: 'int' ou 'float'
        log_scale: Si True, échantillonnage en échelle log
    """
    name: str
    min_val: float
    max_val: float
    param_type: str = "float"
    log_scale: bool = False

    def sample(self, u: float) -> Any:
        """
        Convertit une valeur uniforme [0,1] en valeur du paramètre.

        Args:
            u: Valeur uniforme entre 0 et 1

        Returns:
            Valeur dans l'espace du paramètre
        """
        if self.log_scale and self.min_val > 0:
            # Échantillonnage log-uniforme
            log_min = np.log(self.min_val)
            log_max = np.log(self.max_val)
            value = np.exp(log_min + u * (log_max - log_min))
        else:
            # Échantillonnage linéaire
            value = self.min_val + u * (self.max_val - self.min_val)

        if self.param_type == "int":
            return int(round(value))
        return value


@dataclass
class MonteCarloSampler:
    """
    Échantillonneur Monte Carlo pour optimisation paramétrique.

    Attributes:
        param_spaces: Liste des espaces de paramètres
        n_samples: Nombre d'échantillons à générer
        method: Méthode d'échantillonnage
        seed: Seed pour reproductibilité
    """
    param_spaces: List[ParameterSpace]
    n_samples: int = 100
    method: SamplingMethod = SamplingMethod.LATIN_HYPERCUBE
    seed: Optional[int] = 42

    def __post_init__(self):
        if self.seed is not None:
            np.random.seed(self.seed)
        self._dim = len(self.param_spaces)

    def generate_samples(self) -> List[Dict[str, Any]]:
        """
        Génère les échantillons selon la méthode choisie.

        Returns:
            Liste de dictionnaires {param_name: value}
        """
        if self.method == SamplingMethod.RANDOM:
            uniform_samples = self._random_sampling()
        elif self.method == SamplingMethod.LATIN_HYPERCUBE:
            uniform_samples = self._latin_hypercube_sampling()
        elif self.method == SamplingMethod.SOBOL:
            uniform_samples = self._sobol_sampling()
        else:
            raise ValueError(f"Méthode inconnue: {self.method}")

        # Convertir les valeurs uniformes en valeurs de paramètres
        samples = []
        for row in uniform_samples:
            sample = {}
            for i, space in enumerate(self.param_spaces):
                sample[space.name] = space.sample(row[i])
            samples.append(sample)

        logger.info(
            f"Monte Carlo: {len(samples)} échantillons générés "
            f"({self.method.value}, {self._dim} dimensions)"
        )

        return samples

    def _random_sampling(self) -> np.ndarray:
        """Échantillonnage aléatoire uniforme."""
        return np.random.rand(self.n_samples, self._dim)

    def _latin_hypercube_sampling(self) -> np.ndarray:
        """
        Latin Hypercube Sampling (LHS).

        Garantit une meilleure couverture de l'espace que l'aléatoire pur.
        Chaque dimension est divisée en n_samples intervalles égaux,
        et on place exactement un point dans chaque intervalle.
        """
        result = np.zeros((self.n_samples, self._dim))

        for dim in range(self._dim):
            # Créer n_samples intervalles
            cut_points = np.linspace(0, 1, self.n_samples + 1)

            # Échantillonner uniformément dans chaque intervalle
            for i in range(self.n_samples):
                low = cut_points[i]
                high = cut_points[i + 1]
                result[i, dim] = np.random.uniform(low, high)

            # Mélanger pour éviter les corrélations
            np.random.shuffle(result[:, dim])

        return result

    def _sobol_sampling(self) -> np.ndarray:
        """
        Séquence de Sobol (quasi-random).

        Meilleure distribution que l'aléatoire, propriétés de
        low-discrepancy pour une couverture uniforme.

        Implémentation simplifiée - pour production, utiliser scipy.stats.qmc
        """
        try:
            from scipy.stats import qmc
            sampler = qmc.Sobol(d=self._dim, scramble=True, seed=self.seed)
            return sampler.random(self.n_samples)
        except ImportError:
            logger.warning("scipy non disponible, fallback vers LHS")
            return self._latin_hypercube_sampling()


@dataclass
class MonteCarloResult:
    """
    Résultat d'une optimisation Monte Carlo.

    Attributes:
        samples: Paramètres testés
        scores: Scores obtenus (ex: Sharpe ratio)
        best_params: Meilleurs paramètres trouvés
        best_score: Meilleur score
        convergence_history: Évolution du meilleur score
    """
    samples: List[Dict[str, Any]]
    scores: List[float]
    best_params: Dict[str, Any]
    best_score: float
    convergence_history: List[float] = field(default_factory=list)

    @property
    def n_evaluated(self) -> int:
        """Nombre d'évaluations effectuées."""
        return len(self.scores)

    def top_k(self, k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """
        Retourne les k meilleures configurations.

        Args:
            k: Nombre de configurations à retourner

        Returns:
            Liste de tuples (params, score) triés par score décroissant
        """
        paired = list(zip(self.samples, self.scores))
        paired.sort(key=lambda x: x[1], reverse=True)
        return paired[:k]

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour export."""
        return {
            "n_samples": self.n_evaluated,
            "best_params": self.best_params,
            "best_score": self.best_score,
            "convergence": self.convergence_history,
            "top_5": [
                {"params": p, "score": s}
                for p, s in self.top_k(5)
            ],
        }


class MonteCarloOptimizer:
    """
    Optimiseur Monte Carlo pour recherche de paramètres.

    Utilise l'échantillonnage intelligent pour explorer l'espace
    des paramètres sans tester toutes les combinaisons.

    Example:
        >>> optimizer = MonteCarloOptimizer(
        ...     param_spaces=[
        ...         ParameterSpace("fast_period", 5, 20, "int"),
        ...         ParameterSpace("slow_period", 20, 50, "int"),
        ...     ],
        ...     n_samples=100,
        ... )
        >>> result = optimizer.optimize(evaluate_fn)
        >>> print(f"Best: {result.best_params} -> {result.best_score}")
    """

    def __init__(
        self,
        param_spaces: List[ParameterSpace],
        n_samples: int = 100,
        method: SamplingMethod = SamplingMethod.LATIN_HYPERCUBE,
        seed: Optional[int] = 42,
        early_stop_patience: int = 20,
        early_stop_threshold: float = 0.001,
    ):
        """
        Initialise l'optimiseur.

        Args:
            param_spaces: Espaces des paramètres
            n_samples: Nombre d'échantillons
            method: Méthode d'échantillonnage
            seed: Seed pour reproductibilité
            early_stop_patience: Arrêt si pas d'amélioration après N évals
            early_stop_threshold: Seuil d'amélioration minimum
        """
        self.param_spaces = param_spaces
        self.n_samples = n_samples
        self.method = method
        self.seed = seed
        self.early_stop_patience = early_stop_patience
        self.early_stop_threshold = early_stop_threshold

        self._sampler = MonteCarloSampler(
            param_spaces=param_spaces,
            n_samples=n_samples,
            method=method,
            seed=seed,
        )

    def optimize(
        self,
        evaluate_fn: Callable[[Dict[str, Any]], float],
        constraints_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> MonteCarloResult:
        """
        Lance l'optimisation Monte Carlo.

        Args:
            evaluate_fn: Fonction d'évaluation (params -> score)
            constraints_fn: Fonction de validation des contraintes (optionnel)
            progress_callback: Callback de progression (current, total, best_score)

        Returns:
            MonteCarloResult avec les meilleurs paramètres
        """
        # Générer les échantillons
        all_samples = self._sampler.generate_samples()

        # Filtrer par contraintes si spécifiées
        if constraints_fn is not None:
            samples = [s for s in all_samples if constraints_fn(s)]
            logger.info(
                f"Monte Carlo: {len(samples)}/{len(all_samples)} "
                f"échantillons valides après contraintes"
            )
        else:
            samples = all_samples

        if not samples:
            raise ValueError("Aucun échantillon valide après filtrage des contraintes")

        # Évaluer les échantillons
        scores = []
        best_score = float('-inf')
        best_params = None
        convergence = []
        no_improvement_count = 0

        for i, params in enumerate(samples):
            try:
                score = evaluate_fn(params)
                scores.append(score)

                # Tracking du meilleur
                if score > best_score + self.early_stop_threshold:
                    best_score = score
                    best_params = params.copy()
                    no_improvement_count = 0
                else:
                    no_improvement_count += 1

                convergence.append(best_score)

                # Callback de progression
                if progress_callback is not None:
                    progress_callback(i + 1, len(samples), best_score)

                # Early stopping
                if no_improvement_count >= self.early_stop_patience:
                    logger.info(
                        f"Monte Carlo: Early stop après {i + 1} évaluations "
                        f"(pas d'amélioration depuis {self.early_stop_patience})"
                    )
                    break

            except Exception as e:
                logger.warning(f"Erreur évaluation {params}: {e}")
                scores.append(float('-inf'))

        # Tronquer les samples si early stop
        evaluated_samples = samples[:len(scores)]

        logger.info(
            f"Monte Carlo terminé: {len(scores)} évaluations, "
            f"meilleur score = {best_score:.4f}"
        )

        return MonteCarloResult(
            samples=evaluated_samples,
            scores=scores,
            best_params=best_params or {},
            best_score=best_score,
            convergence_history=convergence,
        )

    @classmethod
    def from_strategy(
        cls,
        strategy_name: str,
        n_samples: int = 100,
        method: SamplingMethod = SamplingMethod.LATIN_HYPERCUBE,
        **kwargs
    ) -> "MonteCarloOptimizer":
        """
        Crée un optimiseur à partir d'une stratégie enregistrée.

        Args:
            strategy_name: Nom de la stratégie
            n_samples: Nombre d'échantillons
            method: Méthode d'échantillonnage
            **kwargs: Arguments additionnels

        Returns:
            MonteCarloOptimizer configuré
        """
        from strategies.base import get_strategy

        strategy_class = get_strategy(strategy_name)
        strategy = strategy_class()

        param_spaces = []

        if hasattr(strategy, 'parameter_specs'):
            for name, spec in strategy.parameter_specs.items():
                param_spaces.append(ParameterSpace(
                    name=name,
                    min_val=spec.min_val,
                    max_val=spec.max_val,
                    param_type=spec.param_type,
                ))

        if not param_spaces:
            raise ValueError(
                f"Stratégie {strategy_name} n'a pas de parameter_specs"
            )

        return cls(
            param_spaces=param_spaces,
            n_samples=n_samples,
            method=method,
            **kwargs
        )


def monte_carlo_sweep(
    strategy_name: str,
    data,
    n_samples: int = 100,
    method: SamplingMethod = SamplingMethod.LATIN_HYPERCUBE,
    metric: str = "sharpe_ratio",
    seed: Optional[int] = 42,
    constraints_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> MonteCarloResult:
    """
    Lance un sweep Monte Carlo sur une stratégie.

    Fonction de convenance qui combine MonteCarloOptimizer
    avec le BacktestEngine.

    Args:
        strategy_name: Nom de la stratégie
        data: DataFrame OHLCV
        n_samples: Nombre d'échantillons
        method: Méthode d'échantillonnage
        metric: Métrique à optimiser
        seed: Seed reproductibilité
        constraints_fn: Contraintes sur les paramètres

    Returns:
        MonteCarloResult

    Example:
        >>> result = monte_carlo_sweep(
        ...     "ema_cross",
        ...     data,
        ...     n_samples=50,
        ...     constraints_fn=lambda p: p["slow_period"] > p["fast_period"]
        ... )
        >>> print(result.best_params)
    """
    from backtest.engine import BacktestEngine
    from strategies.base import get_strategy

    # Créer l'optimiseur
    optimizer = MonteCarloOptimizer.from_strategy(
        strategy_name,
        n_samples=n_samples,
        method=method,
        seed=seed,
    )

    # Créer le moteur de backtest
    engine = BacktestEngine(initial_capital=10000.0)
    strategy_class = get_strategy(strategy_name)

    def evaluate(params: Dict[str, Any]) -> float:
        """Évalue une configuration de paramètres."""
        strategy = strategy_class()
        result = engine.run(data, strategy, params)

        # Récupérer la métrique demandée
        metrics = result.metrics
        if hasattr(metrics, metric):
            return getattr(metrics, metric)
        elif hasattr(metrics, 'to_dict'):
            return metrics.to_dict().get(metric, 0.0)
        return 0.0


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur échantillonnage intelligent
# - Conventions méthodes (RANDOM/LHS/SOBOL) et log_scale explicitées
# - Read-if/Skip-if ajoutés pour guider la lecture

    # Lancer l'optimisation
    return optimizer.optimize(
        evaluate_fn=evaluate,
        constraints_fn=constraints_fn,
    )
