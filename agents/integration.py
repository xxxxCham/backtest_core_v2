"""Module-ID: agents.integration

Purpose: Relier les agents LLM (abstraits) au moteur de backtest concret (BacktestEngine + WalkForwardValidator).

Role in pipeline: orchestration

Key components: run_backtest_for_agent, run_walk_forward_for_agent, create_optimizer_from_engine, create_orchestrator_with_backtest, validate_walk_forward_period

Inputs: DataFrame OHLCV, Config, stratégie (key/name), LLMConfig/RoleModelConfig, paramètres et options walk-forward

Outputs: Résultats de backtest/walk-forward adaptés aux agents, factories d’optimiseurs/orchestrator prêts à l’emploi

Dependencies: backtest.engine, backtest.validation, strategies.base, utils.config, utils.observability, agents.backtest_executor

Conventions: MIN_DAYS_FOR_WALK_FORWARD=180; timestamps détectés (index datetime ou colonne 'timestamp'); WF peut être désactivé si période insuffisante.

Read-if: Vous modifiez le wiring agents↔engine (run_backtest, walk-forward, factories).

Skip-if: Vous ne changez que les stratégies/indicateurs ou la UI.
"""

from __future__ import annotations

# pylint: disable=logging-fstring-interpolation
import random
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardSummary,
    run_walk_forward,
)
from metrics_types import normalize_metrics, pct_to_frac
from strategies.base import get_strategy, get_strategy_overview, list_strategies
from utils.config import Config
from utils.observability import (
    generate_run_id,
    get_obs_logger,
    trace_span,
)

from .autonomous_strategist import AutonomousStrategist, OptimizationSession
from .backtest_executor import BacktestExecutor
from .llm_client import LLMConfig, create_llm_client
from .llm_router import LLMTopologyConfig
from .model_config import RoleModelConfig

if TYPE_CHECKING:  # pragma: no cover
    from .orchestrator import Orchestrator

# Logger module-level (sans run_id spécifique)
_logger = get_obs_logger(__name__)

# Constantes pour validation walk-forward
MIN_DAYS_FOR_WALK_FORWARD = 180  # 6 mois minimum


def _normalize_engine_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_metrics(metrics, "pct")


class AgentBacktestMetrics(TypedDict):
    sharpe_ratio: float
    sortino_ratio: float
    total_return: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    sqn: float
    calmar_ratio: float
    recovery_factor: float
    equity_curve: list[float] | None
    trades: list[dict[str, Any]] | None
    run_id: str


class WalkForwardMetrics(TypedDict):
    train_sharpe: float
    test_sharpe: float
    overfitting_ratio: float
    classic_ratio: float
    degradation_pct: float
    test_stability_std: float
    n_valid_folds: int


def extract_dataframe_timestamps(
    data: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Extrait les timestamps de début et fin d'un DataFrame OHLCV.

    Gère automatiquement:
    - DatetimeIndex
    - Colonne 'timestamp' ou 'date' (datetime ou numérique ms/s)

    Args:
        data: DataFrame OHLCV

    Returns:
        Tuple (start_datetime, end_datetime)

    Raises:
        ValueError: Si aucun timestamp n'est trouvé ou format invalide

    Example:
        >>> start, end = extract_dataframe_timestamps(df)
        >>> duration_days = (end - start).days

    """
    if data is None or data.empty:
        raise ValueError("DataFrame must not be empty")

    # Cas 1: DatetimeIndex
    if isinstance(data.index, pd.DatetimeIndex):
        return data.index.min(), data.index.max()

    # Cas 2: Colonne timestamp/date
    col = None
    if "timestamp" in data.columns:
        col = "timestamp"
    elif "date" in data.columns:
        col = "date"
    else:
        raise ValueError(
            "DataFrame must have DatetimeIndex or 'timestamp'/'date' column",
        )

    ts_col = data[col]

    # Déjà en datetime
    if pd.api.types.is_datetime64_any_dtype(ts_col):
        clean = ts_col.dropna()
        if clean.empty:
            raise ValueError(f"Column '{col}' does not contain valid timestamps")
        return clean.min(), clean.max()

    # Numérique: détecter ms vs s
    if pd.api.types.is_numeric_dtype(ts_col):
        clean = ts_col.dropna()
        if clean.empty:
            raise ValueError(f"Column '{col}' does not contain valid timestamps")
        first_val = clean.iloc[0]
        # Heuristique: >1e12 = millisecondes, sinon secondes
        unit = "ms" if first_val > 1e12 else "s"
        return (
            pd.to_datetime(clean.min(), unit=unit),
            pd.to_datetime(clean.max(), unit=unit),
        )

    raise ValueError(
        f"Column '{col}' must be datetime or numeric, got {ts_col.dtype}",
    )


def validate_walk_forward_period(
    data: pd.DataFrame,
    min_days: int = MIN_DAYS_FOR_WALK_FORWARD,
) -> tuple[bool, int, str]:
    """Valide si la période de données est suffisante pour une walk-forward validation.

    La walk-forward nécessite une période minimale pour avoir une signification
    statistique. En dessous de 6 mois, les folds sont trop courts et les résultats
    sont dominés par le bruit statistique.

    Args:
        data: DataFrame OHLCV avec index datetime ou colonne 'timestamp'
        min_days: Nombre de jours minimum requis (défaut: 180 = 6 mois)

    Returns:
        Tuple (is_valid, duration_days, message)
        - is_valid: True si période suffisante, False sinon
        - duration_days: Durée en jours de la période
        - message: Message explicatif

    Exemples:
        >>> is_valid, days, msg = validate_walk_forward_period(df)
        >>> if not is_valid:
        ...     print(f"⚠️ {msg}")
        ...     # Désactiver walk-forward

    """
    # Extraire les timestamps (fonction helper centralisée)
    start_dt, end_dt = extract_dataframe_timestamps(data)

    # Calculer la durée en jours
    duration = (end_dt - start_dt).days

    # Valider
    if duration < min_days:
        months = duration / 30.0
        min_months = min_days / 30.0
        message = (
            f"Période insuffisante pour walk-forward validation: "
            f"{duration} jours ({months:.1f} mois) < {min_days} jours ({min_months:.0f} mois minimum). "
            f"Walk-forward DÉSACTIVÉ automatiquement pour éviter des résultats non significatifs."
        )
        return False, duration, message

    months = duration / 30.0
    message = (
        f"Période validée pour walk-forward: "
        f"{duration} jours ({months:.1f} mois) ≥ {min_days} jours. "
        f"Walk-forward validation activée."
    )
    return True, duration, message


def run_backtest_for_agent(
    strategy_name: str,
    params: dict[str, Any],
    data: pd.DataFrame,
    *,
    initial_capital: float = 10000.0,
    config: Config | None = None,
    run_id: str | None = None,
) -> AgentBacktestMetrics:
    """Exécute un backtest et retourne les métriques pour un agent.

    C'est le pont entre BacktestExecutor et BacktestEngine.

    Args:
        strategy_name: Nom de la stratégie (ex: "ema_cross")
        params: Paramètres de la stratégie
        data: DataFrame OHLCV
        initial_capital: Capital de départ
        config: Configuration optionnelle
        run_id: Identifiant de corrélation (généré si None)

    Returns:
        Dict avec toutes les métriques nécessaires pour l'agent

    """
    # Générer run_id si absent
    run_id = run_id or generate_run_id()
    logger = get_obs_logger(__name__, run_id=run_id, strategy=strategy_name)

    logger.info(
        "agent_backtest_start params=%s bars=%s",
        params,
        len(data),
    )

    # Créer engine avec le même run_id pour corrélation
    engine = BacktestEngine(
        initial_capital=initial_capital,
        config=config,
        run_id=run_id,
    )

    try:
        with trace_span(logger, "agent_backtest", strategy=strategy_name):
            result = engine.run(
                df=data,
                strategy=strategy_name,
                params=params,
            )

        # Extraire les métriques pour l'agent
        metrics_pct = normalize_metrics(result.metrics, "pct")
        metrics_frac = pct_to_frac(metrics_pct)

        output: AgentBacktestMetrics = {
            "sharpe_ratio": metrics_frac.get("sharpe_ratio", 0),
            "sortino_ratio": metrics_frac.get("sortino_ratio", 0),
            "total_return": metrics_frac.get("total_return", 0),
            "max_drawdown": metrics_frac.get("max_drawdown", 0),
            "win_rate": metrics_frac.get("win_rate", 0),
            "profit_factor": metrics_frac.get("profit_factor", 0),
            "total_trades": metrics_frac.get("total_trades", 0),
            "sqn": metrics_frac.get("sqn", 0),
            "calmar_ratio": metrics_frac.get("calmar_ratio", 0),
            "recovery_factor": metrics_frac.get("recovery_factor", 0),
            # Données brutes pour analyse approfondie
            "equity_curve": (result.equity.tolist() if len(result.equity) < 10000 else None),
            "trades": (result.trades.to_dict("records") if len(result.trades) < 1000 else None),
            # Métadonnées de corrélation
            "run_id": run_id,
        }

        logger.info(
            "agent_backtest_end sharpe=%.2f trades=%s",
            output["sharpe_ratio"],
            output["total_trades"],
        )
        return output

    except Exception as e:
        logger.error("agent_backtest_error error=%s", str(e))
        raise


def run_walk_forward_for_agent(
    strategy_name: str,
    params: dict[str, Any],
    data: pd.DataFrame,
    *,
    n_windows: int = 6,  # 6 fenêtres pour ~4 mois/test sur 24 mois
    train_ratio: float = 0.75,  # 75% train, 25% test (18m/6m optimal)
    initial_capital: float = 10000.0,
    config: Config | None = None,
    n_workers: int = 1,
) -> WalkForwardMetrics:
    """Exécute une validation walk-forward et retourne les métriques.

    Délègue au module ``backtest.walk_forward`` (pipeline standalone)
    puis convertit le résultat en ``WalkForwardMetrics`` pour
    compatibilité avec la couche agents.

    Configuration optimisée pour 2 ans de données :
    - 6 fenêtres → ~4 mois de test par fenêtre
    - 75% train → 18 mois d'entraînement, 6 mois de test
    - 2% embargo → évite le leakage entre train et test

    Args:
        strategy_name: Nom de la stratégie
        params: Paramètres de la stratégie
        data: DataFrame OHLCV
        n_windows: Nombre de fenêtres de validation
        train_ratio: Ratio train/total (1 - test_ratio)
        initial_capital: Capital de départ
        config: Configuration optionnelle
        n_workers: Nombre de workers (réservé futur, séquentiel pour l'instant)

    Returns:
        Dict avec train_sharpe, test_sharpe, overfitting_ratio, métriques robustes

    """
    wfa_cfg = WalkForwardConfig(
        n_folds=n_windows,
        train_ratio=train_ratio,
        embargo_pct=0.02,
    )

    summary: WalkForwardSummary = run_walk_forward(
        df=data,
        strategy_name=strategy_name,
        params=params,
        config=wfa_cfg,
        initial_capital=initial_capital,
        engine_config=config,
    )

    return summary.to_agent_metrics()


def create_optimizer_from_engine(
    llm_config: LLMConfig,
    strategy_name: str,
    data: pd.DataFrame,
    *,
    initial_capital: float = 10000.0,
    config: Config | None = None,
    use_walk_forward: bool = True,
    verbose: bool = True,
    unload_llm_during_backtest: bool | None = None,
    comparison_context: dict[str, Any] | None = None,
    orchestration_logger: Any | None = None,
) -> tuple[AutonomousStrategist, BacktestExecutor]:
    """Factory complète pour créer un optimiseur autonome connecté au vrai moteur.

    C'est LA fonction à utiliser pour une optimisation autonome fonctionnelle.

    Args:
        llm_config: Configuration du LLM (Ollama ou OpenAI)
        strategy_name: Nom de la stratégie à optimiser
        data: DataFrame OHLCV
        initial_capital: Capital de départ
        config: Configuration du backtest
        use_walk_forward: Activer validation walk-forward
        verbose: Logs détaillés
        unload_llm_during_backtest: Si True, décharge le LLM du GPU pendant les backtests
            pour libérer la VRAM. Si None, utilise la variable d'environnement
            UNLOAD_LLM_DURING_BACKTEST (défaut: False pour compatibilité CPU-only)
        comparison_context: Contexte multi-sweep pour enrichir les décisions LLM
        orchestration_logger: Logger pour enregistrer les actions d'orchestration

    Returns:
        (AutonomousStrategist, BacktestExecutor) prêts à l'emploi

    Example:
        >>> from agents.integration import create_optimizer_from_engine
        >>> from agents.llm_client import LLMConfig, LLMProvider
        >>>
        >>> config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.2")
        >>>
        >>> strategist, executor = create_optimizer_from_engine(
        ...     llm_config=config,
        ...     strategy_name="ema_cross",
        ...     data=ohlcv_df,
        ... )
        >>>
        >>> session = strategist.optimize(
        ...     executor=executor,
        ...     initial_params={"fast_period": 10, "slow_period": 21},
        ...     param_bounds={"fast_period": (5, 20), "slow_period": (15, 50)},
        ...     max_iterations=5,
        ... )
        >>>
        >>> print(f"Best Sharpe: {session.best_result.sharpe_ratio}")
        >>> print(f"Best Params: {session.best_result.request.parameters}")

    """
    # Vérifier que la stratégie existe
    if strategy_name not in list_strategies():
        available = ", ".join(list_strategies())
        raise ValueError(
            f"Stratégie '{strategy_name}' inconnue. Disponibles: {available}",
        )

    # Valider la période pour walk-forward (garde-fou)
    walk_forward_disabled_reason = None
    if use_walk_forward:
        is_valid, duration_days, message = validate_walk_forward_period(data)
        if not is_valid:
            _logger.warning(
                "walk_forward_auto_disabled duration_days=%s reason='period_too_short'",
                duration_days,
            )
            _logger.warning(message)
            use_walk_forward = False  # Forcer désactivation
            walk_forward_disabled_reason = message

    # Créer le client LLM
    llm_client = create_llm_client(llm_config)

    # Créer la fonction de backtest
    def backtest_fn(
        strategy: str,
        params: dict[str, Any],
        df: pd.DataFrame,
    ) -> AgentBacktestMetrics:
        return run_backtest_for_agent(
            strategy_name=strategy,
            params=params,
            data=df,
            initial_capital=initial_capital,
            config=config,
        )

    # Créer la fonction de validation (optionnelle)
    def _validation_fn(
        strategy: str,
        params: dict[str, Any],
        df: pd.DataFrame,
        n_windows: int = 6,  # Optimisé pour 2 ans de données
        train_ratio: float = 0.75,  # 75/25 pour meilleur compromis
    ) -> WalkForwardMetrics:
        return run_walk_forward_for_agent(
            strategy_name=strategy,
            params=params,
            data=df,
            n_windows=n_windows,
            train_ratio=train_ratio,
            initial_capital=initial_capital,
            config=config,
        )

    validation_fn = _validation_fn if use_walk_forward else None

    # Préparer un aperçu de stratégie pour le contexte LLM
    strategy_overview = get_strategy_overview(strategy_name)

    # Créer l'exécuteur
    executor = BacktestExecutor(
        backtest_fn=backtest_fn,
        strategy_name=strategy_name,
        data=data,
        validation_fn=validation_fn,
        strategy_description=strategy_overview,
    )

    # Créer le strategist autonome
    strategist = AutonomousStrategist(
        llm_client,
        verbose=verbose,
        unload_llm_during_backtest=unload_llm_during_backtest,
        comparison_context=comparison_context,
        orchestration_logger=orchestration_logger,
    )

    _logger.info(
        "optimizer_created strategy=%s rows=%s walk_forward=%s",
        strategy_name,
        len(data),
        use_walk_forward,
    )

    # Si walk-forward désactivé automatiquement, logger pour rapport final
    if walk_forward_disabled_reason:
        _logger.info(
            "walk_forward_validation_status disabled_reason='%s'",
            walk_forward_disabled_reason,
        )

    return strategist, executor


def get_strategy_param_bounds(
    strategy_name: str,
) -> dict[str, tuple[float, float]]:
    """Récupère les bornes des paramètres d'une stratégie.

    Utilise les parameter_specs de la stratégie si disponibles,
    sinon retourne des bornes par défaut.

    Note: Exclut les paramètres avec optimize=False (ex: leverage).

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        Dict {param_name: (min, max)}

    """
    strategy_class = get_strategy(strategy_name)
    strategy = strategy_class()

    bounds = {}

    # Essayer d'utiliser parameter_specs si disponible
    if hasattr(strategy, "parameter_specs"):
        specs = strategy.parameter_specs
        # parameter_specs est un dict {name: ParameterSpec}
        if isinstance(specs, dict):
            for name, spec in specs.items():
                # Exclure les paramètres avec optimize=False
                if hasattr(spec, "optimize") and spec.optimize is False:
                    continue
                # ParameterSpec utilise min_val et max_val
                if hasattr(spec, "min_val") and hasattr(spec, "max_val"):
                    bounds[name] = (spec.min_val, spec.max_val)

    # Fallback: utiliser default_params avec ±50%
    if not bounds and hasattr(strategy, "default_params"):
        for name, value in strategy.default_params.items():
            if isinstance(value, (int, float)) and value > 0:
                # Exclure leverage du fallback aussi
                if name == "leverage":
                    continue
                bounds[name] = (value * 0.5, value * 2.0)

    return bounds


def get_strategy_param_space(
    strategy_name: str,
    include_step: bool = True,
) -> dict[str, tuple[float, float] | tuple[float, float, float]]:
    """Récupère l'espace des paramètres avec step si disponible.

    Extension de get_strategy_param_bounds() pour permettre:
    - Le calcul unifié des stats d'espace de recherche
    - L'affichage d'estimation dans le mode LLM

    Note: Exclut les paramètres avec optimize=False (ex: leverage).

    Args:
        strategy_name: Nom de la stratégie
        include_step: Inclure le step si disponible

    Returns:
        Dict {param_name: (min, max)} ou {param_name: (min, max, step)}

    """
    strategy_class = get_strategy(strategy_name)
    strategy = strategy_class()

    space = {}

    # Utiliser parameter_specs si disponible
    if hasattr(strategy, "parameter_specs"):
        specs = strategy.parameter_specs
        if isinstance(specs, dict):
            for name, spec in specs.items():
                # Exclure les paramètres avec optimize=False
                if hasattr(spec, "optimize") and spec.optimize is False:
                    continue
                if hasattr(spec, "min_val") and hasattr(spec, "max_val"):
                    min_v = spec.min_val
                    max_v = spec.max_val

                    if include_step and hasattr(spec, "step") and spec.step:
                        space[name] = (min_v, max_v, spec.step)
                    else:
                        space[name] = (min_v, max_v)

    # Fallback: param_ranges (si présent dans la stratégie)
    if not space and hasattr(strategy, "param_ranges"):
        for name, (min_v, max_v) in strategy.param_ranges.items():
            # param_ranges exclut déjà leverage (via property)
            space[name] = (min_v, max_v)

    # Dernier fallback: default_params avec ±50%
    if not space and hasattr(strategy, "default_params"):
        for name, value in strategy.default_params.items():
            if isinstance(value, (int, float)) and value > 0:
                # Exclure leverage du fallback
                if name == "leverage":
                    continue
                space[name] = (value * 0.5, value * 2.0)

    return space


def quick_optimize(
    llm_config: LLMConfig,
    strategy_name: str,
    data: pd.DataFrame,
    max_iterations: int = 10,
    **kwargs,
) -> OptimizationSession:
    """Raccourci pour lancer une optimisation rapidement.

    Détecte automatiquement les paramètres initiaux et les bornes.

    Args:
        llm_config: Configuration LLM
        strategy_name: Nom de la stratégie
        data: DataFrame OHLCV
        max_iterations: Maximum d'itérations
        **kwargs: Arguments additionnels pour create_optimizer_from_engine

    Returns:
        OptimizationSession avec les résultats

    Example:
        >>> session = quick_optimize(
        ...     llm_config=config,
        ...     strategy_name="ema_cross",
        ...     data=df,
        ...     max_iterations=5,
        ... )
        >>> print(session.best_result.sharpe_ratio)

    """
    # Récupérer la stratégie pour les params par défaut
    strategy_class = get_strategy(strategy_name)
    strategy = strategy_class()

    # Paramètres initiaux
    initial_params = strategy.default_params.copy()

    # Bornes des paramètres
    param_bounds = get_strategy_param_bounds(strategy_name)

    if not param_bounds:
        raise ValueError(
            f"Impossible de déterminer les bornes pour '{strategy_name}'. "
            "Utilisez create_optimizer_from_engine avec des bornes explicites.",
        )

    # Créer l'optimiseur
    strategist, executor = create_optimizer_from_engine(
        llm_config=llm_config,
        strategy_name=strategy_name,
        data=data,
        **kwargs,
    )

    # Lancer l'optimisation
    session = strategist.optimize(
        executor=executor,
        initial_params=initial_params,
        param_bounds=param_bounds,
        max_iterations=max_iterations,
    )

    return session


def create_orchestrator_with_backtest(
    strategy_name: str,
    data: pd.DataFrame,
    initial_params: dict[str, Any],
    data_symbol: str = "",
    data_timeframe: str = "",
    llm_config: LLMConfig | None = None,
    role_model_config: RoleModelConfig | None = None,
    llm_topology_config: LLMTopologyConfig | None = None,
    use_walk_forward: bool = True,
    optimization_target: str = "sharpe_ratio",
    min_sharpe: float = 1.0,
    max_drawdown_limit: float = 0.20,
    min_trades: int = 30,
    max_overfitting_ratio: float = 1.5,
    max_proposals_per_iteration: int = 5,
    orchestration_logger: Any | None = None,
    session_id: str | None = None,
    n_workers: int = 1,
    max_iterations: int = 10,
    initial_capital: float = 10000.0,
    config: Config | None = None,
    comparison_context: dict[str, Any] | None = None,
    unload_llm_during_backtest: bool | None = None,
) -> Orchestrator:
    """Crée un Orchestrator multi-agents branché sur le vrai backtest.

    L'Orchestrator par défaut nécessite un callback `on_backtest_needed`.
    Cette fonction le configure automatiquement avec `run_backtest_for_agent()`.

    Args:
        strategy_name: Nom de la stratégie
        data: DataFrame OHLCV
        initial_params: Paramètres initiaux
        data_symbol: Symbole (ex: "BTCUSDC")
        data_timeframe: Timeframe (ex: "1h")
        llm_config: Configuration LLM (optionnel, défaut depuis env)
        role_model_config: Configuration multi-modeles par role
        llm_topology_config: Topologie multi-host/multi-GPU phase 1
        use_walk_forward: Activer la validation walk-forward (si possible)
        optimization_target: Métrique cible d'optimisation
        min_sharpe: Sharpe minimum
        max_drawdown_limit: Drawdown maximum
        min_trades: Nombre minimum de trades
        max_overfitting_ratio: Ratio max train/test pour éviter l'overfitting
        max_proposals_per_iteration: Nombre maximum de propositions par itération
        orchestration_logger: Logger d'orchestration (UI live/persistance)
        session_id: Forcer l'ID de session (corrélation UI)
        n_workers: Nombre de workers pour paralléliser les backtests de propositions
        max_iterations: Maximum d'itérations
        initial_capital: Capital de départ
        config: Configuration du backtest
        comparison_context: Contexte multi-sweep pour enrichir les agents LLM
        unload_llm_during_backtest: Décharge LLM pendant backtests (réservé usage futur)

    Returns:
        Orchestrator configuré et prêt à exécuter

    Example:
        >>> orchestrator = create_orchestrator_with_backtest(
        ...     strategy_name="ema_cross",
        ...     data=df,
        ...     initial_params={"fast_period": 12, "slow_period": 26},
        ... )
        >>> result = orchestrator.run()
        >>> if result.success:
        ...     print(f"Meilleurs params: {result.final_params}")

    """
    # Import ici pour éviter les imports circulaires
    from .base_agent import ParameterConfig
    from .orchestrator import Orchestrator, OrchestratorConfig

    # Valider la période pour walk-forward (garde-fou)
    walk_forward_disabled_reason = None
    if use_walk_forward:
        is_valid, duration_days, message = validate_walk_forward_period(data)
        if not is_valid:
            _logger.warning(
                "walk_forward_auto_disabled duration_days=%s reason='period_too_short'",
                duration_days,
            )
            _logger.warning(message)
            use_walk_forward = False  # Forcer désactivation
            walk_forward_disabled_reason = message

    # Récupérer les specs des paramètres
    param_space = get_strategy_param_space(strategy_name, include_step=True)
    param_specs = []
    for name, bounds in param_space.items():
        if len(bounds) == 3:
            min_v, max_v, step = bounds
        else:
            min_v, max_v = bounds
            step = None
        param_specs.append(
            ParameterConfig(
                name=name,
                min_value=min_v,
                max_value=max_v,
                step=step,
                current_value=initial_params.get(name, (min_v + max_v) / 2),
            ),
        )

    # Créer le callback de backtest
    def on_backtest_needed(params: dict[str, Any]) -> AgentBacktestMetrics:
        return run_backtest_for_agent(
            strategy_name=strategy_name,
            params=params,
            data=data,
            initial_capital=initial_capital,
            config=config,
        )

    data_date_range = ""
    try:
        start_dt, end_dt = extract_dataframe_timestamps(data)
        data_date_range = f"{start_dt} -> {end_dt}"
    except (ValueError, Exception):
        data_date_range = ""

    # Préparer un aperçu de stratégie pour le contexte LLM
    strategy_overview = get_strategy_overview(strategy_name)

    # Créer la config
    orchestrator_config = OrchestratorConfig(
        strategy_name=strategy_name,
        strategy_description=strategy_overview,
        initial_params=initial_params,
        param_specs=param_specs,
        max_iterations=max_iterations,
        optimization_target=optimization_target,
        min_sharpe=min_sharpe,
        max_drawdown_limit=max_drawdown_limit,
        min_trades=min_trades,
        max_overfitting_ratio=max_overfitting_ratio,
        max_proposals_per_iteration=max_proposals_per_iteration,
        llm_config=llm_config,
        role_model_config=role_model_config,
        llm_topology_config=llm_topology_config,
        use_walk_forward=use_walk_forward,
        walk_forward_disabled_reason=walk_forward_disabled_reason,
        data=data,
        data_symbol=data_symbol,
        data_timeframe=data_timeframe,
        data_date_range=data_date_range,
        n_workers=n_workers,
        session_id=session_id,
        orchestration_logger=orchestration_logger,
        comparison_context=comparison_context,
        on_backtest_needed=on_backtest_needed,
    )

    _logger.info(
        "orchestrator_created strategy=%s rows=%s walk_forward=%s",
        strategy_name,
        len(data),
        use_walk_forward,
    )

    # Si walk-forward désactivé automatiquement, logger pour rapport final
    if walk_forward_disabled_reason:
        _logger.info(
            "walk_forward_validation_status disabled_reason='%s'",
            walk_forward_disabled_reason,
        )

    return Orchestrator(orchestrator_config)


# =============================================================================
# LLM Grid Search Integration
# =============================================================================


def generate_sweep_summary(
    sweep_results: Any,  # SweepResults from backtest.sweep
    top_k: list[dict[str, Any]],
    range_proposal: Any,  # RangeProposal from utils.parameters
) -> str:
    """Génère un résumé textuel des résultats de sweep pour feedback LLM.

    Args:
        sweep_results: Résultats complets du sweep (SweepResults)
        top_k: Top K configurations (list of dicts)
        range_proposal: Proposition de ranges initiale

    Returns:
        Résumé formaté pour inclusion dans prompt LLM

    Example output:
        Grid Search Results (48 combinations tested):

        Top 10 Configurations:
        1. Sharpe=2.45, Return=8.3% | bb_period=23, bb_std=2.2
        2. Sharpe=2.12, Return=7.1% | bb_period=22, bb_std=2.3
        ...

        Key Patterns:
        - bb_period optimal range: 22-24
        - bb_std shows weak correlation with Sharpe

    """
    n_combos = sweep_results.n_completed

    summary = f"Grid Search Results ({n_combos} combinations tested):\n\n"
    summary += "Top 10 Configurations:\n"

    for i, config in enumerate(top_k[:10], 1):
        sharpe = config.get("sharpe_ratio", 0)
        ret = config.get("total_return_pct", 0)

        # Extraire params (ignorer success, error, etc.)
        param_keys = [
            k
            for k in config.keys()
            if k
            not in [
                "sharpe_ratio",
                "total_return_pct",
                "max_drawdown_pct",
                "total_trades",
                "success",
                "error",
                "win_rate_pct",
                "profit_factor",
                "sortino_ratio",
                "sqn",
                "calmar_ratio",
            ]
        ]
        params_str = ", ".join(f"{k}={config[k]}" for k in param_keys)

        summary += f"{i}. Sharpe={sharpe:.2f}, Return={ret:.1f}% | {params_str}\n"

    summary += "\nKey Patterns:\n"
    # TODO: Analyse automatique des corrélations (pour itération future)
    # Pour l'instant, juste mentionner les ranges testées
    for param_name, range_def in range_proposal.ranges.items():
        summary += f"- {param_name}: tested range [{range_def['min']}, {range_def['max']}]\n"

    return summary


def run_llm_sweep(
    range_proposal: Any,  # RangeProposal from utils.parameters
    param_specs: list[Any],  # List[ParameterSpec]
    data: pd.DataFrame,
    strategy_name: str,
    initial_capital: float = 10000.0,
    n_workers: int | None = None,
) -> dict[str, Any]:
    """Exécute un sweep de ranges demandé par le LLM.
    Fonction partagée entre mono-agent et multi-agents.

    Args:
        range_proposal: Proposition de ranges (RangeProposal)
        param_specs: Liste des spécifications de paramètres
        data: DataFrame OHLCV
        strategy_name: Nom de la stratégie
        initial_capital: Capital initial
        n_workers: Nombre de workers parallèles (None = auto)

    Returns:
        Dict contenant:
            - best_params: Meilleurs paramètres trouvés
            - best_metrics: Métriques du meilleur résultat
            - top_k: Top 10 configurations (list of dicts)
            - summary: Résumé textuel pour LLM
            - n_combinations: Nombre de combinaisons testées

    Raises:
        ValueError: Si ranges invalides ou trop de combinaisons

    Example:
        >>> from utils.parameters import RangeProposal
        >>> proposal = RangeProposal(
        ...     ranges={"bb_period": {"min": 20, "max": 25, "step": 1}},
        ...     rationale="Test bb_period sensitivity",
        ...     max_combinations=50
        ... )
        >>> result = run_llm_sweep(proposal, param_specs, df, "bollinger_atr")
        >>> print(result["summary"])

    """
    from backtest.sweep import SweepEngine
    from utils.parameters import compute_search_space_stats, normalize_param_ranges

    _logger.info(
        f"llm_sweep_start strategy={strategy_name} "
        f"ranges={range_proposal.ranges} max_combos={range_proposal.max_combinations}",
    )

    # Normaliser ranges (clamp + validate)
    try:
        normalized_ranges, range_warnings = normalize_param_ranges(
            param_specs,
            range_proposal.ranges,
        )
    except ValueError as e:
        _logger.error(f"llm_sweep_validation_failed error='{e}'")
        raise

    if range_warnings:
        for warning in range_warnings:
            _logger.warning("llm_sweep_range_warning: %s", warning)

    # Log search space stats
    stats = compute_search_space_stats(normalized_ranges)
    _logger.info(
        f"llm_sweep_space total_combos={stats.total_combinations} "
        f"estimated_memory_mb={getattr(stats, 'estimated_memory_mb', 'N/A')}",
    )

    if stats.warnings:
        for warning in stats.warnings:
            _logger.warning(f"llm_sweep_warning: {warning}")

    # Vérifier limite
    if stats.total_combinations > range_proposal.max_combinations:
        raise ValueError(
            f"Trop de combinaisons ({stats.total_combinations} > "
            f"{range_proposal.max_combinations}). Réduire les ranges ou augmenter max_combinations.",
        )

    # Construire la grille depuis les ranges normalisées
    param_grid = {name: range_def.get("values", []) for name, range_def in normalized_ranges.items()}

    # Créer SweepEngine
    engine = SweepEngine(
        max_workers=n_workers,
        initial_capital=initial_capital,
        auto_save=False,  # On gère la sauvegarde nous-mêmes
    )

    # Exécuter sweep
    _logger.info(f"llm_sweep_executing n_combos={stats.total_combinations}")

    sweep_results = engine.run_sweep(
        df=data,
        strategy=strategy_name,
        param_grid=param_grid,
        optimize_for=range_proposal.optimize_for,
        show_progress=True,
        early_stop_threshold=range_proposal.early_stop_threshold,
    )

    # Extraire top K
    df_results = sweep_results.to_dataframe()
    top_k = df_results.nlargest(10, range_proposal.optimize_for).to_dict("records")

    # Générer summary pour LLM
    summary = generate_sweep_summary(sweep_results, top_k, range_proposal)

    _logger.info(
        f"llm_sweep_complete n_completed={sweep_results.n_completed} "
        f"best_{range_proposal.optimize_for}={sweep_results.best_metrics.get(range_proposal.optimize_for, 0):.3f}",
    )

    return {
        "best_params": sweep_results.best_params,
        "best_metrics": sweep_results.best_metrics,
        "top_k": top_k,
        "summary": summary,
        "n_combinations": sweep_results.n_completed,
    }


# ===============================================================================
# COMPARISON CONTEXT FOR MULTI-SWEEP LLM
# ===============================================================================


def create_comparison_context(
    mode: str = "multi_sweep",
    strategies: list[str] | None = None,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    sweep_results: list[dict[str, Any]] | None = None,
    best_overall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crée un contexte de comparaison pour les agents LLM en mode multi-sweep.

    Ce contexte permet aux agents de voir:
    - Les stratégies/tokens/timeframes disponibles
    - Les résultats de sweeps précédents
    - Les performances relatives
    - Les alternatives d'optimisation

    Args:
        mode: Mode de comparaison ("multi_sweep", "backtest_simple_comparison")
        strategies: Liste des stratégies disponibles
        symbols: Liste des tokens disponibles
        timeframes: Liste des timeframes disponibles
        sweep_results: Résultats de sweeps précédents (liste de dicts)
        best_overall: Meilleur résultat global (dict)

    Returns:
        Dict contenant le contexte complet pour les templates LLM

    """
    # Anti-biais d'ordre pour le contexte LLM:
    # on mélange les listes candidates afin d'éviter l'effet "premier élément".
    shuffled_strategies = list(strategies or [])
    shuffled_symbols = list(symbols or [])
    shuffled_timeframes = list(timeframes or [])
    if len(shuffled_strategies) > 1:
        random.shuffle(shuffled_strategies)
    if len(shuffled_symbols) > 1:
        random.shuffle(shuffled_symbols)
    if len(shuffled_timeframes) > 1:
        random.shuffle(shuffled_timeframes)

    context = {
        "mode": mode,
        "strategies": shuffled_strategies,
        "symbols": shuffled_symbols,
        "timeframes": shuffled_timeframes,
        "total_combinations": len(shuffled_strategies) * len(shuffled_symbols) * len(shuffled_timeframes),
        "sweep_results": sweep_results or [],
        "best_overall": best_overall or {},
        "has_results": bool(sweep_results),
    }

    # Calculer statistiques si résultats disponibles
    if sweep_results:
        pnls = [r.get("total_pnl", 0) for r in sweep_results]
        sharpes = [r.get("sharpe_ratio", 0) for r in sweep_results]

        context.update(
            {
                "total_sweeps": len(sweep_results),
                "profitable_count": sum(1 for p in pnls if p > 0),
                "avg_pnl": np.mean(pnls) if pnls else 0,
                "median_pnl": np.median(pnls) if pnls else 0,
                "best_sharpe": max(sharpes) if sharpes else 0,
                "avg_sharpe": np.mean(sharpes) if sharpes else 0,
            },
        )

    _logger.debug(
        f"create_comparison_context mode={mode} strategies={len(strategies or [])} "
        f"symbols={len(symbols or [])} timeframes={len(timeframes or [])} "
        f"total_combinations={context['total_combinations']}",
    )

    return context
