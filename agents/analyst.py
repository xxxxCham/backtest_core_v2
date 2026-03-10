"""
Module-ID: agents.analyst

Purpose: Analyser quantitativement les résultats de backtest et diagnostiquer les forces/faiblesses.

Role in pipeline: orchestration

Key components: AnalystAgent, AnalysisResponse, KeyMetricsAssessment

Inputs: AgentContext (métriques, configuration, walk-forward metrics optionnels)

Outputs: AnalysisResponse (JSON Pydantic validé) avec évaluations et ratings

Dependencies: agents.base_agent, utils.template, pydantic, utils.log

Conventions: Ratings en patterns stricts (EXCELLENT/GOOD/FAIR/POOR/CRITICAL); fields non-null; template Jinja2 + parse_json

Read-if: Modification analyse diagnostic, formules de notation, ou structure réponse.

Skip-if: Vous ne changez que propose/critique/validate.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

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

class MetricAssessment(BaseModel):
    """Évaluation d'une métrique individuelle."""
    value: float
    assessment: str = Field(..., min_length=1)


class KeyMetricsAssessment(BaseModel):
    """Évaluation des métriques clés."""
    sharpe_ratio: MetricAssessment
    max_drawdown: MetricAssessment
    win_rate: MetricAssessment
    profit_factor: MetricAssessment


class AnalysisResponse(BaseModel):
    """Structure de la réponse d'analyse du LLM.

    Utilise Pydantic pour validation robuste et typée.
    """
    summary: str = Field(..., min_length=10)
    performance_rating: str = Field(..., pattern="^(EXCELLENT|GOOD|FAIR|POOR|CRITICAL)$")
    risk_rating: str = Field(..., pattern="^(LOW|MODERATE|HIGH|EXTREME)$")
    overfitting_risk: str = Field(..., pattern="^(LOW|MODERATE|HIGH|CRITICAL)$")
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    key_metrics_assessment: KeyMetricsAssessment
    recommendations: List[str] = Field(default_factory=list)
    proceed_to_optimization: bool
    reasoning: str = Field(..., min_length=10)

    @field_validator('strengths', 'weaknesses', 'concerns', 'recommendations', mode='after')
    @classmethod
    def validate_non_empty_strings(cls, v):
        """Valide que les items de liste ne sont pas vides."""
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and not item.strip():
                    raise ValueError("Les items de liste ne doivent pas être vides")
            return [item.strip() if isinstance(item, str) else item for item in v]
        return v


class AnalystAgent(BaseAgent):
    """
    Agent Analyst - Expert en analyse quantitative.

    Analyse:
    - Performance absolue (rendement, sharpe, etc.)
    - Risque (drawdown, volatilité, etc.)
    - Qualité des trades (win rate, profit factor)
    - Overfitting (train vs test)
    - Tendances historiques (si plusieurs itérations)
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.ANALYST

    @property
    def system_prompt(self) -> str:
        return """You are a senior quantitative analyst specializing in algorithmic trading strategy evaluation.

Your expertise includes:
- Statistical analysis of trading performance metrics
- Risk assessment and drawdown analysis
- Detection of overfitting and curve-fitting issues
- Identification of market regime dependencies
- Recognition of strategy strengths and weaknesses

Your analysis must be:
- Data-driven and objective
- Structured and clear
- Actionable with specific recommendations
- Honest about limitations and risks

When analyzing, always consider:
1. Is the sample size (number of trades) sufficient for statistical significance?
2. Are the results consistent across train/test splits (walk-forward)?
3. Is the strategy robust or likely overfit to historical data?
4. What are the main risk factors?

Respond ONLY in valid JSON format with this exact structure:
{
    "summary": "Brief one-paragraph analysis summary",
    "performance_rating": "EXCELLENT|GOOD|FAIR|POOR|CRITICAL",
    "risk_rating": "LOW|MODERATE|HIGH|EXTREME",
    "overfitting_risk": "LOW|MODERATE|HIGH|CRITICAL",
    "strengths": ["strength1", "strength2", ...],
    "weaknesses": ["weakness1", "weakness2", ...],
    "concerns": ["concern1", "concern2", ...],
    "key_metrics_assessment": {
        "sharpe_ratio": {"value": X, "assessment": "..."},
        "max_drawdown": {"value": X, "assessment": "..."},
        "win_rate": {"value": X, "assessment": "..."},
        "profit_factor": {"value": X, "assessment": "..."}
    },
    "recommendations": ["recommendation1", "recommendation2", ...],
    "proceed_to_optimization": true/false,
    "reasoning": "Why proceed or not proceed"
}"""

    def execute(self, context: AgentContext) -> AgentResult:
        """
        Exécute l'analyse quantitative.

        Args:
            context: Contexte avec métriques

        Returns:
            Rapport d'analyse
        """
        start_time = time.time()

        # Construire le prompt utilisateur
        user_prompt = self._build_analysis_prompt(context)

        # Appeler le LLM
        response = self._call_llm(user_prompt, json_mode=True, temperature=0.3)

        execution_time = (time.time() - start_time) * 1000

        # Vérifier la réponse
        if not response.content:
            return AgentResult.failure_result(
                self.role,
                "LLM n'a pas retourné de réponse",
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Parser la réponse LLM avec try/except robuste
        try:
            analysis = response.parse_json()
            if analysis is None:
                return AgentResult.failure_result(
                    self.role,
                    f"Échec parse JSON: {response.parse_error or 'Unknown'}",
                    execution_time_ms=execution_time,
                    raw_llm_response=response,
                )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(f"Parse JSON crash: {e}")
            return AgentResult.failure_result(
                self.role,
                f"Exception parse JSON: {type(e).__name__} - {str(e)}",
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Valider la structure
        try:
            validation_errors = self._validate_analysis(analysis)
            if validation_errors:
                return AgentResult.failure_result(
                    self.role,
                    f"Structure d'analyse invalide: {validation_errors[0]}",
                    execution_time_ms=execution_time,
                    raw_llm_response=response,
                )
        except Exception as e:
            logger.error(f"Validation analysis crash: {e}")
            return AgentResult.failure_result(
                self.role,
                f"Exception validation: {type(e).__name__}",
                execution_time_ms=execution_time,
                raw_llm_response=response,
            )

        # Créer le résultat
        return AgentResult.success_result(
            self.role,
            content=analysis.get("summary", ""),
            data={
                "analysis": analysis,
                "performance_rating": analysis.get("performance_rating"),
                "risk_rating": analysis.get("risk_rating"),
                "overfitting_risk": analysis.get("overfitting_risk"),
                "proceed_to_optimization": analysis.get("proceed_to_optimization", False),
                "strengths": analysis.get("strengths", []),
                "weaknesses": analysis.get("weaknesses", []),
                "concerns": analysis.get("concerns", []),
                "recommendations": analysis.get("recommendations", []),
            },
            execution_time_ms=execution_time,
            tokens_used=response.total_tokens,
            llm_calls=1,
            raw_llm_response=response,
        )

    def _build_analysis_prompt(self, context: AgentContext) -> str:
        """Construit le prompt d'analyse via template Jinja2."""

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

        # Préparer le dictionnaire de contexte pour le template
        template_context = {
            "strategy_name": context.strategy_name,
            "strategy_description": context.strategy_description,
            "data_symbol": context.data_symbol,
            "data_timeframe": context.data_timeframe,
            "data_date_range": context.data_date_range,
            "data_rows": context.data_rows,
            "iteration": context.iteration,
            "comparison_context": context.comparison_context,
            "current_params": context.current_params,
            "param_specs": context.param_specs,
            "current_metrics": current_metrics_dict,
            "train_metrics": train_metrics_dict,
            "test_metrics": test_metrics_dict,
            "overfitting_ratio": context.overfitting_ratio,
            "max_overfitting_ratio": context.max_overfitting_ratio,
            "iteration_history": context.iteration_history,
            "optimization_target": context.optimization_target,
            "min_sharpe": context.min_sharpe,
            "max_drawdown_limit": context.max_drawdown_limit,
            "min_trades": context.min_trades,
            "memory_summary": context.memory_summary,
            "strategy_indicators_context": context.strategy_indicators_context,
            "readonly_indicators_context": context.readonly_indicators_context,
            "indicator_context_warnings": context.indicator_context_warnings,
        }

        # Rendre le template
        return render_prompt("analyst.jinja2", template_context)

    def _validate_analysis(self, analysis: Dict[str, Any]) -> List[str]:
        """Valide la structure de l'analyse avec Pydantic.

        Args:
            analysis: Dictionnaire JSON à valider

        Returns:
            Liste d'erreurs (vide si validation réussie)
        """
        try:
            # Validation Pydantic - lève ValidationError si invalide
            validated = AnalysisResponse.model_validate(analysis)

            # Validation réussie
            logger.debug(
                f"Analyse validée avec succès: {validated.performance_rating} "
                f"performance, {validated.risk_rating} risk"
            )
            return []  # Aucune erreur

        except ValidationError as e:
            # Extraire les messages d'erreur Pydantic
            errors = []
            for error in e.errors():
                field_path = " -> ".join(str(loc) for loc in error["loc"])
                error_msg = error["msg"]
                error_type = error["type"]

                errors.append(
                    f"Champ '{field_path}': {error_msg} (type: {error_type})"
                )

            logger.warning(f"Validation Pydantic échouée: {len(errors)} erreur(s)")
            return errors

        except Exception as e:
            # Erreur inattendue
            logger.error(f"Erreur inattendue lors validation Pydantic: {e}")
            return [f"Erreur validation: {type(e).__name__} - {str(e)}"]
