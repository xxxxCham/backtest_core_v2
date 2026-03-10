"""
Module-ID: utils.run_tracker

Purpose: Déduplique runs d'optimisation cross-sessions (detect déjà exécutés).

Role in pipeline: optimization

Key components: RunTracker, RunSignature, compute_hash(), DuplicateDetector

Inputs: Strategy name, data path, initial params, LLM model, mode

Outputs: Run hash, duplicates_found flag, cached results if available

Dependencies: hashlib, json, dataclasses, pathlib, datetime

Conventions: Hash stable (clés triées); détection inter-runs; stockage disque.

Read-if: Modification détection duplicates ou gestion cache.

Skip-if: Vous appelez tracker.get_cached_result(signature).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class RunSignature:
    """Signature unique d'un run d'optimisation."""

    strategy_name: str
    data_path: str
    initial_params: Dict[str, Any]
    llm_model: Optional[str] = None
    mode: str = "multi_agents"  # "multi_agents", "autonomous", "grid", etc.

    # Métadonnées
    timestamp: str = ""
    session_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def compute_hash(self) -> str:
        """Calcule un hash unique pour cette configuration."""
        # Créer un dict normalisé pour garantir le même hash
        data = {
            "strategy": self.strategy_name,
            "data": self.data_path,
            "params": sorted(self.initial_params.items()),
            "model": self.llm_model or "",
            "mode": self.mode,
        }

        # Convertir en JSON stable (clés triées)
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)

        # Hash SHA256
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "strategy_name": self.strategy_name,
            "data_path": self.data_path,
            "initial_params": self.initial_params,
            "llm_model": self.llm_model,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "hash": self.compute_hash(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunSignature":
        """Crée depuis un dictionnaire."""
        return cls(
            strategy_name=data.get("strategy_name", ""),
            data_path=data.get("data_path", ""),
            initial_params=data.get("initial_params", {}),
            llm_model=data.get("llm_model"),
            mode=data.get("mode", "multi_agents"),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
        )


class RunTracker:
    """
    Tracker des runs d'optimisation pour éviter les doublons.

    Usage:
        tracker = RunTracker()
        signature = RunSignature(strategy="...", data_path="...", ...)

        if tracker.is_duplicate(signature):
            print("Configuration déjà testée!")
        else:
            tracker.register(signature)
            # ... lancer l'optimisation
    """

    def __init__(self, cache_file: Optional[Path] = None):
        """
        Initialise le tracker.

        Args:
            cache_file: Fichier JSON pour persister les runs (défaut: runs/.run_cache.json)
        """
        self.cache_file = cache_file or Path("runs") / ".run_cache.json"
        self.runs: List[RunSignature] = []

        # Charger le cache existant
        self._load_cache()

    def _load_cache(self) -> None:
        """Charge le cache depuis le disque."""
        if not self.cache_file.exists():
            logger.debug(f"Pas de cache existant: {self.cache_file}")
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.runs = [RunSignature.from_dict(item) for item in data.get("runs", [])]
            logger.info(f"Cache chargé: {len(self.runs)} runs enregistrés")

        except Exception as e:
            logger.warning(f"Erreur lors du chargement du cache: {e}")
            self.runs = []

    def _save_cache(self) -> None:
        """Sauvegarde le cache sur disque."""
        try:
            # Créer le répertoire si nécessaire
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "total_runs": len(self.runs),
                "runs": [run.to_dict() for run in self.runs],
            }

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Cache sauvegardé: {len(self.runs)} runs")

        except Exception as e:
            logger.warning(f"Erreur lors de la sauvegarde du cache: {e}")

    def is_duplicate(self, signature: RunSignature) -> bool:
        """
        Vérifie si cette configuration a déjà été exécutée.

        Args:
            signature: Signature du run à vérifier

        Returns:
            True si c'est un doublon, False sinon
        """
        target_hash = signature.compute_hash()

        for existing in self.runs:
            if existing.compute_hash() == target_hash:
                logger.warning(
                    f"Configuration dupliquée détectée! "
                    f"Stratégie: {signature.strategy_name}, "
                    f"Run précédent: {existing.timestamp}"
                )
                return True

        return False

    def find_similar(self, signature: RunSignature) -> List[RunSignature]:
        """
        Trouve les runs similaires (même stratégie et données).

        Args:
            signature: Signature de référence

        Returns:
            Liste des runs similaires
        """
        similar = []

        for existing in self.runs:
            if (
                existing.strategy_name == signature.strategy_name
                and existing.data_path == signature.data_path
                and existing.mode == signature.mode
            ):
                similar.append(existing)

        return similar

    def register(self, signature: RunSignature) -> None:
        """
        Enregistre un nouveau run.

        Args:
            signature: Signature du run à enregistrer
        """
        # Vérifier si déjà présent (ne pas ajouter de doublons)
        if self.is_duplicate(signature):
            logger.warning("Run déjà enregistré, pas de duplication")
            return

        self.runs.append(signature)
        self._save_cache()

        logger.info(
            f"Run enregistré: {signature.strategy_name} "
            f"(hash: {signature.compute_hash()})"
        )

    def clear_old_runs(self, max_age_days: int = 30) -> int:
        """
        Nettoie les runs plus anciens que max_age_days.

        Args:
            max_age_days: Age maximum en jours

        Returns:
            Nombre de runs supprimés
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=max_age_days)
        initial_count = len(self.runs)

        self.runs = [
            run
            for run in self.runs
            if datetime.fromisoformat(run.timestamp) > cutoff
        ]

        removed = initial_count - len(self.runs)

        if removed > 0:
            self._save_cache()
            logger.info(f"Nettoyage: {removed} runs anciens supprimés")

        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur les runs enregistrés."""
        if not self.runs:
            return {
                "total_runs": 0,
                "strategies": {},
                "modes": {},
            }

        # Compter par stratégie
        strategies = {}
        for run in self.runs:
            strategies[run.strategy_name] = strategies.get(run.strategy_name, 0) + 1

        # Compter par mode
        modes = {}
        for run in self.runs:
            modes[run.mode] = modes.get(run.mode, 0) + 1

        return {
            "total_runs": len(self.runs),
            "strategies": strategies,
            "modes": modes,
            "oldest": min(run.timestamp for run in self.runs),
            "newest": max(run.timestamp for run in self.runs),
        }

    # =========================================================================
    # CATALOGS
    # =========================================================================

    def build_catalogs(self) -> Path:
        """
        Construit un catalogue CSV des sessions à partir des traces jsonl.

        Output:
            runs/_catalog/overview.csv
        """
        runs_dir = self.cache_file.parent
        catalog_dir = runs_dir / "_catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)

        rows: List[Dict[str, Any]] = []

        for session_dir in runs_dir.iterdir():
            if not session_dir.is_dir():
                continue
            if session_dir.name.startswith("_"):
                continue
            trace_path = session_dir / "trace.jsonl"
            if not trace_path.exists():
                continue

            total_iterations = 0
            total_llm_tokens = 0
            total_llm_calls = 0

            try:
                with open(trace_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if event.get("event_type") == "iteration":
                            total_iterations += 1

                        tokens = event.get("llm_tokens")
                        if isinstance(tokens, (int, float)):
                            total_llm_tokens += int(tokens)
                            total_llm_calls += 1
                        elif "llm_response" in event:
                            total_llm_calls += 1

            except Exception as e:
                logger.warning(f"Erreur lecture trace {trace_path}: {e}")

            rows.append(
                {
                    "session_id": session_dir.name,
                    "total_iterations": total_iterations,
                    "total_llm_tokens": total_llm_tokens,
                    "total_llm_calls": total_llm_calls,
                }
            )

        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(
                columns=["session_id", "total_iterations", "total_llm_tokens", "total_llm_calls"]
            )

        overview_path = catalog_dir / "overview.csv"
        df.to_csv(overview_path, index=False, encoding="utf-8")

        return overview_path


# Instance globale pour utilisation dans l'UI
_global_tracker: Optional[RunTracker] = None


def get_global_tracker() -> RunTracker:
    """Retourne l'instance globale du tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = RunTracker()
    return _global_tracker


__all__ = [
    "RunSignature",
    "RunTracker",
    "get_global_tracker",
]
