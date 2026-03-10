"""
Module-ID: utils.session_ranges_tracker

Purpose: Tracker de ranges de grid search testées dans une session pour éviter boucles infinies.

Role in pipeline: optimization

Key components: SessionRangesTracker, TestedRange

Inputs: Dict de ranges (param: {min, max, step})

Outputs: Hash range, flag already_tested, ranges_history

Dependencies: hashlib, json, dataclasses, datetime

Conventions: Normalisation JSON + tri clés pour hash stable; stockage session-local.

Read-if: Modification hachage ou détection doublons ranges.

Skip-if: Vous appelez tracker.was_tested(ranges).
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class TestedRange:
    """Représente une range de grid search testée."""

    ranges: Dict[str, Dict[str, float]]  # {"param": {"min": x, "max": y, "step": z}}
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    n_combinations: int = 0
    best_sharpe: Optional[float] = None
    rationale: str = ""

    def compute_hash(self) -> str:
        """Calcule un hash unique pour cette range."""
        # Normaliser les ranges (trier les clés, convertir en JSON)
        normalized = json.dumps(self.ranges, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "ranges": self.ranges,
            "hash": self.compute_hash(),
            "timestamp": self.timestamp,
            "n_combinations": self.n_combinations,
            "best_sharpe": self.best_sharpe,
            "rationale": self.rationale,
        }


class SessionRangesTracker:
    """
    Tracker de ranges de grid search pour UNE session d'optimisation.

    Usage dans l'optimisation LLM:
        # Au début de l'optimisation
        tracker = SessionRangesTracker(session_id="opt_123")

        # Avant chaque sweep
        ranges = {"bb_period": {"min": 20, "max": 25, "step": 1}}
        if tracker.was_tested(ranges):
            print("⚠️ Ranges déjà testées, essayer autre chose!")
        else:
            result = run_sweep(ranges)
            tracker.register(ranges, result)
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Initialise le tracker pour une session.

        Args:
            session_id: Identifiant de session (optionnel)
        """
        self.session_id = session_id or "default"
        self._tested_hashes: Set[str] = set()
        self._tested_ranges: List[TestedRange] = []

        logger.info(f"📊 Nouvelle session de tracking ranges: {self.session_id}")

    def was_tested(self, ranges: Dict[str, Dict[str, float]]) -> bool:
        """
        Vérifie si ces ranges ont déjà été testées dans cette session.

        Args:
            ranges: Dict de ranges à vérifier

        Returns:
            True si déjà testées, False sinon
        """
        tested_range = TestedRange(ranges=ranges)
        range_hash = tested_range.compute_hash()
        return range_hash in self._tested_hashes

    def register(
        self,
        ranges: Dict[str, Dict[str, float]],
        n_combinations: int = 0,
        best_sharpe: Optional[float] = None,
        rationale: str = "",
    ) -> str:
        """
        Enregistre une range testée.

        Args:
            ranges: Dict de ranges testées
            n_combinations: Nombre de combinaisons testées
            best_sharpe: Meilleur Sharpe trouvé (optionnel)
            rationale: Raison du sweep (optionnel)

        Returns:
            Hash de la range
        """
        tested_range = TestedRange(
            ranges=ranges,
            n_combinations=n_combinations,
            best_sharpe=best_sharpe,
            rationale=rationale,
        )

        range_hash = tested_range.compute_hash()

        if range_hash in self._tested_hashes:
            logger.warning(
                f"⚠️ Range déjà testée: {range_hash} | "
                f"Params={list(ranges.keys())}"
            )
            return range_hash

        self._tested_hashes.add(range_hash)
        self._tested_ranges.append(tested_range)

        logger.debug(
            f"✅ Range enregistrée: {range_hash} | "
            f"Params={list(ranges.keys())} | "
            f"N_combos={n_combinations}"
        )

        return range_hash

    def get_summary(self, max_ranges: int = 5) -> str:
        """
        Génère un résumé des ranges testées pour feedback LLM.

        Args:
            max_ranges: Nombre maximum de ranges à afficher

        Returns:
            Résumé textuel
        """
        if not self._tested_ranges:
            return "Aucune range testée dans cette session."

        summary = f"**Ranges déjà testées dans cette session ({len(self._tested_ranges)} total):**\n\n"

        for i, tested in enumerate(self._tested_ranges[:max_ranges], 1):
            params_str = ", ".join(
                f"{param}: [{r['min']}-{r['max']}]"
                for param, r in tested.ranges.items()
            )
            summary += f"{i}. {params_str} | {tested.n_combinations} combos | "
            if tested.best_sharpe is not None:
                summary += f"Best Sharpe={tested.best_sharpe:.3f}"
            else:
                summary += "No result"
            summary += "\n"

        if len(self._tested_ranges) > max_ranges:
            summary += f"\n... et {len(self._tested_ranges) - max_ranges} autres ranges testées."

        return summary

    def get_all_ranges(self) -> List[Dict[str, Any]]:
        """Retourne toutes les ranges testées."""
        return [tested.to_dict() for tested in self._tested_ranges]

    def clear(self) -> None:
        """Efface toutes les ranges testées (nouveau début de session)."""
        self._tested_hashes.clear()
        self._tested_ranges.clear()
        logger.info(f"🧹 Tracker ranges réinitialisé: {self.session_id}")
