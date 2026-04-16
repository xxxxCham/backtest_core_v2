# ruff: noqa: I001
"""
Module-ID: agents.builder_proposal_helpers

Purpose: Normalisation, validation et sanitisation des propositions LLM
         du Strategy Builder, ainsi que helpers de sweep paramétrique.

Role in pipeline: transformation / validation de données

Dependencies: agents.builder_ast_utils, agents.builder_objective_parser,
              agents.builder_text_utils, agents.builder_constants
"""

from __future__ import annotations

import itertools
import json
import os
import re
from typing import Any, Dict, List, Optional, Union, cast

import numpy as np
import pandas as pd

from agents.builder_ast_utils import (
    _extract_default_params_signature,
    _extract_generate_signals_signature,
    _extract_required_indicators_signature,
    _normalize_required_indicator_names,
)
from agents.builder_objective_parser import (
    _build_indicator_override_reason,
    _canonicalize_indicator_name,
    _extract_objective_indicator_names,
)
from agents.builder_constants import (
    ERR_DSL,
    ERR_JSON,
    ERR_PARAM,
    ERR_SIG,
)
from agents.builder_text_utils import (
    _err,
    _format_python_dict_literal,
)


# ---------------------------------------------------------------------------
# Constantes locales
# ---------------------------------------------------------------------------
_PROPOSAL_PLACEHOLDER_VALUES = {
    "",
    "-",
    "—",
    # EN
    "n/a",
    "na",
    "none",
    "null",
    "brief description",
    "what you expect this change to achieve and why",
    "when to buy",
    "when to sell",
    "when to close",
    # FR
    "aucun",
    "aucune",
    "néant",
    "sans objet",
    "non applicable",
    "description brève",
    "brève description",
    "ce que vous attendez de ce changement et pourquoi",
    "quand acheter",
    "quand vendre",
    "quand clôturer",
    "condition d'achat",
    "condition de vente",
    "condition de sortie",
}

_BUILDER_PROPOSAL_REQUIRED_KEYS = {
    "strategy_name",
    "used_indicators",
    "entry_long_logic",
    "exit_logic",
    "risk_management",
    "default_params",
    "parameter_specs",
}

_BUILDER_SWEEP_MAX_COMBINATIONS = max(
    1,
    int(os.getenv("BACKTEST_BUILDER_SWEEP_MAX_COMBINATIONS", "9")),
)
_BUILDER_SWEEP_MAX_PARAMS = max(
    1,
    int(os.getenv("BACKTEST_BUILDER_SWEEP_MAX_PARAMS", "3")),
)
_BUILDER_SWEEP_EXCLUDED_PARAMS = frozenset(
    {
        "leverage",
        "warmup",
        "fees_bps",
        "slippage_bps",
    }
)


# ---------------------------------------------------------------------------
# Utilitaires de base
# ---------------------------------------------------------------------------

def _normalize_change_type(change_type: Any) -> str:
    """Normalise le type de changement dans {logic, params, both, accept}."""
    raw = str(change_type or "").strip().lower()
    if raw in {"logic", "params", "both", "accept"}:
        return raw
    if "param" in raw:
        return "params"
    if "logic" in raw:
        return "logic"
    if "accept" in raw:
        return "accept"
    return "logic"


def _dedupe_preserve_order(values: List[Any]) -> List[Any]:
    deduped: List[Any] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _is_placeholder_text(value: Any) -> bool:
    """Détecte un champ placeholder/générique au lieu d'une vraie consigne."""
    text = str(value or "").strip().lower()
    if text in _PROPOSAL_PLACEHOLDER_VALUES:
        return True
    return (
        "placeholder" in text
        or text.startswith("example")
        or text.startswith("exemple")
        or "to achieve and why" in text
        or "à remplir" in text
        or "à compléter" in text
        or "à définir" in text
        or text.startswith("votre ")
        or text.startswith("décrivez ")
    )


def _is_logic_like_change_type(change_type: Any) -> bool:
    return _normalize_change_type(change_type) in {"logic", "both"}


def _infer_direction_constraint_from_objective(objective: Any) -> str:
    """Déduit une contrainte long-only / short-only depuis l'objectif texte."""
    normalized = " ".join(str(objective or "").strip().lower().split())
    if not normalized:
        return "long_short"

    long_only_markers = (
        # EN
        "only execute buy orders",
        "only execute buy order",
        "only buy orders",
        "buy signals",
        "buy-only",
        "long only",
        "long-only",
        "only execute long orders",
        "only execute long positions",
        "only take long trades",
        # FR
        "uniquement des achats",
        "achat seulement",
        "achat uniquement",
        "long seulement",
        "long uniquement",
        "signaux d'achat",
        "uniquement des ordres d'achat",
        "uniquement des positions longues",
        "prendre uniquement des positions longues",
        "uniquement des trades long",
        "exécuter uniquement des ordres d'achat",
        "positions longues uniquement",
        "que des achats",
        "que des longs",
    )
    short_only_markers = (
        # EN
        "only execute sell orders",
        "only execute sell order",
        "only sell orders",
        "sell signals",
        "sell-only",
        "short only",
        "short-only",
        "only execute short orders",
        "only execute short positions",
        "only take short trades",
        # FR
        "uniquement des ventes",
        "vente seulement",
        "vente uniquement",
        "short seulement",
        "short uniquement",
        "signaux de vente",
        "uniquement des ordres de vente",
        "uniquement des positions short",
        "prendre uniquement des positions short",
        "uniquement des trades short",
        "exécuter uniquement des ordres de vente",
        "positions short uniquement",
        "que des ventes",
        "que des shorts",
    )

    long_only = any(marker in normalized for marker in long_only_markers)
    short_only = any(marker in normalized for marker in short_only_markers)

    if long_only and not short_only:
        return "long_only"
    if short_only and not long_only:
        return "short_only"
    return "long_short"


# ---------------------------------------------------------------------------
# Normalisation / sanitation des propositions
# ---------------------------------------------------------------------------

def _normalize_proposal_keys(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise les clés JSON d'une proposition LLM (case-insensitive)."""
    if not proposal:
        return proposal

    _CANONICAL = {
        "strategy_name": "strategy_name",
        "hypothesis": "hypothesis",
        "change_type": "change_type",
        "indicator_override_reason": "indicator_override_reason",
        "used_indicators": "used_indicators",
        "indicator_params": "indicator_params",
        "entry_long_logic": "entry_long_logic",
        "entry_short_logic": "entry_short_logic",
        "exit_logic": "exit_logic",
        "risk_management": "risk_management",
        "default_params": "default_params",
        "parameter_specs": "parameter_specs",
    }
    lower_map = {k.lower(): v for k, v in _CANONICAL.items()}

    normalized: Dict[str, Any] = {}
    for key, value in proposal.items():
        canonical = lower_map.get(key.lower().replace(" ", "_"), key)
        normalized[canonical] = value

    if isinstance(normalized.get("parameter_specs"), dict):
        normalized_specs: Dict[str, Any] = {}
        for param_name, raw_spec in normalized["parameter_specs"].items():
            if not isinstance(raw_spec, dict):
                normalized_specs[param_name] = raw_spec
                continue
            spec_lower = {
                str(k).strip().lower().replace(" ", "_"): v
                for k, v in raw_spec.items()
            }
            normalized_specs[param_name] = {
                "min": spec_lower.get("min", spec_lower.get("min_val", spec_lower.get("min_value"))),
                "max": spec_lower.get("max", spec_lower.get("max_val", spec_lower.get("max_value"))),
                "default": spec_lower.get("default"),
                "type": spec_lower.get("type", spec_lower.get("param_type")),
                "step": spec_lower.get("step"),
            }
        normalized["parameter_specs"] = normalized_specs

    if "change_type" in normalized:
        normalized["change_type"] = _normalize_change_type(
            normalized.get("change_type", "")
        )
    else:
        normalized["change_type"] = "logic"

    if "hypothesis" not in normalized:
        normalized["hypothesis"] = ""

    return normalized


def _flatten_nested_logic(val: Any) -> str:
    """Flatten a nested dict/list logic field into a plain string."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " AND ".join(str(item) for item in val if item)
    if not isinstance(val, dict):
        return str(val)

    desc = val.get("description", "")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()

    for key in val:
        if key in ("logic_expression", "indicators", "description"):
            continue
        inner = val[key]
        if isinstance(inner, dict):
            inner_desc = inner.get("description", "")
            if isinstance(inner_desc, str) and inner_desc.strip():
                return inner_desc.strip()
        return str(key).strip()

    for key, inner in val.items():
        if isinstance(inner, dict):
            result = _flatten_nested_logic(inner)
            if result:
                return result

    return json.dumps(val, ensure_ascii=False)[:200]


def _looks_pathological_param_name(name: str) -> bool:
    """Détecte les noms de paramètres manifestement dégénérés produits par un LLM."""
    candidate = str(name or "").strip().lower()
    if not candidate:
        return True
    if len(candidate) > 64:
        return True
    if re.search(r"([^_]+(?:_[^_]+)*)_(?:\1){1,}$", candidate):
        return True
    chunks = [part for part in candidate.split("_") if part]
    if len(chunks) >= 6:
        seen = set()
        duplicate_count = 0
        for chunk in chunks:
            if chunk in seen:
                duplicate_count += 1
            else:
                seen.add(chunk)
        if duplicate_count >= 3:
            return True
    return False


def _sanitize_param_mapping(raw: Any) -> Dict[str, Any]:
    """Conserve uniquement les paramètres au nom raisonnable."""
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        param_name = key.strip()
        if not param_name or _looks_pathological_param_name(param_name):
            continue
        cleaned[param_name] = value
    return cleaned


def _sanitize_proposal_payload(
    proposal: Dict[str, Any],
    *,
    available_indicators: List[str],
    objective: str = "",
    direction_constraint: Optional[str] = None,
) -> Dict[str, Any]:
    """Nettoie/sauve une proposition LLM sans relâcher le contrat final."""
    if not isinstance(proposal, dict):
        return {}

    allowed = {
        "strategy_name",
        "hypothesis",
        "change_type",
        "indicator_override_reason",
        "used_indicators",
        "indicator_params",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
        "default_params",
        "parameter_specs",
        "direction_constraint",
    }
    cleaned: Dict[str, Any] = {
        k: v for k, v in proposal.items() if k in allowed
    }

    if not cleaned.get("entry_long_logic"):
        cleaned["entry_long_logic"] = str(
            proposal.get("long_logic")
            or proposal.get("long_entry")
            or proposal.get("long")
            or ""
        ).strip()
    if not cleaned.get("entry_short_logic"):
        cleaned["entry_short_logic"] = str(
            proposal.get("short_logic")
            or proposal.get("short_entry")
            or proposal.get("short")
            or ""
        ).strip()
    if not cleaned.get("exit_logic"):
        cleaned["exit_logic"] = "sortie sur signal inverse"

    if not cleaned.get("risk_management"):
        risk_raw = proposal.get("risk") or proposal.get("risk_rules")
        if isinstance(risk_raw, (dict, list)):
            cleaned["risk_management"] = json.dumps(risk_raw, ensure_ascii=False)
        else:
            cleaned["risk_management"] = str(risk_raw or "ATR stop/take-profit")

    known = {str(x or "").strip().lower() for x in available_indicators if str(x or "").strip()}
    objective_locked_indicators = _extract_objective_indicator_names(
        objective,
        available_indicators=available_indicators,
    )
    used = cleaned.get("used_indicators", [])
    normalized_used: List[str] = []
    if isinstance(used, list):
        for item in used:
            ind = _canonicalize_indicator_name(item, known=known)
            if ind and ind not in normalized_used:
                normalized_used.append(ind)
    if not normalized_used:
        if objective_locked_indicators:
            normalized_used = list(objective_locked_indicators)
        else:
            normalized_used = ["atr"] if "atr" in known else sorted(known)[:2]
    cleaned["used_indicators"] = normalized_used

    default_params = _sanitize_param_mapping(cleaned.get("default_params"))
    default_params["leverage"] = min(2, max(1, int(default_params.get("leverage", 1) or 1)))
    default_params.setdefault("stop_atr_mult", 1.5)
    default_params.setdefault("tp_atr_mult", 3.0)
    default_params.setdefault("warmup", 50)
    cleaned["default_params"] = default_params

    specs = _sanitize_param_mapping(cleaned.get("parameter_specs"))
    if "leverage" not in specs:
        specs["leverage"] = {"min": 1, "max": 2, "default": default_params["leverage"], "type": "int", "step": 1}
    if "stop_atr_mult" not in specs:
        specs["stop_atr_mult"] = {"min": 1.0, "max": 2.0, "default": default_params["stop_atr_mult"], "type": "float", "step": 0.1}
    if "tp_atr_mult" not in specs:
        specs["tp_atr_mult"] = {"min": 2.0, "max": 4.5, "default": default_params["tp_atr_mult"], "type": "float", "step": 0.1}
    cleaned["parameter_specs"] = specs

    cleaned["change_type"] = _normalize_change_type(cleaned.get("change_type", "logic"))
    cleaned["hypothesis"] = str(cleaned.get("hypothesis", "") or "").strip()
    if not cleaned["hypothesis"]:
        cleaned["hypothesis"] = "Ajustement structurel basé sur le diagnostic précédent."
    raw_override_reason = str(
        cleaned.get("indicator_override_reason", "") or ""
    ).strip()

    cleaned["strategy_name"] = str(cleaned.get("strategy_name", "builder_strategy") or "builder_strategy").strip()
    effective_direction = str(
        direction_constraint or _infer_direction_constraint_from_objective(objective)
    ).strip().lower()
    if effective_direction not in {"long_only", "short_only", "long_short"}:
        effective_direction = "long_short"
    cleaned["direction_constraint"] = effective_direction

    if objective_locked_indicators:
        objective_set = set(objective_locked_indicators)
        proposal_indicators = _normalize_required_indicator_names(
            cast(Optional[List[str]], cleaned.get("used_indicators"))
        )
        added = [ind for ind in proposal_indicators if ind not in objective_set]
        removed = [ind for ind in objective_locked_indicators if ind not in set(proposal_indicators)]
        allows_semi_open_override = (
            cleaned["change_type"] in {"logic", "both"}
            and len(proposal_indicators) <= max(1, len(objective_locked_indicators) + 1)
            and ((len(added) == 1 and len(removed) == 0) or (len(added) == 1 and len(removed) == 1))
        )
        if not proposal_indicators:
            cleaned["used_indicators"] = list(objective_locked_indicators)
            cleaned.pop("indicator_override_reason", None)
        elif not added and not removed:
            cleaned["used_indicators"] = proposal_indicators
            cleaned.pop("indicator_override_reason", None)
        elif allows_semi_open_override:
            cleaned["used_indicators"] = proposal_indicators
            cleaned["indicator_override_reason"] = (
                raw_override_reason
                or _build_indicator_override_reason(
                    objective_locked_indicators,
                    proposal_indicators,
                )
            )
        else:
            cleaned["used_indicators"] = list(objective_locked_indicators)
            cleaned.pop("indicator_override_reason", None)
    elif raw_override_reason:
        cleaned["indicator_override_reason"] = raw_override_reason
    else:
        cleaned.pop("indicator_override_reason", None)

    for key in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        val = cleaned.get(key, "")
        if isinstance(val, dict):
            val = _flatten_nested_logic(val)
        elif isinstance(val, list):
            val = " AND ".join(str(item) for item in val if item)
        cleaned[key] = str(val or "").strip()

    _PROPOSAL_SCRUB_PATTERNS = [
        (re.compile(r"\.iloc\b"), " (use numpy boolean indexing)"),
        (re.compile(r"\.loc\b"), " (use numpy boolean indexing)"),
        (re.compile(r"\.rolling\b"), " (pre-computed by indicator)"),
        (re.compile(r"\.shift\b"), " (use np.roll)"),
        (re.compile(r"\.ewm\b"), " (pre-computed by indicator)"),
        (re.compile(r"df\s*\[\s*['\"]signal['\"]\s*\]"), "signals array"),
    ]
    for key in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        val = cleaned.get(key, "")
        if not isinstance(val, str):
            continue
        for pat, repl in _PROPOSAL_SCRUB_PATTERNS:
            val = pat.sub(repl, val)
        cleaned[key] = val

    if effective_direction == "long_only":
        cleaned["entry_short_logic"] = ""
    elif effective_direction == "short_only":
        cleaned["entry_long_logic"] = ""

    return cleaned


def _is_empty_proposal(proposal: Dict[str, Any]) -> bool:
    """Vérifie si une proposition LLM est vide ou inutilisable."""
    if not proposal:
        return True
    hyp = str(proposal.get("hypothesis", "")).strip()
    inds = proposal.get("used_indicators", [])
    if not hyp or hyp in ("—", "-", "N/A", ""):
        return True
    if not inds:
        return True
    return False


# ---------------------------------------------------------------------------
# Sweep paramétrique Builder
# ---------------------------------------------------------------------------

def _coerce_builder_sweep_value(value: Any, param_type: str) -> Any:
    normalized_type = str(param_type or "").strip().lower()
    if normalized_type == "bool":
        return bool(value)
    numeric = float(value)
    if normalized_type == "int":
        return int(round(numeric))
    return round(numeric, 6)


def _build_builder_sweep_values(
    param_name: str,
    default_value: Any,
    spec: Dict[str, Any],
) -> List[Any]:
    param_type = str(spec.get("type", "") or "").strip().lower()
    if param_name in _BUILDER_SWEEP_EXCLUDED_PARAMS:
        return [default_value]

    if param_type == "bool":
        return _dedupe_preserve_order([bool(default_value), not bool(default_value)])

    if param_type not in {"int", "float"}:
        return [default_value]

    try:
        min_v = float(spec.get("min"))  # type: ignore[arg-type]
        max_v = float(spec.get("max"))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return [default_value]

    if min_v > max_v:
        return [default_value]

    try:
        default_numeric = float(
            default_value if default_value is not None else spec.get("default")  # type: ignore[arg-type]
        )
    except (ValueError, TypeError):
        default_numeric = float(spec.get("default", min_v) or min_v)  # type: ignore[arg-type]

    default_numeric = min(max(default_numeric, min_v), max_v)

    step_numeric: Optional[float] = None
    if spec.get("step") is not None:
        try:
            step_numeric = float(spec.get("step"))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            step_numeric = None
        if step_numeric is not None and step_numeric <= 0:
            step_numeric = None

    if step_numeric is not None:
        raw_values = [
            default_numeric,
            max(min_v, default_numeric - step_numeric),
            min(max_v, default_numeric + step_numeric),
        ]
    else:
        raw_values = [default_numeric, min_v, max_v]

    coerced = _dedupe_preserve_order(
        [
            _coerce_builder_sweep_value(value, param_type)
            for value in raw_values
        ]
    )
    return coerced[:3] if coerced else [default_value]


def _build_builder_sweep_plan(proposal: Dict[str, Any]) -> Dict[str, Any]:
    change_type = _normalize_change_type(proposal.get("change_type", "logic"))
    if change_type == "accept":
        return {
            "enabled": False,
            "reason": "accept_change_type",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    default_params = _sanitize_param_mapping(proposal.get("default_params"))
    parameter_specs = _sanitize_param_mapping(proposal.get("parameter_specs"))
    if not default_params or not parameter_specs:
        return {
            "enabled": False,
            "reason": "missing_parameter_specs",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    sweep_candidates: List[tuple[str, List[Any]]] = []
    for param_name, spec in parameter_specs.items():
        if not isinstance(spec, dict):
            continue
        default_value = default_params.get(param_name, spec.get("default"))
        values = _build_builder_sweep_values(param_name, default_value, spec)
        if len(values) > 1:
            sweep_candidates.append((param_name, values))

    if not sweep_candidates:
        return {
            "enabled": False,
            "reason": "single_point_only",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    selected: List[tuple[str, List[Any]]] = []
    current_combinations = 1
    for param_name, values in sweep_candidates[:_BUILDER_SWEEP_MAX_PARAMS]:
        limited_values = list(values[:3])
        while (
            len(limited_values) > 1
            and current_combinations * len(limited_values) > _BUILDER_SWEEP_MAX_COMBINATIONS
        ):
            limited_values = limited_values[:-1]
        if len(limited_values) <= 1:
            continue
        selected.append((param_name, limited_values))
        current_combinations *= len(limited_values)

    if not selected:
        return {
            "enabled": False,
            "reason": "max_combination_budget",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    param_names = [param_name for param_name, _ in selected]
    parameter_values = {param_name: list(values) for param_name, values in selected}
    param_grid: List[Dict[str, Any]] = []
    for combo in itertools.product(*(values for _, values in selected)):
        params = dict(default_params)
        for param_name, value in zip(param_names, combo):
            params[param_name] = value
        param_grid.append(params)

    return {
        "enabled": len(param_grid) > 1,
        "reason": "" if len(param_grid) > 1 else "single_point_only",
        "param_grid": param_grid[:_BUILDER_SWEEP_MAX_COMBINATIONS],
        "parameter_values": parameter_values,
        "param_names": param_names,
    }


# ---------------------------------------------------------------------------
# Fallback déterministe de proposition
# ---------------------------------------------------------------------------

def _build_deterministic_proposal_fallback(
    *,
    objective: str,
    available_indicators: List[str],
    last_iteration: "Union[BuilderIteration, Any, None]" = None,
    ctx: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Construit une proposition contractuelle minimale quand le LLM dérape."""
    # Accepte IterationContext ou BuilderIteration (import tardif pour éviter circularité)
    if ctx is None:
        from agents.builder_state import IterationContext
        ctx = last_iteration if isinstance(last_iteration, IterationContext) else IterationContext(last_iteration)
    objective_indicators = _extract_objective_indicator_names(
        objective,
        available_indicators=available_indicators,
    )
    known = [x.strip().lower() for x in available_indicators if isinstance(x, str) and x.strip()]
    if objective_indicators:
        used = objective_indicators[:5]
    else:
        preferred = [
            x for x in ["rsi", "ema", "atr", "bollinger", "supertrend", "adx", "stochastic"]
            if x in known
        ]
        used = preferred[:3] if len(preferred) >= 3 else (preferred or known[:2] or ["atr"])

    change_type = "logic"
    if ctx.is_category("approaching_target", "stable_positive"):
        change_type = "params"

    return {
        "strategy_name": "builder_strategy",
        "hypothesis": (
            "Fallback contractuel: proposition générée automatiquement pour maintenir "
            "la progression quand la sortie LLM n'est pas exploitable."
        ),
        "change_type": change_type,
        "used_indicators": used,
        "indicator_override_reason": "",
        "entry_long_logic": "Entrée long si momentum haussier confirmé et risque contrôlé.",
        "entry_short_logic": "Entrée short si momentum baissier confirmé et risque contrôlé.",
        "exit_logic": "Sortie sur signal inverse ou invalidation momentum.",
        "risk_management": "Leverage modéré, stop ATR, take-profit ATR.",
        "default_params": {
            "leverage": 1,
            "stop_atr_mult": 1.5,
            "tp_atr_mult": 3.0,
            "warmup": 50,
        },
        "parameter_specs": {
            "leverage": {"min": 1, "max": 2, "default": 1, "type": "int", "step": 1},
            "stop_atr_mult": {"min": 1.0, "max": 2.0, "default": 1.5, "type": "float", "step": 0.1},
            "tp_atr_mult": {"min": 2.0, "max": 4.5, "default": 3.0, "type": "float", "step": 0.1},
        },
    }


# ---------------------------------------------------------------------------
# Validation de proposition
# ---------------------------------------------------------------------------

def _proposal_issues(proposal: Dict[str, Any]) -> List[str]:
    """Retourne la liste des raisons rendant une proposition invalide."""
    issues: List[str] = []
    if not proposal:
        issues.append("empty_payload")
        return issues

    allowed_top_keys = {
        "strategy_name",
        "hypothesis",
        "change_type",
        "indicator_override_reason",
        "used_indicators",
        "indicator_params",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
        "default_params",
        "parameter_specs",
        "direction_constraint",
    }
    required_top_keys = set(_BUILDER_PROPOSAL_REQUIRED_KEYS)

    unknown_keys = sorted(set(proposal.keys()) - allowed_top_keys)
    if unknown_keys:
        issues.append("json_additional_properties_root")

    missing_keys = sorted(k for k in required_top_keys if k not in proposal)
    if missing_keys:
        issues.append("json_missing_required")

    hyp = str(proposal.get("hypothesis", "")).strip()
    inds = proposal.get("used_indicators", [])
    if not hyp or hyp in ("—", "-", "N/A", ""):
        issues.append("missing_hypothesis")
    if not isinstance(inds, list) or not inds:
        issues.append("missing_used_indicators")

    critical_fields = (
        "hypothesis",
        "entry_long_logic",
        "exit_logic",
        "risk_management",
    )
    for key in critical_fields:
        if _is_placeholder_text(proposal.get(key, "")):
            issues.append(f"placeholder_{key}")

    default_params = proposal.get("default_params")
    if default_params is not None and not isinstance(default_params, dict):
        issues.append("default_params_not_dict")

    parameter_specs = proposal.get("parameter_specs")
    if parameter_specs is not None and not isinstance(parameter_specs, dict):
        issues.append("parameter_specs_not_dict")
    elif isinstance(parameter_specs, dict):
        allowed_spec_keys = {"min", "max", "default", "type", "step"}
        for param_name, spec in parameter_specs.items():
            if not isinstance(spec, dict):
                issues.append("parameter_spec_item_not_dict")
                continue
            extra_spec_keys = set(spec.keys()) - allowed_spec_keys
            if extra_spec_keys:
                issues.append("parameter_spec_additional_properties")
            for required in ("min", "max", "default", "type"):
                if spec.get(required) is None:
                    issues.append("parameter_spec_missing_required")
                    break
            ptype = str(spec.get("type", "")).strip().lower()
            if ptype and ptype not in {"int", "float", "bool"}:
                issues.append("parameter_spec_invalid_type")
            try:
                min_v = float(spec.get("min"))  # type: ignore[arg-type]
                max_v = float(spec.get("max"))  # type: ignore[arg-type]
                if min_v > max_v:
                    issues.append("parameter_spec_min_gt_max")
            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                issues.append("parameter_spec_non_numeric_bounds")
            if "step" in spec and spec.get("step") is not None:
                try:
                    step = float(spec.get("step"))  # type: ignore[arg-type]
                    if step <= 0:
                        issues.append("parameter_spec_invalid_step")
                except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                    issues.append("parameter_spec_invalid_step")

    ct = _normalize_change_type(proposal.get("change_type", "logic"))
    if ct not in ("logic", "params", "both", "accept"):
        issues.append("invalid_change_type")

    dedup: List[str] = []
    for issue in issues:
        if issue not in dedup:
            dedup.append(issue)
    return dedup


def _proposal_has_placeholder_fields(proposal: Dict[str, Any]) -> bool:
    """Détecte les placeholders sur les champs critiques d'une proposition."""
    critical_fields = (
        "hypothesis",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
    )
    for key in critical_fields:
        if _is_placeholder_text(proposal.get(key, "")):
            return True
    return False


def _is_invalid_proposal(proposal: Dict[str, Any]) -> bool:
    """Validation minimale d'une proposition avant phase code."""
    return bool(_proposal_issues(proposal))


def _proposal_error_code(issues: List[str]) -> str:
    """Mappe les issues de proposition vers un code d'erreur stable."""
    if not issues:
        return ""
    joined = "|".join(issues)
    if "json_" in joined or "parameter_spec_" in joined:
        return ERR_JSON
    if "parameter" in joined or "default_params" in joined:
        return ERR_PARAM
    return ERR_DSL


def _proposal_reuses_previous_indicator_set(
    proposal: Dict[str, Any],
    previous_indicators: tuple[str, ...],
) -> bool:
    """Retourne True si la proposition recycle exactement le même set d'indicateurs."""
    if not previous_indicators:
        return False
    current = {
        str(ind).strip().lower()
        for ind in proposal.get("used_indicators", [])
        if str(ind).strip()
    }
    previous = {str(ind).strip().lower() for ind in previous_indicators if str(ind).strip()}
    return bool(current) and current == previous


def _proposal_has_meaningful_param_delta(
    previous_code: str,
    proposal: Dict[str, Any],
) -> bool:
    """Indique si une proposition params-only change réellement default_params."""
    previous_params = _sanitize_param_mapping(
        _extract_default_params_signature(previous_code)
    )
    current_params = _sanitize_param_mapping(proposal.get("default_params"))
    if not current_params:
        return False
    return current_params != previous_params


def _proposal_changes_indicator_set_in_params_mode(
    previous_code: str,
    proposal: Dict[str, Any],
) -> bool:
    """Détecte une proposition params-only qui change en réalité les indicateurs."""
    previous_indicators = {
        str(ind).strip().lower()
        for ind in _extract_required_indicators_signature(previous_code)
        if str(ind).strip()
    }
    current_indicators = {
        str(ind).strip().lower()
        for ind in proposal.get("used_indicators", [])
        if str(ind).strip()
    }
    if not previous_indicators or not current_indicators:
        return False
    return current_indicators != previous_indicators


def _params_only_contract_respected(previous_code: str, new_code: str) -> tuple[bool, str]:
    """Vérifie qu'une itération params-only n'a pas modifié la logique."""
    prev_inds = _extract_required_indicators_signature(previous_code)
    new_inds = _extract_required_indicators_signature(new_code)
    if prev_inds and new_inds and prev_inds != new_inds:
        return (
            False,
            f"required_indicators modifiés: avant={prev_inds} après={new_inds}",
        )

    prev_sig = _extract_generate_signals_signature(previous_code)
    new_sig = _extract_generate_signals_signature(new_code)
    if prev_sig and new_sig and prev_sig != new_sig:
        return (
            False,
            "generate_signals modifié alors que change_type=params",
        )

    return True, ""


def _rewrite_default_params_from_proposal(
    previous_code: str,
    proposal: Dict[str, Any],
) -> Optional[str]:
    """Réécrit uniquement default_params dans un code existant (mode params-only)."""
    default_params = proposal.get("default_params")
    if not isinstance(default_params, dict) or not default_params:
        return None

    pattern = re.compile(
        r"(?ms)^(\s*)(def\s+default_params\s*\(\s*self\s*\)\s*(?:->\s*[^:\n]+)?\s*:)\n"
        r".*?(?=^\1(?:def\s+|@property)|^\s*class\s+|\Z)"
    )
    match = pattern.search(previous_code)
    if not match:
        return None

    indent = match.group(1)
    def_header = match.group(2)
    body_indent = indent + "    "
    literal = _format_python_dict_literal(default_params)
    literal_lines = literal.splitlines() or ["{}"]

    if len(literal_lines) == 1:
        return_stmt = f"{body_indent}return {literal_lines[0]}\n"
    else:
        return_stmt = f"{body_indent}return {literal_lines[0]}\n"
        return_stmt += "".join(f"{body_indent}{line}\n" for line in literal_lines[1:])

    replacement = f"{indent}{def_header}\n{return_stmt}"

    patched = previous_code[:match.start()] + replacement + previous_code[match.end():]
    return patched


# Nécessaire pour le type hint forward reference
from agents.builder_state import BuilderIteration as BuilderIteration  # noqa: E402, F401
