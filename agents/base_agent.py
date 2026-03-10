"""
Module-ID: agents.base_agent

Purpose: Classe abstraite et structures communes pour tous les agents LLM (Analyst/Strategist/Critic/Validator).

Role in pipeline: orchestration

Key components: BaseAgent (abstract), AgentRole, MetricsSnapshot, ParameterConfig, AgentContext, AgentResult

Inputs: AgentContext (état partagé entre agents)

Outputs: AgentResult (succès/erreur + résultat typé)

Dependencies: agents.llm_client, agents.state_machine, utils.log

Conventions: Chaque agent implémente execute() et role property; _call_llm() helper pour requêtes LLM; AgentContext immuable entre appels.

Read-if: Modification contrat agent, ajout de nouvelles structures, ou intégration LLM.

Skip-if: Vous ne changez qu'un agent spécifique.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from utils.observability import get_obs_logger

from .llm_client import LLMClient, LLMMessage, LLMResponse
from .state_machine import ValidationResult

logger = get_obs_logger(__name__)


class AgentRole(Enum):
    """Rôles des agents."""
    ANALYST = "analyst"
    STRATEGIST = "strategist"
    CRITIC = "critic"
    VALIDATOR = "validator"


@dataclass
class MetricsSnapshot:
    """Snapshot des métriques de performance."""

    # Métriques de base
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Métriques Tier S
    sqn: float = 0.0
    calmar_ratio: float = 0.0
    recovery_factor: float = 0.0
    ulcer_index: float = 0.0

    # Stats trades
    total_trades: int = 0
    avg_trade_duration: float = 0.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MetricsSnapshot:
        """Crée depuis un dictionnaire."""
        total_return = data.get("total_return")
        if total_return is None:
            total_return_pct = data.get("total_return_pct", 0.0)
            total_return = total_return_pct / 100.0

        max_drawdown = data.get("max_drawdown", 0.0)
        if abs(max_drawdown) > 1.0:
            max_drawdown = max_drawdown / 100.0

        win_rate = data.get("win_rate", 0.0)
        if win_rate > 1.0:
            win_rate = win_rate / 100.0

        avg_trade_duration = data.get("avg_trade_duration")
        if avg_trade_duration is None:
            avg_trade_duration = data.get("avg_trade_duration_hours", 0.0)

        return cls(
            total_return=total_return,
            sharpe_ratio=data.get("sharpe_ratio", 0.0),
            sortino_ratio=data.get("sortino_ratio", 0.0),
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=data.get("profit_factor", 0.0),
            sqn=data.get("sqn", 0.0),
            calmar_ratio=data.get("calmar_ratio", 0.0),
            recovery_factor=data.get("recovery_factor", 0.0),
            ulcer_index=data.get("ulcer_index", 0.0),
            total_trades=data.get("total_trades", 0),
            avg_trade_duration=avg_trade_duration,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "sqn": self.sqn,
            "calmar_ratio": self.calmar_ratio,
            "recovery_factor": self.recovery_factor,
            "ulcer_index": self.ulcer_index,
            "total_trades": self.total_trades,
            "avg_trade_duration": self.avg_trade_duration,
        }

    def to_summary_str(self) -> str:
        """Résumé textuel pour le LLM."""
        return f"""Performance Metrics:
- Total Return: {self.total_return:.2%}
- Sharpe Ratio: {self.sharpe_ratio:.2f}
- Sortino Ratio: {self.sortino_ratio:.2f}
- Max Drawdown: {self.max_drawdown:.2%}
- Win Rate: {self.win_rate:.2%}
- Profit Factor: {self.profit_factor:.2f}
- SQN: {self.sqn:.2f}
- Calmar Ratio: {self.calmar_ratio:.2f}
- Recovery Factor: {self.recovery_factor:.2f}
- Total Trades: {self.total_trades}"""


@dataclass
class ParameterConfig:
    """Configuration d'un paramètre de stratégie."""

    name: str
    current_value: Any
    min_value: Any = None
    max_value: Any = None
    step: Any = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "current_value": self.current_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step": self.step,
            "description": self.description,
        }


@dataclass
class AgentContext:
    """
    Contexte partagé entre les agents.

    Contient toutes les informations nécessaires pour
    l'analyse et la prise de décision.
    """

    # Identification
    session_id: str = ""
    iteration: int = 0

    # Stratégie
    strategy_name: str = ""
    strategy_description: str = ""
    current_params: Dict[str, Any] = field(default_factory=dict)
    param_specs: List[ParameterConfig] = field(default_factory=list)

    # Données
    data_path: str = ""
    data_symbol: str = ""
    data_timeframe: str = ""
    data_rows: int = 0
    data_date_range: str = ""
    comparison_context: Optional[Dict[str, Any]] = None

    # Résultats actuels
    current_metrics: Optional[MetricsSnapshot] = None
    train_metrics: Optional[MetricsSnapshot] = None
    test_metrics: Optional[MetricsSnapshot] = None

    # Walk-forward results
    walk_forward_results: List[Dict[str, Any]] = field(default_factory=list)
    overfitting_ratio: float = 0.0
    classic_ratio: float = 0.0
    degradation_pct: float = 0.0
    test_stability_std: float = 0.0
    n_valid_folds: int = 0
    walk_forward_windows: int = 0

    # Historique des itérations
    iteration_history: List[Dict[str, Any]] = field(default_factory=list)
    best_metrics: Optional[MetricsSnapshot] = None
    best_params: Dict[str, Any] = field(default_factory=dict)

    # Objectifs
    optimization_target: str = "sharpe_ratio"
    min_sharpe: float = 1.0
    max_drawdown_limit: float = 0.20
    min_trades: int = 30
    max_overfitting_ratio: float = 1.5

    # Messages des agents précédents
    analyst_report: str = ""
    strategist_proposals: List[Dict[str, Any]] = field(default_factory=list)
    critic_assessment: str = ""
    critic_concerns: List[str] = field(default_factory=list)
    memory_summary: str = ""

    # Contexte indicateurs (stratégie vs lecture seule)
    strategy_indicators_context: str = ""
    readonly_indicators_context: str = ""
    indicator_context_warnings: List[str] = field(default_factory=list)

    # Résultats de sweep (LLM grid search)
    sweep_results: Optional[Dict[str, Any]] = None
    sweep_summary: str = ""

    def to_summary_str(self) -> str:
        """Résumé textuel pour le LLM."""
        summary = f"""=== Optimization Context ===
Strategy: {self.strategy_name}
Data: {self.data_symbol} {self.data_timeframe} ({self.data_rows} rows)
Date Range: {self.data_date_range}
Iteration: {self.iteration}

Current Parameters:
{self._params_to_str()}

Optimization Objectives:
- Target: {self.optimization_target}
- Min Sharpe: {self.min_sharpe}
- Max Drawdown: {self.max_drawdown_limit:.0%}
- Min Trades: {self.min_trades}
- Max Overfitting Ratio: {self.max_overfitting_ratio}
"""

        if self.current_metrics:
            summary += f"\n{self.current_metrics.to_summary_str()}"

        if self.train_metrics and self.test_metrics:
            summary += f"""

Walk-Forward Analysis:
- Train Sharpe: {self.train_metrics.sharpe_ratio:.2f}
- Test Sharpe: {self.test_metrics.sharpe_ratio:.2f}
- Overfitting Ratio: {self.overfitting_ratio:.2f}
"""

        return summary

    def _params_to_str(self) -> str:
        """Formate les paramètres en string."""
        lines = []
        for k, v in self.current_params.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines) if lines else "  (none)"


@dataclass
class AgentResult:
    """
    Résultat d'exécution d'un agent.

    Contient:
    - Le succès/échec
    - Les données produites
    - Les erreurs éventuelles
    - Les métriques de performance
    """

    success: bool
    agent_role: AgentRole

    # Contenu principal
    content: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    # Erreurs et avertissements
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Métriques d'exécution
    execution_time_ms: float = 0.0
    tokens_used: int = 0
    llm_calls: int = 0

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)

    # Réponse LLM brute (pour debug)
    raw_llm_response: Optional[LLMResponse] = None

    @classmethod
    def success_result(
        cls,
        role: AgentRole,
        content: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> AgentResult:
        """Crée un résultat de succès."""
        return cls(
            success=True,
            agent_role=role,
            content=content,
            data=data or {},
            **kwargs,
        )

    @classmethod
    def failure_result(
        cls,
        role: AgentRole,
        error: str,
        **kwargs,
    ) -> AgentResult:
        """Crée un résultat d'échec."""
        return cls(
            success=False,
            agent_role=role,
            errors=[error],
            **kwargs,
        )

    def to_validation_result(self) -> ValidationResult:
        """Convertit en ValidationResult pour la state machine."""
        if self.success:
            return ValidationResult.success(
                message=self.content[:100] if self.content else "OK",
                **self.data,
            )
        else:
            return ValidationResult.failure(
                message=self.errors[0] if self.errors else "Unknown error",
                errors=self.errors,
            )


class BaseAgent(ABC):
    """
    Classe de base pour tous les agents LLM.

    Chaque agent doit implémenter:
    - role: Son rôle dans le workflow
    - system_prompt: Le prompt système définissant sa personnalité
    - execute(): La logique d'exécution principale
    - validate_result(): Validation du résultat produit
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialise l'agent.

        Args:
            llm_client: Client LLM à utiliser
        """
        self.llm = llm_client
        self._execution_count = 0
        self._total_tokens = 0

    @property
    @abstractmethod
    def role(self) -> AgentRole:
        """Rôle de l'agent."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Prompt système définissant la personnalité de l'agent."""
        pass

    @abstractmethod
    def execute(self, context: AgentContext) -> AgentResult:
        """
        Exécute la tâche principale de l'agent.

        Args:
            context: Contexte d'exécution

        Returns:
            Résultat de l'exécution
        """
        pass

    def validate_result(self, result: AgentResult) -> ValidationResult:
        """
        Valide le résultat produit par l'agent.

        Args:
            result: Résultat à valider

        Returns:
            Résultat de validation
        """
        if not result.success:
            return ValidationResult.failure(
                f"Agent {self.role.value} a échoué",
                errors=result.errors,
            )

        if not result.content and not result.data:
            return ValidationResult.failure(
                f"Agent {self.role.value} n'a produit aucun résultat"
            )

        return ValidationResult.success()

    def _call_llm(
        self,
        user_message: str,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """
        Appelle le LLM avec le prompt système de l'agent.

        Args:
            user_message: Message utilisateur
            json_mode: Forcer réponse JSON
            temperature: Override température

        Returns:
            Réponse LLM
        """
        messages = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=user_message),
        ]

        response = self.llm.chat(
            messages,
            json_mode=json_mode,
            temperature=temperature,
        )

        self._execution_count += 1
        self._total_tokens += response.total_tokens

        return response

    @property
    def stats(self) -> Dict[str, Any]:
        """Statistiques de l'agent."""
        return {
            "role": self.role.value,
            "execution_count": self._execution_count,
            "total_tokens": self._total_tokens,
        }
