"""
Module-ID: agents.strategist

Purpose: Proposer des ajustements créatifs mais réalistes des paramètres basés sur l'analyse.

Role in pipeline: orchestration

Key components: StrategistAgent, ParameterProposal, ProposalList

Inputs: AgentContext (analyst_result, param_bounds, param_specs)

Outputs: Liste de ParameterProposal (params validés, justifications, priorités)

Dependencies: agents.base_agent, utils.template, utils.parameters

Conventions: Propositions clampées aux bornes; bornes min < max obligatoires; justifications exigées; template Jinja2.

Read-if: Modification propositions, créativité/conservatisme, ou clémence des contraintes.

Skip-if: Vous ne touchez qu'à analyze/critique/validate.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from utils.observability import get_obs_logger
from utils.template import render_prompt

from .base_agent import (
    AgentContext,
    AgentResult,
    AgentRole,
    BaseAgent,
)

logger = get_obs_logger(__name__)


# === Modèles Pydantic pour validation ===


class ExpectedImpact(BaseModel):
    """Impact attendu d'une proposition."""
    sharpe_ratio: str = ""
    drawdown: str = ""
    trade_frequency: str = ""


class ProposalItem(BaseModel):
    """Une proposition de paramètres du Strategist."""
    id: int
    name: str = Field(..., min_length=1)
    priority: str = Field(default="MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH)$")
    parameters: Dict[str, Any]
    rationale: str = Field(..., min_length=5)
    changes_from_current: Optional[Dict[str, Any]] = None
    expected_impact: Optional[ExpectedImpact] = None
    risks: List[str] = Field(default_factory=list)

    @field_validator("priority", "risk_level", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.upper().strip()
        return v if v in ("HIGH", "MEDIUM", "LOW") else "MEDIUM"


class SweepRequest(BaseModel):
    """Requête de grid search du Strategist."""
    ranges: Dict[str, Dict[str, float]]
    rationale: str = Field(..., min_length=5)
    optimize_for: str = "sharpe_ratio"
    max_combinations: int = Field(default=100, ge=1, le=10000)


class StrategistResponse(BaseModel):
    """Structure de réponse complète du Strategist."""
    analysis_summary: str = ""
    optimization_strategy: str = ""
    proposals: List[ProposalItem] = Field(default_factory=list)
    sweep: Optional[SweepRequest] = None
    constraints_respected: bool = True
    fallback_recommendation: str = ""


class StrategistAgent(BaseAgent):
    """
    Agent Strategist - Expert en optimisation de stratégies.

    Propose:
    - Ajustements de paramètres basés sur l'analyse
    - Combinaisons créatives mais réalistes
    - Prioritisation par impact/risque
    - Justifications détaillées
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.STRATEGIST

    @property
    def system_prompt(self) -> str:
        return """You are a senior quantitative strategist specializing in algorithmic trading strategy optimization.

Your expertise includes:
- Parameter optimization for trading strategies
- Understanding indicator behavior across different settings
- Balancing risk/reward trade-offs
- Creative but grounded strategy improvements
- Avoiding overfitting while maximizing performance

When proposing parameter changes:
1. Consider the analyst's findings and recommendations
2. Propose changes that address identified weaknesses
3. Stay within reasonable parameter bounds
4. Prioritize robustness over maximum performance
5. Consider how parameters interact with each other
6. Avoid drastic changes that might cause instability

IMPORTANT CONSTRAINTS:
- Each parameter must stay within its min/max bounds
- Propose 3-5 parameter sets, ordered by priority
- First proposal should be conservative, later ones more aggressive
- Always explain the rationale for each change

Respond ONLY in valid JSON format with this exact structure:
{
    "analysis_summary": "Brief summary of analyst findings you're addressing",
    "optimization_strategy": "Overall approach to optimization",
    "proposals": [
        {
            "id": 1,
            "name": "Conservative Adjustment",
            "priority": "HIGH|MEDIUM|LOW",
            "risk_level": "LOW|MEDIUM|HIGH",
            "parameters": {
                "param_name": value,
                ...
            },
            "changes_from_current": {
                "param_name": {"from": old_value, "to": new_value, "change_percent": X}
            },
            "rationale": "Why this configuration might improve performance",
            "expected_impact": {
                "sharpe_ratio": "+X% to +Y%",
                "drawdown": "similar|reduced|increased",
                "trade_frequency": "similar|higher|lower"
            },
            "risks": ["risk1", "risk2"]
        }
    ],
    "constraints_respected": true,
    "fallback_recommendation": "What to do if all proposals fail"
}"""

    def execute(self, context: AgentContext) -> AgentResult:
        """
        Génère des propositions de paramètres.

        Args:
            context: Contexte avec rapport analyst

        Returns:
            Liste de propositions ordonnées
        """
        start_time = time.time()

        # Construire le prompt
        user_prompt = self._build_proposal_prompt(context)

        # Appeler le LLM
        response = self._call_llm(user_prompt, json_mode=True, temperature=0.7)

        execution_time = (time.time() - start_time) * 1000

        # Vérifier la réponse
        if not response.content:
            return AgentResult.failure_result(
                self.role,
                "LLM n'a pas retourné de réponse",
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Parser le JSON
        proposals_data = response.parse_json()
        if proposals_data is None:
            return AgentResult.failure_result(
                self.role,
                "Échec parsing JSON: %s" % (response.parse_error or "Unknown"),
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Validation Pydantic (best-effort : on ne bloque pas si la structure est partielle)
        try:
            validated_response = StrategistResponse.model_validate(proposals_data)
            logger.debug(
                "strategist_response_validated proposals=%d sweep=%s",
                len(validated_response.proposals),
                validated_response.sweep is not None,
            )
        except ValidationError as exc:
            logger.warning("strategist_pydantic_partial errors=%d", len(exc.errors()))
            # Fallback : on continue avec les données brutes
            validated_response = None

        # Détecter un sweep request
        sweep = proposals_data.get("sweep")
        if sweep:
            return AgentResult.success_result(
                self.role,
                content=proposals_data.get("optimization_strategy", ""),
                data={"sweep": sweep},
                execution_time_ms=execution_time,
                tokens_used=response.total_tokens,
                llm_calls=1,
                raw_llm_response=response,
            )

        # Valider et corriger les propositions
        proposals = proposals_data.get("proposals", [])
        validated_proposals = self._validate_and_fix_proposals(proposals, context)

        if not validated_proposals:
            return AgentResult.failure_result(
                self.role,
                "Aucune proposition valide générée",
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Créer le résultat
        return AgentResult.success_result(
            self.role,
            content=proposals_data.get("optimization_strategy", ""),
            data={
                "proposals": validated_proposals,
                "analysis_summary": proposals_data.get("analysis_summary", ""),
                "optimization_strategy": proposals_data.get("optimization_strategy", ""),
                "fallback_recommendation": proposals_data.get("fallback_recommendation", ""),
                "total_proposals": len(validated_proposals),
            },
            execution_time_ms=execution_time,
            tokens_used=response.total_tokens,
            llm_calls=1,
            raw_llm_response=response,
        )

    def _build_proposal_prompt(self, context: AgentContext) -> str:
        """Construit le prompt de proposition via template Jinja2."""

        # Convertir MetricsSnapshot en dict pour le template
        current_metrics_dict = None
        if context.current_metrics:
            current_metrics_dict = context.current_metrics.to_dict()

        best_metrics_dict = None
        if context.best_metrics:
            best_metrics_dict = context.best_metrics.to_dict()

        template_context = {
            "strategy_name": context.strategy_name,
            "strategy_description": context.strategy_description,
            "iteration": context.iteration,
            "comparison_context": context.comparison_context,
            "param_specs": context.param_specs,
            "current_params": context.current_params,
            "current_metrics": current_metrics_dict,
            "overfitting_ratio": context.overfitting_ratio,
            "max_overfitting_ratio": context.max_overfitting_ratio,
            "analyst_report": context.analyst_report,
            "best_metrics": best_metrics_dict,
            "best_params": context.best_params,
            "optimization_target": context.optimization_target,
            "min_sharpe": context.min_sharpe,
            "max_drawdown_limit": context.max_drawdown_limit,
            "min_trades": context.min_trades,
            "iteration_history": context.iteration_history,
            # Résumé des paramètres déjà testés dans cette session
            "session_params_summary": getattr(context, 'session_params_summary', None),
            "memory_summary": context.memory_summary,
            "strategy_indicators_context": context.strategy_indicators_context,
            "readonly_indicators_context": context.readonly_indicators_context,
            "indicator_context_warnings": context.indicator_context_warnings,
        }

        return render_prompt("strategist.jinja2", template_context)

    def _validate_and_fix_proposals(
        self,
        proposals: List[Dict[str, Any]],
        context: AgentContext,
    ) -> List[Dict[str, Any]]:
        """
        Valide et corrige les propositions.

        S'assure que tous les paramètres respectent les contraintes.
        """
        validated = []

        # Créer un dict des specs pour lookup rapide
        specs_dict = {spec.name: spec for spec in context.param_specs}

        for proposal in proposals:
            params = proposal.get("parameters", {})
            fixed_params = {}

            # Vérifier chaque paramètre
            for param_name, value in params.items():
                if param_name not in specs_dict:
                    logger.warning("param_unknown_ignored name=%s", param_name)
                    continue

                spec = specs_dict[param_name]

                # Forcer les contraintes
                if spec.min_value is not None and value < spec.min_value:
                    logger.warning(
                        "param_clamped_min name=%s value=%s min=%s",
                        param_name, value, spec.min_value,
                    )
                    value = spec.min_value

                if spec.max_value is not None and value > spec.max_value:
                    logger.warning(
                        "param_clamped_max name=%s value=%s max=%s",
                        param_name, value, spec.max_value,
                    )
                    value = spec.max_value

                # Arrondir au step si spécifié
                if spec.step is not None and spec.step > 0:
                    if isinstance(value, float) and isinstance(spec.step, (int, float)):
                        value = round(value / spec.step) * spec.step
                    elif isinstance(value, int) and isinstance(spec.step, int):
                        value = (value // spec.step) * spec.step

                fixed_params[param_name] = value

            # Ajouter les paramètres manquants avec valeurs actuelles
            for param_name in specs_dict:
                if param_name not in fixed_params:
                    fixed_params[param_name] = context.current_params.get(
                        param_name,
                        specs_dict[param_name].current_value
                    )

            if fixed_params:
                proposal["parameters"] = fixed_params
                proposal["validated"] = True
                validated.append(proposal)

        return validated
