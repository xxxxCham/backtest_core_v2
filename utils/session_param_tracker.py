"""
Module-ID: utils.session_param_tracker

Purpose: Déduplie paramètres testés DANS UNE SESSION d'optimisation (vs run_tracker cross-sessions).

Role in pipeline: optimization

Key components: SessionParameterTracker, TestedParams, compute_hash()

Inputs: Dict de paramètres, scores (Sharpe, return)

Outputs: Hash param, flag already_tested, tested_history

Dependencies: hashlib, json, dataclasses, datetime

Conventions: Normalisation JSON + tri clés pour hash stable; stockage session-local.

Read-if: Modification hachage ou détection doublons intra-session.

Skip-if: Vous appelez tracker.is_already_tested(params).
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class TestedParams:
    """Représente une combinaison de paramètres testée."""

    params: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sharpe_ratio: Optional[float] = None
    total_return: Optional[float] = None

    def compute_hash(self) -> str:
        """Calcule un hash unique pour cette combinaison de paramètres."""
        # Normaliser les paramètres (trier les clés, convertir en JSON)
        normalized = json.dumps(self.params, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "params": self.params,
            "hash": self.compute_hash(),
            "timestamp": self.timestamp,
            "sharpe_ratio": self.sharpe_ratio,
            "total_return": self.total_return,
        }


class SessionParameterTracker:
    """
    Tracker de paramètres pour UNE session d'optimisation.

    Usage dans l'optimisation LLM:
        # Au début de l'optimisation
        tracker = SessionParameterTracker(session_id="opt_123")

        # Avant chaque test
        params = {"period": 20, "std_dev": 2.0}
        if tracker.was_tested(params):
            print("⚠️ Paramètres déjà testés, essayer autre chose!")
        else:
            result = run_backtest(params)
            tracker.register(params, result)
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Initialise le tracker pour une session.

        Args:
            session_id: Identifiant de la session (auto-généré si None)
        """
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.tested_params: List[TestedParams] = []
        self.tested_hashes: Set[str] = set()

        # Stats
        self.session_start = datetime.now()
        self.total_tests = 0
        self.duplicates_prevented = 0

        logger.info(f"📊 Nouvelle session de tracking: {self.session_id}")

    def was_tested(self, params: Dict[str, Any]) -> bool:
        """
        Vérifie si cette combinaison de paramètres a déjà été testée DANS CETTE SESSION.

        Args:
            params: Dictionnaire des paramètres à vérifier

        Returns:
            True si déjà testé, False sinon
        """
        test_params = TestedParams(params=params)
        param_hash = test_params.compute_hash()

        if param_hash in self.tested_hashes:
            self.duplicates_prevented += 1
            logger.warning(
                f"⚠️ Paramètres DÉJÀ TESTÉS dans cette session! "
                f"Hash: {param_hash} | Params: {params}"
            )
            return True

        return False

    def register(
        self,
        params: Dict[str, Any],
        sharpe_ratio: Optional[float] = None,
        total_return: Optional[float] = None
    ) -> None:
        """
        Enregistre une nouvelle combinaison de paramètres testée.

        Args:
            params: Paramètres testés
            sharpe_ratio: Sharpe ratio obtenu (optionnel)
            total_return: Rendement total obtenu (optionnel)
        """
        tested = TestedParams(
            params=params,
            sharpe_ratio=sharpe_ratio,
            total_return=total_return
        )

        param_hash = tested.compute_hash()

        # Vérifier si déjà présent (sécurité)
        if param_hash in self.tested_hashes:
            logger.warning("Tentative d'enregistrement de paramètres déjà testés (ignoré)")
            return

        self.tested_params.append(tested)
        self.tested_hashes.add(param_hash)
        self.total_tests += 1

        sharpe_str = f"{sharpe_ratio:.3f}" if sharpe_ratio is not None else "N/A"
        logger.info(
            f"✅ Paramètres enregistrés ({self.total_tests}/{self.total_tests}): "
            f"Hash={param_hash} | Sharpe={sharpe_str}"
        )

    def get_best_params(self, metric: str = "sharpe_ratio") -> Optional[TestedParams]:
        """
        Retourne les meilleurs paramètres selon la métrique.

        Args:
            metric: "sharpe_ratio" ou "total_return"

        Returns:
            TestedParams avec la meilleure performance, ou None si aucun
        """
        if not self.tested_params:
            return None

        # Filtrer ceux qui ont la métrique
        valid = [p for p in self.tested_params if getattr(p, metric) is not None]

        if not valid:
            return None

        return max(valid, key=lambda p: getattr(p, metric))

    def get_tested_count(self) -> int:
        """Nombre de combinaisons différentes testées."""
        return len(self.tested_params)

    def get_duplicates_prevented(self) -> int:
        """Nombre de duplications évitées."""
        return self.duplicates_prevented

    def get_all_params(self) -> List[Dict[str, Any]]:
        """Retourne toutes les combinaisons testées (pour analyse)."""
        return [tp.params for tp in self.tested_params]

    def get_summary(self) -> str:
        """
        Retourne un résumé de la session pour les LLMs.

        Format utilisable par les LLMs pour éviter les duplications.
        """
        if not self.tested_params:
            return "Aucun paramètre testé dans cette session."

        best_sharpe = self.get_best_params("sharpe_ratio")
        best_return = self.get_best_params("total_return")

        summary = [
            f"📊 Résumé Session: {self.session_id}",
            "",
            f"🔢 Tests effectués: {self.total_tests}",
            f"🚫 Duplications évitées: {self.duplicates_prevented}",
            "",
            "✅ PARAMÈTRES DÉJÀ TESTÉS (NE PAS RETESTER):",
        ]

        # Lister tous les paramètres testés
        for i, tested in enumerate(self.tested_params[-10:], 1):  # Derniers 10
            params_str = json.dumps(tested.params, sort_keys=True)
            perf_str = ""
            if tested.sharpe_ratio:
                perf_str = f" | Sharpe={tested.sharpe_ratio:.3f}"
            if tested.total_return:
                perf_str += f" | Return={tested.total_return:.2%}"

            summary.append(f"  {i}. {params_str}{perf_str}")

        if len(self.tested_params) > 10:
            summary.append(f"  ... et {len(self.tested_params) - 10} autres")

        summary.append("")
        summary.append("🏆 MEILLEURS RÉSULTATS:")

        if best_sharpe:
            summary.append(
                f"  Meilleur Sharpe: {best_sharpe.sharpe_ratio:.3f} "
                f"avec {json.dumps(best_sharpe.params)}"
            )

        if best_return:
            summary.append(
                f"  Meilleur Return: {best_return.total_return:.2%} "
                f"avec {json.dumps(best_return.params)}"
            )

        return "\n".join(summary)

    def to_dict(self) -> Dict[str, Any]:
        """Exporte la session complète en dict (pour sauvegarde)."""
        return {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat(),
            "total_tests": self.total_tests,
            "duplicates_prevented": self.duplicates_prevented,
            "tested_params": [tp.to_dict() for tp in self.tested_params],
        }

    def save(self, path: str) -> None:
        """Sauvegarde la session dans un fichier JSON."""
        from pathlib import Path

        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Session sauvegardée: {save_path}")


__all__ = ["SessionParameterTracker", "TestedParams"]
