"""
Module-ID: backtest.facade

Purpose: Interface stable et typée entre l'UI et le backend (BacktestEngine + agents LLM).

Role in pipeline: orchestration / api

Key components: BackendFacade, BacktestRequest, BackendResponse, ResponseStatus, ErrorCode

Inputs: BacktestRequest (params, stratégie, données), validation_fn optionnel

Outputs: BackendResponse (format unifié), erreurs structurées (jamais de traceback brut UI)

Dependencies: backtest.engine, backtest.errors, utils.config, dataclasses

Conventions: Erreurs via Response.status/error_code/error_message (jamais exceptions UI); contrats Request/Response immuables; warmup auto >= 200.

Read-if: Modification l'API UI↔backend, erreurs struct, ou contrats de réponse.

Skip-if: Vous ne touchez qu'au moteur backtest pur.
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.engine import BacktestEngine, RunResult
from backtest.errors import (
    DataError,
    InsufficientDataError,
    UserInputError,
)
from metrics_types import UIMetricsPct, normalize_metrics
from utils.config import Config
from utils.log import get_logger

logger = get_logger(__name__)

# Warmup minimal par défaut (conservateur pour couvrir la plupart des stratégies)
WARMUP_MIN_DEFAULT = 200


# =============================================================================
# ENUMS & STATUS
# =============================================================================

class ResponseStatus(Enum):
    """Status de réponse du backend."""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"  # Succès partiel (ex: grille avec quelques échecs)


class ErrorCode(Enum):
    """Codes d'erreur pour l'UI."""
    INVALID_PARAMS = "invalid_params"
    INVALID_DATA = "invalid_data"
    DATA_NOT_FOUND = "data_not_found"
    INSUFFICIENT_DATA = "insufficient_data"
    STRATEGY_NOT_FOUND = "strategy_not_found"
    BACKEND_INTERNAL = "backend_internal"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_CONNECTION_FAILED = "llm_connection_failed"
    OPTIMIZATION_FAILED = "optimization_failed"


# =============================================================================
# REQUEST DATACLASSES
# =============================================================================

@dataclass
class BacktestRequest:
    """
    Requête pour un backtest simple.

    Attributes:
        strategy_name: Nom de la stratégie (ex: "ema_cross")
        params: Paramètres de la stratégie
        data: DataFrame OHLCV OU None (si symbol/timeframe fournis)
        symbol: Symbole pour charger les données
        timeframe: Timeframe pour charger les données
        initial_capital: Capital de départ
        date_start: Date de début (optionnel)
        date_end: Date de fin (optionnel)
    """
    strategy_name: str
    params: Dict[str, Any]
    data: Optional[pd.DataFrame] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    initial_capital: float = 10000.0
    date_start: Optional[str] = None
    date_end: Optional[str] = None

    def __post_init__(self):
        """Validation à la création."""
        if self.data is None and (self.symbol is None or self.timeframe is None):
            raise ValueError("Soit 'data' soit 'symbol'+'timeframe' requis")


@dataclass
class GridOptimizationRequest:
    """
    Requête pour une optimisation en grille.

    Attributes:
        strategy_name: Nom de la stratégie
        param_grid: Liste de dicts de paramètres à tester
        data: DataFrame OHLCV
        initial_capital: Capital de départ
        max_combinations: Limite de combinaisons
        metric_to_optimize: Métrique à maximiser ("sharpe", "return", etc.)
    """
    strategy_name: str
    param_grid: List[Dict[str, Any]]
    data: pd.DataFrame
    initial_capital: float = 10000.0
    max_combinations: int = 10000
    metric_to_optimize: str = "sharpe_ratio"
    symbol: str = "UNKNOWN"
    timeframe: str = "1h"


@dataclass
class LLMOptimizationRequest:
    """
    Requête pour une optimisation LLM autonome.

    Attributes:
        strategy_name: Nom de la stratégie
        initial_params: Paramètres de départ
        param_bounds: Bornes {param: (min, max)}
        data: DataFrame OHLCV
        llm_provider: "ollama" ou "openai"
        llm_model: Nom du modèle
        llm_api_key: Clé API (pour OpenAI)
        llm_base_url: URL (pour Ollama)
        max_iterations: Nombre max d'itérations
        use_walk_forward: Activer validation anti-overfitting
        initial_capital: Capital de départ
    """
    strategy_name: str
    initial_params: Dict[str, Any]
    param_bounds: Dict[str, tuple]
    data: pd.DataFrame
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"
    llm_api_key: Optional[str] = None
    llm_base_url: str = "http://localhost:11434"
    max_iterations: int = 10
    use_walk_forward: bool = True
    initial_capital: float = 10000.0
    target_sharpe: float = 2.0


# =============================================================================
# RESPONSE DATACLASSES
# =============================================================================

@dataclass
class UIMetrics:
    """
    Métriques formatées pour l'affichage UI.

    Format stable garanti - l'UI peut dépendre de ces champs.
    """
    # Rendement
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    annualized_return: float = 0.0

    # Risque
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility_annual: float = 0.0

    # Trading
    total_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # Avancé (optionnel)
    sqn: Optional[float] = None
    recovery_factor: Optional[float] = None

    @classmethod
    def from_run_result(cls, result: RunResult) -> "UIMetrics":
        """Crée UIMetrics depuis un RunResult."""
        m = normalize_metrics(result.metrics, "pct")
        return cls(
            total_pnl=m.get("total_pnl", 0.0),
            total_return_pct=m.get("total_return_pct", 0.0),
            annualized_return=m.get("annualized_return", 0.0),
            sharpe_ratio=m.get("sharpe_ratio", 0.0),
            sortino_ratio=m.get("sortino_ratio", 0.0),
            calmar_ratio=m.get("calmar_ratio", 0.0),
            max_drawdown_pct=m.get("max_drawdown_pct", 0.0),
            volatility_annual=m.get("volatility_annual", 0.0),
            total_trades=m.get("total_trades", 0),
            win_rate_pct=m.get("win_rate_pct", 0.0),
            profit_factor=m.get("profit_factor", 0.0),
            expectancy=m.get("expectancy", 0.0),
            sqn=m.get("sqn"),
            recovery_factor=m.get("recovery_factor"),
        )

    def to_dict(self) -> UIMetricsPct:
        """Convertit en dict pour sérialisation."""
        return {
            "total_pnl": self.total_pnl,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "volatility_annual": self.volatility_annual,
            "total_trades": self.total_trades,
            "win_rate_pct": self.win_rate_pct,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "sqn": self.sqn,
            "recovery_factor": self.recovery_factor,
        }


@dataclass
class UIPayload:
    """
    Payload complet pour l'affichage UI.

    Contient toutes les données nécessaires pour afficher un résultat de backtest.
    """
    metrics: UIMetrics
    equity_series: Optional[pd.Series] = None
    trades_df: Optional[pd.DataFrame] = None
    params_used: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_run_result(cls, result: RunResult) -> "UIPayload":
        """Crée UIPayload depuis un RunResult."""
        return cls(
            metrics=UIMetrics.from_run_result(result),
            equity_series=result.equity,
            trades_df=result.trades,
            params_used=result.meta.get("params", {}),
            meta=result.meta,
        )


@dataclass
class ErrorInfo:
    """
    Information d'erreur structurée.

    L'UI utilise ces champs pour afficher un message cohérent.
    """
    code: ErrorCode
    message_user: str  # Message compréhensible pour l'utilisateur
    hint: Optional[str] = None  # Suggestion de correction
    trace_id: Optional[str] = None  # ID pour debug/logs
    details: Optional[str] = None  # Stack trace (mode debug)

    def __post_init__(self):
        if self.trace_id is None:
            self.trace_id = str(uuid.uuid4())[:8]


@dataclass
class BackendResponse:
    """
    Réponse unifiée du backend vers l'UI.

    Contrat stable:
    - status: toujours présent
    - payload: présent si SUCCESS
    - error: présent si ERROR
    """
    status: ResponseStatus
    payload: Optional[UIPayload] = None
    error: Optional[ErrorInfo] = None
    message: str = ""  # Message de statut court
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.status == ResponseStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        return self.status == ResponseStatus.ERROR


@dataclass
class GridOptimizationResponse:
    """Réponse d'une optimisation en grille."""
    status: ResponseStatus
    results: List[Dict[str, Any]] = field(default_factory=list)  # Tous les résultats
    best_result: Optional[UIPayload] = None  # Meilleur résultat
    best_params: Dict[str, Any] = field(default_factory=dict)
    error: Optional[ErrorInfo] = None
    total_tested: int = 0
    total_success: int = 0
    total_failed: int = 0
    duration_ms: float = 0.0


@dataclass
class LLMOptimizationResponse:
    """Réponse d'une optimisation LLM."""
    status: ResponseStatus
    best_result: Optional[UIPayload] = None
    best_params: Dict[str, Any] = field(default_factory=dict)
    iterations_history: List[Dict[str, Any]] = field(default_factory=list)
    total_iterations: int = 0
    convergence_reason: Optional[str] = None
    improvement_pct: float = 0.0
    error: Optional[ErrorInfo] = None
    duration_ms: float = 0.0


# =============================================================================
# FACADE PRINCIPALE
# =============================================================================

class BackendFacade:
    """
    Façade principale pour toutes les interactions UI ↔ Backend.

    Point d'entrée unique garantissant:
    - Validation des entrées
    - Gestion d'erreurs centralisée
    - Format de sortie unifié
    - Traçabilité

    Usage:
        facade = BackendFacade()
        response = facade.run_backtest(request)

        if response.is_success:
            display_results(response.payload)
        else:
            show_error(response.error)
    """

    def __init__(self, config: Optional[Config] = None, debug: bool = False):
        """
        Initialise la façade.

        Args:
            config: Configuration globale
            debug: Inclure les stack traces dans les erreurs
        """
        self.config = config or Config()
        self.debug = debug
        self._logger = get_logger(__name__)

    # =========================================================================
    # BACKTEST SIMPLE
    # =========================================================================

    def run_backtest(self, request: BacktestRequest) -> BackendResponse:
        """
        Exécute un backtest simple.

        Args:
            request: BacktestRequest avec stratégie, params, data

        Returns:
            BackendResponse avec payload ou erreur
        """
        import time
        start = time.time()
        trace_id = str(uuid.uuid4())[:8]

        self._logger.info(f"[{trace_id}] run_backtest: {request.strategy_name}")

        try:
            # 1. Charger les données si nécessaire
            if request.data is None:
                df = self._load_data(
                    request.symbol,
                    request.timeframe,
                    request.date_start,
                    request.date_end
                )
            else:
                df = request.data

            # 2. Valider les données
            self._validate_dataframe(df)

            # 3. Créer et exécuter le backtest
            engine = BacktestEngine(
                initial_capital=request.initial_capital,
                config=self.config
            )

            result = engine.run(
                df=df,
                strategy=request.strategy_name,
                params=request.params,
                symbol=request.symbol or "UNKNOWN",
                timeframe=request.timeframe or "1h",
            )

            # 4. Convertir en payload UI
            payload = UIPayload.from_run_result(result)
            duration_ms = (time.time() - start) * 1000

            return BackendResponse(
                status=ResponseStatus.SUCCESS,
                payload=payload,
                message=f"Backtest terminé | Sharpe: {payload.metrics.sharpe_ratio:.2f}",
                duration_ms=duration_ms,
            )

        except UserInputError as e:
            return self._error_response(
                ErrorCode.INVALID_PARAMS, str(e),
                hint="Vérifiez les paramètres de stratégie",
                trace_id=trace_id, start_time=start
            )
        except InsufficientDataError as e:
            return self._error_response(
                ErrorCode.INSUFFICIENT_DATA,
                str(e),
                hint=e.hint,
                trace_id=trace_id,
                start_time=start
            )
        except DataError as e:
            return self._error_response(
                ErrorCode.INVALID_DATA, str(e),
                hint="Vérifiez le format des données OHLCV",
                trace_id=trace_id, start_time=start
            )
        except ValueError as e:
            error_str = str(e).lower()
            if "stratégie" in error_str or "strategy" in error_str:
                return self._error_response(
                    ErrorCode.STRATEGY_NOT_FOUND, str(e),
                    hint="Utilisez list_strategies() pour voir les disponibles",
                    trace_id=trace_id, start_time=start
                )
            return self._error_response(
                ErrorCode.INVALID_PARAMS, str(e),
                trace_id=trace_id, start_time=start
            )
        except Exception:
            self._logger.exception(f"[{trace_id}] Erreur inattendue")
            return self._error_response(
                ErrorCode.BACKEND_INTERNAL,
                "Erreur interne du moteur de backtest",
                details=traceback.format_exc() if self.debug else None,
                trace_id=trace_id, start_time=start
            )

    # =========================================================================
    # OPTIMISATION GRILLE
    # =========================================================================

    def run_grid_optimization(
        self,
        request: GridOptimizationRequest,
        progress_callback: Optional[callable] = None
    ) -> GridOptimizationResponse:
        """
        Exécute une optimisation en grille.

        Args:
            request: GridOptimizationRequest
            progress_callback: Fonction appelée à chaque itération (i, total)

        Returns:
            GridOptimizationResponse avec tous les résultats
        """
        import time
        start = time.time()
        trace_id = str(uuid.uuid4())[:8]

        self._logger.info(
            f"[{trace_id}] run_grid_optimization: {request.strategy_name}, "
            f"{len(request.param_grid)} combinaisons"
        )

        try:
            # Valider les données
            self._validate_dataframe(request.data)

            # Limiter les combinaisons
            param_grid = request.param_grid[:request.max_combinations]

            engine = BacktestEngine(
                initial_capital=request.initial_capital,
                config=self.config
            )

            results = []
            best_metric = float("-inf")
            best_result = None
            best_params = {}
            success_count = 0
            fail_count = 0

            for i, params in enumerate(param_grid):
                if progress_callback:
                    progress_callback(i + 1, len(param_grid))

                try:
                    result = engine.run(
                        df=request.data,
                        strategy=request.strategy_name,
                        params=params,
                        symbol=request.symbol,
                        timeframe=request.timeframe,
                    )

                    metric_value = result.metrics.get(request.metric_to_optimize, 0)

                    results.append({
                        "params": params,
                        "metrics": UIMetrics.from_run_result(result).to_dict(),
                        "success": True,
                    })

                    if metric_value > best_metric:
                        best_metric = metric_value
                        best_result = UIPayload.from_run_result(result)
                        best_params = params

                    success_count += 1

                except Exception as e:
                    results.append({
                        "params": params,
                        "error": str(e),
                        "success": False,
                    })
                    fail_count += 1

            duration_ms = (time.time() - start) * 1000

            status = ResponseStatus.SUCCESS if fail_count == 0 else ResponseStatus.PARTIAL

            return GridOptimizationResponse(
                status=status,
                results=results,
                best_result=best_result,
                best_params=best_params,
                total_tested=len(param_grid),
                total_success=success_count,
                total_failed=fail_count,
                duration_ms=duration_ms,
            )

        except InsufficientDataError as e:
            return GridOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.INSUFFICIENT_DATA,
                    message_user=str(e),
                    hint=e.hint,
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )
        except DataError as e:
            return GridOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.INVALID_DATA,
                    message_user=str(e),
                    hint="Vérifiez le format des données OHLCV",
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception:
            self._logger.exception(f"[{trace_id}] Erreur optimisation grille")
            return GridOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.BACKEND_INTERNAL,
                    message_user="Erreur lors de l'optimisation",
                    details=traceback.format_exc() if self.debug else None,
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )

    # =========================================================================
    # OPTIMISATION LLM
    # =========================================================================

    def run_llm_optimization(
        self,
        request: LLMOptimizationRequest,
        progress_callback: Optional[callable] = None
    ) -> LLMOptimizationResponse:
        """
        Exécute une optimisation LLM autonome.

        Args:
            request: LLMOptimizationRequest
            progress_callback: Fonction appelée à chaque itération

        Returns:
            LLMOptimizationResponse
        """
        import time
        start = time.time()
        trace_id = str(uuid.uuid4())[:8]

        self._logger.info(
            f"[{trace_id}] run_llm_optimization: {request.strategy_name}, "
            f"provider={request.llm_provider}"
        )

        try:
            # Vérifier disponibilité LLM
            from agents.integration import create_optimizer_from_engine
            from agents.llm_client import LLMConfig, LLMProvider
        except ImportError:
            return LLMOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.LLM_UNAVAILABLE,
                    message_user="Module agents LLM non disponible",
                    hint="Vérifiez l'installation des dépendances agents",
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            # Valider les données
            self._validate_dataframe(request.data)

            # Configurer le LLM
            provider = (
                LLMProvider.OLLAMA
                if request.llm_provider.lower() == "ollama"
                else LLMProvider.OPENAI
            )

            llm_config = LLMConfig(
                provider=provider,
                model=request.llm_model,
                openai_api_key=request.llm_api_key,
                ollama_host=request.llm_base_url,
            )

            # Créer l'optimiseur
            strategist, executor = create_optimizer_from_engine(
                llm_config=llm_config,
                strategy_name=request.strategy_name,
                data=request.data,
                initial_capital=request.initial_capital,
                use_walk_forward=request.use_walk_forward,
                verbose=True,
            )

            # Exécuter l'optimisation
            session = strategist.optimize(
                executor=executor,
                initial_params=request.initial_params,
                param_bounds=request.param_bounds,
                max_iterations=request.max_iterations,
                target_sharpe=request.target_sharpe,
            )

            # Convertir l'historique
            history = []
            for exp in session.history:
                history.append({
                    "params": exp.request.parameters,
                    "sharpe_ratio": exp.sharpe_ratio,
                    "total_pnl": exp.total_pnl,
                })

            # Calculer l'amélioration
            improvement = 0.0
            if history and history[0]["sharpe_ratio"] != 0:
                initial = history[0]["sharpe_ratio"]
                final = session.best_result.sharpe_ratio
                improvement = ((final - initial) / abs(initial)) * 100

            # Reconstruire le meilleur résultat complet
            engine = BacktestEngine(
                initial_capital=request.initial_capital,
                config=self.config
            )
            best_run = engine.run(
                df=request.data,
                strategy=request.strategy_name,
                params=session.best_result.request.parameters,
            )
            best_payload = UIPayload.from_run_result(best_run)

            duration_ms = (time.time() - start) * 1000

            return LLMOptimizationResponse(
                status=ResponseStatus.SUCCESS,
                best_result=best_payload,
                best_params=session.best_result.request.parameters,
                iterations_history=history,
                total_iterations=session.total_iterations,
                convergence_reason=session.convergence_reason,
                improvement_pct=improvement,
                duration_ms=duration_ms,
            )

        except InsufficientDataError as e:
            return LLMOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.INSUFFICIENT_DATA,
                    message_user=str(e),
                    hint=e.hint,
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )
        except DataError as e:
            return LLMOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.INVALID_DATA,
                    message_user=str(e),
                    hint="Vérifiez le format des données OHLCV",
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )
        except ConnectionError as e:
            return LLMOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.LLM_CONNECTION_FAILED,
                    message_user=f"Impossible de se connecter au LLM: {e}",
                    hint="Vérifiez que Ollama est démarré ou que la clé API est valide",
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            self._logger.exception(f"[{trace_id}] Erreur optimisation LLM")
            return LLMOptimizationResponse(
                status=ResponseStatus.ERROR,
                error=ErrorInfo(
                    code=ErrorCode.OPTIMIZATION_FAILED,
                    message_user=f"Erreur lors de l'optimisation LLM: {str(e)}",
                    details=traceback.format_exc() if self.debug else None,
                    trace_id=trace_id,
                ),
                duration_ms=(time.time() - start) * 1000,
            )

    # =========================================================================
    # HELPERS PRIVÉS
    # =========================================================================

    def _estimate_bars_between(
        self,
        start: str,
        end: str,
        timeframe: str
    ) -> int:
        """
        Estime le nombre de barres entre deux dates pour un timeframe donné.

        Args:
            start: Date de début ISO (ex: "2024-01-01")
            end: Date de fin ISO
            timeframe: Timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.)

        Returns:
            Nombre approximatif de barres
        """
        from datetime import datetime

        try:
            # Parser les dates (supporter différents formats)
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))

            # Calculer la durée en heures
            duration_hours = (end_dt - start_dt).total_seconds() / 3600

            # Conversion timeframe -> heures par barre
            timeframe_hours = {
                '1m': 1/60, '5m': 5/60, '15m': 15/60, '30m': 0.5,
                '1h': 1, '2h': 2, '4h': 4, '6h': 6, '8h': 8, '12h': 12,
                '1d': 24, '1w': 24*7,
            }

            hours_per_bar = timeframe_hours.get(timeframe, 1)
            estimated_bars = int(duration_hours / hours_per_bar)

            return estimated_bars

        except Exception as e:
            self._logger.warning(f"Impossible d'estimer les barres: {e}")
            return 0  # En cas d'erreur, retourner 0 (pas de validation)

    def _load_data(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str],
        end: Optional[str],
        warmup_required: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Charge les données OHLCV avec validation de warmup minimal.

        Args:
            symbol: Symbole à charger (ex: "BTCUSDT")
            timeframe: Timeframe (1h, 4h, 1d, etc.)
            start: Date de début (optionnel)
            end: Date de fin (optionnel)
            warmup_required: Nombre minimal de barres requis (défaut: WARMUP_MIN_DEFAULT)

        Returns:
            DataFrame OHLCV validé

        Raises:
            InsufficientDataError: Si les données sont insuffisantes
            DataError: Si les données sont introuvables
        """
        from data.loader import load_ohlcv

        # 1. Déterminer le warmup minimal requis
        warmup_min = warmup_required or WARMUP_MIN_DEFAULT

        # 2. Valider la cohérence de la fenêtre temporelle
        if start and end:
            expected_bars = self._estimate_bars_between(start, end, timeframe)

            if expected_bars > 0 and expected_bars < warmup_min:
                self._logger.warning(
                    f"Fenêtre trop courte détectée: {expected_bars} barres estimées < {warmup_min} requis. "
                    f"Neutralisation des dates pour charger toutes les données disponibles."
                )
                # Neutraliser les dates pour recharger tout
                start = None
                end = None

        # 3. Charger les données
        df = load_ohlcv(symbol, timeframe, start=start, end=end)

        # 4. Vérifier que les données existent
        if df is None or df.empty:
            raise DataError(
                f"Données non trouvées: {symbol}_{timeframe}",
                symbol=symbol,
                timeframe=timeframe
            )

        # 5. Validation finale: vérifier que nous avons assez de barres
        actual_bars = len(df)
        if actual_bars < warmup_min:
            raise InsufficientDataError(
                message=f"Données insuffisantes: {actual_bars} barres < {warmup_min} requis pour {symbol}_{timeframe}",
                available_bars=actual_bars,
                required_bars=warmup_min,
                symbol=symbol,
                timeframe=timeframe,
                hint=f"Le warmup des indicateurs nécessite au minimum {warmup_min} barres. "
                     f"Disponibles: {actual_bars}. Utilisez une période plus longue."
            )

        self._logger.debug(
            f"Données chargées avec succès: {actual_bars} barres (warmup requis: {warmup_min})"
        )

        return df

    def _validate_dataframe(
        self,
        df: pd.DataFrame,
        warmup_required: Optional[int] = None,
        symbol: str = "UNKNOWN",
        timeframe: str = "UNKNOWN"
    ) -> None:
        """
        Valide un DataFrame OHLCV.

        Args:
            df: DataFrame à valider
            warmup_required: Nombre minimal de barres requis (optionnel)
            symbol: Symbole pour les messages d'erreur
            timeframe: Timeframe pour les messages d'erreur

        Raises:
            DataError: Si le format est invalide
            InsufficientDataError: Si les données sont insuffisantes
        """
        if df is None or df.empty:
            raise DataError("DataFrame vide ou None")

        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataError(f"Colonnes manquantes: {missing}")

        if not isinstance(df.index, pd.DatetimeIndex):
            raise DataError("L'index doit être un DatetimeIndex")

        # Validation warmup optionnelle
        if warmup_required is not None:
            actual_bars = len(df)
            if actual_bars < warmup_required:
                raise InsufficientDataError(
                    message=f"Données insuffisantes: {actual_bars} barres < {warmup_required} requis pour {symbol}_{timeframe}",
                    available_bars=actual_bars,
                    required_bars=warmup_required,
                    symbol=symbol,
                    timeframe=timeframe,
                    hint=f"Le warmup des indicateurs nécessite au minimum {warmup_required} barres. "
                         f"Disponibles: {actual_bars}. Utilisez une période plus longue."
                )

    def _error_response(
        self,
        code: ErrorCode,
        message: str,
        hint: Optional[str] = None,
        details: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_time: float = 0,
    ) -> BackendResponse:
        """Crée une réponse d'erreur standardisée."""
        import time
        return BackendResponse(
            status=ResponseStatus.ERROR,
            error=ErrorInfo(
                code=code,
                message_user=message,
                hint=hint,
                details=details,
                trace_id=trace_id,
            ),
            duration_ms=(time.time() - start_time) * 1000 if start_time else 0,
        )


# =============================================================================
# FACTORY & HELPERS
# =============================================================================

# Instance globale (singleton)
_facade_instance: Optional[BackendFacade] = None


def get_facade(config: Optional[Config] = None, debug: bool = False) -> BackendFacade:
    """
    Retourne l'instance globale de la façade.

    Args:
        config: Configuration (utilisée seulement à la première création)
        debug: Mode debug

    Returns:
        BackendFacade instance
    """
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = BackendFacade(config=config, debug=debug)
    return _facade_instance


def to_ui_payload(result: RunResult) -> UIPayload:
    """
    Convertit un RunResult en UIPayload.

    Fonction utilitaire pour la compatibilité avec le code existant.

    Args:
        result: RunResult du moteur

    Returns:
        UIPayload prêt pour l'affichage
    """
    return UIPayload.from_run_result(result)


def run_backtest(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interface simple legacy: lance un backtest à partir d'un dict de config.

    Attendu (exemple):
        {
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 10000.0,
            "strategy": "ema_cross",
            "params": {"fast_period": 10, "slow_period": 30},
            "data": <DataFrame>  # optionnel
        }
    """
    if not isinstance(config, dict):
        raise TypeError("config doit être un dict")

    symbol = config.get("symbol")
    timeframe = config.get("timeframe")
    strategy = config.get("strategy")
    params = config.get("params", {})
    initial_capital = float(config.get("initial_capital", 10000.0))
    start_date = config.get("start_date")
    end_date = config.get("end_date")
    df = config.get("data")

    if df is None:
        from data.loader import load_ohlcv

        if symbol is None or timeframe is None:
            raise ValueError("symbol et timeframe requis si data absent")
        df = load_ohlcv(symbol, timeframe, start=start_date, end=end_date)

    engine = BacktestEngine(initial_capital=initial_capital)
    result = engine.run(
        df=df,
        strategy=strategy,
        params=params,
        symbol=symbol or "UNKNOWN",
        timeframe=timeframe or "1h",
    )

    metrics = result.metrics
    total_return_pct = metrics.get("total_return_pct", 0.0)

    return {
        "total_return": total_return_pct / 100.0,
        "total_return_pct": total_return_pct,
        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
        "total_trades": metrics.get("total_trades", 0),
        "metrics": metrics,
        "run_id": result.meta.get("run_id"),
    }


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur l'interface stable UI↔backend
# - Conventions contrats Request/Response et erreurs structurées explicitées
# - Read-if/Skip-if ajoutés pour guider la lecture
