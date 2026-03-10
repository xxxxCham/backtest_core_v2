"""
Module-ID: agents.validator

Purpose: Prendre la décision finale (APPROVE/REJECT/ITERATE/ABORT) avec synthèse des agents.

Role in pipeline: orchestration

Key components: ValidatorAgent, ValidationDecision, ValidatorResponse

Inputs: AgentContext complet (analyst_result, propositions, critic_evaluation)

Outputs: ValidationDecision (APPROVE/REJECT/ITERATE/ABORT) avec justifications

Dependencies: agents.base_agent, agents.state_machine, utils.template

Conventions: Decision irrévocable une fois APPROVED/REJECTED; ITERATE remet à ANALYZE; ABORT → FAILED; template Jinja2.

Read-if: Modification critères décision, seuils approbation, ou logique d'itération.

Skip-if: Vous ne changez que analyze/propose/critique.
"""

from __future__ import annotations

import time
from enum import Enum
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


class ValidationDecision(Enum):
    """Décisions possibles du Validator."""
    APPROVE = "APPROVE"      # Accepter la configuration
    REJECT = "REJECT"        # Rejeter définitivement
    ITERATE = "ITERATE"      # Continuer l'optimisation
    ABORT = "ABORT"          # Arrêter (problème grave)


# === Modèles Pydantic pour validation ===


class CriteriaCheck(BaseModel):
    """Vérification des critères objectifs."""
    sharpe_meets_minimum: bool = False
    drawdown_within_limit: bool = False
    overfitting_acceptable: bool = False
    sufficient_trades: bool = False
    critic_approved: bool = False


class AgentSynthesis(BaseModel):
    """Synthèse des contributions des agents."""
    analyst_key_points: List[str] = Field(default_factory=list)
    strategist_contribution: str = ""
    critic_concerns_addressed: bool = False


class ApprovedConfig(BaseModel):
    """Détails si décision APPROVE."""
    final_parameters: Dict[str, Any] = Field(default_factory=dict)
    expected_performance: Dict[str, Any] = Field(default_factory=dict)
    deployment_notes: List[str] = Field(default_factory=list)
    monitoring_recommendations: List[str] = Field(default_factory=list)


class IterateGuidance(BaseModel):
    """Détails si décision ITERATE."""
    focus_areas: List[str] = Field(default_factory=list)
    suggested_approach: str = ""
    max_more_iterations: int = Field(default=3, ge=1, le=20)


class RejectionDetails(BaseModel):
    """Détails si décision REJECT."""
    primary_reasons: List[str] = Field(default_factory=list)
    fundamental_issues: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class ValidatorResponse(BaseModel):
    """Structure de réponse complète du Validator."""
    decision: str = Field(..., pattern="^(APPROVE|REJECT|ITERATE|ABORT)$")
    confidence: int = Field(default=50, ge=0, le=100)
    summary: str = ""
    criteria_check: Optional[CriteriaCheck] = None
    agent_synthesis: Optional[AgentSynthesis] = None
    if_approved: Optional[ApprovedConfig] = None
    if_iterate: Optional[IterateGuidance] = None
    if_rejected: Optional[RejectionDetails] = None
    final_report: str = ""

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.upper().strip()
        return v if v in ("APPROVE", "REJECT", "ITERATE", "ABORT") else "ITERATE"


class ValidatorAgent(BaseAgent):
    """
    Agent Validator - Décideur final.

    Responsabilités:
    - Synthétiser les avis des agents
    - Vérifier les critères objectifs
    - Prendre la décision finale
    - Justifier clairement le verdict
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.VALIDATOR

    @property
    def system_prompt(self) -> str:
        return """You are the final decision-maker for trading strategy optimization.

Your role is to synthesize all agent reports and make the final call.

Decision criteria:
1. APPROVE: Configuration meets ALL requirements and is production-ready
   - Sharpe ratio >= minimum threshold
   - Drawdown <= maximum allowed
   - Overfitting ratio <= threshold
   - Sufficient trades for statistical validity
   - Approved by Critic with reasonable confidence

2. ITERATE: Promising but needs more optimization
   - Shows potential but doesn't meet all criteria
   - Clear path to improvement exists
   - Not at max iterations yet
   - Risk of overfitting is manageable

3. REJECT: Should stop optimization entirely
   - Fundamental strategy issues identified
   - Max iterations reached without meeting criteria
   - High overfitting that can't be fixed
   - Market regime mismatch

4. ABORT: Critical error requiring human intervention
   - System malfunction
   - Data quality issues
   - Inconsistent results

Your decision MUST be based on objective criteria, not feelings.
Be conservative - when in doubt, ITERATE rather than APPROVE.

Respond ONLY in valid JSON format with this exact structure:
{
    "decision": "APPROVE|REJECT|ITERATE|ABORT",
    "confidence": 0-100,
    "summary": "Brief summary of the decision rationale",

    "criteria_check": {
        "sharpe_meets_minimum": true/false,
        "drawdown_within_limit": true/false,
        "overfitting_acceptable": true/false,
        "sufficient_trades": true/false,
        "critic_approved": true/false
    },

    "agent_synthesis": {
        "analyst_key_points": ["point1", "point2"],
        "strategist_contribution": "summary",
        "critic_concerns_addressed": true/false
    },

    "if_approved": {
        "final_parameters": {"param": value},
        "expected_performance": {"metric": value},
        "deployment_notes": ["note1", "note2"],
        "monitoring_recommendations": ["rec1", "rec2"]
    },

    "if_iterate": {
        "focus_areas": ["area1", "area2"],
        "suggested_approach": "what to try next",
        "max_more_iterations": 3
    },

    "if_rejected": {
        "primary_reasons": ["reason1", "reason2"],
        "fundamental_issues": ["issue1"],
        "recommendations": ["what to do instead"]
    },

    "final_report": "Comprehensive final report paragraph"
}"""

    def execute(self, context: AgentContext) -> AgentResult:
        """
        Effectue la validation finale.

        Args:
            context: Contexte complet

        Returns:
            Décision finale
        """
        start_time = time.time()

        # Vérification préliminaire des critères objectifs
        objective_check = self._check_objective_criteria(context)

        # Construire le prompt
        user_prompt = self._build_validation_prompt(context, objective_check)

        # Appeler le LLM
        response = self._call_llm(user_prompt, json_mode=True, temperature=0.2)

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
        validation = response.parse_json()
        if validation is None:
            return AgentResult.failure_result(
                self.role,
                "Échec parsing JSON: %s" % (response.parse_error or "Unknown"),
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Validation Pydantic (best-effort)
        try:
            validated_resp = ValidatorResponse.model_validate(validation)
            logger.debug(
                "validator_response_validated decision=%s confidence=%d",
                validated_resp.decision, validated_resp.confidence,
            )
        except ValidationError as exc:
            logger.warning("validator_pydantic_partial errors=%d", len(exc.errors()))

        # Extraire la décision
        decision_str = validation.get("decision", "ITERATE")
        try:
            decision = ValidationDecision(decision_str)
        except ValueError:
            decision = ValidationDecision.ITERATE
            validation["decision"] = "ITERATE"

        # Valider la cohérence décision/critères
        decision = self._validate_decision_coherence(decision, objective_check, validation)
        validation["decision"] = decision.value

        # Extraire les données selon la décision
        result_data = {
            "validation": validation,
            "decision": decision.value,
            "confidence": validation.get("confidence", 50),
            "criteria_check": validation.get("criteria_check", objective_check),
            "final_report": validation.get("final_report", ""),
        }

        if decision == ValidationDecision.APPROVE:
            result_data["approved_config"] = validation.get("if_approved", {})
        elif decision == ValidationDecision.ITERATE:
            result_data["iterate_guidance"] = validation.get("if_iterate", {})
        elif decision == ValidationDecision.REJECT:
            result_data["rejection_details"] = validation.get("if_rejected", {})

        return AgentResult.success_result(
            self.role,
            content=validation.get("summary", ""),
            data=result_data,
            execution_time_ms=execution_time,
            tokens_used=response.total_tokens,
            llm_calls=1,
            raw_llm_response=response,
        )

    def _check_objective_criteria(self, context: AgentContext) -> Dict[str, bool]:
        """Vérifie les critères objectifs."""
        checks = {
            "sharpe_meets_minimum": False,
            "drawdown_within_limit": False,
            "overfitting_acceptable": False,
            "sufficient_trades": False,
            "critic_approved": False,
        }

        if context.current_metrics:
            metrics = context.current_metrics
            checks["sharpe_meets_minimum"] = metrics.sharpe_ratio >= context.min_sharpe
            checks["drawdown_within_limit"] = abs(metrics.max_drawdown) <= context.max_drawdown_limit
            checks["sufficient_trades"] = metrics.total_trades >= context.min_trades

        # Vérifier overfitting
        if context.overfitting_ratio > 0:
            checks["overfitting_acceptable"] = context.overfitting_ratio <= context.max_overfitting_ratio
        else:
            # Si pas de walk-forward, considérer acceptable par défaut
            checks["overfitting_acceptable"] = True

        # Vérifier si le critic a approuvé
        if context.strategist_proposals:
            # Chercher des propositions approuvées par le critic
            for prop in context.strategist_proposals:
                eval_data = prop.get("critic_evaluation", {})
                if eval_data.get("recommendation") == "APPROVE":
                    checks["critic_approved"] = True
                    break

        return checks

    def _build_validation_prompt(
        self,
        context: AgentContext,
        objective_check: Dict[str, bool],
    ) -> str:
        """Construit le prompt de validation via template Jinja2."""

        # Convertir MetricsSnapshot en dict pour le template
        current_metrics_dict = None
        if context.current_metrics:
            current_metrics_dict = context.current_metrics.to_dict()

        train_metrics_dict = None
        if context.train_metrics:
            train_metrics_dict = context.train_metrics.to_dict()

        test_metrics_dict = None
        if context.test_metrics:
            test_metrics_dict = context.test_metrics.to_dict()

        best_metrics_dict = None
        if context.best_metrics:
            best_metrics_dict = context.best_metrics.to_dict()

        template_context = {
            "strategy_name": context.strategy_name,
            "strategy_description": context.strategy_description,
            "iteration": context.iteration,
            "comparison_context": context.comparison_context,
            "objective_check": objective_check,
            "current_metrics": current_metrics_dict,
            "min_sharpe": context.min_sharpe,
            "max_drawdown_limit": context.max_drawdown_limit,
            "min_trades": context.min_trades,
            "overfitting_ratio": context.overfitting_ratio,
            "max_overfitting_ratio": context.max_overfitting_ratio,
            "classic_ratio": context.classic_ratio,
            "degradation_pct": context.degradation_pct,
            "test_stability_std": context.test_stability_std,
            "n_valid_folds": context.n_valid_folds,
            "walk_forward_windows": context.walk_forward_windows,
            "train_metrics": train_metrics_dict,
            "test_metrics": test_metrics_dict,
            "analyst_report": context.analyst_report,
            "strategist_proposals": context.strategist_proposals,
            "critic_concerns": context.critic_concerns,
            "iteration_history": context.iteration_history,
            "best_metrics": best_metrics_dict,
            "current_params": context.current_params,
            "memory_summary": context.memory_summary,
            "strategy_indicators_context": context.strategy_indicators_context,
            "readonly_indicators_context": context.readonly_indicators_context,
            "indicator_context_warnings": context.indicator_context_warnings,
        }

        return render_prompt("validator.jinja2", template_context)

    def _validate_decision_coherence(
        self,
        decision: ValidationDecision,
        objective_check: Dict[str, bool],
        validation: Dict[str, Any],
    ) -> ValidationDecision:
        """
        Valide la cohérence entre la décision et les critères.

        Empêche les décisions incohérentes (ex: APPROVE sans meeting criteria).
        """
        all_criteria_met = all(objective_check.values())

        # Ne pas APPROVE si tous les critères ne sont pas remplis
        if decision == ValidationDecision.APPROVE and not all_criteria_met:
            logger.warning(
                "validator_decision_override from=APPROVE to=ITERATE reason=criteria_not_met"
            )
            return ValidationDecision.ITERATE

        # Ne pas REJECT si on peut encore itérer et que c'est prometteur
        # (ceci est géré par l'orchestrator)

        return decision
