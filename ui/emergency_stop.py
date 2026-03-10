"""
Module-ID: ui.emergency_stop

Purpose: Système d'arrêt d'urgence et nettoyage mémoire complet.

Role in pipeline: ui / cleanup

Key components: EmergencyStopHandler, full_memory_cleanup

Inputs: Session state, logger

Outputs: RAM/VRAM libérée, processus arrêtés

Dependencies: gc, psutil, torch, MemoryManager

Conventions: Nettoyage agressif tous composants; logs détaillés; fallback sur erreurs.

Read-if: Modification logique arrêt d'urgence

Skip-if: Utilisation normale du bouton stop
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EmergencyStopHandler:
    """
    Gestionnaire d'arrêt d'urgence avec nettoyage mémoire complet.

    Responsabilités:
    - Arrêter tous les threads/processus en cours
    - Vider les caches (indicateurs, LLM, GPU)
    - Libérer RAM et VRAM
    - Réinitialiser les états Streamlit
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._cleanup_stats: Dict[str, Any] = {}

    def request_stop(self) -> None:
        """Demande l'arrêt de tous les processus en cours."""
        self._stop_event.set()
        logger.warning("🛑 ARRÊT D'URGENCE DEMANDÉ")

    def is_stop_requested(self) -> bool:
        """Vérifie si un arrêt a été demandé."""
        return self._stop_event.is_set()

    def reset_stop(self) -> None:
        """Réinitialise le flag d'arrêt."""
        self._stop_event.clear()

    def full_cleanup(self, session_state: Optional[Any] = None) -> Dict[str, Any]:
        """
        Effectue un nettoyage mémoire complet de tous les composants.

        Args:
            session_state: État de session Streamlit (optionnel)

        Returns:
            Dict avec statistiques de nettoyage
        """
        stats = {
            "timestamp": time.time(),
            "components_cleaned": [],
            "errors": [],
            "ram_freed_mb": 0.0,
            "vram_freed_mb": 0.0,
        }

        # 1. Arrêter les opérations en cours
        self._stop_running_operations(session_state, stats)

        # 2. Nettoyer les LLM (décharger de la VRAM)
        self._cleanup_llm_models(stats)

        # 3. Nettoyer le cache d'indicateurs
        self._cleanup_indicator_cache(stats)

        # 4. Nettoyer PyTorch (si utilisé)
        self._cleanup_pytorch(stats)

        # 5. Nettoyer le MemoryManager
        self._cleanup_memory_manager(stats)

        # 6. Garbage collection agressif
        self._aggressive_gc(stats)

        # 7. Réinitialiser les états Streamlit
        if session_state is not None:
            self._reset_session_state(session_state, stats)

        # 8. Mesurer la mémoire libérée
        self._measure_freed_memory(stats)

        self._cleanup_stats = stats
        return stats

    def _stop_running_operations(
        self,
        session_state: Optional[Any],
        stats: Dict[str, Any]
    ) -> None:
        """Arrête toutes les opérations en cours."""
        try:
            # Signaler l'arrêt via le flag global
            self.request_stop()

            # Arrêter SweepEngine si en cours
            # Note: On ne peut pas accéder à l'instance en cours directement,
            # mais le flag _stop_requested sera vérifié dans la boucle
            stats["components_cleaned"].append("sweep_engine_signal")

            # Arrêter les agents LLM en cours
            if session_state is not None:
                if hasattr(session_state, "is_running"):
                    session_state.is_running = False
                if hasattr(session_state, "stop_requested"):
                    session_state.stop_requested = True
                stats["components_cleaned"].append("session_flags")

            logger.info("✅ Opérations arrêtées")

        except Exception as e:
            logger.error(f"❌ Erreur arrêt opérations: {e}")
            stats["errors"].append(f"stop_operations: {e}")

    def _cleanup_llm_models(self, stats: Dict[str, Any]) -> None:
        """Décharge tous les modèles LLM de la VRAM avec vérification complète."""
        try:
            import httpx

            from agents.ollama_manager import unload_model

            # Récupérer la liste de TOUS les modèles chargés
            try:
                response = httpx.get("http://127.0.0.1:11434/api/ps", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])

                    if not models:
                        logger.debug("Aucun modèle LLM chargé")
                        stats["components_cleaned"].append("llm_none_loaded")
                        return

                    # Décharger chaque modèle avec vérification
                    n_unloaded = 0
                    for model_info in models:
                        model_name = model_info.get("name", "")
                        if model_name:
                            try:
                                success = unload_model(model_name)
                                if success:
                                    n_unloaded += 1
                                    logger.info(f"🗑️ LLM déchargé: {model_name}")
                                    stats["components_cleaned"].append(f"llm_{model_name}")
                                else:
                                    logger.warning(f"⚠️ Échec déchargement: {model_name}")
                                    stats["errors"].append(f"llm_unload_{model_name}_failed")
                            except Exception as e:
                                logger.warning(f"⚠️ Erreur déchargement {model_name}: {e}")
                                stats["errors"].append(f"llm_{model_name}: {e}")

                    # Vérification finale : aucun modèle ne devrait rester
                    response_check = httpx.get("http://127.0.0.1:11434/api/ps", timeout=3.0)
                    if response_check.status_code == 200:
                        remaining = response_check.json().get("models", [])
                        if remaining:
                            logger.warning(f"⚠️ {len(remaining)} modèle(s) encore en mémoire après cleanup")
                            stats["errors"].append(f"llm_remaining_{len(remaining)}_models")
                        else:
                            logger.info(f"✅ Tous les LLM déchargés ({n_unloaded} modèles)")

                else:
                    logger.debug(f"Ollama API non accessible (status {response.status_code})")
                    stats["errors"].append(f"ollama_api_status_{response.status_code}")

            except httpx.TimeoutException:
                logger.warning("⚠️ Timeout connexion Ollama API")
                stats["errors"].append("ollama_api_timeout")
            except Exception as e:
                logger.debug(f"Impossible de décharger LLM via API: {e}")
                stats["errors"].append(f"llm_api_error: {e}")

        except ImportError:
            logger.debug("Module agents.ollama_manager non disponible")
            # Pas d'erreur si module non installé
        except Exception as e:
            stats["errors"].append(f"llm_cleanup: {e}")

    def _cleanup_indicator_cache(self, stats: Dict[str, Any]) -> None:
        """Vide le cache d'indicateurs."""
        try:
            from data.indicator_bank import IndicatorBank

            bank = IndicatorBank()

            # D'abord nettoyer les entrées expirées
            n_expired = bank.cleanup_expired()
            if n_expired > 0:
                stats["components_cleaned"].append(f"indicator_expired_{n_expired}")

            # Ensuite vider complètement le cache si nécessaire
            # Note: Garder commenté par défaut pour ne pas perdre le cache
            # Décommenter si vous voulez un nettoyage vraiment complet
            # bank.clear()
            # stats["components_cleaned"].append("indicator_bank_full_clear")

            # Vider le cache mémoire interne
            if hasattr(bank, "_memory_cache"):
                bank._memory_cache.clear()
                stats["components_cleaned"].append("indicator_memory_cache")

            logger.info(f"🗑️ Cache indicateurs nettoyé ({n_expired} expirés)")

        except Exception as e:
            stats["errors"].append(f"indicator_cache: {e}")

    def _cleanup_pytorch(self, stats: Dict[str, Any]) -> None:
        """Libère le cache PyTorch CUDA."""
        try:
            import torch

            if torch.cuda.is_available():
                # Vider le cache pour tous les devices
                n_devices = torch.cuda.device_count()
                for i in range(n_devices):
                    with torch.cuda.device(i):
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()

                stats["components_cleaned"].append("pytorch_cuda")
                logger.info("🗑️ PyTorch VRAM vidée")

        except ImportError:
            pass  # PyTorch non installé
        except Exception as e:
            stats["errors"].append(f"pytorch: {e}")

    def _cleanup_memory_manager(self, stats: Dict[str, Any]) -> None:
        """Nettoie le MemoryManager central."""
        try:
            from utils.memory import MemoryManager

            # Créer une instance pour forcer le cleanup
            manager = MemoryManager()
            n_freed = manager.cleanup(aggressive=True)

            if n_freed > 0:
                stats["ram_freed_mb"] += n_freed / (1024**2)
                stats["components_cleaned"].append(f"memory_manager_{n_freed}_bytes")

            # Vider tous les caches managés
            for cache_name in list(manager._caches.keys()):
                cache = manager._caches[cache_name]
                freed = cache.clear()
                if freed > 0:
                    stats["ram_freed_mb"] += freed / (1024**2)
                    stats["components_cleaned"].append(f"managed_cache_{cache_name}")

            logger.info("🗑️ MemoryManager nettoyé")

        except Exception as e:
            stats["errors"].append(f"memory_manager: {e}")

    def _aggressive_gc(self, stats: Dict[str, Any]) -> None:
        """Garbage collection agressif multi-passes."""
        try:
            # 3 passes de GC pour collecter les références cycliques
            for i in range(3):
                collected = gc.collect(generation=2)  # Full collection
                if i == 0:
                    stats["gc_collected_objects"] = collected

            stats["components_cleaned"].append("garbage_collector")
            logger.info(f"🗑️ GC: {stats.get('gc_collected_objects', 0)} objets collectés")

        except Exception as e:
            stats["errors"].append(f"gc: {e}")

    def _reset_session_state(
        self,
        session_state: Any,
        stats: Dict[str, Any]
    ) -> None:
        """Réinitialise les états Streamlit pertinents et nettoie le contexte LLM."""
        try:
            # Flags de contrôle
            if hasattr(session_state, "is_running"):
                session_state.is_running = False
            if hasattr(session_state, "stop_requested"):
                session_state.stop_requested = False

            # Nettoyer TOUS les résultats et contextes précédents
            llm_keys_to_clean = [
                "last_run_result",
                "last_winner_params",
                "last_winner_metrics",
                "last_winner_origin",
                "last_winner_meta",
                "orchestration_logs",
                "llm_optimizer",
                "llm_session",
                "current_optimization",
            ]

            n_cleaned = 0
            for key in llm_keys_to_clean:
                if hasattr(session_state, key):
                    delattr(session_state, key)
                    n_cleaned += 1

            if n_cleaned > 0:
                stats["components_cleaned"].append(f"session_llm_context_{n_cleaned}_keys")
                logger.info(f"🗑️ Contexte LLM nettoyé ({n_cleaned} clés)")

            stats["components_cleaned"].append("session_state")
            logger.info("✅ Session state réinitialisé")

        except Exception as e:
            stats["errors"].append(f"session_state: {e}")

    def _measure_freed_memory(self, stats: Dict[str, Any]) -> None:
        """Mesure approximative de la mémoire libérée."""
        try:
            import psutil

            process = psutil.Process()
            mem_info = process.memory_info()

            # Note: On ne peut pas mesurer directement la RAM libérée
            # car le GC ne rend pas forcément la mémoire au système
            # On indique juste l'usage actuel
            stats["current_ram_mb"] = mem_info.rss / (1024**2)

        except ImportError:
            pass
        except Exception as e:
            stats["errors"].append(f"measure_memory: {e}")

    def get_last_cleanup_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du dernier nettoyage."""
        return self._cleanup_stats.copy()


# Instance singleton
_emergency_handler: Optional[EmergencyStopHandler] = None


def get_emergency_handler() -> EmergencyStopHandler:
    """Retourne le gestionnaire d'arrêt d'urgence singleton."""
    global _emergency_handler
    if _emergency_handler is None:
        _emergency_handler = EmergencyStopHandler()
    return _emergency_handler


def execute_emergency_stop(session_state: Optional[Any] = None) -> Dict[str, Any]:
    """
    Raccourci pour exécuter un arrêt d'urgence complet.

    Args:
        session_state: État de session Streamlit

    Returns:
        Dict avec statistiques de nettoyage

    Example:
        >>> stats = execute_emergency_stop(st.session_state)
        >>> st.success(f"✅ {len(stats['components_cleaned'])} composants nettoyés")
    """
    handler = get_emergency_handler()
    return handler.full_cleanup(session_state)
