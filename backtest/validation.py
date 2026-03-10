"""
Module-ID: backtest.validation

Purpose: Valider l'absence d'overfitting via walk-forward analysis avec fenêtres glissantes train/test.

Role in pipeline: validation

Key components: ValidationFold, WalkForwardValidator, validate_combinatorial

Inputs: DataFrame OHLCV, n_folds (défaut 5), train_ratio (défaut 0.7)

Outputs: ValidationFold list, overfitting_ratio estimé, métriques train vs test

Dependencies: numpy, pandas, utils.log

Conventions: Embargo temporel respecté; fold_id 0-based; overfitting_ratio > 1.0 signale overfitting; fenêtres non-chevauchantes.

Read-if: Intégration validation au pipeline, détection overfitting, ou paramètres de folds.

Skip-if: Vous n'utilisez pas la validation walk-forward.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationFold:
    """Représente un pli de validation."""

    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    # Métriques calculées après backtest
    train_metrics: Optional[Dict[str, Any]] = None
    test_metrics: Optional[Dict[str, Any]] = None

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_size(self) -> int:
        return self.test_end - self.test_start

    @property
    def overfitting_ratio(self) -> Optional[float]:
        """
        Ratio d'overfitting: performance train vs test.
        > 1.0 = overfitting probable
        """
        if self.train_metrics is None or self.test_metrics is None:
            return None

        train_sharpe = self.train_metrics.get("sharpe_ratio", 0)
        test_sharpe = self.test_metrics.get("sharpe_ratio", 0)

        if test_sharpe == 0:
            return float('inf') if train_sharpe > 0 else 1.0

        return train_sharpe / test_sharpe


@dataclass
class WalkForwardResult:
    """Résultat complet d'une validation walk-forward."""

    folds: List[ValidationFold]
    total_train_samples: int
    total_test_samples: int
    embargo_samples: int

    # Métriques agrégées
    avg_train_sharpe: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_train_return: float = 0.0
    avg_test_return: float = 0.0
    avg_overfitting_ratio: float = 0.0

    # Métriques robustes (nouvelles)
    robust_overfitting_ratio: float = 0.0
    degradation_pct: float = 0.0
    test_stability_std: float = 0.0
    n_valid_folds: int = 0

    # Stabilité
    sharpe_std: float = 0.0
    return_std: float = 0.0

    # Verdict
    is_robust: bool = False
    confidence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_folds": len(self.folds),
            "total_train_samples": self.total_train_samples,
            "total_test_samples": self.total_test_samples,
            "embargo_samples": self.embargo_samples,
            "avg_train_sharpe": self.avg_train_sharpe,
            "avg_test_sharpe": self.avg_test_sharpe,
            "avg_train_return": self.avg_train_return,
            "avg_test_return": self.avg_test_return,
            "avg_overfitting_ratio": self.avg_overfitting_ratio,
            "robust_overfitting_ratio": self.robust_overfitting_ratio,
            "degradation_pct": self.degradation_pct,
            "test_stability_std": self.test_stability_std,
            "n_valid_folds": self.n_valid_folds,
            "sharpe_std": self.sharpe_std,
            "return_std": self.return_std,
            "is_robust": self.is_robust,
            "confidence_score": self.confidence_score,
            "folds": [
                {
                    "fold_id": f.fold_id,
                    "train_range": f"{f.train_start}-{f.train_end}",
                    "test_range": f"{f.test_start}-{f.test_end}",
                    "overfitting_ratio": f.overfitting_ratio,
                }
                for f in self.folds
            ],
        }


class WalkForwardValidator:
    """
    Validateur Walk-Forward pour détecter l'overfitting.

    Divise les données en fenêtres train/test glissantes avec:
    - Embargo temporel entre train et test (évite le leakage)
    - Purge des données trop proches du test

    Usage:
        validator = WalkForwardValidator(n_folds=5, test_pct=0.2)
        folds = validator.split(df)
        for fold in folds:
            # Optimiser sur train_data
            # Valider sur test_data
    """

    def __init__(
        self,
        n_folds: int = 5,
        test_pct: float = 0.2,
        embargo_pct: float = 0.01,
        purge_pct: float = 0.0,
        min_train_samples: int = 100,
        min_test_samples: int = 50,
        expanding: bool = False
    ):
        """
        Args:
            n_folds: Nombre de fenêtres de validation
            test_pct: Pourcentage de données pour le test (par fold)
            embargo_pct: Embargo entre train et test (% du total)
            purge_pct: Purge avant le test (données exclues)
            min_train_samples: Minimum de samples pour le train
            min_test_samples: Minimum de samples pour le test (évite les indicateurs invalides)
            expanding: Si True, fenêtre d'entraînement qui grandit
        """
        self.n_folds = n_folds
        self.test_pct = test_pct
        self.embargo_pct = embargo_pct
        self.purge_pct = purge_pct
        self.min_train_samples = min_train_samples
        self.min_test_samples = min_test_samples
        self.expanding = expanding

        logger.info(
            f"WalkForwardValidator: {n_folds} folds, "
            f"test={test_pct:.0%}, embargo={embargo_pct:.1%}"
        )

    def split(self, data: pd.DataFrame) -> List[ValidationFold]:
        """
        Génère les indices des fenêtres walk-forward.

        Args:
            data: DataFrame avec les données OHLCV

        Returns:
            Liste de ValidationFold avec les indices
        """
        n_samples = len(data)

        # Calculer les tailles
        embargo_size = max(1, int(n_samples * self.embargo_pct))
        purge_size = max(0, int(n_samples * self.purge_pct))
        test_size = max(10, int(n_samples * self.test_pct))

        # Espace disponible pour train + test par fold
        # Dans walk-forward, on avance progressivement
        fold_size = (n_samples - embargo_size) // self.n_folds

        folds = []

        for i in range(self.n_folds):
            if self.expanding:
                # Fenêtre expandante: train grandit à chaque fold
                train_start = 0
            else:
                # Fenêtre roulante: train de taille fixe
                train_start = i * fold_size

            # Fin du train (avant embargo)
            train_end = (i + 1) * fold_size - embargo_size - purge_size

            # Début du test (après embargo)
            test_start = train_end + embargo_size + purge_size

            # Fin du test
            test_end = min(test_start + test_size, n_samples)

            # Vérifications
            if train_end - train_start < self.min_train_samples:
                logger.warning(f"Fold {i}: train trop petit ({train_end - train_start} < {self.min_train_samples}), skip")
                continue

            if test_end - test_start < self.min_test_samples:
                logger.warning(f"Fold {i}: test trop petit ({test_end - test_start} < {self.min_test_samples}), skip")
                continue

            fold = ValidationFold(
                fold_id=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
            folds.append(fold)

        logger.info(f"Walk-forward: {len(folds)} folds générés")
        return folds

    def get_data_splits(
        self,
        data: pd.DataFrame,
        fold: ValidationFold
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Retourne les DataFrames train et test pour un fold.

        PERF: pas de .copy() — le moteur lit mais ne mute pas le DataFrame.
        Les slices partagent la mémoire avec le DataFrame source.

        Args:
            data: DataFrame complet
            fold: ValidationFold avec les indices

        Returns:
            Tuple (train_df, test_df)
        """
        train_df = data.iloc[fold.train_start:fold.train_end]
        test_df = data.iloc[fold.test_start:fold.test_end]

        return train_df, test_df


class OverfittingDetector:
    """
    Détecte l'overfitting en comparant les performances train/test.

    Méthodes:
    - Ratio Sharpe train/test
    - Dégradation du return
    - Instabilité des paramètres optimaux
    """

    def __init__(
        self,
        max_overfitting_ratio: float = 2.0,
        min_test_sharpe: float = 0.5,
        min_confidence: float = 0.6
    ):
        """
        Args:
            max_overfitting_ratio: Ratio max train/test accepté
            min_test_sharpe: Sharpe minimum sur test
            min_confidence: Score de confiance minimum
        """
        self.max_overfitting_ratio = max_overfitting_ratio
        self.min_test_sharpe = min_test_sharpe
        self.min_confidence = min_confidence

    def analyze(self, result: WalkForwardResult) -> Dict[str, Any]:
        """
        Analyse complète des résultats walk-forward.

        Args:
            result: Résultats de validation walk-forward

        Returns:
            Dict avec diagnostic d'overfitting
        """
        diagnosis = {
            "overfitting_detected": False,
            "severity": "none",
            "reasons": [],
            "recommendations": [],
        }

        # Vérifier ratio d'overfitting
        if result.avg_overfitting_ratio > self.max_overfitting_ratio:
            diagnosis["overfitting_detected"] = True
            diagnosis["reasons"].append(
                f"Ratio overfitting trop élevé: {result.avg_overfitting_ratio:.2f} "
                f"(max: {self.max_overfitting_ratio})"
            )

        # Vérifier performance sur test
        if result.avg_test_sharpe < self.min_test_sharpe:
            diagnosis["overfitting_detected"] = True
            diagnosis["reasons"].append(
                f"Sharpe test trop bas: {result.avg_test_sharpe:.2f} "
                f"(min: {self.min_test_sharpe})"
            )

        # Vérifier stabilité
        if result.sharpe_std > abs(result.avg_test_sharpe):
            diagnosis["reasons"].append(
                f"Performance instable: std={result.sharpe_std:.2f} > mean={result.avg_test_sharpe:.2f}"
            )

        # Vérifier confidence
        if result.confidence_score < self.min_confidence:
            diagnosis["overfitting_detected"] = True
            diagnosis["reasons"].append(
                f"Confiance insuffisante: {result.confidence_score:.1%} "
                f"(min: {self.min_confidence:.0%})"
            )

        # Déterminer la sévérité
        if not diagnosis["overfitting_detected"]:
            diagnosis["severity"] = "none"
        elif result.avg_overfitting_ratio > 3.0 or result.avg_test_sharpe < 0:
            diagnosis["severity"] = "critical"
        elif result.avg_overfitting_ratio > 2.0:
            diagnosis["severity"] = "high"
        else:
            diagnosis["severity"] = "moderate"

        # Recommandations
        if diagnosis["overfitting_detected"]:
            diagnosis["recommendations"] = [
                "Réduire le nombre de paramètres optimisés",
                "Augmenter la période de test",
                "Utiliser des contraintes sur les paramètres",
                "Essayer une granularité plus grossière",
                "Ajouter de la régularisation",
            ]

        return diagnosis


def compute_robust_overfitting_metrics(folds: List[ValidationFold]) -> Dict[str, float]:
    """
    Calcule des métriques robustes d'overfitting avec pénalité de stabilité.

    Amélioration par rapport au simple ratio train/test :
    - Prend en compte la variabilité des performances out-of-sample
    - Calcule la dégradation en pourcentage
    - Pénalise l'instabilité des résultats

    Args:
        folds: Liste des folds avec métriques train/test

    Returns:
        Dict avec métriques robustes
    """
    # Filtrer les folds valides
    valid_folds = [f for f in folds if f.train_metrics and f.test_metrics]

    if not valid_folds:
        return {
            "overfitting_ratio": 999.0,
            "robust_ratio": 999.0,
            "degradation_pct": 100.0,
            "test_stability_std": 0.0,
            "n_valid_folds": 0,
        }

    # Extraire les Sharpe ratios
    train_sharpes = [f.train_metrics.get("sharpe_ratio", 0) for f in valid_folds]
    test_sharpes = [f.test_metrics.get("sharpe_ratio", 0) for f in valid_folds]

    # Moyennes
    avg_train = np.mean(train_sharpes)
    avg_test = np.mean(test_sharpes)
    std_test = np.std(test_sharpes)

    # Ratio classique train/test
    if avg_test > 0:
        base_ratio = avg_train / avg_test
    else:
        base_ratio = 999.0

    # Dégradation en pourcentage
    if avg_train > 0:
        degradation_pct = ((avg_train - avg_test) / avg_train) * 100
    else:
        degradation_pct = 100.0

    # Pénalité pour instabilité (coefficient ajustable)
    # Plus l'écart-type est grand, plus le modèle est instable out-of-sample
    stability_penalty = std_test * 2.0

    # Ratio robuste = ratio classique + pénalité de stabilité
    robust_ratio = base_ratio + stability_penalty

    return {
        "overfitting_ratio": base_ratio,
        "robust_ratio": robust_ratio,
        "degradation_pct": max(0, degradation_pct),  # Pas de dégradation négative
        "test_stability_std": std_test,
        "n_valid_folds": len(valid_folds),
    }


def calculate_walk_forward_metrics(folds: List[ValidationFold]) -> WalkForwardResult:
    """
    Calcule les métriques agrégées de la validation walk-forward.

    Args:
        folds: Liste des folds avec leurs métriques

    Returns:
        WalkForwardResult avec les métriques agrégées
    """
    valid_folds = [f for f in folds if f.train_metrics and f.test_metrics]

    if not valid_folds:
        return WalkForwardResult(
            folds=folds,
            total_train_samples=0,
            total_test_samples=0,
            embargo_samples=0,
        )

    # Extraire les métriques
    train_sharpes = [f.train_metrics.get("sharpe_ratio", 0) for f in valid_folds]
    test_sharpes = [f.test_metrics.get("sharpe_ratio", 0) for f in valid_folds]
    train_returns = [f.train_metrics.get("total_return_pct", 0) for f in valid_folds]
    test_returns = [f.test_metrics.get("total_return_pct", 0) for f in valid_folds]
    overfitting_ratios = [f.overfitting_ratio for f in valid_folds if f.overfitting_ratio]

    # Calculer les moyennes
    avg_train_sharpe = np.mean(train_sharpes)
    avg_test_sharpe = np.mean(test_sharpes)
    avg_train_return = np.mean(train_returns)
    avg_test_return = np.mean(test_returns)
    avg_overfitting = np.mean(overfitting_ratios) if overfitting_ratios else 1.0

    # Stabilité
    sharpe_std = np.std(test_sharpes)
    return_std = np.std(test_returns)

    # Score de confiance (0-1)
    # Basé sur: performance, stabilité, cohérence train/test
    confidence_factors = []

    # Performance test positive
    if avg_test_sharpe > 0:
        confidence_factors.append(min(avg_test_sharpe / 2, 1.0))
    else:
        confidence_factors.append(0)

    # Stabilité
    if sharpe_std > 0:
        stability = 1 / (1 + sharpe_std)
        confidence_factors.append(stability)

    # Cohérence train/test
    if avg_overfitting < 3:
        coherence = 1 - (avg_overfitting - 1) / 2
        confidence_factors.append(max(0, coherence))
    else:
        confidence_factors.append(0)

    confidence_score = np.mean(confidence_factors) if confidence_factors else 0

    # Verdict de robustesse
    is_robust = (
        avg_test_sharpe > 0.5 and
        avg_overfitting < 2.0 and
        confidence_score > 0.5
    )

    # Totaux
    total_train = sum(f.train_size for f in valid_folds)
    total_test = sum(f.test_size for f in valid_folds)
    embargo = valid_folds[0].test_start - valid_folds[0].train_end if valid_folds else 0

    # Calculer les métriques robustes d'overfitting
    robust_metrics = compute_robust_overfitting_metrics(folds)

    return WalkForwardResult(
        folds=folds,
        total_train_samples=total_train,
        total_test_samples=total_test,
        embargo_samples=embargo,
        avg_train_sharpe=avg_train_sharpe,
        avg_test_sharpe=avg_test_sharpe,
        avg_train_return=avg_train_return,
        avg_test_return=avg_test_return,
        avg_overfitting_ratio=avg_overfitting,
        robust_overfitting_ratio=robust_metrics["robust_ratio"],
        degradation_pct=robust_metrics["degradation_pct"],
        test_stability_std=robust_metrics["test_stability_std"],
        n_valid_folds=robust_metrics["n_valid_folds"],
        sharpe_std=sharpe_std,
        return_std=return_std,
        is_robust=is_robust,
        confidence_score=confidence_score,
    )


def train_test_split(
    data: pd.DataFrame,
    test_pct: float = 0.2,
    embargo_pct: float = 0.01
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split simple train/test avec embargo temporel.

    L'embargo évite le data leakage entre train et test
    (important pour les données temporelles).

    Args:
        data: DataFrame complet
        test_pct: Pourcentage pour le test
        embargo_pct: Embargo entre train et test

    Returns:
        Tuple (train_df, test_df)
    """
    n = len(data)
    embargo_size = max(1, int(n * embargo_pct))
    test_size = max(10, int(n * test_pct))

    train_end = n - test_size - embargo_size
    test_start = train_end + embargo_size

    train_df = data.iloc[:train_end].copy()
    test_df = data.iloc[test_start:].copy()

    logger.info(
        f"Train/Test split: train={len(train_df)}, "
        f"embargo={embargo_size}, test={len(test_df)}"
    )

    return train_df, test_df


def format_validation_report(result: WalkForwardResult) -> str:
    """
    Formate un rapport de validation walk-forward.
    """
    verdict_emoji = "✅" if result.is_robust else "❌"

    report = f"""
╔══════════════════════════════════════════════════════════╗
║            VALIDATION WALK-FORWARD                        ║
╠══════════════════════════════════════════════════════════╣
║ VERDICT: {verdict_emoji} {"ROBUST" if result.is_robust else "OVERFITTING DÉTECTÉ"}
║ Confiance: {result.confidence_score:.1%}
╠══════════════════════════════════════════════════════════╣
║ CONFIGURATION                                             ║
║   Nombre de folds:     {len(result.folds):>10d}                      ║
║   Samples train:       {result.total_train_samples:>10d}                      ║
║   Samples test:        {result.total_test_samples:>10d}                      ║
║   Embargo:             {result.embargo_samples:>10d}                      ║
╠══════════════════════════════════════════════════════════╣
║ PERFORMANCES MOYENNES                                     ║
║   Sharpe Train:        {result.avg_train_sharpe:>10.3f}                      ║
║   Sharpe Test:         {result.avg_test_sharpe:>10.3f}                      ║
║   Return Train:        {result.avg_train_return:>10.2f}%                     ║
║   Return Test:         {result.avg_test_return:>10.2f}%                     ║
╠══════════════════════════════════════════════════════════╣
║ STABILITÉ & OVERFITTING                                   ║
║   Ratio Classique:     {result.avg_overfitting_ratio:>10.2f}x                     ║
║   Ratio Robuste:       {result.robust_overfitting_ratio:>10.2f}x (avec pénalité) ║
║   Dégradation:         {result.degradation_pct:>10.1f}%                     ║
║   Std Test (stabilité):{result.test_stability_std:>10.3f}                      ║
║   Folds valides:       {result.n_valid_folds:>10d}                      ║
║   Std Sharpe:          {result.sharpe_std:>10.3f}                      ║
║   Std Return:          {result.return_std:>10.2f}%                     ║
╠══════════════════════════════════════════════════════════╣
║ CRITÈRES RECOMMANDÉS                                      ║
║   ✓ Ratio robuste < 1.8                                  ║
║   ✓ Dégradation < 40%                                    ║
║   ✓ Std stabilité < 0.5                                  ║
║   ✓ Folds valides >= 4                                   ║
╚══════════════════════════════════════════════════════════╝
"""

    # Détail par fold
    if result.folds:
        report += "\n📊 DÉTAIL PAR FOLD:\n"
        for fold in result.folds:
            if fold.train_metrics and fold.test_metrics:
                train_s = fold.train_metrics.get("sharpe_ratio", 0)
                test_s = fold.test_metrics.get("sharpe_ratio", 0)
                ratio = fold.overfitting_ratio or 0
                status = "🟢" if ratio < 2 else "🟡" if ratio < 3 else "🔴"
                report += (
                    f"  {status} Fold {fold.fold_id}: "
                    f"Train={train_s:.2f} → Test={test_s:.2f} "
                    f"(ratio: {ratio:.2f}x)\n"
                )

    return report


__all__ = [
    "ValidationFold",
    "WalkForwardResult",
    "WalkForwardValidator",
    "OverfittingDetector",
    "calculate_walk_forward_metrics",
    "train_test_split",
    "format_validation_report",
]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur validation/walk-forward
# - Conventions embargo/overfitting_ratio explicitées (ratio > 1.0 = risk)
# - Read-if/Skip-if ajoutés pour tri rapide
