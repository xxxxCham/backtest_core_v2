"""
Module-ID: backtest.pareto

Purpose: Optimiser multi-objectif avec détection domination Pareto et early stopping automatique.

Role in pipeline: optimization

Key components: ParetoPoint, ParetoFrontier, pareto_optimize, is_dominated

Inputs: points (params + métriques), directions optimisation (1=max, -1=min)

Outputs: ParetoFrontier (frontière optimale), points dominés exclu

Dependencies: numpy

Conventions: Point domine si >= sur tous les objectifs et > sur au moins un; frontière mise à jour dynamiquement; early stop si nouvelle solution non-dominée.

Read-if: Multi-objectif (ex: Sharpe ET max_drawdown), pruning automatique, or frontière de Pareto.

Skip-if: Single-objectif uniquement (sweep/optuna simple).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ParetoPoint:
    """
    Point dans l'espace des objectifs.

    Attributes:
        params: Paramètres de la stratégie
        objectives: Dict des valeurs d'objectifs (nom -> valeur)
        metadata: Données additionnelles
    """
    params: Dict[str, Any]
    objectives: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Convertit les objectifs en float."""
        self.objectives = {k: float(v) for k, v in self.objectives.items()}

    def dominates(self, other: "ParetoPoint", directions: Dict[str, int]) -> bool:
        """
        Vérifie si ce point domine l'autre.

        Un point A domine B si:
        - A est au moins aussi bon que B sur tous les objectifs
        - A est strictement meilleur sur au moins un objectif

        Args:
            other: Autre point à comparer
            directions: Dict objectif -> direction (1=maximiser, -1=minimiser)

        Returns:
            True si self domine other
        """
        dominated_keys = set(self.objectives.keys()) & set(other.objectives.keys())

        at_least_as_good = True
        strictly_better = False

        for key in dominated_keys:
            direction = directions.get(key, 1)  # Défaut: maximiser
            self_val = self.objectives[key] * direction
            other_val = other.objectives[key] * direction

            if self_val < other_val:
                at_least_as_good = False
                break
            elif self_val > other_val:
                strictly_better = True

        return at_least_as_good and strictly_better

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "params": self.params,
            "objectives": self.objectives,
            "metadata": self.metadata,
        }


@dataclass
class ParetoFrontier:
    """
    Frontière de Pareto dynamique.

    Maintient l'ensemble des points non-dominés.
    """
    directions: Dict[str, int] = field(default_factory=dict)
    points: List[ParetoPoint] = field(default_factory=list)

    def __post_init__(self):
        """Initialise les directions par défaut."""
        # Objectifs standards
        default_directions = {
            "sharpe_ratio": 1,      # Maximiser
            "sortino_ratio": 1,     # Maximiser
            "total_return": 1,      # Maximiser
            "profit_factor": 1,     # Maximiser
            "win_rate": 1,          # Maximiser
            "max_drawdown": -1,     # Minimiser
            "volatility": -1,       # Minimiser
            "sqn": 1,               # Maximiser
            "calmar_ratio": 1,      # Maximiser
        }

        for key, direction in default_directions.items():
            if key not in self.directions:
                self.directions[key] = direction

    def add_point(self, point: ParetoPoint) -> bool:
        """
        Ajoute un point à la frontière si non-dominé.

        Met à jour la frontière en supprimant les points dominés.

        Args:
            point: Point à ajouter

        Returns:
            True si le point a été ajouté (non-dominé)
        """
        # Vérifier si le nouveau point est dominé
        for existing in self.points:
            if existing.dominates(point, self.directions):
                return False

        # Supprimer les points dominés par le nouveau
        self.points = [
            p for p in self.points
            if not point.dominates(p, self.directions)
        ]

        # Ajouter le nouveau point
        self.points.append(point)
        return True

    def is_dominated(self, point: ParetoPoint) -> bool:
        """Vérifie si un point est dominé par la frontière."""
        for existing in self.points:
            if existing.dominates(point, self.directions):
                return True
        return False

    def get_best(self, objective: str) -> Optional[ParetoPoint]:
        """Retourne le meilleur point pour un objectif donné."""
        if not self.points:
            return None

        direction = self.directions.get(objective, 1)

        return max(
            self.points,
            key=lambda p: p.objectives.get(objective, float('-inf')) * direction
        )

    def size(self) -> int:
        """Retourne le nombre de points sur la frontière."""
        return len(self.points)

    def to_list(self) -> List[Dict[str, Any]]:
        """Convertit la frontière en liste de dicts."""
        return [p.to_dict() for p in self.points]


class ParetoPruner:
    """
    Pruner basé sur la dominance de Pareto.

    Permet d'arrêter l'évaluation de combinaisons de paramètres
    qui sont clairement dominées.

    Example:
        >>> pruner = ParetoPruner(objectives=["sharpe_ratio", "max_drawdown"])
        >>>
        >>> for params in param_grid:
        >>>     # Estimation rapide (partielle)
        >>>     quick_result = quick_evaluate(params)
        >>>
        >>>     if pruner.should_prune(quick_result):
        >>>         continue  # Skip cette combinaison
        >>>
        >>>     # Évaluation complète
        >>>     full_result = full_evaluate(params)
        >>>     pruner.report(params, full_result)
    """

    def __init__(
        self,
        objectives: List[str],
        directions: Optional[Dict[str, int]] = None,
        prune_threshold: float = 0.8,
        min_frontier_size: int = 5,
    ):
        """
        Args:
            objectives: Liste des objectifs à optimiser
            directions: Dict objectif -> direction (1=max, -1=min)
            prune_threshold: Seuil de pruning (0-1)
            min_frontier_size: Taille min de frontière avant pruning
        """
        self.objectives = objectives
        self.prune_threshold = prune_threshold
        self.min_frontier_size = min_frontier_size

        # Configurer les directions
        dir_config = directions or {}
        self.frontier = ParetoFrontier(directions=dir_config)

        # Stats
        self._total_evaluated = 0
        self._total_pruned = 0
        self._total_reported = 0

    def should_prune(
        self,
        partial_objectives: Dict[str, float],
        params: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Détermine si une combinaison devrait être pruned.

        Args:
            partial_objectives: Estimation partielle des objectifs
            params: Paramètres (optionnel, pour logging)

        Returns:
            True si la combinaison devrait être ignorée
        """
        self._total_evaluated += 1

        # Pas de pruning si frontière trop petite
        if self.frontier.size() < self.min_frontier_size:
            return False

        # Créer un point avec les objectifs partiels
        point = ParetoPoint(
            params=params or {},
            objectives=partial_objectives,
        )

        # Vérifier la domination
        if self.frontier.is_dominated(point):
            # Appliquer le seuil de pruning (probabiliste)
            if np.random.random() < self.prune_threshold:
                self._total_pruned += 1
                return True

        return False

    def report(
        self,
        params: Dict[str, Any],
        objectives: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Rapporte les résultats complets d'une évaluation.

        Args:
            params: Paramètres évalués
            objectives: Valeurs des objectifs
            metadata: Données additionnelles

        Returns:
            True si le point a été ajouté à la frontière
        """
        self._total_reported += 1

        point = ParetoPoint(
            params=params,
            objectives={k: objectives.get(k, 0) for k in self.objectives},
            metadata=metadata or {},
        )

        return self.frontier.add_point(point)

    def get_frontier(self) -> ParetoFrontier:
        """Retourne la frontière de Pareto."""
        return self.frontier

    def get_best_params(self, objective: str) -> Optional[Dict[str, Any]]:
        """Retourne les meilleurs paramètres pour un objectif."""
        best = self.frontier.get_best(objective)
        return best.params if best else None

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de pruning."""
        return {
            "total_evaluated": self._total_evaluated,
            "total_pruned": self._total_pruned,
            "total_reported": self._total_reported,
            "frontier_size": self.frontier.size(),
            "prune_rate": self._total_pruned / max(1, self._total_evaluated),
        }


class MultiObjectiveOptimizer:
    """
    Optimiseur multi-objectif avec Pareto pruning.

    Combine grid search avec pruning intelligent pour
    réduire le nombre d'évaluations nécessaires.

    Example:
        >>> optimizer = MultiObjectiveOptimizer(
        >>>     objectives=["sharpe_ratio", "max_drawdown"],
        >>>     directions={"sharpe_ratio": 1, "max_drawdown": -1}
        >>> )
        >>>
        >>> results = optimizer.optimize(
        >>>     param_grid={"fast": [5,10,15], "slow": [20,30,40]},
        >>>     evaluate_fn=run_backtest,
        >>>     quick_evaluate_fn=quick_backtest,  # Optional
        >>> )
    """

    def __init__(
        self,
        objectives: List[str],
        directions: Optional[Dict[str, int]] = None,
        prune_threshold: float = 0.7,
        min_samples_before_prune: int = 10,
    ):
        """
        Args:
            objectives: Objectifs à optimiser
            directions: Directions d'optimisation
            prune_threshold: Agressivité du pruning
            min_samples_before_prune: Échantillons minimum avant pruning
        """
        self.objectives = objectives
        self.directions = directions or {}
        self.prune_threshold = prune_threshold
        self.min_samples_before_prune = min_samples_before_prune

        self._pruner: Optional[ParetoPruner] = None
        self._results: List[Dict[str, Any]] = []

    def optimize(
        self,
        param_grid: Dict[str, List[Any]],
        evaluate_fn: Callable[[Dict[str, Any]], Dict[str, float]],
        quick_evaluate_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = None,
        constraints_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        progress_callback: Optional[Callable[[int, int, Dict], None]] = None,
        max_evaluations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Exécute l'optimisation multi-objectif.

        Args:
            param_grid: Grille de paramètres
            evaluate_fn: Fonction d'évaluation complète
            quick_evaluate_fn: Fonction d'évaluation rapide (pour pruning)
            constraints_fn: Fonction de contraintes (retourne True si valide)
            progress_callback: Callback de progression
            max_evaluations: Nombre max d'évaluations

        Returns:
            Dict avec frontier, stats, all_results
        """
        # Initialiser le pruner
        self._pruner = ParetoPruner(
            objectives=self.objectives,
            directions=self.directions,
            prune_threshold=self.prune_threshold,
            min_frontier_size=self.min_samples_before_prune,
        )
        self._results = []

        # Générer toutes les combinaisons
        combinations = self._generate_combinations(param_grid)
        total = len(combinations)

        if max_evaluations:
            combinations = combinations[:max_evaluations]

        evaluated = 0
        pruned = 0

        for i, params in enumerate(combinations):
            # Vérifier contraintes
            if constraints_fn and not constraints_fn(params):
                continue

            # Quick evaluation pour décider du pruning
            if quick_evaluate_fn and evaluated >= self.min_samples_before_prune:
                quick_result = quick_evaluate_fn(params)

                if self._pruner.should_prune(quick_result, params):
                    pruned += 1
                    if progress_callback:
                        progress_callback(i + 1, total, {"status": "pruned"})
                    continue

            # Évaluation complète
            try:
                result = evaluate_fn(params)
                self._pruner.report(params, result, {"index": evaluated})

                self._results.append({
                    "params": params,
                    "objectives": result,
                    "on_frontier": True,  # Sera mis à jour
                })

                evaluated += 1

                if progress_callback:
                    progress_callback(i + 1, total, {
                        "status": "evaluated",
                        "frontier_size": self._pruner.frontier.size(),
                    })

            except Exception as e:
                logger.warning(f"Évaluation échouée pour {params}: {e}")

        # Marquer les points sur la frontière
        frontier_params = [p.params for p in self._pruner.frontier.points]
        for result in self._results:
            result["on_frontier"] = result["params"] in frontier_params

        return {
            "frontier": self._pruner.frontier.to_list(),
            "stats": {
                **self._pruner.get_stats(),
                "total_combinations": total,
                "evaluated": evaluated,
                "pruned": pruned,
            },
            "all_results": self._results,
            "best_per_objective": {
                obj: self._pruner.get_best_params(obj)
                for obj in self.objectives
            },
        }

    def _generate_combinations(
        self,
        param_grid: Dict[str, List[Any]]
    ) -> List[Dict[str, Any]]:
        """Génère toutes les combinaisons de paramètres."""
        import itertools

        keys = list(param_grid.keys())
        values = [param_grid[k] for k in keys]

        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))

        # Mélanger pour éviter les biais
        np.random.shuffle(combinations)

        return combinations


def pareto_optimize(
    param_grid: Dict[str, List[Any]],
    evaluate_fn: Callable[[Dict[str, Any]], Dict[str, float]],
    objectives: List[str] = ["sharpe_ratio", "max_drawdown"],
    **kwargs
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour optimisation Pareto rapide.

    Args:
        param_grid: Grille de paramètres
        evaluate_fn: Fonction d'évaluation
        objectives: Objectifs à optimiser
        **kwargs: Arguments additionnels pour MultiObjectiveOptimizer

    Returns:
        Résultats d'optimisation

    Example:
        >>> results = pareto_optimize(
        >>>     param_grid={"fast": [5,10,15], "slow": [20,30,40]},
        >>>     evaluate_fn=lambda p: backtest(p).metrics,
        >>> )
        >>> print(f"Frontier size: {len(results['frontier'])}")
    """
    optimizer = MultiObjectiveOptimizer(objectives=objectives, **kwargs)
    return optimizer.optimize(param_grid, evaluate_fn)


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur multi-objectif/domination Pareto
# - Conventions domination et frontière explicitées (>= tous, > au moins un)
# - Read-if/Skip-if ajoutés pour guider la lecture


__all__ = [
    "ParetoPoint",
    "ParetoFrontier",
    "ParetoPruner",
    "MultiObjectiveOptimizer",
    "pareto_optimize",
]
