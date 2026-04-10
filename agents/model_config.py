"""
Module-ID: agents.model_config

Purpose: Configuration multi-modèles par rôle d'agent avec sélection intelligente (rapide/lourd par itération).

Role in pipeline: orchestration

Key components: RoleModelConfig, ModelCategory, KNOWN_MODELS, get_model

Inputs: role (analyst/strategist/critic/validator), iteration, allow_heavy flag

Outputs: Modèle sélectionné (aléatoire parmi configurés), fallback si non dispo

Dependencies: utils.log, httpx (Ollama discovery)

Conventions: ANALYST=rapide, STRATEGIST=moyen, CRITIC/VALIDATOR=lourd optionnel; early iterations excluent modèles lourds; fallback cascade si modèle absent.

Read-if: Ajout modèles, configuration par rôle, ou règles de sélection itérative.

Skip-if: Vous utilisez la config par défaut.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import httpx

from utils.model_loader import (
    get_all_ollama_models,
    get_ollama_runtime_model_names,
    normalize_model_name,
)
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)

# Seuil en milliards de paramètres au-delà duquel un modèle nécessite approbation manuelle
MAX_AUTO_SELECT_PARAMS_B: float = 50.0


def _ollama_base_url() -> str:
    """Retourne l'URL de base Ollama (avec fallback local)."""
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return base.rstrip("/")


def _fetch_ollama_tags_with_retries(
    *,
    max_attempts: int = 5,
    timeout_s: float = 3.0,
    base_backoff_s: float = 1.0,
    warn_on_failure: bool = True,
    fast_fail_on_connection_refused: bool = False,
) -> Optional[dict]:
    """Récupère /api/tags avec retries/backoff (Ollama peut démarrer lentement)."""
    def _is_connection_refused(exc: BaseException) -> bool:
        text = str(exc or "").lower()
        if "10061" in text:
            return True
        if "connection refused" in text:
            return True
        if "aucune connexion" in text and "refus" in text:
            return True
        return False

    url = f"{_ollama_base_url()}/api/tags"
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            resp = httpx.get(url, timeout=timeout_s)
            if resp.status_code == 200:
                return resp.json()
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if fast_fail_on_connection_refused and _is_connection_refused(exc):
                break

        if attempt < max_attempts - 1:
            sleep_s = float(base_backoff_s * (2 ** attempt))
            time.sleep(sleep_s)

    if warn_on_failure and last_exc is not None:
        logger.warning("Impossible de lister les modeles Ollama apres retries: %s", last_exc)
    return None


def _infer_category_from_size(size_gb: float) -> ModelCategory:
    if size_gb < 6:
        return ModelCategory.LIGHT
    if size_gb < 15:
        return ModelCategory.MEDIUM
    return ModelCategory.HEAVY


def _ollama_name_from_library_entry(entry: Dict[str, Any]) -> Optional[str]:
    model_name = entry.get("model_name")
    tag = entry.get("tag")
    if model_name and tag:
        return normalize_model_name(f"{model_name}:{tag}")
    if model_name:
        return normalize_model_name(str(model_name))
    ollama_name = entry.get("ollama_name")
    if ollama_name:
        return normalize_model_name(str(ollama_name))
    return normalize_model_name(str(entry.get("id") or "")) or None


def _model_info_from_library_entry(entry: Dict[str, Any]) -> Optional[ModelInfo]:
    name = _ollama_name_from_library_entry(entry)
    if not name:
        return None

    if name in KNOWN_MODELS:
        return KNOWN_MODELS[name]

    size_gb = float(entry.get("size_gb") or 0)
    category = _infer_category_from_size(size_gb)
    description = entry.get("description") or f"Modele {name} ({size_gb:.1f} GB)"

    return ModelInfo(
        name=name,
        category=category,
        description=description,
        recommended_for=["analyst", "strategist"],
    )


def _normalize_model_name(name: str) -> str:
    """Normalise un nom de modele via la couche centrale de model_loader."""
    return normalize_model_name(name)


def is_cloud_only_model(model_name: str) -> bool:
    """Retourne True si le modèle est défini comme cloud-only dans le registre."""
    resolved_name = _normalize_model_name(str(model_name or "").strip())
    if not resolved_name:
        return False
    info = KNOWN_MODELS.get(resolved_name) or KNOWN_MODELS.get(str(model_name or "").strip())
    return bool(info and info.cloud_only)


def list_cloud_only_model_names() -> List[str]:
    """Retourne la liste canonique des modèles Ollama Cloud supportés par le projet."""
    return sorted(
        {
            info.name
            for info in KNOWN_MODELS.values()
            if bool(getattr(info, "cloud_only", False))
        }
    )


class ModelCategory(Enum):
    """Catégories de modèles par taille/vitesse."""

    LIGHT = "light"      # < 10B params, rapide (< 30s)
    MEDIUM = "medium"    # 10-30B params, modéré (30s-2min)
    HEAVY = "heavy"      # > 30B params, lent (> 2min)


@dataclass
class ModelInfo:
    """Information sur un modèle LLM."""

    name: str                      # Nom Ollama (ex: "deepseek-r1:32b")
    category: ModelCategory        # Catégorie de taille
    description: str = ""          # Description courte
    recommended_for: List[str] = field(default_factory=list)  # Rôles recommandés
    avg_response_time_s: float = 30.0  # Temps de réponse moyen estimé
    params_billions: float = 0.0   # Nombre de paramètres en milliards (0 = inconnu)
    cloud_only: bool = False        # True = hébergé sur Ollama Cloud, nécessite des crédits

    @property
    def requires_manual_approval(self) -> bool:
        """True si le modèle dépasse le seuil d'auto-sélection (> 50B params)."""
        return self.params_billions > MAX_AUTO_SELECT_PARAMS_B

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, ModelInfo):
            return self.name == other.name
        return False


# Base de données des modèles connus avec leurs caractéristiques
KNOWN_MODELS: Dict[str, ModelInfo] = {
    # Light models (< 10B) - Rapides
    "deepseek-r1:8b": ModelInfo(
        name="deepseek-r1:8b",
        category=ModelCategory.LIGHT,
        description="DeepSeek R1 8B - Rapide, bon pour analyses simples",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=15.0,
        params_billions=8.0,
    ),
    "mistral:7b-instruct": ModelInfo(
        name="mistral:7b-instruct",
        category=ModelCategory.LIGHT,
        description="Mistral 7B Instruct - Très rapide, polyvalent",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=10.0,
        params_billions=7.0,
    ),
    "llama3.1:8b-local": ModelInfo(
        name="llama3.1:8b-local",
        category=ModelCategory.LIGHT,
        description="Llama 3.1 8B - Rapide, bonne qualité",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=20.0,
        params_billions=8.0,
    ),
    "martain7r/finance-llama-8b:q4_k_m": ModelInfo(
        name="martain7r/finance-llama-8b:q4_k_m",
        category=ModelCategory.LIGHT,
        description="Finance Llama 8B - Spécialisé finance/trading",
        recommended_for=["analyst", "critic"],
        avg_response_time_s=15.0,
        params_billions=8.0,
    ),

    "deepseek-moe-16b-local": ModelInfo(
        name="deepseek-moe-16b-local",
        category=ModelCategory.LIGHT,
        description="DeepSeek MoE 16B Chat (2.8B actifs) - MoE ultra-rapide, Q4_K_M",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=12.0,
        params_billions=16.4,
    ),

    # Medium models (10-30B) - Équilibrés
    "gemma4:26b": ModelInfo(
        name="gemma4:26b",
        category=ModelCategory.MEDIUM,
        description="Gemma 4 26B A4B - Google MoE local récent, très bon ratio qualité/VRAM",
        recommended_for=["analyst", "strategist", "critic"],
        avg_response_time_s=95.0,
        params_billions=26.0,
    ),
    "deepseek-r1-distill:14b": ModelInfo(
        name="deepseek-r1-distill:14b",
        category=ModelCategory.MEDIUM,
        description="DeepSeek R1 Distill 14B - Raisonnement efficace",
        recommended_for=["strategist", "critic", "validator"],
        avg_response_time_s=60.0,
        params_billions=14.0,
    ),
    "mistral:22b": ModelInfo(
        name="mistral:22b",
        category=ModelCategory.MEDIUM,
        description="Mistral 22B - Puissant et raisonnablement rapide",
        recommended_for=["critic", "validator"],
        avg_response_time_s=90.0,
        params_billions=22.0,
    ),
    "devstral-small-2:24b": ModelInfo(
        name="devstral-small-2:24b",
        category=ModelCategory.MEDIUM,
        description="Devstral Small 2 24B Q4_K_M - agent code local, contexte 393k",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=65.0,
        params_billions=24.0,
    ),
    "lfm2:24b": ModelInfo(
        name="lfm2:24b",
        category=ModelCategory.MEDIUM,
        description="LFM2 24B Q4_K_M - generaliste efficace pour usage local 24GB",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=55.0,
        params_billions=23.8,
    ),
    "glm-4.7-flash-23b-local": ModelInfo(
        name="glm-4.7-flash-23b-local",
        category=ModelCategory.MEDIUM,
        description="GLM 4.7 Flash local - MoE rapide polyvalent, Q3_K_M",
        recommended_for=["analyst", "strategist", "critic"],
        avg_response_time_s=25.0,
        params_billions=29.9,
    ),
    "qwen3-30b-a3b:q4_k_m": ModelInfo(
        name="qwen3-30b-a3b:q4_k_m",
        category=ModelCategory.MEDIUM,
        description="Qwen3 30B A3B Q4_K_M - MoE coding/reasoning, runtime C:\\AI",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=55.0,
        params_billions=30.5,
    ),

    # Heavy models (> 30B) - Puissants mais lents
    "deepseek-r1:32b": ModelInfo(
        name="deepseek-r1:32b",
        category=ModelCategory.HEAVY,
        description="DeepSeek R1 32B - Excellent raisonnement",
        recommended_for=["critic", "validator"],
        avg_response_time_s=180.0,
        params_billions=32.0,
    ),
    "gemma4:31b": ModelInfo(
        name="gemma4:31b",
        category=ModelCategory.HEAVY,
        description="Gemma 4 31B Dense - Google open model haut de gamme pour raisonnement local",
        recommended_for=["critic", "validator"],
        avg_response_time_s=165.0,
        params_billions=31.0,
    ),
    "qwq:32b": ModelInfo(
        name="qwq:32b",
        category=ModelCategory.HEAVY,
        description="QwQ 32B - Raisonnement profond",
        recommended_for=["critic", "validator"],
        avg_response_time_s=200.0,
        params_billions=32.0,
    ),
    "qwen2.5:32b": ModelInfo(
        name="qwen2.5:32b",
        category=ModelCategory.HEAVY,
        description="Qwen 2.5 32B - Polyvalent haute qualité",
        recommended_for=["strategist", "critic", "validator"],
        avg_response_time_s=150.0,
        params_billions=32.0,
    ),
    "qwen3-vl:32b": ModelInfo(
        name="qwen3-vl:32b",
        category=ModelCategory.HEAVY,
        description="Qwen 3 VL 32B - Vision + langage, outils, thinking",
        recommended_for=["analyst"],  # Pour analyse de charts
        avg_response_time_s=180.0,
        params_billions=33.4,
    ),
    "deepseek-coder-33b-local": ModelInfo(
        name="deepseek-coder-33b-local",
        category=ModelCategory.HEAVY,
        description="DeepSeek Coder 33B - Dense, spécialisé code, Q5_K_M",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=180.0,
        params_billions=33.3,
    ),
    "qwen3-coder:30b": ModelInfo(
        name="qwen3-coder:30b",
        category=ModelCategory.HEAVY,
        description="Qwen3 Coder 30B - modele code principal local actuellement chargeable",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=60.0,
        params_billions=30.0,
    ),
    "qwen3.5:35b": ModelInfo(
        name="qwen3.5:35b",
        category=ModelCategory.HEAVY,
        description="Qwen 3.5 35B - generaliste multimodal recent, haut de gamme local",
        recommended_for=["analyst", "critic", "validator"],
        avg_response_time_s=170.0,
        params_billions=36.0,
    ),
    "deepseek-r1:70b": ModelInfo(
        name="deepseek-r1:70b",
        category=ModelCategory.HEAVY,
        description="DeepSeek R1 70B - Maximum puissance, TRÈS LENT (>50B: approbation manuelle requise)",
        recommended_for=["validator"],  # Réservé aux décisions critiques
        avg_response_time_s=600.0,  # ~10 minutes
        params_billions=70.0,
    ),
    "gpt-oss:20b": ModelInfo(
        name="gpt-oss:20b",
        category=ModelCategory.MEDIUM,
        description="GPT OSS 20B",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=100.0,
        params_billions=20.0,
    ),
    # Llama 3.3 70B - Multi-GPU optimisé
    "llama3.3:70b-instruct-q4_K_M": ModelInfo(
        name="llama3.3:70b-instruct-q4_K_M",
        category=ModelCategory.HEAVY,
        description="Llama 3.3 70B Instruct Q4 - Multi-GPU (>50B: approbation manuelle requise)",
        recommended_for=["critic", "validator"],
        avg_response_time_s=300.0,
        params_billions=70.0,
    ),
    "llama3.3-70b-2gpu": ModelInfo(
        name="llama3.3-70b-2gpu",
        category=ModelCategory.HEAVY,
        description="Llama 3.3 70B Multi-GPU (2 GPUs) - RTX 5080+2060 (>50B: approbation manuelle requise)",
        recommended_for=["critic", "validator"],
        avg_response_time_s=180.0,  # Plus rapide avec 2 GPUs
        params_billions=70.0,
    ),

    # ── Nouveaux modèles Ollama 2025-2026 ──────────────────────────────────────

    # Light -- nouveaux
    "qwen3:8b": ModelInfo(
        name="qwen3:8b",
        category=ModelCategory.LIGHT,
        description="Qwen3 8B - Thinking + tools, dernière génération Alibaba",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=18.0,
        params_billions=8.0,
    ),
    "qwen3.5:9b": ModelInfo(
        name="qwen3.5:9b",
        category=ModelCategory.LIGHT,
        description="Qwen3.5 9B - Vision + tools + thinking, multimodal récent",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=22.0,
        params_billions=9.0,
    ),
    "deepseek-r1:7b": ModelInfo(
        name="deepseek-r1:7b",
        category=ModelCategory.LIGHT,
        description="DeepSeek R1 7B - Raisonnement distil, compact",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=12.0,
        params_billions=7.0,
    ),
    "phi4-mini:3.8b": ModelInfo(
        name="phi4-mini:3.8b",
        category=ModelCategory.LIGHT,
        description="Phi-4 Mini 3.8B - Tools + multilingual (Microsoft)",
        recommended_for=["analyst"],
        avg_response_time_s=8.0,
        params_billions=3.8,
    ),

    # Medium -- nouveaux
    "phi4:14b": ModelInfo(
        name="phi4:14b",
        category=ModelCategory.MEDIUM,
        description="Phi-4 14B - SOTA Microsoft, raisonnement et maths avancés",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=50.0,
        params_billions=14.0,
    ),
    "phi4-reasoning:14b": ModelInfo(
        name="phi4-reasoning:14b",
        category=ModelCategory.MEDIUM,
        description="Phi-4 Reasoning 14B - Rival des 70B sur tâches complexes (Microsoft)",
        recommended_for=["critic", "validator"],
        avg_response_time_s=70.0,
        params_billions=14.0,
    ),
    "qwen3:14b": ModelInfo(
        name="qwen3:14b",
        category=ModelCategory.MEDIUM,
        description="Qwen3 14B - Thinking + tools, excellent équilibre",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=55.0,
        params_billions=14.0,
    ),
    "qwen3.5:27b": ModelInfo(
        name="qwen3.5:27b",
        category=ModelCategory.MEDIUM,
        description="Qwen3.5 27B - Vision + tools + thinking, haut de gamme local",
        recommended_for=["critic", "validator"],
        avg_response_time_s=120.0,
        params_billions=27.0,
    ),
    "devstral:24b": ModelInfo(
        name="devstral:24b",
        category=ModelCategory.MEDIUM,
        description="Devstral 24B - Meilleur agent code open-source (Mistral)",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=80.0,
        params_billions=24.0,
    ),
    "mistral-small3.2:24b": ModelInfo(
        name="mistral-small3.2:24b",
        category=ModelCategory.MEDIUM,
        description="Mistral Small 3.2 24B - Vision + tools + 128k contexte",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=75.0,
        params_billions=24.0,
    ),
    "magistral:24b": ModelInfo(
        name="magistral:24b",
        category=ModelCategory.MEDIUM,
        description="Magistral 24B - Raisonnement thinking, Mistral petit modèle raisonnant",
        recommended_for=["critic", "validator"],
        avg_response_time_s=90.0,
        params_billions=24.0,
    ),
    "cogito:14b": ModelInfo(
        name="cogito:14b",
        category=ModelCategory.MEDIUM,
        description="Cogito 14B - Raisonnement hybride Deep Cogito, surpasse LLaMA/Qwen de même taille",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=60.0,
        params_billions=14.0,
    ),
    "cogito:8b": ModelInfo(
        name="cogito:8b",
        category=ModelCategory.LIGHT,
        description="Cogito 8B - Raisonnement hybride Deep Cogito, compact",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=20.0,
        params_billions=8.0,
    ),

    # Heavy -- nouveaux
    "qwen3:32b": ModelInfo(
        name="qwen3:32b",
        category=ModelCategory.HEAVY,
        description="Qwen3 32B dense - Thinking + tools, flagship Alibaba 2025",
        recommended_for=["critic", "validator"],
        avg_response_time_s=180.0,
        params_billions=32.0,
    ),
    "cogito:32b": ModelInfo(
        name="cogito:32b",
        category=ModelCategory.HEAVY,
        description="Cogito 32B - Raisonnement hybride, top benchmarks open-source",
        recommended_for=["critic", "validator"],
        avg_response_time_s=200.0,
        params_billions=32.0,
    ),
    "nemotron:70b": ModelInfo(
        name="nemotron:70b",
        category=ModelCategory.HEAVY,
        description="Nemotron 70B - NVIDIA Llama 3.1 finetuné, ultra-helpful (>50B: approbation manuelle)",
        recommended_for=["validator"],
        avg_response_time_s=600.0,
        params_billions=70.0,
    ),
    "llama4:16x17b": ModelInfo(
        name="llama4:16x17b",
        category=ModelCategory.HEAVY,
        description="Llama 4 Scout MoE 16x17B - Meta multimodal vision (>50B: approbation manuelle)",
        recommended_for=["analyst", "validator"],
        avg_response_time_s=400.0,
        params_billions=109.0,
    ),
    "deepseek-v3:671b": ModelInfo(
        name="deepseek-v3:671b",
        category=ModelCategory.HEAVY,
        description="DeepSeek V3 671B MoE (37B actifs) - Téléchargeable mais ~390 Go disque (>50B: approbation manuelle)",
        recommended_for=["validator"],
        avg_response_time_s=900.0,
        params_billions=671.0,
        cloud_only=False,
    ),
    "deepseek-r1:671b": ModelInfo(
        name="deepseek-r1:671b",
        category=ModelCategory.HEAVY,
        description="DeepSeek R1 671B MoE - Raisonnement niveau O3 - Téléchargeable mais ~380 Go disque (>50B: approbation manuelle)",
        recommended_for=["validator"],
        avg_response_time_s=900.0,
        params_billions=671.0,
        cloud_only=False,
    ),

    # ── Modèles CLOUD-ONLY (hébergés sur Ollama Cloud, non téléchargeables) ───
    # Ces modèles nécessitent des crédits Ollama Cloud pour fonctionner.
    # Ils ne peuvent pas tourner localement, quelle que soit la configuration GPU.

    # DeepSeek cloud
    "deepseek-v3.2": ModelInfo(
        name="deepseek-v3.2",
        category=ModelCategory.HEAVY,
        description="DeepSeek V3.2 671B - Thinking + non-thinking hybride, dernier flagship DeepSeek ☁️ Cloud",
        recommended_for=["strategist", "critic", "validator"],
        avg_response_time_s=60.0,
        params_billions=671.0,
        cloud_only=True,
    ),
    "deepseek-v3.1": ModelInfo(
        name="deepseek-v3.1",
        category=ModelCategory.HEAVY,
        description="DeepSeek V3.1 671B - Mode thinking et non-thinking hybride ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=60.0,
        params_billions=671.0,
        cloud_only=True,
    ),

    # GLM family (Z.ai / Zhipu)
    "glm-4.7": ModelInfo(
        name="glm-4.7",
        category=ModelCategory.HEAVY,
        description="GLM-4.7 - Coding avancé + raisonnement thinking (Z.ai) ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=45.0,
        params_billions=0.0,
        cloud_only=True,
    ),
    "glm-4.6": ModelInfo(
        name="glm-4.6",
        category=ModelCategory.HEAVY,
        description="GLM-4.6 - Agentique, raisonnement et code (Z.ai) ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=40.0,
        params_billions=0.0,
        cloud_only=True,
    ),
    "glm-5": ModelInfo(
        name="glm-5",
        category=ModelCategory.HEAVY,
        description="GLM-5 744B MoE (40B actifs) - Raisonnement long + systèmes complexes (Z.ai) ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=50.0,
        params_billions=744.0,
        cloud_only=True,
    ),

    # Qwen cloud (tailles non téléchargeables)
    "qwen3-coder:480b": ModelInfo(
        name="qwen3-coder:480b",
        category=ModelCategory.HEAVY,
        description="Qwen3 Coder 480B - Meilleur modèle code agentique Alibaba ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=90.0,
        params_billions=480.0,
        cloud_only=True,
    ),
    "qwen3.5:122b": ModelInfo(
        name="qwen3.5:122b",
        category=ModelCategory.HEAVY,
        description="Qwen3.5 122B - Vision + tools + thinking haut de gamme ☁️ Cloud",
        recommended_for=["analyst", "critic", "validator"],
        avg_response_time_s=70.0,
        params_billions=122.0,
        cloud_only=True,
    ),
    "qwen3-next:80b": ModelInfo(
        name="qwen3-next:80b",
        category=ModelCategory.HEAVY,
        description="Qwen3-Next 80B - Thinking haute efficacité, première génération Qwen3-Next ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=65.0,
        params_billions=80.0,
        cloud_only=True,
    ),
    "qwen3-vl:235b": ModelInfo(
        name="qwen3-vl:235b",
        category=ModelCategory.HEAVY,
        description="Qwen3 VL 235B - Vision + language + thinking, flagship Qwen multimodal ☁️ Cloud",
        recommended_for=["analyst", "validator"],
        avg_response_time_s=80.0,
        params_billions=235.0,
        cloud_only=True,
    ),

    # Kimi (Moonshot AI)
    "kimi-k2": ModelInfo(
        name="kimi-k2",
        category=ModelCategory.HEAVY,
        description="Kimi K2 MoE - Excellent agent code, benchmarks SOTA open-source (Moonshot) ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=55.0,
        params_billions=0.0,
        cloud_only=True,
    ),
    "kimi-k2-thinking": ModelInfo(
        name="kimi-k2-thinking",
        category=ModelCategory.HEAVY,
        description="Kimi K2 Thinking - Meilleur raisonnement open-source Moonshot ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=90.0,
        params_billions=0.0,
        cloud_only=True,
    ),
    "kimi-k2.5": ModelInfo(
        name="kimi-k2.5",
        category=ModelCategory.HEAVY,
        description="Kimi K2.5 - Multimodal agentique (vision + thinking + instant) ☁️ Cloud",
        recommended_for=["analyst", "strategist"],
        avg_response_time_s=50.0,
        params_billions=0.0,
        cloud_only=True,
    ),

    # MiniMax
    "minimax-m2.7": ModelInfo(
        name="minimax-m2.7",
        category=ModelCategory.HEAVY,
        description="MiniMax M2.7 - Code + workflows agentiques + productivité (dernier MiniMax) ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=50.0,
        params_billions=0.0,
        cloud_only=True,
    ),
    "minimax-m2.5": ModelInfo(
        name="minimax-m2.5",
        category=ModelCategory.HEAVY,
        description="MiniMax M2.5 - Productivité et code SOTA ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=45.0,
        params_billions=0.0,
        cloud_only=True,
    ),

    # NVIDIA
    "nemotron-3-super:120b": ModelInfo(
        name="nemotron-3-super:120b",
        category=ModelCategory.HEAVY,
        description="NVIDIA Nemotron-3 Super 120B MoE (12B actifs) - Multi-agent, tools + thinking ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=60.0,
        params_billions=120.0,
        cloud_only=True,
    ),

    # Mistral cloud
    "devstral-2:123b": ModelInfo(
        name="devstral-2:123b",
        category=ModelCategory.HEAVY,
        description="Devstral-2 123B - Meilleur agent code open-source toutes tailles (Mistral) ☁️ Cloud",
        recommended_for=["strategist", "critic"],
        avg_response_time_s=75.0,
        params_billions=123.0,
        cloud_only=True,
    ),
    "mistral-large-3": ModelInfo(
        name="mistral-large-3",
        category=ModelCategory.HEAVY,
        description="Mistral Large 3 - Vision + tools, flagship enterprise Mistral ☁️ Cloud",
        recommended_for=["critic", "validator"],
        avg_response_time_s=65.0,
        params_billions=0.0,
        cloud_only=True,
    ),

    # GPT-OSS (OpenAI open weights)
    "gpt-oss:120b": ModelInfo(
        name="gpt-oss:120b",
        category=ModelCategory.HEAVY,
        description="GPT-OSS 120B - OpenAI open weight, raisonnement + agent (approbation manuelle) ☁️ Cloud",
        recommended_for=["validator"],
        avg_response_time_s=80.0,
        params_billions=120.0,
        cloud_only=True,
    ),

    # Cogito cloud
    "cogito-2.1:671b": ModelInfo(
        name="cogito-2.1:671b",
        category=ModelCategory.HEAVY,
        description="Cogito v2.1 671B - Raisonnement instruction tuned (MIT license) ☁️ Cloud",
        recommended_for=["validator"],
        avg_response_time_s=120.0,
        params_billions=671.0,
        cloud_only=True,
    ),
}


@dataclass
class RoleModelAssignment:
    """Configuration des modèles pour un rôle."""

    role: str
    models: List[str] = field(default_factory=list)
    allow_heavy_after_iteration: int = 3  # N'autoriser les modèles lourds qu'après N itérations
    prefer_specialized: bool = True  # Préférer les modèles spécialisés pour ce rôle

    def get_available_models(
        self,
        iteration: int = 1,
        allow_heavy: bool = False,
        installed_models: Optional[Set[str]] = None,
        allow_very_large: bool = False,
    ) -> List[str]:
        """
        Retourne les modèles disponibles pour cette itération.

        Args:
            iteration: Numéro d'itération actuel
            allow_heavy: Forcer l'autorisation des modèles lourds (catégorie HEAVY)
            installed_models: Set des modèles installés (pour filtrage)
            allow_very_large: Autoriser les modèles > 50B params (nécessite approbation manuelle)

        Returns:
            Liste des modèles utilisables
        """
        available = []

        for model_name in self.models:
            resolved_name = _normalize_model_name(model_name) or model_name
            model_info = KNOWN_MODELS.get(resolved_name) or KNOWN_MODELS.get(model_name)

            if (
                installed_models
                and not bool(model_info and model_info.cloud_only)
                and resolved_name not in installed_models
                and model_name not in installed_models
            ):
                continue

            if model_info:
                if model_info.requires_manual_approval and not allow_very_large:
                    logger.debug(
                        f"Modele {resolved_name} exclu (>{MAX_AUTO_SELECT_PARAMS_B}B params, approbation requise)"
                    )
                    continue

                if model_info.category == ModelCategory.HEAVY:
                    if not allow_heavy and iteration < self.allow_heavy_after_iteration:
                        continue

            available.append(resolved_name)

        return available


@dataclass
class RoleModelConfig:
    """
    Configuration complète des modèles par rôle.

    Permet d'assigner plusieurs modèles à chaque rôle avec sélection
    aléatoire ou basée sur des critères.
    """

    # Configuration par rôle
    analyst: RoleModelAssignment = field(default_factory=lambda: RoleModelAssignment(
        role="analyst",
        models=[
            # Light
            "phi4-mini:3.8b", "deepseek-r1:7b", "deepseek-r1:8b",
            "qwen3:8b", "cogito:8b", "qwen3.5:9b",
            "mistral:7b-instruct", "martain7r/finance-llama-8b:q4_k_m",
            # Medium
            "gemma4:26b", "deepseek-moe-16b-local", "glm-4.7-flash-23b-local", "lfm2:24b",
            # Heavy
            "gemma4:31b", "qwen3-vl:32b", "qwen3.5:35b", "llama4:16x17b",
        ],
        allow_heavy_after_iteration=5,
    ))

    strategist: RoleModelAssignment = field(default_factory=lambda: RoleModelAssignment(
        role="strategist",
        models=[
            # Light
            "deepseek-r1:7b", "deepseek-r1:8b", "qwen3:8b", "cogito:8b",
            # Medium
            "gemma4:26b", "phi4:14b", "qwen3:14b", "cogito:14b",
            "deepseek-r1-distill:14b", "mistral:22b",
            "glm-4.7-flash-23b-local", "devstral:24b", "devstral-small-2:24b",
            "mistral-small3.2:24b", "lfm2:24b", "qwen3-30b-a3b:q4_k_m",
            # Heavy local
            "gemma4:31b", "deepseek-coder-33b-local", "qwen3-coder:30b", "qwen3.5:35b",
            # Cloud-only (☁️ crédits Ollama requis)
            "deepseek-v3.2", "glm-4.7", "glm-4.6",
            "qwen3-coder:480b", "kimi-k2", "kimi-k2.5",
            "minimax-m2.7", "devstral-2:123b",
        ],
        allow_heavy_after_iteration=3,
    ))

    critic: RoleModelAssignment = field(default_factory=lambda: RoleModelAssignment(
        role="critic",
        models=[
            # Medium
            "gemma4:26b", "phi4-reasoning:14b", "qwen3:14b", "cogito:14b", "deepseek-r1-distill:14b",
            "mistral:22b", "glm-4.7-flash-23b-local",
            "devstral:24b", "devstral-small-2:24b", "mistral-small3.2:24b",
            "magistral:24b", "lfm2:24b", "qwen3.5:27b",
            # Heavy local
            "gemma4:31b", "deepseek-r1:32b", "qwq:32b", "qwen3:32b", "cogito:32b",
            "deepseek-coder-33b-local", "qwen3.5:35b",
            # Cloud-only (☁️ crédits Ollama requis)
            "deepseek-v3.2", "glm-4.7", "glm-4.6", "glm-5",
            "qwen3-coder:480b", "qwen3.5:122b",
            "kimi-k2", "minimax-m2.7", "minimax-m2.5",
            "nemotron-3-super:120b", "devstral-2:123b", "mistral-large-3",
        ],
        allow_heavy_after_iteration=2,
    ))

    validator: RoleModelAssignment = field(default_factory=lambda: RoleModelAssignment(
        role="validator",
        models=[
            # Medium
            "gemma4:26b", "phi4-reasoning:14b", "deepseek-r1-distill:14b",
            "qwen3.5:27b", "magistral:24b",
            # Heavy local
            "gemma4:31b", "deepseek-r1:32b", "qwq:32b", "qwen3:32b", "cogito:32b",
            "qwen3.5:35b",
            # Very large local (>50B — approbation manuelle)
            "deepseek-r1:70b", "nemotron:70b",
            "llama3.3:70b-instruct-q4_K_M", "llama3.3-70b-2gpu",
            # Cloud-only (☁️ crédits Ollama requis)
            "deepseek-v3.2", "deepseek-v3.1",
            "glm-5", "qwen3.5:122b", "qwen3-next:80b", "qwen3-vl:235b",
            "kimi-k2-thinking", "nemotron-3-super:120b",
            "gpt-oss:120b", "cogito-2.1:671b",
            # deepseek-r1:671b et deepseek-v3:671b sont téléchargeables (non cloud), retirés ici
        ],
        allow_heavy_after_iteration=3,
    ))

    # Cache des modèles installés
    _installed_models: Optional[Set[str]] = field(default=None, repr=False)

    def __post_init__(self):
        """Initialise le cache des modèles installés."""
        self._refresh_installed_models()

    def _refresh_installed_models(self) -> Set[str]:
        """Rafraîchit la liste des modèles Ollama installés."""
        names: Set[str] = set()
        catalog_names = list(get_ollama_runtime_model_names())

        for name in catalog_names:
            norm = _normalize_model_name(name)
            if norm:
                names.add(name)
                names.add(norm)

        # 1) Source principale: API /api/tags (Ollama en cours d'exécution)
        data = _fetch_ollama_tags_with_retries(
            max_attempts=1 if names else 5,
            timeout_s=1.0 if names else 3.0,
            base_backoff_s=0.25 if names else 1.0,
            warn_on_failure=not names,
            fast_fail_on_connection_refused=bool(names),
        )
        if data:
            for m in data.get("models", []):
                raw = m.get("name", "")
                norm = _normalize_model_name(raw)
                if norm:
                    names.add(raw)
                    names.add(norm)

        # 2) Fallback: models.json (permet d'afficher quelque chose si l'API est indisponible)
        if not names:
            for name in catalog_names:
                norm = _normalize_model_name(name)
                if norm:
                    names.add(name)
                    names.add(norm)

        self._installed_models = names
        logger.debug("Modeles consideres comme installes: %s", len(self._installed_models))

        return self._installed_models

    def get_installed_models(self) -> Set[str]:
        """Retourne les modèles installés (avec cache)."""
        if self._installed_models is None:
            self._refresh_installed_models()
        return self._installed_models or set()

    def get_role_assignment(self, role: str) -> RoleModelAssignment:
        """Retourne l'assignment pour un rôle."""
        role = role.lower()
        if role == "analyst":
            return self.analyst
        elif role == "strategist":
            return self.strategist
        elif role == "critic":
            return self.critic
        elif role == "validator":
            return self.validator
        else:
            # Défaut: utiliser analyst
            logger.warning(f"Rôle inconnu: {role}, utilisation de analyst")
            return self.analyst

    def get_model(
        self,
        role: str,
        iteration: int = 1,
        allow_heavy: bool = False,
        random_selection: bool = True,
        allow_very_large: bool = False,
    ) -> Optional[str]:
        """
        Obtient un modèle pour un rôle donné.

        Args:
            role: Nom du rôle (analyst, strategist, critic, validator)
            iteration: Numéro d'itération actuel
            allow_heavy: Forcer l'autorisation des modèles lourds (catégorie HEAVY)
            random_selection: Si True, sélection aléatoire parmi les modèles disponibles
            allow_very_large: Autoriser les modèles > 50B params (approbation manuelle)

        Returns:
            Nom du modèle ou None si aucun disponible
        """
        assignment = self.get_role_assignment(role)
        installed = self.get_installed_models()

        # Niveau 1: intersection config role ∩ installed
        available = assignment.get_available_models(
            iteration=iteration,
            allow_heavy=allow_heavy,
            installed_models=installed,
            allow_very_large=allow_very_large,
        )
        if available:
            return random.choice(available) if (random_selection and len(available) > 1) else available[0]

        # Niveau 2: fallback sur la config du role, meme si Ollama est down / liste vide
        fallback_cfg = assignment.get_available_models(
            iteration=iteration,
            allow_heavy=allow_heavy,
            installed_models=None,
            allow_very_large=allow_very_large,
        )
        if fallback_cfg:
            return (
                random.choice(fallback_cfg)
                if (random_selection and len(fallback_cfg) > 1)
                else fallback_cfg[0]
            )

        # Niveau 3: n'importe quel modele installe
        if installed:
            return next(iter(installed))

        logger.warning("Aucun modele disponible pour %s (iteration=%s)", role, iteration)
        return None

    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Retourne les infos d'un modele."""
        resolved_name = _normalize_model_name(model_name)
        return KNOWN_MODELS.get(resolved_name) or KNOWN_MODELS.get(model_name)

    def set_role_models(self, role: str, models: List[str]) -> None:
        """Configure les modeles pour un role."""
        assignment = self.get_role_assignment(role)
        assignment.models = [_normalize_model_name(model) for model in models]
        logger.info(f"Modeles pour {role}: {assignment.models}")

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la configuration."""
        return {
            "analyst": {
                "models": self.analyst.models,
                "allow_heavy_after_iteration": self.analyst.allow_heavy_after_iteration,
            },
            "strategist": {
                "models": self.strategist.models,
                "allow_heavy_after_iteration": self.strategist.allow_heavy_after_iteration,
            },
            "critic": {
                "models": self.critic.models,
                "allow_heavy_after_iteration": self.critic.allow_heavy_after_iteration,
            },
            "validator": {
                "models": self.validator.models,
                "allow_heavy_after_iteration": self.validator.allow_heavy_after_iteration,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RoleModelConfig:
        """Désérialise la configuration."""
        config = cls()

        for role in ["analyst", "strategist", "critic", "validator"]:
            if role in data:
                role_data = data[role]
                assignment = config.get_role_assignment(role)
                assignment.models = [_normalize_model_name(m) for m in role_data.get("models", assignment.models)]
                assignment.allow_heavy_after_iteration = role_data.get(
                    "allow_heavy_after_iteration",
                    assignment.allow_heavy_after_iteration
                )

        return config


def list_available_models() -> List[ModelInfo]:
    """Liste tous les modèles installés ou présents dans models.json."""
    result_by_name: Dict[str, ModelInfo] = {}

    for entry in get_all_ollama_models():
        info = _model_info_from_library_entry(entry)
        if info:
            result_by_name[info.name] = info

    for runtime_name in get_ollama_runtime_model_names():
        normalized_name = _normalize_model_name(runtime_name)
        if not normalized_name or normalized_name in result_by_name:
            continue
        if normalized_name in KNOWN_MODELS:
            result_by_name[normalized_name] = KNOWN_MODELS[normalized_name]
            continue
        result_by_name[normalized_name] = ModelInfo(
            name=normalized_name,
            category=ModelCategory.MEDIUM,
            description=f"Modele {normalized_name} (runtime Ollama detecte localement)",
            recommended_for=["analyst", "strategist"],
        )

    data = _fetch_ollama_tags_with_retries()
    if data:
        models = data.get("models", [])
        for m in models:
            name = _normalize_model_name(m.get("name", ""))
            if not name:
                continue
            if name in KNOWN_MODELS:
                result_by_name[name] = KNOWN_MODELS[name]
                continue
            if name in result_by_name:
                continue

            size_gb = m.get("size", 0) / (1024**3)
            category = _infer_category_from_size(size_gb)
            result_by_name[name] = ModelInfo(
                name=name,
                category=category,
                description=f"Modele {name} ({size_gb:.1f} GB)",
                recommended_for=["analyst", "strategist"],
            )

    for model_name in list_cloud_only_model_names():
        info = KNOWN_MODELS.get(model_name)
        if info is not None:
            result_by_name.setdefault(model_name, info)

    if not result_by_name:
        # Fallback: retourner les modèles connus (utile pour l'UI quand Ollama est lent)
        return list(KNOWN_MODELS.values())

    return sorted(result_by_name.values(), key=lambda info: info.name)


def get_models_by_category(category: ModelCategory) -> List[ModelInfo]:
    """Retourne les modèles installés d'une catégorie."""
    all_models = list_available_models()
    return [m for m in all_models if m.category == category]


# Singleton pour la configuration globale
_global_config: Optional[RoleModelConfig] = None


def get_global_model_config() -> RoleModelConfig:
    """Retourne la configuration globale (singleton)."""
    global _global_config
    if _global_config is None:
        _global_config = RoleModelConfig()
    return _global_config


def set_global_model_config(config: RoleModelConfig) -> None:
    """Définit la configuration globale."""
    global _global_config
    _global_config = config


__all__ = [
    "ModelCategory",
    "ModelInfo",
    "RoleModelAssignment",
    "RoleModelConfig",
    "KNOWN_MODELS",
    "MAX_AUTO_SELECT_PARAMS_B",
    "is_cloud_only_model",
    "list_cloud_only_model_names",
    "list_available_models",
    "get_models_by_category",
    "get_global_model_config",
    "set_global_model_config",
]
