"""
Module-ID: catalog.builder_export

Purpose: Export des variants en Format A (texte structuré) et Format B (JSON proposal Builder).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from catalog.models import Archetype


def to_text_v1(
    proposal: Dict[str, Any],
    archetype: Optional[Archetype] = None,
) -> str:
    """
    Format A : texte structuré FICHE_STRATEGIE v1.

    Compatible prompt Builder LLM. Chaque fiche est un bloc de texte
    lisible et injectable comme "objective".
    """
    lines = ["FICHE_STRATEGIE v1"]

    # ID
    strategy_name = proposal.get("strategy_name", "unknown")
    lines.append(f"id: {strategy_name}")

    # Archetype
    if archetype:
        lines.append(f"archetype: {archetype.archetype_id}")
        lines.append(f"family: {archetype.family}")
        lines.append(f"timeframe: {archetype.timeframe}")
        lines.append(f"side: {archetype.side}")

    # Indicateurs
    used = proposal.get("used_indicators", [])
    ind_params = proposal.get("indicator_params", {})
    lines.append("indicators:")
    for ind in used:
        params_str = ""
        if ind in ind_params:
            params_parts = [f"{k}={v}" for k, v in ind_params[ind].items()]
            params_str = f"({', '.join(params_parts)})"
        lines.append(f"  - {ind}{params_str}")

    # Entry/Exit
    lines.append("entry:")
    entry_long = proposal.get("entry_long_logic", "")
    if entry_long:
        lines.append(f"  - long: {entry_long}")
    entry_short = proposal.get("entry_short_logic", "")
    if entry_short:
        lines.append(f"  - short: {entry_short}")

    lines.append("exit:")
    exit_logic = proposal.get("exit_logic", "")
    if exit_logic:
        lines.append(f"  - condition: {exit_logic}")

    # Risk
    lines.append("risk:")
    default_params = proposal.get("default_params", {})
    risk_mgmt = proposal.get("risk_management", "")

    if "stop_atr_mult" in default_params:
        lines.append(f"  stop_atr_mult: {default_params['stop_atr_mult']}")
    if "stop_loss_pct" in default_params:
        lines.append(f"  stop_loss_pct: {default_params['stop_loss_pct']}")
    if "tp_atr_mult" in default_params:
        lines.append(f"  tp_atr_mult: {default_params['tp_atr_mult']}")
    if "take_profit_pct" in default_params:
        lines.append(f"  take_profit_pct: {default_params['take_profit_pct']}")
    if risk_mgmt:
        lines.append(f"  description: {risk_mgmt}")

    # Constraints
    lines.append("constraints:")
    lines.append("  - no_lookahead: true")
    lines.append("  - only_registry_indicators: true")

    return "\n".join(lines)


def to_json_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format B : JSON proposal compatible StrategyBuilder.

    Retourne un dict avec toutes les clés requises par _BUILDER_PROPOSAL_REQUIRED_KEYS :
    strategy_name, used_indicators, entry_long_logic, exit_logic,
    risk_management, default_params, parameter_specs
    """
    # S'assurer que toutes les clés obligatoires sont présentes
    result: Dict[str, Any] = {
        "strategy_name": proposal.get("strategy_name", "catalog_variant"),
        "hypothesis": proposal.get("hypothesis", ""),
        "change_type": proposal.get("change_type", "logic"),
        "used_indicators": proposal.get("used_indicators", []),
        "indicator_params": proposal.get("indicator_params", {}),
        "entry_long_logic": proposal.get("entry_long_logic", ""),
        "entry_short_logic": proposal.get("entry_short_logic", ""),
        "exit_logic": proposal.get("exit_logic", ""),
        "risk_management": proposal.get("risk_management", ""),
        "default_params": proposal.get("default_params", {}),
        "parameter_specs": proposal.get("parameter_specs", {}),
    }

    # Forcer leverage=1
    result["default_params"].setdefault("leverage", 1)
    result["default_params"].setdefault("warmup", 50)

    return result
