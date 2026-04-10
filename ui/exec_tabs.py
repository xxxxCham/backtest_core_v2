"""Module-ID: ui.exec_tabs — Tabs mode d'exécution (pilot v0)

Ce module rend les onglets de sélection du mode d'exécution dans la page
principale (hors sidebar). Il est appelé depuis app.py après
render_setup_previews() et avant render_main().
"""
from __future__ import annotations

import html
import json
import os
import subprocess
from typing import Any, Dict, List

import logging
import re

import streamlit as st

logger = logging.getLogger(__name__)

from backtest.result_store import get_builder_sessions_dir
from config.market_selection import (
    UNIVERSE_MODE_CANONICAL,
    UNIVERSE_MODE_EXPLORATORY,
)
from agents.llm_config import (
    DEFAULT_LLM_INFERENCE_MODE,
    apply_llm_inference_settings,
    normalize_llm_inference_settings,
    normalize_llm_model_inference_profiles,
    resolve_llm_inference_settings,
)

from agents.llm_router import (
    LLMTopologyConfig,
    build_phase1_topology,
    build_single_host_topology,
    normalize_ollama_host,
)
from ui.constants import MODE_OPTIONS, build_strategy_options
from ui.context import (
    KNOWN_MODELS,
    LLM_AVAILABLE,
    LLM_IMPORT_ERROR,
    LLMConfig,
    LLMProvider,
    ModelCategory,
    RECOMMENDED_FOR_STRATEGY,
    ensure_ollama_running,
    get_global_model_config,
    is_ollama_available,
    list_available_models,
    list_strategies,
    set_global_model_config,
)
from ui.components.model_selector import render_model_selector
from ui.state import (
    BUILDER_UNIVERSE_MODE_CANONICAL,
    BUILDER_EXECUTION_MODE_DUAL_LANE,
    BUILDER_EXECUTION_MODE_EXPERT,
    BUILDER_EXECUTION_MODE_MONO,
    SidebarState,
    normalize_builder_multi_llm_role_pool_overrides,
    resolve_builder_dual_lane_preferences,
    resolve_builder_execution_preferences,
    resolve_builder_flow_analysis_preferences,
    resolve_builder_runtime_preferences,
)
from agents.model_config import list_cloud_only_model_names

try:
    from core.llm_multi import (
        DEFAULT_MULTI_LLM_PROFILE,
        delete_multi_llm_profile,
        discover_local_models,
        get_profile_definition,
        get_profile_role_pools,
        get_user_multi_llm_profiles_dir,
        install_missing_models,
        list_profile_names,
        plan_missing_downloads,
        resolve_profile_assignments,
        save_multi_llm_profile,
    )

    _MULTI_LLM_AVAILABLE = True
except ImportError:
    DEFAULT_MULTI_LLM_PROFILE = "24GB_balanced"
    delete_multi_llm_profile = None
    get_profile_role_pools = None
    get_profile_definition = None
    get_user_multi_llm_profiles_dir = None
    save_multi_llm_profile = None
    _MULTI_LLM_AVAILABLE = False

try:
    from core.llm_multi.roles import (
        MULTI_LLM_ROLE_DETAILS,
        SIMPLE_MULTI_LLM_ACTIVE_ROLES,
    )
except ImportError:
    SIMPLE_MULTI_LLM_ACTIVE_ROLES = (
        "idea_llm",
        "builder_llm",
        "critic_llm",
        "risk_llm",
    )
    MULTI_LLM_ROLE_DETAILS: Dict[str, Dict[str, str]] = {}

_BUILDER_FLOW_ANALYSIS_STEP_LABELS = {
    "code_repair": "Réparation canonique",
    "precheck": "Précheck des signaux",
    "postprocess_logic": "Nettoyage logique",
    "auto_fix_indicators": "Auto-fix indicateurs",
    "runtime_fix": "Correction runtime",
    "deterministic_fallback": "Fallback déterministe",
    "stagnation_branching": "Branching de stagnation",
    "positive_progress_gate": "Garde de progression positive",
    "stop_override": "Override stop",
    "accept_override": "Override accept",
    "params_contract_check": "Contrat de paramètres",
    "indicator_binding": "Bindings d'indicateurs",
    "proposal_sanitize": "Sanitize proposition",
    "prompt_leakage_filter": "Filtre de fuite de prompt",
    "indicator_ranking": "Classement des indicateurs",
    "iteration_history": "Historique d'itérations",
    "diagnostic_context": "Contexte diagnostique",
    "llm_analysis": "Analyse LLM",
}

def _ollama_is_available(ollama_host: str | None = None) -> bool:
    """Retourne l'etat Ollama de maniere defensive si helper optionnel absent."""
    if callable(is_ollama_available):
        try:
            return bool(is_ollama_available(ollama_host=ollama_host))
        except Exception as exc:
            logger.debug("Ollama availability check failed: %s", exc)
            return False
    return False


def _ollama_start_if_needed(
    ollama_host: str | None = None,
    *,
    gpu_target: str | None = None,
) -> tuple[bool, str]:
    """Demarre Ollama via le helper UI quand disponible."""
    if callable(ensure_ollama_running):
        try:
            return ensure_ollama_running(
                ollama_host=ollama_host,
                gpu_target=gpu_target,
            )
        except TypeError:
            return ensure_ollama_running(ollama_host=ollama_host)
        except Exception as exc:
            return False, f"Erreur demarrage Ollama: {exc}"
    return False, "Helper ensure_ollama_running indisponible"


def _prime_multiselect_state(
    key: str,
    *,
    desired: list[str],
    options: list[str],
) -> None:
    valid_desired = [item for item in desired if item in options]
    if key not in st.session_state:
        if valid_desired:
            st.session_state[key] = valid_desired
        return

    current_raw = st.session_state.get(key)
    current = current_raw if isinstance(current_raw, list) else []
    valid_current = [item for item in current if item in options]

    if valid_current != current:
        st.session_state[key] = valid_current


def _normalize_builder_multi_llm_role_overrides(raw_value: Any) -> Dict[str, List[str]]:
    return normalize_builder_multi_llm_role_pool_overrides(raw_value)


def _collect_inference_model_candidates(*groups: Any) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()

    def _push(raw_value: Any) -> None:
        if isinstance(raw_value, str):
            value = raw_value.strip()
            if value and value not in seen:
                seen.add(value)
                ordered.append(value)
            return
        if isinstance(raw_value, dict):
            for nested in raw_value.values():
                _push(nested)
            return
        if isinstance(raw_value, (list, tuple, set)):
            for nested in raw_value:
                _push(nested)

    for group in groups:
        _push(group)
    return ordered


def _format_inference_settings_caption(settings: Dict[str, Any]) -> str:
    num_ctx = settings.get("num_ctx")
    ctx_label = str(num_ctx) if num_ctx is not None else "auto"
    return (
        f"temp={settings['temperature']:.2f} | "
        f"ctx={ctx_label} | max_tokens={int(settings['max_tokens'])}"
    )


def _render_llm_inference_settings_editor(
    *,
    active_models: List[str],
    section_label: str,
) -> tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    st.markdown(f"##### {section_label}")
    st.caption(
        "Réglages Ollama partagés: température, num_ctx et max tokens. "
        "Les overrides par modèle prennent la priorité sur le global."
    )

    inference_mode = str(
        st.radio(
            "Portée des réglages",
            options=["global", "per_model"],
            index=0
            if str(
                st.session_state.get("llm_inference_mode", DEFAULT_LLM_INFERENCE_MODE)
                or DEFAULT_LLM_INFERENCE_MODE
            )
            == "global"
            else 1,
            format_func=lambda value: (
                "Global uniquement"
                if value == "global"
                else "Global + override par modèle"
            ),
            horizontal=True,
        )
        or DEFAULT_LLM_INFERENCE_MODE
    ).strip() or DEFAULT_LLM_INFERENCE_MODE
    st.session_state["llm_inference_mode"] = inference_mode

    current_global = normalize_llm_inference_settings(
        st.session_state.get("llm_inference_global_settings")
    )
    global_col1, global_col2, global_col3 = st.columns(3)
    with global_col1:
        global_temperature = st.slider(
            "Température globale",
            min_value=0.0,
            max_value=2.0,
            value=float(current_global["temperature"]),
            step=0.05,
            help="Valeur par défaut pour les requêtes Ollama si aucun profil modèle ne la remplace.",
        )
    with global_col2:
        global_num_ctx = int(
            st.number_input(
                "Contexte global (0 = auto)",
                min_value=0,
                max_value=262144,
                value=int(current_global["num_ctx"] or 0),
                step=1024,
                help="0 laisse Ollama utiliser le contexte par défaut du modèle.",
            )
        )
    with global_col3:
        global_max_tokens = int(
            st.number_input(
                "Max tokens global",
                min_value=64,
                max_value=32768,
                value=int(current_global["max_tokens"]),
                step=128,
                help="Cap par défaut des tokens générés si aucun appel ne le surcharge explicitement.",
            )
        )

    global_settings = normalize_llm_inference_settings(
        {
            "temperature": global_temperature,
            "num_ctx": global_num_ctx,
            "max_tokens": global_max_tokens,
        }
    )
    st.session_state["llm_inference_global_settings"] = dict(global_settings)

    model_profiles = normalize_llm_model_inference_profiles(
        st.session_state.get("llm_inference_model_profiles")
    )
    model_options = _collect_inference_model_candidates(active_models, model_profiles)

    if inference_mode == "per_model":
        if not model_options:
            st.info("Aucun modèle disponible pour éditer un override spécifique.")
        else:
            selected_profile_model = str(
                st.selectbox(
                    "Modèle à surcharger",
                    options=model_options,
                    index=(
                        model_options.index(active_models[0])
                        if active_models and active_models[0] in model_options
                        else 0
                    ),
                    help="L'override de ce modèle prime sur les réglages globaux.",
                )
                or model_options[0]
            ).strip()
            profile_defaults = resolve_llm_inference_settings(
                selected_profile_model,
                global_settings=global_settings,
                model_profiles=model_profiles,
            )
            has_override = selected_profile_model in model_profiles
            with st.form("llm_inference_model_profile_form"):
                profile_col1, profile_col2, profile_col3 = st.columns(3)
                with profile_col1:
                    profile_temperature = st.slider(
                        "Température modèle",
                        min_value=0.0,
                        max_value=2.0,
                        value=float(profile_defaults["temperature"]),
                        step=0.05,
                    )
                with profile_col2:
                    profile_num_ctx = int(
                        st.number_input(
                            "Contexte modèle (0 = auto)",
                            min_value=0,
                            max_value=262144,
                            value=int(profile_defaults["num_ctx"] or 0),
                            step=1024,
                        )
                    )
                with profile_col3:
                    profile_max_tokens = int(
                        st.number_input(
                            "Max tokens modèle",
                            min_value=64,
                            max_value=32768,
                            value=int(profile_defaults["max_tokens"]),
                            step=128,
                        )
                    )
                save_col, reset_col = st.columns(2)
                with save_col:
                    save_override = st.form_submit_button(
                        "Enregistrer l'override",
                        use_container_width=True,
                    )
                with reset_col:
                    remove_override = st.form_submit_button(
                        "Supprimer l'override",
                        type="secondary",
                        use_container_width=True,
                        disabled=not has_override,
                    )

            if save_override:
                model_profiles[selected_profile_model] = normalize_llm_inference_settings(
                    {
                        "temperature": profile_temperature,
                        "num_ctx": profile_num_ctx,
                        "max_tokens": profile_max_tokens,
                    },
                    defaults=global_settings,
                )
                st.session_state["llm_inference_model_profiles"] = dict(model_profiles)
                st.success(f"Override enregistré pour {selected_profile_model}.")
            elif remove_override and selected_profile_model in model_profiles:
                model_profiles.pop(selected_profile_model, None)
                st.session_state["llm_inference_model_profiles"] = dict(model_profiles)
                st.info(f"Override supprimé pour {selected_profile_model}.")

    model_profiles = normalize_llm_model_inference_profiles(
        st.session_state.get("llm_inference_model_profiles")
    )
    st.session_state["llm_inference_model_profiles"] = dict(model_profiles)

    if active_models:
        st.caption("Réglages effectifs des modèles actifs:")
        for model_name in active_models[:6]:
            effective = resolve_llm_inference_settings(
                model_name,
                global_settings=global_settings,
                model_profiles=model_profiles,
            )
            st.caption(
                f"• {model_name}: {_format_inference_settings_caption(effective)}"
            )

    return global_settings, model_profiles


def _available_runtime_role_models(inventory: Any, role: str) -> List[str]:
    candidates = []
    for model in list(getattr(inventory, "discovered_models", []) or []):
        if not bool(getattr(model, "verified_available", False)):
            continue
        if str(getattr(model, "backend", "") or "").strip() != "ollama":
            continue
        if bool(getattr(inventory, "live_ollama_reachable", False)) and not bool(
            getattr(model, "live", False)
        ):
            continue
        candidates.append(model)

    candidates.sort(
        key=lambda model: (
            0 if role in list(getattr(model, "role_hints", []) or []) else 1,
            0 if bool(getattr(model, "live", False)) else 1,
            str(getattr(model, "name", "") or "").lower(),
        )
    )
    ordered: List[str] = []
    seen: set[str] = set()
    for model in candidates:
        name = str(getattr(model, "name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)

    recommended_tags = {
        "idea_llm": {"analyst", "strategist"},
        "builder_llm": {"strategist"},
        "critic_llm": {"critic", "validator"},
        "risk_llm": {"critic", "validator"},
    }.get(str(role or "").strip(), set())
    cloud_models = sorted(
        list_cloud_only_model_names(),
        key=lambda name: (
            0
            if recommended_tags
            and bool(
                set(getattr(KNOWN_MODELS.get(name), "recommended_for", []) or [])
                & recommended_tags
            )
            else 1,
            name,
        ),
    )
    for name in cloud_models:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _sync_builder_multi_llm_profile_role_pools(
    selected_profile: str,
) -> Dict[str, List[str]]:
    """Synchronise les pools du profil avec les overrides actuels.

    Règles:
    - Premier chargement (profil jamais appliqué) → charge intégralement les pools du profil.
    - Changement de profil → recharge intégralement les pools du nouveau profil.
    - Même profil → conserve les sélections manuelles actuelles; remplit uniquement
      les rôles dont le widget n'a JAMAIS été rendu (jamais dans session_state).
    """
    applied_profile = str(
        st.session_state.get("_builder_multi_llm_applied_profile", "") or ""
    ).strip()
    applied_signature = str(
        st.session_state.get("_builder_multi_llm_applied_profile_signature", "") or ""
    ).strip()

    profile_role_pools: Dict[str, List[str]] = {}
    if callable(get_profile_role_pools):
        try:
            profile_role_pools = _normalize_builder_multi_llm_role_overrides(
                get_profile_role_pools(selected_profile)
            )
        except Exception as exc:
            logger.warning("Failed to load profile role pools for %r: %s", selected_profile, exc)
            profile_role_pools = {}

    profile_signature_payload: Dict[str, Any] = {
        "profile": selected_profile,
        "pools": profile_role_pools,
    }
    if callable(get_profile_definition):
        try:
            profile_definition = dict(get_profile_definition(selected_profile) or {})
        except Exception as exc:
            logger.warning(
                "Failed to load profile definition for %r: %s",
                selected_profile,
                exc,
            )
            profile_definition = {}
        for field_name in ("updated_at", "created_at", "derived_from"):
            field_value = str(profile_definition.get(field_name, "") or "").strip()
            if field_value:
                profile_signature_payload[field_name] = field_value
    try:
        profile_signature = json.dumps(
            profile_signature_payload,
            sort_keys=True,
            ensure_ascii=True,
        )
    except Exception:
        profile_signature = selected_profile

    first_load = not applied_profile
    profile_changed = bool(applied_profile) and applied_profile != selected_profile
    profile_updated = (
        bool(applied_profile)
        and applied_profile == selected_profile
        and bool(profile_signature)
        and profile_signature != applied_signature
    )

    if first_load or profile_changed or profile_updated:
        # Chargement intégral : remplace tout par les pools du profil.
        current_role_overrides = dict(profile_role_pools)
        if current_role_overrides:
            st.session_state["builder_multi_llm_role_overrides"] = dict(
                current_role_overrides
            )
            for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
                st.session_state[
                    f"builder_multi_llm_role_override_select_{role}"
                ] = list(current_role_overrides.get(role, []))
        else:
            # Profil sans pools -> vider les overrides
            st.session_state["builder_multi_llm_role_overrides"] = {}
            for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
                st.session_state[
                    f"builder_multi_llm_role_override_select_{role}"
                ] = []
    else:
        # Même profil : respecter les sélections manuelles actuelles.
        current_role_overrides = _normalize_builder_multi_llm_role_overrides(
            st.session_state.get("builder_multi_llm_role_overrides", {})
        )
        # Remplir UNIQUEMENT les rôles dont le widget n'a jamais été rendu.
        for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
            widget_key = f"builder_multi_llm_role_override_select_{role}"
            if widget_key not in st.session_state and role in profile_role_pools:
                current_role_overrides[role] = list(profile_role_pools[role])
                st.session_state[widget_key] = list(profile_role_pools[role])

    st.session_state["_builder_multi_llm_applied_profile"] = selected_profile
    st.session_state["_builder_multi_llm_applied_profile_signature"] = profile_signature
    return current_role_overrides


def _render_builder_expert_multi_role_section(
    *,
    builder_ollama_host: str,
    builder_topology: LLMTopologyConfig,
    builder_multi_llm_profile: str,
) -> tuple[str, Dict[str, List[str]]]:
    pending_profile_sync = str(
        st.session_state.pop("_builder_multi_llm_profile_sync", "") or ""
    ).strip()
    if pending_profile_sync:
        st.session_state["builder_multi_llm_profile"] = pending_profile_sync
        st.session_state["builder_multi_llm_profile_select"] = pending_profile_sync

    saved_notice = str(
        st.session_state.pop("_builder_multi_llm_profile_saved_notice", "") or ""
    ).strip()
    if saved_notice:
        st.success(saved_notice)
    deleted_notice = str(
        st.session_state.pop("_builder_multi_llm_profile_deleted_notice", "") or ""
    ).strip()
    if deleted_notice:
        st.success(deleted_notice)

    profile_options = list_profile_names() if callable(list_profile_names) else []
    if not profile_options:
        profile_options = [DEFAULT_MULTI_LLM_PROFILE]

    default_profile = str(
        builder_multi_llm_profile or DEFAULT_MULTI_LLM_PROFILE
    ).strip() or DEFAULT_MULTI_LLM_PROFILE
    if default_profile not in profile_options:
        default_profile = profile_options[0]

    selected_profile = st.selectbox(
        "Profil multi-LLM",
        options=profile_options,
        index=profile_options.index(default_profile),
        key="builder_multi_llm_profile_select",
        help=(
            "Profil de référence du Builder Expert. "
            "Les présélections sauvegardées depuis cette section réapparaissent ici."
        ),
    )
    st.session_state["builder_multi_llm_profile"] = selected_profile
    profile_payload = (
        get_profile_definition(selected_profile)
        if callable(get_profile_definition)
        else {}
    )
    is_builtin_profile = bool(profile_payload.get("builtin", True))
    derived_from = str(profile_payload.get("derived_from", "") or "").strip()
    profile_badge = "builtin" if is_builtin_profile else "custom"
    profile_caption_parts = [f"Type: {profile_badge}"]
    if derived_from:
        profile_caption_parts.append(f"Dérivé de: {derived_from}")
    if callable(get_user_multi_llm_profiles_dir):
        profile_caption_parts.append(
            f"Dossier custom: {get_user_multi_llm_profiles_dir()}"
        )
    st.caption(" | ".join(profile_caption_parts))
    current_role_overrides = _sync_builder_multi_llm_profile_role_pools(
        selected_profile
    )
    if current_role_overrides:
        st.caption(
            "Présélection chargée: "
            + ", ".join(
                f"{role}={len(models)}"
                for role, models in current_role_overrides.items()
            )
        )

    inventory = discover_local_models(
        ollama_host=builder_ollama_host,
        include_live_ollama=True,
    )
    distinct_runtime_hosts = {
        str(getattr(endpoint, "ollama_host", "") or "").strip()
        for endpoint in builder_topology.endpoints.values()
        if bool(getattr(endpoint, "enabled", True))
    }
    require_live_ollama = bool(
        inventory.live_ollama_reachable and len(distinct_runtime_hosts) <= 1
    )
    default_resolution = resolve_profile_assignments(
        selected_profile,
        inventory,
        require_live_ollama=require_live_ollama,
    )
    default_assignments = {
        assignment.role: assignment
        for assignment in default_resolution["assignments"]
    }
    summary = inventory.summary()
    st.caption(
        f"Inventaire local: {summary['verified_models']} verifies / "
        f"{summary['total_models']} references | "
        f"backends: {summary['by_backend']}"
    )
    if not require_live_ollama:
        st.warning(
            "Validation runtime distante indisponible: affichage basé sur l'inventaire local."
        )
    st.markdown("##### Rôles actifs")
    selected_role_overrides: Dict[str, List[str]] = {}
    for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
        role_detail = MULTI_LLM_ROLE_DETAILS.get(role, {})
        role_models = _available_runtime_role_models(inventory, role)
        current_override_pool = list(current_role_overrides.get(role, []) or [])
        for selected_model in current_override_pool:
            if selected_model not in role_models:
                role_models = [selected_model, *role_models]
        role_models = list(dict.fromkeys(role_models))
        widget_key = f"builder_multi_llm_role_override_select_{role}"
        _prime_multiselect_state(
            widget_key,
            desired=current_override_pool,
            options=role_models,
        )
        default_requested = str(
            getattr(default_assignments.get(role), "requested_model", "") or ""
        )
        selected_models = st.multiselect(
            role,
            options=role_models,
            key=widget_key,
            help=str(role_detail.get("purpose", "") or ""),
        )
        default_requested = str(
            getattr(default_assignments.get(role), "requested_model", "") or ""
        )
        summary_parts: List[str] = []
        # Toujours enregistrer, même si vide ([] préserve le rôle dans le dict
        # et permet à _prime_multiselect_state de le retrouver au prochain rerun).
        selected_role_overrides[role] = list(selected_models)
        if selected_models:
            summary_parts.append(
                "Sélection: " + ", ".join(selected_models)
            )
        else:
            summary_parts.append("Sélection: profil par défaut")
        stage = str(role_detail.get("stage", "") or "").strip()
        purpose = str(role_detail.get("purpose", "") or "").strip()
        if stage or purpose:
            summary_parts.append(" | ".join(part for part in (stage, purpose) if part))
        if default_requested:
            summary_parts.append(f"Profil: {default_requested}")
        st.caption(" • ".join(summary_parts))

    if st.session_state.pop("_builder_multi_llm_close_save_toggle", False):
        st.session_state.pop("builder_multi_llm_save_profile_toggle", None)
    with st.expander("Présélections personnalisées", expanded=False):
        save_toggle = st.toggle(
            "💾 Enregistrer cette présélection",
            value=bool(st.session_state.get("builder_multi_llm_save_profile_toggle", False)),
            key="builder_multi_llm_save_profile_toggle",
            help=(
                "Sauvegarde les choix manuels de cette section comme un profil réutilisable "
                "dans la liste des présélections."
            ),
        )
        if save_toggle:
            suggested_name = str(
                st.session_state.get("builder_multi_llm_save_profile_name", "")
                or f"{selected_profile}_custom"
            ).strip()
            save_profile_name = st.text_input(
                "Nom de la présélection",
                value=suggested_name,
                key="builder_multi_llm_save_profile_name",
                placeholder="Ex: Qwen builder + DeepSeek critique",
            ).strip()
            if st.button(
                "Ajouter aux présélections",
                key="builder_multi_llm_save_profile_button",
                disabled=not (save_profile_name and selected_role_overrides),
            ):
                if not callable(save_multi_llm_profile):
                    st.error("Sauvegarde des profils indisponible dans ce workspace.")
                else:
                    try:
                        already_exists = save_profile_name in profile_options
                        save_multi_llm_profile(
                            save_profile_name,
                            base_profile_name=selected_profile,
                            role_overrides=selected_role_overrides,
                            description=(
                                f"Preset utilisateur derive de {selected_profile} "
                                "via la configuration Expert Multi-Role."
                            ),
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Impossible d'enregistrer la présélection: {exc}")
                    else:
                        st.session_state["_builder_multi_llm_profile_sync"] = (
                            save_profile_name
                        )
                        st.session_state["_builder_multi_llm_profile_saved_notice"] = (
                            (
                                f"Présélection `{save_profile_name}` mise à jour."
                                if already_exists
                                else f"Présélection `{save_profile_name}` ajoutée aux profils multi-LLM."
                            )
                        )
                        st.session_state["_builder_multi_llm_close_save_toggle"] = True
                        st.rerun()
        delete_disabled = is_builtin_profile or not selected_profile.strip()
        delete_help = (
            "Les profils intégrés sont protégés."
            if is_builtin_profile
            else "Supprime la présélection personnalisée active."
        )
        if st.button(
            "Supprimer cette présélection",
            key="builder_multi_llm_delete_profile_button",
            disabled=delete_disabled,
            help=delete_help,
        ):
            if not callable(delete_multi_llm_profile):
                st.error("Suppression des profils indisponible dans ce workspace.")
            else:
                try:
                    deleted = delete_multi_llm_profile(selected_profile)
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Impossible de supprimer la présélection: {exc}")
                else:
                    fallback_profile = DEFAULT_MULTI_LLM_PROFILE
                    if fallback_profile == selected_profile or fallback_profile not in profile_options:
                        fallback_profile = next(
                            (name for name in profile_options if name != selected_profile),
                            DEFAULT_MULTI_LLM_PROFILE,
                        )
                    st.session_state["builder_multi_llm_role_overrides"] = {}
                    for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
                        st.session_state.pop(
                            f"builder_multi_llm_role_override_select_{role}",
                            None,
                        )
                    st.session_state["_builder_multi_llm_profile_sync"] = fallback_profile
                    st.session_state["_builder_multi_llm_profile_deleted_notice"] = (
                        f"Présélection `{selected_profile}` supprimée."
                        if deleted
                        else f"Présélection `{selected_profile}` déjà absente du dossier custom."
                    )
                    st.rerun()

    st.session_state["builder_multi_llm_role_overrides"] = selected_role_overrides
    resolution = resolve_profile_assignments(
        selected_profile,
        inventory,
        role_overrides=selected_role_overrides or None,
        require_live_ollama=require_live_ollama,
    )

    def _resolve_builder_runtime_route(role: str) -> Any:
        if role == "idea_llm":
            return builder_topology.resolve_builder_phase_route(
                "objective_gen",
                fallback_host=builder_ollama_host,
            )
        if role == "builder_llm":
            return builder_topology.resolve_builder_phase_route(
                "code",
                fallback_host=builder_ollama_host,
            )
        if role == "risk_llm":
            return builder_topology.resolve_builder_phase_route(
                "pre_reflection",
                fallback_host=builder_ollama_host,
            )
        return builder_topology.resolve_builder_phase_route(
            "analysis",
            fallback_host=builder_ollama_host,
        )

    role_rows = [
        {
            "role": assignment.role,
            "etape": MULTI_LLM_ROLE_DETAILS.get(assignment.role, {}).get("stage", "-"),
            "fonction": MULTI_LLM_ROLE_DETAILS.get(assignment.role, {}).get("purpose", "-"),
            "host_runtime": _resolve_builder_runtime_route(assignment.role).ollama_host,
            "gpu_cible": _resolve_builder_runtime_route(assignment.role).gpu_target,
            "pool_override": ", ".join(selected_role_overrides.get(assignment.role, [])) or "-",
            "demande": assignment.requested_model,
            "resolu": assignment.resolved_model or "-",
            "pret_runtime": assignment.available,
            "visible_hote": assignment.live if assignment.backend == "ollama" else "-",
            "source": assignment.source or "-",
            "raison": assignment.reason or "-",
        }
        for assignment in resolution["assignments"]
        if assignment.role in SIMPLE_MULTI_LLM_ACTIVE_ROLES
    ]
    unavailable_roles = [
        assignment
        for assignment in resolution["assignments"]
        if assignment.role in SIMPLE_MULTI_LLM_ACTIVE_ROLES
        and not assignment.available
    ]
    missing_requests = plan_missing_downloads(
        selected_profile,
        inventory,
        role_overrides=selected_role_overrides or None,
        require_live_ollama=require_live_ollama,
    )
    host_only_unavailable = [
        assignment.role
        for assignment in unavailable_roles
        if not assignment.install_required
    ]
    if host_only_unavailable:
        st.warning(
            "Roles détectés localement mais non exposés par l'hôte Ollama actif: "
            + ", ".join(host_only_unavailable)
        )
    with st.expander("Diagnostic de résolution", expanded=False):
        st.dataframe(role_rows, width="stretch")
        if missing_requests:
            st.warning(
                "Roles manquants: "
                + ", ".join(request.role for request in missing_requests)
            )
            if st.button(
                "⬇️ Installer les modeles manquants",
                key="builder_multi_llm_install_missing",
                help="Tente un ollama pull pour les roles manquants.",
            ):
                results = install_missing_models(
                    missing_requests,
                    ollama_host=builder_ollama_host,
                )
                st.session_state["builder_multi_llm_install_results"] = [
                    result.to_dict() for result in results
                ]
                if all(result.success for result in results):
                    st.success("Installation terminee.")
                else:
                    st.warning("Installation partielle ou echec sur certains roles.")
        elif not unavailable_roles:
            st.success("Tous les roles du profil sont résolus localement.")

        last_install_results = st.session_state.get(
            "builder_multi_llm_install_results",
            [],
        )
        if last_install_results:
            st.dataframe(last_install_results, width="stretch", hide_index=True)
        _render_builder_runtime_diagnostic_panel()
        with st.expander("Inventaire brut", expanded=False):
            st.json(inventory.to_dict())

    return selected_profile, dict(selected_role_overrides)


def _render_builder_runtime_diagnostic_panel() -> None:
    diagnostic = st.session_state.get("builder_runtime_diagnostic")
    acceptance_probe = st.session_state.get("builder_runtime_acceptance_probe")
    with st.expander("🛰️ Diagnostic runtime inter-modeles", expanded=False):
        if isinstance(acceptance_probe, dict):
            st.markdown("**Validation hôte / modèle exact**")
            probe_message = str(acceptance_probe.get("message", "") or "").strip()
            probe_status = str(acceptance_probe.get("status", "") or "").strip()
            warmup_ok = acceptance_probe.get("warmup_ok")
            if bool(acceptance_probe.get("accepted")) and warmup_ok is False:
                st.warning(probe_message or "Le nom exact est accepté, mais le warmup a échoué.")
            elif bool(acceptance_probe.get("accepted")):
                st.success(probe_message or "Le nom exact est accepté par l'hôte Ollama.")
            elif probe_message:
                st.error(probe_message)

            summary_parts = [
                f"demande=`{acceptance_probe.get('requested_model', '-') or '-'}`",
                f"exact=`{acceptance_probe.get('resolved_model', '-') or '-'}`",
                f"status=`{probe_status or '-'}`",
                f"host=`{acceptance_probe.get('ollama_host', '-') or '-'}`",
            ]
            tags_status = acceptance_probe.get("tags_status_code")
            if tags_status is not None:
                summary_parts.append(f"tags={tags_status}")
            runtime_status = acceptance_probe.get("runtime_status_code")
            if runtime_status is not None:
                summary_parts.append(f"probe={runtime_status}")
            if acceptance_probe.get("present_in_tags") is True:
                summary_parts.append("visible_dans_tags=yes")
            elif acceptance_probe.get("present_in_tags") is False:
                summary_parts.append("visible_dans_tags=no")
            if acceptance_probe.get("cloud_only"):
                summary_parts.append("cloud_only=yes")
            st.caption(" | ".join(summary_parts))

            warmup_detail = str(acceptance_probe.get("warmup_detail", "") or "").strip()
            if warmup_detail:
                st.caption(f"Warmup: {warmup_detail}")
            runtime_error_body = str(acceptance_probe.get("runtime_error_body", "") or "").strip()
            if runtime_error_body:
                st.caption(f"Réponse runtime: {runtime_error_body}")

        if not isinstance(diagnostic, dict):
            st.caption(
                "Aucun snapshot runtime multi-LLM pour l'instant. "
                "Lance une session Builder multi-roles pour voir les switches reellement observes."
            )
            return

        summary_parts = [
            f"profil=`{diagnostic.get('profile_name', '-') or '-'}`",
            f"mode=`{diagnostic.get('mode', '-') or '-'}`",
            f"event=`{diagnostic.get('event', '-') or '-'}`",
            f"phase=`{diagnostic.get('phase', '-') or '-'}`",
            f"iteration={int(diagnostic.get('iteration', 0) or 0)}/{int(diagnostic.get('max_iterations', 0) or 0)}",
        ]
        status = str(diagnostic.get("status", "") or "").strip()
        if status:
            summary_parts.append(f"status=`{status}`")
        updated_at = str(diagnostic.get("updated_at", "") or "").strip()
        if updated_at:
            summary_parts.append(f"maj=`{updated_at}`")
        st.caption(" | ".join(summary_parts))

        objective_preview = str(diagnostic.get("objective_preview", "") or "").strip()
        if objective_preview:
            st.caption(f"Objectif: {objective_preview}")

        host_rows = list(diagnostic.get("host_rows", []) or [])
        if host_rows:
            st.markdown("**Hosts runtime**")
            st.dataframe(host_rows, width="stretch", hide_index=True)

        role_rows = list(diagnostic.get("role_rows", []) or [])
        if role_rows:
            st.markdown("**Routage par role**")
            st.dataframe(role_rows, width="stretch", hide_index=True)

        recent_events = list(diagnostic.get("recent_events", []) or [])
        if recent_events:
            st.markdown("**Derniers evenements observes**")
            st.dataframe(recent_events, width="stretch", hide_index=True)
        else:
            st.caption("Aucun switch inter-modeles enregistre sur la session courante.")


def _topology_session_keys(session_prefix: str) -> Dict[str, str]:
    prefix = str(session_prefix or "exec").strip() or "exec"
    return {
        "control_host": f"{prefix}_llm_topology_control_host",
        "primary_gpu": f"{prefix}_llm_topology_primary_gpu_target",
        "control_gpu": f"{prefix}_llm_topology_control_gpu_target",
        "trace_only": f"{prefix}_llm_topology_trace_only",
    }


LLM_ROUTING_MODE_STANDARD = "single_endpoint"
LLM_ROUTING_MODE_COOPERATIVE = "cooperative_multi_gpu"
LLM_ROUTING_MODE_OPTIONS = [
    LLM_ROUTING_MODE_STANDARD,
    LLM_ROUTING_MODE_COOPERATIVE,
]
LLM_ROUTING_MODE_LABELS = {
    LLM_ROUTING_MODE_STANDARD: "1 endpoint partage",
    LLM_ROUTING_MODE_COOPERATIVE: "Plusieurs endpoints / multi-GPU",
}
LLM_ROUTING_MODE_HELP = {
    LLM_ROUTING_MODE_STANDARD: (
        "Conserve un seul endpoint Ollama pour toutes les phases et tous les roles. "
        "Ce reglage ne change pas le nombre de roles LLM."
    ),
    LLM_ROUTING_MODE_COOPERATIVE: (
        "Separe les endpoints productifs et de controle, avec cibles GPU distinctes. "
        "Ce reglage concerne le routage des hosts, pas l'orchestration multi-roles."
    ),
}


def _normalize_llm_routing_mode(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if value in LLM_ROUTING_MODE_OPTIONS:
        return value
    return LLM_ROUTING_MODE_STANDARD


def _current_llm_routing_mode(session_key: str = "exec_llm_routing_mode") -> str:
    return _normalize_llm_routing_mode(
        st.session_state.get(session_key, LLM_ROUTING_MODE_STANDARD)
    )


def _render_global_llm_routing_mode_control(
    *,
    scope_label: str,
    session_key: str,
) -> None:
    st.markdown("#### Topologie des Endpoints LLM")
    st.caption(
        f"Reglage partage pour `{scope_label}`. "
        "Il pilote la repartition des phases/roles entre endpoints Ollama."
    )
    st.radio(
        "Topologie de routage",
        options=LLM_ROUTING_MODE_OPTIONS,
        index=LLM_ROUTING_MODE_OPTIONS.index(_current_llm_routing_mode(session_key)),
        format_func=lambda mode: LLM_ROUTING_MODE_LABELS.get(mode, mode),
        key=session_key,
        horizontal=True,
    )
    st.caption(LLM_ROUTING_MODE_HELP.get(_current_llm_routing_mode(session_key), ""))


def _render_topology_runtime_status(
    *,
    topology: LLMTopologyConfig,
    routing_mode: str,
    session_prefix: str,
) -> None:
    summary = _summarize_topology_runtime_status(
        topology=topology,
        routing_mode=routing_mode,
    )
    primary_host = summary["primary_host"]
    control_host = summary["control_host"]
    primary_gpu = summary["primary_gpu"]
    control_gpu = summary["control_gpu"]

    st.markdown("**Etat runtime des endpoints**")

    if summary["show_single_endpoint"]:
        primary_available = _ollama_is_available(primary_host)
        status = "🟢" if primary_available else "🔴"
        st.caption(f"{status} Endpoint unique")
        st.code(f"{primary_host}\nGPU cible: {primary_gpu}")
        if not primary_available and primary_host.startswith("http://127.0.0.1"):
            if st.button(
                "🚀 Demarrer endpoint",
                key=f"{session_prefix}_start_primary_endpoint",
            ):
                success, msg = _ollama_start_if_needed(
                    primary_host,
                    gpu_target=primary_gpu,
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            if primary_gpu != control_gpu:
                st.caption(
                    "GPU secondaire demande: "
                    f"`{control_gpu}` (non effectif tant que principal et critique "
                    "partagent le meme host/port)."
                )
            else:
                st.caption(
                    "Les routes principales et critiques pointent actuellement "
                    "sur ce meme endpoint."
                )
            st.warning(
                "Multi-GPU non effectif ici: pour separer reellement les charges "
                "entre GPUs, il faut deux endpoints Ollama distincts "
                "(meme IP possible, mais ports differents)."
            )
        else:
            st.caption(
                "Mode standard: toutes les phases et tous les roles utilisent "
                "cet endpoint unique."
            )
        return

    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    primary_host = normalize_ollama_host(getattr(primary_endpoint, "ollama_host", ""))
    control_host = normalize_ollama_host(getattr(control_endpoint, "ollama_host", primary_host))
    primary_gpu = str(getattr(primary_endpoint, "gpu_target", "") or "GPU-0")
    control_gpu = str(getattr(control_endpoint, "gpu_target", "") or primary_gpu)

    col_a, col_b = st.columns(2)
    with col_a:
        primary_available = _ollama_is_available(primary_host)
        status = "🟢" if primary_available else "🔴"
        st.caption(f"{status} Endpoint principal")
        st.code(f"{primary_host}\nGPU cible: {primary_gpu}")
        if not primary_available and primary_host.startswith("http://127.0.0.1"):
            if st.button(
                "🚀 Demarrer principal",
                key=f"{session_prefix}_start_primary_endpoint",
            ):
                success, msg = _ollama_start_if_needed(
                    primary_host,
                    gpu_target=primary_gpu,
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    with col_b:
        control_available = _ollama_is_available(control_host)
        status = "🟢" if control_available else "🔴"
        st.caption(f"{status} Endpoint critique")
        st.code(f"{control_host}\nGPU cible: {control_gpu}")
        if not control_available and control_host.startswith("http://127.0.0.1"):
            if st.button(
                "🚀 Demarrer critique",
                key=f"{session_prefix}_start_control_endpoint",
            ):
                success, msg = _ollama_start_if_needed(
                    control_host,
                    gpu_target=control_gpu,
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    if not (_ollama_is_available(primary_host) and _ollama_is_available(control_host)):
        st.warning(
            "Le mode multi-endpoint exige deux endpoints Ollama actifs. "
            "Tant qu'un host manque, les roles ne pourront pas se repartir proprement."
        )
    else:
        st.caption(
            "Deux endpoints distincts sont detectes. Le mode multi-endpoint peut repartir "
            "proposal/code sur le principal et analysis/pre_reflection sur le critique."
        )


def _summarize_topology_runtime_status(
    *,
    topology: LLMTopologyConfig,
    routing_mode: str,
) -> Dict[str, Any]:
    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    primary_host = normalize_ollama_host(getattr(primary_endpoint, "ollama_host", ""))
    control_host = normalize_ollama_host(getattr(control_endpoint, "ollama_host", primary_host))
    primary_gpu = str(getattr(primary_endpoint, "gpu_target", "") or "GPU-0")
    control_gpu = str(getattr(control_endpoint, "gpu_target", "") or primary_gpu)
    cooperative = routing_mode == LLM_ROUTING_MODE_COOPERATIVE
    shared_endpoint = primary_host == control_host
    return {
        "primary_host": primary_host,
        "control_host": control_host,
        "primary_gpu": primary_gpu,
        "control_gpu": control_gpu,
        "cooperative": cooperative,
        "shared_endpoint": shared_endpoint,
        "show_single_endpoint": (not cooperative) or shared_endpoint,
        "split_effective": cooperative and not shared_endpoint,
    }


@st.cache_data(show_spinner=False, ttl=60)
def _discover_gpu_inventory() -> List[Dict[str, Any]]:
    inventory: List[Dict[str, Any]] = []
    if os.name == "nt":
        try:
            cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            raw = str(result.stdout or "").strip()
            if raw:
                payload = json.loads(raw)
                records = payload if isinstance(payload, list) else [payload]
                for index, record in enumerate(records):
                    item = record or {}
                    name = str(item.get("Name", "") or "").strip()
                    try:
                        memory_bytes = int(item.get("AdapterRAM") or 0)
                    except (TypeError, ValueError):
                        memory_bytes = 0
                    inventory.append(
                        {
                            "id": f"GPU-{index}",
                            "name": name or f"GPU {index}",
                            "memory_bytes": memory_bytes,
                        }
                    )
        except Exception as exc:
            logger.debug("pynvml GPU inventory failed: %s", exc)
    if inventory:
        return inventory

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in str(result.stdout or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                gpu_index = int(parts[0])
                memory_bytes = int(parts[2]) * 1024 * 1024
            except (TypeError, ValueError):
                continue
            inventory.append(
                {
                    "id": f"GPU-{gpu_index}",
                    "name": parts[1] or f"GPU {gpu_index}",
                    "memory_bytes": memory_bytes,
                }
            )
    except Exception as exc:
        logger.debug("nvidia-smi GPU inventory failed: %s", exc)
        return []

    return inventory


def _gpu_rank(item: Dict[str, Any]) -> tuple[int, int, int]:
    name = str(item.get("name", "") or "").lower()
    memory_bytes = int(item.get("memory_bytes") or 0)
    model_score = 0
    match = re.search(r"(?:rtx|gtx|rx)\s*(\d{3,4})", name)
    if match:
        try:
            model_score = int(match.group(1))
        except (TypeError, ValueError):
            model_score = 0
    if any(token in name for token in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
        vendor_rank = 3
    elif any(token in name for token in ("radeon rx", "intel arc")):
        vendor_rank = 2
    elif "graphics" in name or "vega" in name or "uhd" in name or "iris" in name:
        vendor_rank = 0
    else:
        vendor_rank = 1
    return vendor_rank, model_score, memory_bytes


def _format_gpu_option_label(item: Dict[str, Any]) -> str:
    memory_bytes = int(item.get("memory_bytes") or 0)
    memory_gib = memory_bytes / float(1024**3) if memory_bytes > 0 else 0.0
    memory_suffix = f" ({memory_gib:.1f} GiB)" if memory_gib > 0 else ""
    return f"{item['id']} · {item['name']}{memory_suffix}"


def _recommended_gpu_targets() -> tuple[str, str]:
    inventory = _discover_gpu_inventory()
    if not inventory:
        return "GPU-0", "GPU-1"
    ranked = sorted(inventory, key=_gpu_rank, reverse=True)
    primary = str(ranked[0].get("id", "GPU-0") or "GPU-0")
    control = (
        str(ranked[1].get("id", primary) or primary)
        if len(ranked) > 1
        else primary
    )
    return primary, control


def _is_generic_gpu_target(value: str) -> bool:
    normalized = str(value or "").strip()
    return normalized in {"", "auto", "GPU-0", "GPU-1"}


def _render_gpu_target_selector(
    *,
    label: str,
    key: str,
    default_value: str,
    help_text: str,
) -> str:
    inventory = _discover_gpu_inventory()
    option_map = {
        str(item.get("id", "")): _format_gpu_option_label(item)
        for item in inventory
        if str(item.get("id", "")).strip()
    }
    options = list(option_map.keys())
    fallback_value = str(default_value or "").strip() or (options[0] if options else "GPU-0")
    if fallback_value not in option_map:
        option_map[fallback_value] = fallback_value
        options.insert(0, fallback_value)
    current_value = str(st.session_state.get(key, fallback_value) or fallback_value).strip()
    if current_value not in option_map:
        option_map[current_value] = current_value
        options.insert(0, current_value)
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = current_value if current_value in options else fallback_value
    if options:
        selected = st.selectbox(
            label,
            options,
            key=key,
            format_func=lambda value: option_map.get(value, value),
            help=help_text,
        )
        return str(selected or fallback_value)
    return st.text_input(
        label,
        value=fallback_value,
        key=key,
        help=help_text,
    ).strip()


def _get_phase1_topology_from_session(
    primary_host: str,
    *,
    session_prefix: str,
    config_state_key: str,
    routing_mode_key: str,
) -> LLMTopologyConfig:
    keys = _topology_session_keys(session_prefix)
    data = st.session_state.get(config_state_key)
    has_persisted_topology = isinstance(data, (LLMTopologyConfig, dict))
    if isinstance(data, LLMTopologyConfig):
        topology = data
    elif isinstance(data, dict):
        topology = LLMTopologyConfig.from_dict(data)
    else:
        topology = build_phase1_topology(primary_host=primary_host)

    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    recommended_primary_gpu, recommended_control_gpu = _recommended_gpu_targets()

    primary_default = str(getattr(primary_endpoint, "gpu_target", "") or "").strip()
    if (
        not has_persisted_topology
        and
        keys["primary_gpu"] not in st.session_state
        and _is_generic_gpu_target(primary_default)
    ):
        primary_default = recommended_primary_gpu
    control_default = str(getattr(control_endpoint, "gpu_target", "") or "").strip()
    if (
        not has_persisted_topology
        and
        keys["control_gpu"] not in st.session_state
        and _is_generic_gpu_target(control_default)
    ):
        control_default = recommended_control_gpu

    control_host = str(
        st.session_state.get(
            keys["control_host"],
            getattr(control_endpoint, "ollama_host", primary_host),
        )
        or primary_host
    ).strip()
    primary_gpu = str(
        st.session_state.get(
            keys["primary_gpu"],
            primary_default or recommended_primary_gpu,
        )
        or recommended_primary_gpu
    ).strip()
    control_gpu = str(
        st.session_state.get(
            keys["control_gpu"],
            control_default or recommended_control_gpu,
        )
        or recommended_control_gpu
    ).strip()
    trace_only = bool(
        st.session_state.get(
            keys["trace_only"],
            getattr(topology, "trace_only", True),
        )
    )

    if _current_llm_routing_mode(routing_mode_key) == LLM_ROUTING_MODE_COOPERATIVE:
        return build_phase1_topology(
            primary_host=primary_host,
            control_host=control_host,
            primary_gpu_target=primary_gpu or recommended_primary_gpu,
            control_gpu_target=control_gpu or recommended_control_gpu,
            trace_only=trace_only,
        )
    return build_single_host_topology(
        primary_host=primary_host,
        primary_gpu_target=primary_gpu or recommended_primary_gpu,
        trace_only=trace_only,
    )


def _render_phase1_topology_editor(
    *,
    primary_host: str,
    primary_label: str,
    session_prefix: str,
    config_state_key: str,
    routing_mode_key: str,
) -> LLMTopologyConfig:
    keys = _topology_session_keys(session_prefix)
    topology = _get_phase1_topology_from_session(
        primary_host,
        session_prefix=session_prefix,
        config_state_key=config_state_key,
        routing_mode_key=routing_mode_key,
    )
    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    routing_mode = _current_llm_routing_mode(routing_mode_key)

    with st.expander("🧭 Topologie multi-host (Phase 1)", expanded=False):
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.caption(
                "Phase 1: séparation des endpoints productif et de contrôle avec "
                "preuve d'exécution, sans changer la logique métier."
            )
        else:
            st.caption(
                "Mode standard: toutes les phases et tous les rôles reviennent "
                "sur le même endpoint Ollama."
            )
        st.caption(f"{primary_label}: `{primary_host}`")
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.text_input(
                "Endpoint contrôle / critique",
                value=str(
                    st.session_state.get(
                        keys["control_host"],
                        getattr(control_endpoint, "ollama_host", primary_host),
                    )
                ),
                key=keys["control_host"],
                help=(
                    "Endpoint Ollama dédié aux rôles de contrôle "
                    "(critic/validator/analysis)."
                ),
            )

        col_gpu_a, col_gpu_b = st.columns(2)
        with col_gpu_a:
            _render_gpu_target_selector(
                label="GPU cible productif",
                key=keys["primary_gpu"],
                default_value=str(getattr(primary_endpoint, "gpu_target", "") or ""),
                help_text="GPU visé pour l'endpoint productif.",
            )
        with col_gpu_b:
            if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
                _render_gpu_target_selector(
                    label="GPU cible contrôle",
                    key=keys["control_gpu"],
                    default_value=str(getattr(control_endpoint, "gpu_target", "") or ""),
                    help_text="GPU visé pour l'endpoint de contrôle.",
                )
            else:
                st.caption("GPU cible critique")
                st.caption("Non utilisée en mode standard (endpoint unique).")

        st.toggle(
            "Mode trace-only",
            value=bool(
                st.session_state.get(
                    keys["trace_only"],
                    getattr(topology, "trace_only", True),
                )
            ),
            key=keys["trace_only"],
            help=(
                "Active l'observabilité/routage de phase 1 sans introduire de "
                "nouvelles décisions parallèles."
            ),
        )
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.caption("Routage phase 1 par défaut:")
            st.caption("- Builder proposal/code -> endpoint productif")
            st.caption("- Builder analysis/pre_reflection -> endpoint contrôle")
            st.caption("- Orchestrateur analyst/strategist -> endpoint productif")
            st.caption("- Orchestrateur critic/validator -> endpoint contrôle")
        else:
            st.caption("Routage standard:")
            st.caption("- Tous les rôles et phases -> endpoint productif unique")

    topology = _get_phase1_topology_from_session(
        primary_host,
        session_prefix=session_prefix,
        config_state_key=config_state_key,
        routing_mode_key=routing_mode_key,
    )
    st.session_state[config_state_key] = topology.to_dict()
    _render_topology_runtime_status(
        topology=topology,
        routing_mode=routing_mode,
        session_prefix=session_prefix,
    )
    return topology


# ── Clés session_state exposées aux onglets (lues ensuite par sidebar.py) ──
EXEC_GRID_USE_OPTUNA = "exec_grid_use_optuna"
EXEC_GRID_N_TRIALS = "exec_grid_n_trials"
EXEC_GRID_SAMPLER = "exec_grid_sampler"
EXEC_GRID_METRIC = "exec_grid_metric"
EXEC_GRID_PRUNING = "exec_grid_pruning"
EXEC_GRID_EARLY_STOP = "exec_grid_early_stop"

BUILDER_EXECUTION_MODE_LABELS = {
    BUILDER_EXECUTION_MODE_MONO: "Mono",
    BUILDER_EXECUTION_MODE_EXPERT: "Expert Multi-Role",
    BUILDER_EXECUTION_MODE_DUAL_LANE: "Dual Lane Multi-GPU",
}
BUILDER_EXECUTION_MODE_HELP = {
    BUILDER_EXECUTION_MODE_MONO: (
        "1 seul LLM, 1 seul endpoint Ollama, aucun role specialise."
    ),
    BUILDER_EXECUTION_MODE_EXPERT: (
        "4 roles logiques (`idea`, `builder`, `critic`, `risk`) avec "
        "4 modeles configurables sur un endpoint unique."
    ),
    BUILDER_EXECUTION_MODE_DUAL_LANE: (
        "2 LLM seulement, chacun sur son endpoint/GPU, couvrant ensemble tous "
        "les roles du mode Expert."
    ),
}


BUILDER_CONFIG_CSS = """
<style>
.bc-builder-config-strip {
    margin: 0.15rem 0 0.9rem 0;
    padding: 0.55rem 0 0.75rem 0;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}
.bc-builder-config-strip-title {
    font-size: 1rem;
    font-weight: 700;
    color: #e8eef7;
    margin-bottom: 0.25rem;
}
.bc-builder-config-strip-subtitle {
    color: #9fb2c8;
    font-size: 0.93rem;
    line-height: 1.45;
}
.bc-inline-field-label {
    display: inline-flex;
    align-items: center;
    gap: 0.38rem;
    margin: 0 0 0.4rem 0;
    color: #dbe7f6;
    font-size: 0.94rem;
    font-weight: 600;
    line-height: 1.2;
}
.bc-inline-help-trigger {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1rem;
    height: 1rem;
    border-radius: 999px;
    border: 1px solid rgba(148, 163, 184, 0.45);
    background: rgba(15, 23, 42, 0.92);
    color: #cfe0f8;
    font-size: 0.68rem;
    font-weight: 700;
    cursor: help;
    user-select: none;
}
.bc-inline-help-tooltip {
    position: absolute;
    top: calc(100% + 0.3rem);
    left: 50%;
    transform: translateX(-50%);
    width: min(18rem, 38vw);
    padding: 0.34rem 0.5rem;
    border-radius: 8px;
    background: rgba(8, 15, 29, 0.97);
    border: 1px solid rgba(96, 165, 250, 0.24);
    box-shadow: 0 10px 24px rgba(2, 8, 23, 0.28);
    color: #c7d6eb;
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1.35;
    letter-spacing: 0.01em;
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    z-index: 30;
    transition: opacity 120ms ease, visibility 120ms ease;
}
.bc-inline-help-trigger:hover .bc-inline-help-tooltip,
.bc-inline-help-trigger:focus-visible .bc-inline-help-tooltip {
    opacity: 1;
    visibility: visible;
}
</style>
"""


def _inject_builder_config_styles() -> None:
    st.markdown(BUILDER_CONFIG_CSS, unsafe_allow_html=True)


def _render_builder_config_hero() -> None:
    st.markdown(
        """
<div class="bc-builder-config-strip">
    <div class="bc-builder-config-strip-title">Builder Workspace</div>
    <div class="bc-builder-config-strip-subtitle">Architecture, mission, modèles, puis paramètres. Les diagnostics avancés restent disponibles mais ne structurent plus l'écran.</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_inline_help_label(label: str, help_text: str) -> None:
    safe_label = html.escape(label)
    safe_help_text = html.escape(help_text)
    st.markdown(
        f"""
<div class="bc-inline-field-label">
    <span>{safe_label}</span>
    <span class="bc-inline-help-trigger" tabindex="0" aria-label="Aide: {safe_label}">
        ?
        <span class="bc-inline-help-tooltip">{safe_help_text}</span>
    </span>
</div>
""",
        unsafe_allow_html=True,
    )


def _init_exec_tabs_state() -> None:
    """Initialisation idempotente — sûre à appeler à chaque rerun."""
    defaults: dict = {
        "optimization_mode": "Grille de Paramètres",
        "grid_worker_threads": 1,
        "exec_llm_routing_mode": LLM_ROUTING_MODE_STANDARD,
        "builder_llm_routing_mode": LLM_ROUTING_MODE_STANDARD,
        EXEC_GRID_USE_OPTUNA: False,
        EXEC_GRID_N_TRIALS: 200,
        EXEC_GRID_SAMPLER: "tpe",
        EXEC_GRID_METRIC: "sharpe_ratio",
        EXEC_GRID_PRUNING: True,
        EXEC_GRID_EARLY_STOP: 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Commit B — Onglet Backtest Simple
# ─────────────────────────────────────────────────────────────────────────────

def _render_backtest_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Backtest Simple."""
    st.markdown("#### 📊 Backtest Simple")
    st.caption("Teste **1 combinaison** de paramètres — résultat immédiat, idéal pour valider une hypothèse.")

    if state.strategy_key:
        col1, col2, col3 = st.columns(3)
        col1.metric("Stratégie", state.strategy_key)
        col2.metric("Symbole", state.symbol or "—")
        col3.metric("Timeframe", state.timeframe or "—")

        with st.expander("Paramètres appliqués", expanded=False):
            st.json(state.params)

        if state.use_walk_forward:
            st.info(f"🔬 Walk-Forward actif — {state.wfa_n_folds} folds, train {state.wfa_train_ratio:.0%}")
    else:
        st.info("Sélectionnez une stratégie dans la sidebar pour commencer.")

    st.markdown("---")
    st.caption("Lancez ce mode depuis la barre d'actions principale juste en dessous.")


# ─────────────────────────────────────────────────────────────────────────────
# Commit C — Onglet Grille / Optuna
# ─────────────────────────────────────────────────────────────────────────────

def _render_grid_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Grille de Paramètres / Optuna.

    Widgets écrits dans session_state (via key=).  sidebar.py les lit ensuite
    pour alimenter SidebarState avant chaque run.
    """
    st.markdown("#### 🔢 Grille de Paramètres / Optuna")
    n_workers = int(st.session_state.get("ui_n_workers", 32))

    use_optuna = st.checkbox(
        "⚡ Utiliser Optuna (Bayésien)",
        key=EXEC_GRID_USE_OPTUNA,
        help="Explore intelligemment l'espace — 10‑100× plus rapide que la grille exhaustive.",
    )

    if use_optuna:
        st.caption("🎯 **Mode Bayésien** — exploration intelligente")
        col_a, col_b = st.columns(2)
        with col_a:
            st.number_input(
                "Nombre de trials",
                min_value=10,
                max_value=10_000,
                step=10,
                key=EXEC_GRID_N_TRIALS,
                help="Recommandé : 100-500",
            )
            st.selectbox(
                "Algorithme",
                ["tpe", "cmaes", "random"],
                key=EXEC_GRID_SAMPLER,
                help="TPE : rapide | CMA-ES : espaces continus | Random : baseline",
            )
        with col_b:
            st.selectbox(
                "Métrique à optimiser",
                ["sharpe_ratio", "sortino_ratio", "total_return_pct", "profit_factor", "calmar_ratio"],
                key=EXEC_GRID_METRIC,
            )
            st.checkbox(
                "Pruning ✂️ (arrêt précoce)",
                key=EXEC_GRID_PRUNING,
                help="Abandonne les trials peu prometteurs — accélère la recherche.",
            )
        n_trials_val = int(st.session_state.get(EXEC_GRID_N_TRIALS, 200))
        st.slider(
            "Early stop patience (0 = désactivé)",
            min_value=0,
            max_value=max(200, n_trials_val),
            key=EXEC_GRID_EARLY_STOP,
            help="Arrêt après N trials sans amélioration.",
        )
        st.caption(f"⚡ {n_trials_val} trials × {n_workers} workers")
    else:
        st.caption("🔢 **Mode Grille exhaustive** — explore tous les points min/max/step")
        st.markdown("---")
        # CRITICAL: key='grid_worker_threads' conservée verbatim — lue par render_main
        _default_threads = max(1, min(int(st.session_state.get("grid_worker_threads", 1)), 16))
        if "grid_worker_threads" not in st.session_state:
            st.session_state["grid_worker_threads"] = _default_threads
        worker_threads = st.slider(
            "Threads par worker (CPU/BLAS)",
            min_value=1,
            max_value=16,
            step=1,
            key="grid_worker_threads",
            help="Total ≈ workers × threads. Recommandé : 1 si beaucoup de workers.",
        )
        st.caption(f"Total théorique : ~{n_workers * worker_threads} threads")

    st.markdown("---")
    st.caption("Lancez ce mode depuis la barre d'actions principale juste en dessous.")


def _render_builder_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Strategy Builder.

    Reprise stricte du bloc Builder historiquement en sidebar.
    """
    _inject_builder_config_styles()

    pending_autonomous_toggle_sync = st.session_state.pop(
        "_builder_autonomous_toggle_sync", None
    )
    if pending_autonomous_toggle_sync is not None:
        synchronized_value = bool(pending_autonomous_toggle_sync)
        st.session_state["builder_autonomous"] = synchronized_value
        st.session_state["builder_autonomous_toggle"] = synchronized_value
    elif "builder_autonomous_toggle" not in st.session_state:
        st.session_state["builder_autonomous_toggle"] = bool(
            st.session_state.get("builder_autonomous", False)
        )

    st.markdown("#### 🏗️ Strategy Builder")
    _render_builder_config_hero()

    execution_preferences = resolve_builder_execution_preferences(st.session_state)
    default_execution_mode = str(execution_preferences["builder_execution_mode"])
    if str(st.session_state.get("builder_execution_mode", "") or "") != default_execution_mode:
        st.session_state["builder_execution_mode"] = default_execution_mode
    if (
        "builder_execution_mode_select" not in st.session_state
        or str(st.session_state.get("builder_execution_mode_select", "") or "")
        not in BUILDER_EXECUTION_MODE_LABELS
    ):
        st.session_state["builder_execution_mode_select"] = default_execution_mode

    _builder_mode_col, _builder_auto_col = st.columns([3, 2])
    with _builder_mode_col:
        _render_inline_help_label(
            "Architecture Builder",
            "Mono utilise un seul modèle. Expert distribue le travail entre les rôles idée, builder, critic et risk. Dual Lane sépare les lanes productives et critiques sur deux endpoints ou GPU.",
        )
        builder_execution_mode = st.radio(
            "Architecture Builder",
            options=list(BUILDER_EXECUTION_MODE_LABELS.keys()),
            index=list(BUILDER_EXECUTION_MODE_LABELS.keys()).index(
                st.session_state["builder_execution_mode_select"]
            ),
            format_func=lambda mode: BUILDER_EXECUTION_MODE_LABELS.get(mode, mode),
            key="builder_execution_mode_select",
            horizontal=True,
            label_visibility="collapsed",
        )
    with _builder_auto_col:
        _render_inline_help_label(
            "Mode autonome 24/24",
            "Quand ce mode est activé, le Builder génère des objectifs variés et enchaîne les sessions automatiquement jusqu'à arrêt manuel.",
        )
        builder_autonomous = st.toggle(
            "🔄 Mode autonome 24/24",
            key="builder_autonomous_toggle",
            label_visibility="collapsed",
        )
    st.session_state["builder_execution_mode"] = builder_execution_mode
    st.session_state["builder_llm_routing_mode"] = (
        LLM_ROUTING_MODE_COOPERATIVE
        if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE
        else LLM_ROUTING_MODE_STANDARD
    )
    st.session_state["builder_multi_llm_enabled"] = (
        builder_execution_mode != BUILDER_EXECUTION_MODE_MONO
    )
    mode_help = BUILDER_EXECUTION_MODE_HELP.get(builder_execution_mode, "")
    if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE:
        mode_help = (
            mode_help
            + " Lane principale = idea + builder ; lane critique = critic + risk."
        ).strip()
    if mode_help:
        st.caption(mode_help)
    st.session_state["builder_autonomous"] = builder_autonomous

    builder_auto_pause = 10
    builder_auto_use_llm = True
    builder_multi_llm_enabled = builder_execution_mode != BUILDER_EXECUTION_MODE_MONO
    builder_multi_llm_profile = str(
        st.session_state.get("builder_multi_llm_profile", DEFAULT_MULTI_LLM_PROFILE)
    )
    builder_multi_llm_role_overrides = _normalize_builder_multi_llm_role_overrides(
        st.session_state.get("builder_multi_llm_role_overrides", {})
    )
    dual_lane_preferences = resolve_builder_dual_lane_preferences(st.session_state)
    builder_dual_lane_primary_model = str(
        dual_lane_preferences["builder_dual_lane_primary_model"] or "deepseek-r1:32b"
    ).strip() or "deepseek-r1:32b"
    builder_dual_lane_critic_model = str(
        dual_lane_preferences["builder_dual_lane_critic_model"] or builder_dual_lane_primary_model
    ).strip() or builder_dual_lane_primary_model
    st.session_state["builder_dual_lane_primary_model"] = builder_dual_lane_primary_model
    st.session_state["builder_dual_lane_critic_model"] = builder_dual_lane_critic_model
    builder_use_parametric_catalog = False

    st.session_state["builder_multi_llm_enabled"] = builder_multi_llm_enabled
    legacy_builder_model = str(st.session_state.pop("builder_model", "") or "").strip()
    if legacy_builder_model and not str(
        st.session_state.get("builder_model_single_llm", "") or ""
    ).strip():
        st.session_state["builder_model_single_llm"] = legacy_builder_model
    builder_model_single_llm = str(
        st.session_state.get("builder_model_select")
        or st.session_state.get("builder_model_single_llm")
        or "deepseek-r1:32b"
    ).strip() or "deepseek-r1:32b"
    if builder_multi_llm_enabled:
        st.session_state.pop("builder_model_select", None)

    if builder_multi_llm_enabled and not _MULTI_LLM_AVAILABLE:
        st.warning(
            "Le mode Builder multi-LLM est indisponible dans ce workspace. "
            "Repassez en mode `Mono` tant que le module multi-LLM n'est pas charge."
        )
    elif _MULTI_LLM_AVAILABLE:
        profile_options = list_profile_names()
        default_profile = str(
            st.session_state.get(
                "builder_multi_llm_profile",
                DEFAULT_MULTI_LLM_PROFILE,
            )
        )
        if default_profile not in profile_options and profile_options:
            default_profile = profile_options[0]
        builder_multi_llm_profile = default_profile
        st.session_state["builder_multi_llm_profile"] = builder_multi_llm_profile

    mission_tab, models_tab, params_tab = st.tabs(
        ["Mission", "Modèles & runtime", "Paramètres"]
    )

    with mission_tab:
        if builder_autonomous:
            st.markdown("##### Mission autonome")
            builder_auto_pause = st.slider(
                "⏱️ Pause entre runs (s)",
                min_value=0,
                max_value=120,
                value=st.session_state.get("builder_auto_pause", 10),
                key="builder_auto_pause_slider",
                help="Délai en secondes entre chaque session autonome.",
            )
            st.session_state["builder_auto_pause"] = builder_auto_pause

            builder_auto_use_llm = True
            builder_use_parametric_catalog = False
            st.session_state["builder_auto_use_llm"] = True
            st.session_state["builder_use_parametric_catalog"] = False
            st.caption(
                "Les objectifs de session sont maintenant générés prioritairement par le LLM. "
                "En cas d'incident, le Builder bascule sur un fallback simple non affiché dans l'interface."
            )

    pending_objective_sync = st.session_state.pop(
        "_builder_objective_input_sync", None
    )
    if isinstance(pending_objective_sync, str):
        st.session_state["builder_objective_input"] = pending_objective_sync

    builder_objective = st.text_area(
        "🎯 Objectif de la stratégie",
        value=st.session_state.get("builder_objective", ""),
        height=120,
        placeholder=(
            "Ex: Trend-following BTC 1h avec EMA + RSI.\n"
            "Mean reversion sur Bollinger bands + ATR filter.\n"
            "Scalping MACD cross avec stop ATR serré."
        ),
        help="Décrivez la stratégie que l'IA doit créer. Soyez précis sur les indicateurs, le style, et les objectifs.",
        key="builder_objective_input",
        disabled=builder_autonomous,
    )
    st.session_state["builder_objective"] = builder_objective

    _market_pick_default = st.session_state.get("builder_auto_market_pick", True)
    builder_auto_market_pick = st.toggle(
        "🧭 LLM choisit token/TF",
        value=_market_pick_default,
        key="builder_auto_market_pick_toggle",
        help=(
            "Avant chaque session Builder, le LLM sélectionne automatiquement "
            "le symbole et le timeframe les plus adaptés à l'objectif."
        ),
    )
    st.session_state["builder_auto_market_pick"] = builder_auto_market_pick

    universe_mode_options = [UNIVERSE_MODE_CANONICAL, UNIVERSE_MODE_EXPLORATORY]
    current_universe_mode = str(
        st.session_state.get("builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL)
        or BUILDER_UNIVERSE_MODE_CANONICAL
    ).strip() or BUILDER_UNIVERSE_MODE_CANONICAL
    if current_universe_mode not in universe_mode_options:
        current_universe_mode = BUILDER_UNIVERSE_MODE_CANONICAL
    builder_universe_mode = st.radio(
        "🌐 Univers marché",
        options=universe_mode_options,
        index=universe_mode_options.index(current_universe_mode),
        format_func=lambda value: (
            "Canonique (robuste par défaut)"
            if value == UNIVERSE_MODE_CANONICAL
            else "Exploratoire (opt-in)"
        ),
        horizontal=True,
        help=(
            "Canonique = univers robuste pour runs autonomes et validation sérieuse. "
            "Exploratoire = découverte explicite hors univers canonique."
        ),
    )
    st.session_state["builder_universe_mode"] = builder_universe_mode
    if builder_universe_mode == UNIVERSE_MODE_CANONICAL:
        st.caption(
            "Les runs Builder utilisent par défaut l’univers canonique: filtres locaux, liquidité réelle et volatilité adaptée à la stratégie."
        )
    else:
        st.warning(
            "Mode exploratoire actif: ce run reste hors validation sérieuse tant qu’il n’a pas été rejoué en univers canonique."
        )

    with st.expander("Aide de rédaction", expanded=False):
        st.markdown(
            "**Structure recommandée :**\n"
            "```\n"
            "[Style] sur [marché] [timeframe].\n"
            "Indicateurs : [ind1] + [ind2] + [ind3].\n"
            "Entrées : [conditions d'entrée].\n"
            "Sorties : [conditions de sortie].\n"
            "Risk management : [SL/TP/sizing].\n"
            "```"
        )

    with models_tab:
        builder_ollama_host = st.text_input(
            (
                "URL Ollama lane principale"
                if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE
                else "URL Ollama (Builder)"
            ),
            value=str(
                st.session_state.get(
                    "builder_ollama_host",
                    os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
                )
            ),
            key="builder_ollama_host",
            help=(
                "Endpoint Ollama principal du Builder."
                if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE
                else "Endpoint Ollama utilisé par le mode Strategy Builder."
            ),
        ).strip()

        control_host = builder_ollama_host
        primary_gpu = "GPU-0"
        control_gpu = primary_gpu
        if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE:
            builder_topology = _render_phase1_topology_editor(
                primary_host=builder_ollama_host,
                primary_label="Endpoint principal Builder",
                session_prefix="builder",
                config_state_key="builder_llm_topology_config",
                routing_mode_key="builder_llm_routing_mode",
            )
            primary_endpoint = builder_topology.endpoints.get(
                "builder_primary",
                builder_topology.endpoints.get("default"),
            )
            control_endpoint = builder_topology.endpoints.get(
                "control",
                builder_topology.endpoints.get("default"),
            )
            control_host = normalize_ollama_host(
                getattr(control_endpoint, "ollama_host", builder_ollama_host)
            )
            primary_gpu = str(getattr(primary_endpoint, "gpu_target", "") or "GPU-0")
            control_gpu = str(getattr(control_endpoint, "gpu_target", "") or primary_gpu)
        else:
            builder_topology = _get_phase1_topology_from_session(
                builder_ollama_host,
                session_prefix="builder",
                config_state_key="builder_llm_topology_config",
                routing_mode_key="builder_llm_routing_mode",
            )
            st.session_state["builder_llm_topology_config"] = builder_topology.to_dict()

        runtime_preferences = resolve_builder_runtime_preferences(st.session_state)
        builder_auto_start_state = bool(
            runtime_preferences["builder_auto_start_ollama"]
        )
        builder_preload_model = bool(runtime_preferences["builder_preload_model"])
        builder_keep_alive_minutes = int(
            runtime_preferences["builder_keep_alive_minutes"]
        )
        builder_unload_after_run = bool(
            runtime_preferences["builder_unload_after_run"]
        )
        builder_ollama_available = _ollama_is_available(builder_ollama_host)
        _rt_status_col, _rt_action_col = st.columns([4, 1])
        with _rt_status_col:
            st.markdown("##### Runtime & connexion")
            st.caption(
                f"{'🟢 Connecté' if builder_ollama_available else '⚠️ Hors ligne'} sur {builder_ollama_host}"
            )
        with _rt_action_col:
            builder_ollama_action_label = (
                "🧪 Tester" if builder_ollama_available else "🚀 Démarrer"
            )
            if st.button(builder_ollama_action_label, key="builder_start_ollama"):
                with st.spinner("Vérification / démarrage d'Ollama..."):
                    success, msg = _ollama_start_if_needed(
                        builder_ollama_host,
                        gpu_target=str(
                            getattr(
                                builder_topology.endpoints.get(
                                    "builder_primary",
                                    builder_topology.endpoints.get("default"),
                                ),
                                "gpu_target",
                                "",
                            )
                            or ""
                        ),
                    )
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with st.expander("Réglages runtime avancés", expanded=False):
            builder_auto_start_state = st.toggle(
                "Auto-demarrer Ollama local si necessaire",
                value=builder_auto_start_state,
                key="builder_auto_start_ollama_toggle",
                help="Tente de demarrer l'endpoint local si le Builder ne le trouve pas.",
            )
            builder_preload_model = st.toggle(
                "Precharger le modele avant la session",
                value=builder_preload_model,
                key="builder_preload_model_toggle",
                help="Fait un warmup explicite avant le premier appel Builder.",
            )
            builder_keep_alive_minutes = int(
                st.number_input(
                    "Keep-alive Ollama (minutes)",
                    min_value=0,
                    max_value=240,
                    value=builder_keep_alive_minutes,
                    step=5,
                    key="builder_keep_alive_minutes_input",
                    help="Temps de retention du modele entre deux appels runtime.",
                )
            )
            builder_unload_after_run = st.toggle(
                "Decharger les modeles en fin de session",
                value=builder_unload_after_run,
                key="builder_unload_after_run_toggle",
                help="Libere la RAM/VRAM du Builder a la fin du run ou du cleanup multi-role.",
            )

        st.session_state["builder_auto_start_ollama"] = builder_auto_start_state
        st.session_state["builder_preload_model"] = builder_preload_model
        st.session_state["builder_keep_alive_minutes"] = builder_keep_alive_minutes
        st.session_state["builder_unload_after_run"] = builder_unload_after_run
        flow_analysis_preferences = resolve_builder_flow_analysis_preferences(
            st.session_state
        )
        builder_flow_analysis_enabled = bool(
            flow_analysis_preferences["builder_flow_analysis_enabled"]
        )
        builder_flow_analysis_ablation = dict(
            flow_analysis_preferences["builder_flow_analysis_ablation"]
        )

        if builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE:
            st.markdown("##### Lanes actives")
            col_lane_a, col_lane_b = st.columns(2)
            with col_lane_a:
                builder_dual_lane_primary_model = render_model_selector(
                    label="Modele lane principale",
                    key="builder_dual_lane_primary_model_select",
                    help_text="Couvre idea_llm et builder_llm.",
                    show_details=True,
                    compact=True,
                    ollama_host=builder_ollama_host,
                    include_library_models=True,
                    current_value=builder_dual_lane_primary_model,
                )
            with col_lane_b:
                builder_dual_lane_critic_model = render_model_selector(
                    label="Modele lane critique",
                    key="builder_dual_lane_critic_model_select",
                    help_text="Couvre critic_llm et risk_llm.",
                    show_details=True,
                    compact=True,
                    ollama_host=control_host,
                    include_library_models=True,
                    current_value=builder_dual_lane_critic_model,
                )
            st.session_state["builder_dual_lane_primary_model"] = (
                builder_dual_lane_primary_model
            )
            st.session_state["builder_dual_lane_critic_model"] = (
                builder_dual_lane_critic_model
            )
            builder_multi_llm_role_overrides = {
                "idea_llm": [builder_dual_lane_primary_model],
                "builder_llm": [builder_dual_lane_primary_model],
                "critic_llm": [builder_dual_lane_critic_model],
                "risk_llm": [builder_dual_lane_critic_model],
            }
            st.session_state["builder_multi_llm_role_overrides"] = dict(
                builder_multi_llm_role_overrides
            )
            with st.expander("Résumé lanes", expanded=False):
                lane_rows = [
                    {
                        "lane": "principale",
                        "roles_couverts": "idea_llm, builder_llm",
                        "endpoint": builder_ollama_host,
                        "gpu_cible": primary_gpu,
                        "modele": builder_dual_lane_primary_model,
                    },
                    {
                        "lane": "critique",
                        "roles_couverts": "critic_llm, risk_llm",
                        "endpoint": control_host,
                        "gpu_cible": control_gpu,
                        "modele": builder_dual_lane_critic_model,
                    },
                ]
                st.dataframe(lane_rows, width="stretch", hide_index=True)
                _render_builder_runtime_diagnostic_panel()
        else:
            current_builder_model = builder_model_single_llm
            builder_model_single_llm = current_builder_model or "deepseek-r1:32b"
            if builder_execution_mode == BUILDER_EXECUTION_MODE_MONO:
                builder_model_single_llm = render_model_selector(
                    label="Modele LLM",
                    key="builder_model_select",
                    help_text="Modèles installés sur Ollama en priorité, puis catalogue local connu si l'inventaire serveur est incomplet.",
                    show_details=True,
                    compact=True,
                    ollama_host=builder_ollama_host,
                    include_library_models=True,
                    current_value=current_builder_model,
                )
                st.session_state["builder_multi_llm_role_overrides"] = {}
            st.session_state["builder_model_single_llm"] = builder_model_single_llm

            if (
                builder_execution_mode == BUILDER_EXECUTION_MODE_EXPERT
                and _MULTI_LLM_AVAILABLE
            ):
                builder_multi_llm_profile, builder_multi_llm_role_overrides = (
                    _render_builder_expert_multi_role_section(
                        builder_ollama_host=builder_ollama_host,
                        builder_topology=builder_topology,
                        builder_multi_llm_profile=builder_multi_llm_profile,
                    )
                )

        active_builder_models = _collect_inference_model_candidates(
            [builder_model_single_llm],
            [builder_dual_lane_primary_model, builder_dual_lane_critic_model],
            builder_multi_llm_role_overrides,
        )
        _render_llm_inference_settings_editor(
            active_models=active_builder_models,
            section_label="Inférence Ollama du Builder",
        )

        st.markdown("##### Analyse du flux Builder")
        st.caption(
            "Répond à trois questions: ce qui bloque le flux, ce qui aide réellement le Builder, "
            "et où une session instrumentée diverge. Cette analyse mesure le pipeline Builder; "
            "elle ne garantit pas la qualité de marché de la stratégie."
        )
        builder_flow_analysis_enabled = st.toggle(
            "Activer l'analyse de flux sur le prochain run",
            value=builder_flow_analysis_enabled,
            key="builder_flow_analysis_enabled_toggle",
            help=(
                "Enregistre un résumé lisible et un fichier `pipeline_traces.json` "
                "pour la session Builder suivante."
            ),
        )
        st.session_state["builder_flow_analysis_enabled"] = (
            builder_flow_analysis_enabled
        )

        if builder_execution_mode == BUILDER_EXECUTION_MODE_MONO:
            default_disabled_steps = [
                step
                for step, enabled in builder_flow_analysis_ablation.items()
                if not enabled
            ]
            _ABLATION_PRESETS: dict[str, tuple[str, list[str]]] = {
                "full": (
                    "🔒 Pipeline complet",
                    [],
                ),
                "fast": (
                    "⚡ Analyse rapide",
                    ["llm_analysis", "indicator_ranking", "iteration_history", "diagnostic_context"],
                ),
                "debug": (
                    "🧪 Debug pipeline",
                    ["llm_analysis", "runtime_fix", "code_repair", "indicator_binding",
                     "indicator_ranking", "iteration_history", "diagnostic_context"],
                ),
            }
            st.caption("Presets d'ablation — benchmark mesuré localement (ms/iter) :")
            _preset_cols = st.columns(len(_ABLATION_PRESETS))
            for _col, (_pk, (_plabel, _pdisabled)) in zip(_preset_cols, _ABLATION_PRESETS.items()):
                with _col:
                    if st.button(
                        _plabel,
                        key=f"ablation_preset_{_pk}",
                        use_container_width=True,
                        help={
                            "full": "Toutes les 18 étapes actives — pipeline de production.",
                            "fast": "Désactive l'appel LLM analyse + classement NLP → "
                                    "économie ~1 LLM call/iter, fallback rule-based multi-critères.",
                            "debug": "Désactive steps LLM + code_repair (~22 ms) + "
                                     "indicator_binding (~2.4 ms) → pipeline léger sans Ollama.",
                        }[_pk],
                    ):
                        _valid_disabled = [
                            s for s in _pdisabled
                            if s in builder_flow_analysis_ablation
                        ]
                        st.session_state["builder_flow_analysis_disabled_steps_multiselect"] = (
                            _valid_disabled
                        )
                        default_disabled_steps = _valid_disabled

            disabled_steps = st.multiselect(
                "Étapes à désactiver pour diagnostic avancé",
                options=list(builder_flow_analysis_ablation.keys()),
                default=default_disabled_steps,
                key="builder_flow_analysis_disabled_steps_multiselect",
                format_func=lambda step: _BUILDER_FLOW_ANALYSIS_STEP_LABELS.get(step, step),
                help=(
                    "Laisser vide pour un pipeline complet. Désactiver une étape sert "
                    "uniquement à mesurer son impact sur le flux du Builder mono."
                ),
            )
            normalized_ablation = {
                step: step not in disabled_steps
                for step in builder_flow_analysis_ablation.keys()
            }
            st.session_state["builder_flow_analysis_ablation"] = normalized_ablation
            with st.expander("Ce que mesure cette analyse", expanded=False):
                st.caption(
                    "Niveau 1: synthèse lisible. Niveau 2: chronologie de session. "
                    "Niveau 3: ablation, comparaison entre sessions et JSON brut."
                )
        else:
            st.session_state["builder_flow_analysis_disabled_steps_multiselect"] = []
            st.session_state["builder_flow_analysis_ablation"] = {
                step: True for step in builder_flow_analysis_ablation.keys()
            }
            st.caption(
                "La lecture détaillée dans l'interface est prioritairement optimisée "
                "pour le mode Mono dans cette première vague. Les métadonnées restent "
                "compatibles avec les sessions multi-LLM."
            )

    with params_tab:
        st.markdown("##### Paramètres de construction")
        builder_max_iterations = st.slider(
            "Itérations max",
            min_value=1,
            max_value=30,
            value=st.session_state.get("builder_max_iterations", 10),
            key="builder_max_iters_slider",
            help="Nombre maximum de tentatives pour améliorer la stratégie.",
        )
        _param_col1, _param_col2 = st.columns(2)
        with _param_col1:
            builder_target_sharpe = st.number_input(
                "Sharpe cible",
                min_value=0.0,
                max_value=5.0,
                value=st.session_state.get("builder_target_sharpe", 1.0),
                step=0.1,
                key="builder_target_sharpe_input",
                help="Sharpe ratio minimum pour accepter automatiquement la stratégie.",
            )
        with _param_col2:
            builder_capital = st.number_input(
                "Capital initial ($)",
                min_value=100.0,
                max_value=1_000_000.0,
                value=st.session_state.get("builder_capital", 10000.0),
                step=1000.0,
                key="builder_capital_input",
                format="%.0f",
            )

        try:
            from indicators.registry import list_indicators
            indicators = list_indicators()
            with st.expander(f"Références ({len(indicators)} indicateurs)", expanded=False):
                st.write(", ".join(sorted(indicators)))
        except Exception as exc:
            logger.warning("Failed to list indicators: %s", exc)

        sandbox_root = get_builder_sessions_dir()
        if sandbox_root.exists():
            sessions = sorted(
                [d.name for d in sandbox_root.iterdir() if d.is_dir() and d.name != ".gitkeep"],
                reverse=True,
            )
            if sessions:
                with st.expander(f"Sessions précédentes ({len(sessions)})", expanded=False):
                    for s in sessions[:10]:
                        st.caption(f"• {s}")

    # Garder des variables locales synchronisées pour debug lisible
    _ = (
        builder_ollama_host,
        builder_topology,
        builder_auto_start_state,
        builder_keep_alive_minutes,
        builder_unload_after_run,
        builder_max_iterations,
        builder_target_sharpe,
        builder_capital,
        builder_auto_pause,
        builder_auto_use_llm,
        builder_multi_llm_enabled,
        builder_multi_llm_profile,
        builder_multi_llm_role_overrides,
        builder_use_parametric_catalog,
    )


def _render_llm_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Optimisation LLM (migration depuis sidebar)."""
    st.markdown("#### 🤖 Optimisation LLM")
    st.caption("∞ Combinaisons LLM (non limitées)")
    _render_global_llm_routing_mode_control(
        scope_label="Optimisation LLM",
        session_key="exec_llm_routing_mode",
    )
    st.caption(
        "Routage actif: "
        f"**{LLM_ROUTING_MODE_LABELS.get(_current_llm_routing_mode('exec_llm_routing_mode'), _current_llm_routing_mode('exec_llm_routing_mode'))}**"
    )
    st.caption("Le lancement se fait via la sidebar, section `Actions`.")
    n_workers = int(st.session_state.get("ui_n_workers", 32))
    st.caption(f"🔧 Parallélisation: jusqu'à {n_workers} backtests simultanés")

    llm_config = None
    llm_model = None
    llm_use_multi_agent = False
    llm_unload_during_backtest = bool(st.session_state.get("llm_unload_during_backtest", True))
    role_model_config = None

    llm_compare_enabled = False
    llm_compare_auto_run = True
    llm_compare_strategies: list[str] = []
    llm_compare_tokens: list[str] = []
    llm_compare_timeframes: list[str] = []
    llm_compare_metric = "sharpe_ratio"
    llm_compare_aggregate = "median"
    llm_compare_max_runs = 25
    llm_compare_use_preset = True
    llm_compare_generate_report = True
    llm_inference_global_settings = normalize_llm_inference_settings(
        st.session_state.get("llm_inference_global_settings")
    )
    llm_inference_model_profiles = normalize_llm_model_inference_profiles(
        st.session_state.get("llm_inference_model_profiles")
    )

    available_strategies = list_strategies() if callable(list_strategies) else []
    strategy_options = build_strategy_options(available_strategies)
    strategy_name = state.strategy_name or next(iter(strategy_options.keys()), "")
    symbol = state.symbol
    timeframe = state.timeframe
    available_tokens = state.available_tokens
    available_timeframes = state.available_timeframes

    if not LLM_AVAILABLE:
        st.error("❌ Module LLM non disponible")
        st.caption(f"Erreur: {LLM_IMPORT_ERROR}")
    else:
        llm_provider = st.selectbox(
            "Provider LLM",
            ["Ollama (Local)", "OpenAI"],
            key="exec_llm_provider",
            help="Ollama = gratuit et local | OpenAI = API payante",
        )

        llm_use_multi_agent = st.checkbox(
            "Mode multi-agents 👥",
            value=bool(st.session_state.get("llm_use_multi_agent", False)),
            key="llm_use_multi_agent",
            help="Utiliser Analyst/Strategist/Critic/Validator",
        )

        def _extract_model_params_b(model_name: str) -> float | None:
            match = re.search(r"(\d+(?:\.\d+)?)b", model_name.lower())
            if match:
                return float(match.group(1))
            return None

        def _is_model_under_limit(model_name: str, limit: float) -> bool:
            size = _extract_model_params_b(model_name)
            return bool(size is not None and size < limit)

        def _is_model_over_limit(model_name: str, limit: float) -> bool:
            size = _extract_model_params_b(model_name)
            return bool(size is not None and size >= limit)

        if "Ollama" in llm_provider:
            ollama_host = st.text_input(
                "URL Ollama",
                value=str(
                    st.session_state.get(
                        "exec_llm_ollama_host",
                        os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
                    )
                ),
                key="exec_llm_ollama_host",
                help="Adresse du serveur Ollama",
            ).strip()
            llm_topology = _render_phase1_topology_editor(
                primary_host=ollama_host,
                primary_label="Endpoint productif orchestrateur",
                session_prefix="exec",
                config_state_key="exec_llm_topology_config",
                routing_mode_key="exec_llm_routing_mode",
            )
            exec_ollama_available = _ollama_is_available(ollama_host)
            if exec_ollama_available:
                st.caption(f"🟢 Ollama connecté sur `{ollama_host}`")
            else:
                st.warning(f"⚠️ Ollama non détecté sur `{ollama_host}`")
            exec_ollama_action_label = (
                "🧪 Tester Ollama" if exec_ollama_available else "🚀 Démarrer Ollama"
            )
            if st.button(exec_ollama_action_label, key="exec_start_ollama"):
                with st.spinner("Vérification / démarrage d'Ollama..."):
                    success, msg = _ollama_start_if_needed(
                        ollama_host,
                        gpu_target=str(
                            getattr(
                                llm_topology.endpoints.get(
                                    "builder_primary",
                                    llm_topology.endpoints.get("default"),
                                ),
                                "gpu_target",
                                "",
                            )
                            or ""
                        ),
                    )
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            llm_use_multi_model = False
            if llm_use_multi_agent:
                llm_use_multi_model = st.checkbox(
                    "Multi-modeles par role",
                    value=bool(st.session_state.get("llm_use_multi_model", False)),
                    key="llm_use_multi_model",
                    help="Assigner differents modeles a chaque role d'agent",
                )

            if llm_use_multi_model:
                available_models_list = list_available_models() if callable(list_available_models) else []
                available_model_names = [m.name for m in available_models_list]

                llm_limit_small_models = st.checkbox(
                    "Limiter selection aleatoire a <20B",
                    value=bool(st.session_state.get("llm_limit_small_models", True)),
                    key="llm_limit_small_models",
                    help="Filtre la liste par taille et exclut deepseek-r1:70b",
                )
                llm_limit_large_models = st.checkbox(
                    "Limiter selection aleatoire a >=20B",
                    value=bool(st.session_state.get("llm_limit_large_models", False)),
                    key="llm_limit_large_models",
                    help="Filtre la liste par taille (>=20B uniquement)",
                )

                effective_small_filter = llm_limit_small_models
                effective_large_filter = llm_limit_large_models
                if effective_small_filter and effective_large_filter:
                    st.warning("Filtres <20B et >=20B actifs: >=20B prioritaire.")
                    effective_small_filter = False

                excluded_models = set()
                if not effective_large_filter:
                    excluded_models = {"deepseek-r1:70b"}
                if excluded_models:
                    available_model_names = [m for m in available_model_names if m not in excluded_models]

                if effective_small_filter:
                    filtered = [m for m in available_model_names if _is_model_under_limit(m, 20)]
                    if filtered:
                        available_model_names = filtered
                    else:
                        st.warning("Aucun modele <20B detecte, filtre desactive.")

                if effective_large_filter:
                    filtered = [m for m in available_model_names if _is_model_over_limit(m, 20)]
                    if filtered:
                        available_model_names = filtered
                    else:
                        available_model_names = []
                        st.warning("Aucun modele >=20B detecte.")

                role_model_config = get_global_model_config() if callable(get_global_model_config) else None
                if role_model_config is None:
                    st.warning("Configuration multi-modeles indisponible, fallback en mode single-model.")
                    llm_use_multi_model = False
                    available_model_names = []

            if llm_use_multi_model and role_model_config is not None:

                def model_with_badge(name: str) -> str:
                    info = KNOWN_MODELS.get(name) if isinstance(KNOWN_MODELS, dict) else None
                    if info:
                        if info.category == ModelCategory.LIGHT:
                            return f"[L] {name}"
                        if info.category == ModelCategory.MEDIUM:
                            return f"[M] {name}"
                        return f"[H] {name}"
                    return name

                model_options_display = [model_with_badge(m) for m in available_model_names]
                name_to_display = {n: model_with_badge(n) for n in available_model_names}
                display_to_name = {v: k for k, v in name_to_display.items()}

                st.caption("**Modeles par role d'agent**")
                analyst_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.analyst.models
                    if m in available_model_names
                ]
                strategist_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.strategist.models
                    if m in available_model_names
                ]
                critic_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.critic.models
                    if m in available_model_names
                ]
                validator_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.validator.models
                    if m in available_model_names
                ]

                _prime_multiselect_state(
                    "analyst_models",
                    desired=analyst_defaults[:3] if analyst_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "strategist_models",
                    desired=strategist_defaults[:3] if strategist_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "critic_models",
                    desired=critic_defaults[:3] if critic_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "validator_models",
                    desired=validator_defaults[:3] if validator_defaults else model_options_display[:2],
                    options=model_options_display,
                )

                analyst_selection = st.multiselect(
                    "Modeles Analyst",
                    model_options_display,
                    key="analyst_models",
                )
                strategist_selection = st.multiselect(
                    "Modeles Strategist",
                    model_options_display,
                    key="strategist_models",
                )
                critic_selection = st.multiselect(
                    "Modeles Critic",
                    model_options_display,
                    key="critic_models",
                )
                validator_selection = st.multiselect(
                    "Modeles Validator",
                    model_options_display,
                    key="validator_models",
                )

                heavy_after_iter = st.number_input(
                    "Autoriser apres iteration N",
                    min_value=1,
                    max_value=20,
                    value=3,
                    key="exec_llm_heavy_after_iter",
                )

                def _normalize_selection(selection: list[str]) -> list[str]:
                    names = [display_to_name.get(m, m) for m in selection]
                    return [n for n in names if n in available_model_names]

                role_model_config.analyst.models = _normalize_selection(analyst_selection)
                role_model_config.strategist.models = _normalize_selection(strategist_selection)
                role_model_config.critic.models = _normalize_selection(critic_selection)
                role_model_config.validator.models = _normalize_selection(validator_selection)
                for assignment in [
                    role_model_config.analyst,
                    role_model_config.strategist,
                    role_model_config.critic,
                    role_model_config.validator,
                ]:
                    assignment.allow_heavy_after_iteration = heavy_after_iter

                if callable(set_global_model_config):
                    set_global_model_config(role_model_config)
                if role_model_config.analyst.models:
                    llm_model = role_model_config.analyst.models[0]
                elif available_model_names:
                    llm_model = available_model_names[0]
            else:
                current_exec_llm_model = str(
                    st.session_state.get("llm_model_select")
                    or st.session_state.get("exec_llm_model")
                    or st.session_state.get("llm_model")
                    or ""
                ).strip()
                llm_model = render_model_selector(
                    label="Modele Ollama",
                    key="llm_model_select",
                    preferred_order=RECOMMENDED_FOR_STRATEGY,
                    help_text=(
                        "Modèles installés sur Ollama en priorité, puis catalogue local connu "
                        "si l'inventaire serveur est incomplet. Aucun fallback silencieux n'est appliqué."
                    ),
                    show_details=True,
                    compact=True,
                    ollama_host=ollama_host,
                    include_library_models=True,
                    current_value=current_exec_llm_model,
                )
            llm_inference_global_settings, llm_inference_model_profiles = (
                _render_llm_inference_settings_editor(
                    active_models=[llm_model] if llm_model else [],
                    section_label="Inférence Ollama",
                )
            )
            if llm_model and callable(LLMConfig):
                llm_config = apply_llm_inference_settings(
                    LLMConfig(
                        provider=LLMProvider.OLLAMA,
                        model=llm_model,
                        ollama_host=ollama_host,
                    ),
                    model_name=llm_model,
                    global_settings=llm_inference_global_settings,
                    model_profiles=llm_inference_model_profiles,
                )
            st.session_state["exec_llm_topology_config"] = llm_topology.to_dict()
        else:
            openai_key = st.text_input(
                "Clé API OpenAI",
                type="password",
                key="exec_llm_openai_key",
                help="Votre clé API OpenAI",
            )
            llm_model = st.selectbox(
                "Modèle OpenAI",
                ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
                key="exec_llm_openai_model",
                help="gpt-4o-mini recommandé pour coût/performance",
            )
            if openai_key and callable(LLMConfig):
                llm_config = LLMConfig(
                    provider=LLMProvider.OPENAI,
                    model=llm_model,
                    openai_api_key=openai_key,
                )
            else:
                st.warning("⚠️ Clé API requise")

        with st.expander("⚙️ Options d'optimisation LLM", expanded=False):
            llm_unlimited_iterations = st.checkbox(
                "Itérations illimitées",
                value=bool(st.session_state.get("llm_unlimited_iterations", True)),
                key="llm_unlimited_iterations",
            )

            if llm_unlimited_iterations:
                st.caption("∞ itérations (arrêt manuel)")
            else:
                st.slider(
                    "Max itérations",
                    min_value=3,
                    max_value=50,
                    value=int(st.session_state.get("exec_llm_max_iterations", 10)),
                    key="exec_llm_max_iterations",
                )

            walk_forward_enabled = True
            df_cached = st.session_state.get("ohlcv_df")
            if df_cached is not None and not df_cached.empty:
                data_duration_days = (df_cached.index[-1] - df_cached.index[0]).days
                if (data_duration_days / 30.44) < 6:
                    walk_forward_enabled = False

            st.checkbox(
                "Walk-Forward Validation",
                value=bool(st.session_state.get("exec_llm_use_walk_forward", walk_forward_enabled)),
                disabled=not walk_forward_enabled,
                key="exec_llm_use_walk_forward",
            )

            llm_unload_during_backtest = st.checkbox(
                "Décharger LLM du GPU",
                value=bool(st.session_state.get("exec_llm_unload", llm_unload_during_backtest)),
                key="exec_llm_unload",
            )

        with st.expander("Comparaison multi-strategies", expanded=False):
            llm_compare_enabled = st.checkbox(
                "Comparer strategies (multi-tokens/timeframes)",
                value=bool(st.session_state.get("llm_compare_enabled", False)),
                key="llm_compare_enabled",
            )
            if llm_compare_enabled:
                llm_compare_auto_run = st.checkbox(
                    "Execution automatique",
                    value=bool(st.session_state.get("llm_compare_auto_run", True)),
                    key="llm_compare_auto_run",
                )
                _prime_multiselect_state(
                    "llm_compare_strategy_labels",
                    desired=[strategy_name] if strategy_name else [],
                    options=list(strategy_options.keys()),
                )
                compare_strategy_labels = st.multiselect(
                    "Strategies a comparer",
                    list(strategy_options.keys()),
                    key="llm_compare_strategy_labels",
                )
                llm_compare_strategies = [
                    strategy_options[label]
                    for label in compare_strategy_labels
                    if label in strategy_options
                ]
                _prime_multiselect_state(
                    "llm_compare_tokens",
                    desired=[symbol] if symbol else [],
                    options=available_tokens,
                )
                llm_compare_tokens = st.multiselect(
                    "Tokens",
                    available_tokens,
                    key="llm_compare_tokens",
                )
                _prime_multiselect_state(
                    "llm_compare_timeframes",
                    desired=[timeframe] if timeframe else [],
                    options=available_timeframes,
                )
                llm_compare_timeframes = st.multiselect(
                    "Timeframes",
                    available_timeframes,
                    key="llm_compare_timeframes",
                )
                llm_compare_metric = st.selectbox(
                    "Metrica principale",
                    ["sharpe_ratio", "total_return_pct", "max_drawdown", "win_rate"],
                    index=0,
                    key="llm_compare_metric",
                )
                llm_compare_aggregate = st.selectbox(
                    "Agregation",
                    ["median", "mean", "worst"],
                    index=0,
                    key="llm_compare_aggregate",
                )
                llm_compare_max_runs = int(st.number_input(
                    "Max runs comparaison",
                    min_value=1,
                    max_value=500,
                    value=int(st.session_state.get("llm_compare_max_runs", 25)),
                    step=1,
                    key="llm_compare_max_runs",
                ))
                llm_compare_use_preset = st.checkbox(
                    "Utiliser presets si disponibles",
                    value=bool(st.session_state.get("llm_compare_use_preset", True)),
                    key="llm_compare_use_preset",
                )
                llm_compare_generate_report = st.checkbox(
                    "Generer justification LLM",
                    value=bool(st.session_state.get("llm_compare_generate_report", True)),
                    key="llm_compare_generate_report",
                )

                if not llm_compare_auto_run:
                    if "llm_compare_run_now" not in st.session_state:
                        st.session_state["llm_compare_run_now"] = False
                    if st.button("Lancer comparaison", key="llm_compare_run_button"):
                        st.session_state["llm_compare_run_now"] = True
            else:
                if "llm_compare_run_now" in st.session_state:
                    st.session_state["llm_compare_run_now"] = False

    st.session_state["exec_llm_config_obj"] = llm_config
    st.session_state["exec_llm_model"] = llm_model
    st.session_state["exec_llm_use_multi_agent"] = llm_use_multi_agent
    st.session_state["exec_llm_role_model_config"] = role_model_config
    st.session_state["exec_llm_compare_enabled"] = llm_compare_enabled
    st.session_state["exec_llm_compare_auto_run"] = llm_compare_auto_run
    st.session_state["exec_llm_compare_strategies"] = llm_compare_strategies
    st.session_state["exec_llm_compare_tokens"] = llm_compare_tokens
    st.session_state["exec_llm_compare_timeframes"] = llm_compare_timeframes
    st.session_state["exec_llm_compare_metric"] = llm_compare_metric
    st.session_state["exec_llm_compare_aggregate"] = llm_compare_aggregate
    st.session_state["exec_llm_compare_max_runs"] = llm_compare_max_runs
    st.session_state["exec_llm_compare_use_preset"] = llm_compare_use_preset
    st.session_state["exec_llm_compare_generate_report"] = llm_compare_generate_report


def _sync_exec_mode_selector(current_mode: str) -> str:
    mode_names = [mode_name for mode_name, _icon, _desc in MODE_OPTIONS]
    selected_mode = str(current_mode or mode_names[0]).strip()
    if selected_mode not in mode_names:
        selected_mode = mode_names[0]

    if st.session_state.get("exec_mode_selector") != selected_mode:
        st.session_state["exec_mode_selector"] = selected_mode
    return selected_mode


def _handle_exec_mode_change() -> None:
    mode_names = [mode_name for mode_name, _icon, _desc in MODE_OPTIONS]
    selected_mode = str(st.session_state.get("exec_mode_selector", "") or "").strip()
    if selected_mode in mode_names:
        st.session_state["optimization_mode"] = selected_mode


def _render_mode_selector(current_mode: str) -> str:
    mode_names = [mode_name for mode_name, _icon, _desc in MODE_OPTIONS]
    _sync_exec_mode_selector(current_mode)

    st.markdown("#### Mode d'exécution")
    selected_mode = st.radio(
        "Mode d'exécution",
        options=mode_names,
        key="exec_mode_selector",
        on_change=_handle_exec_mode_change,
        horizontal=True,
        label_visibility="collapsed",
        format_func=lambda mode: next(
            (
                f"{icon} {name}"
                for name, icon, _desc in MODE_OPTIONS
                if name == mode
            ),
            str(mode),
        ),
    )
    if st.session_state.get("optimization_mode") != selected_mode:
        st.session_state["optimization_mode"] = selected_mode
    return str(selected_mode)


def render_exec_tabs(state: SidebarState) -> None:
    """Affiche uniquement le contenu du mode d'exécution actif."""
    _init_exec_tabs_state()
    mode_names = [mode_name for mode_name, _icon, _desc in MODE_OPTIONS]
    active_mode = str(
        st.session_state.get("optimization_mode", state.optimization_mode)
        or state.optimization_mode
    ).strip()
    if active_mode not in mode_names:
        active_mode = mode_names[0]
        st.session_state["optimization_mode"] = active_mode
    st.markdown("---")
    description = next(
        (desc for mode_name, _icon, desc in MODE_OPTIONS if mode_name == active_mode),
        "",
    )
    if description:
        st.caption(f"✅ Mode actif — {description}")

    if active_mode == "Backtest Simple":
        _render_backtest_tab(state)
    elif active_mode == "Grille de Paramètres":
        _render_grid_tab(state)
    elif active_mode == "🤖 Optimisation LLM":
        _render_llm_tab(state)
    elif active_mode == "🏗️ Strategy Builder":
        _render_builder_tab(state)
