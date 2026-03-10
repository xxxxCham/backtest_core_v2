"""Handler for INIT state - Configuration validation, initial backtest, walk-forward metrics."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from utils.observability import get_obs_logger

from ..base_agent import MetricsSnapshot
from ..integration import run_walk_forward_for_agent
from ..state_machine import AgentState, ValidationResult

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def ensure_indicator_context(orch: "Orchestrator") -> None:
    """Compute indicator context once per run (deduplicated from init + analyze)."""
    if orch._indicator_context_cached or orch._loaded_data is None:
        return
    try:
        from ..indicator_context import build_indicator_context

        indicator_ctx = build_indicator_context(
            df=orch._loaded_data,
            strategy_name=orch.context.strategy_name,
            params=orch.context.current_params,
        )
        orch.context.strategy_indicators_context = indicator_ctx.get("strategy", "")
        orch.context.readonly_indicators_context = indicator_ctx.get("read_only", "")
        orch.context.indicator_context_warnings = indicator_ctx.get("warnings", [])
        orch._indicator_context_cached = True
        orch._log_event(
            "indicator_context",
            strategy_indicators_context=orch.context.strategy_indicators_context,
            readonly_indicators_context=orch.context.readonly_indicators_context,
            warnings=orch.context.indicator_context_warnings,
        )
    except Exception as exc:
        orch._warnings.append(f"Contexte indicateurs indisponible: {exc}")
        orch.context.strategy_indicators_context = ""
        orch.context.readonly_indicators_context = ""
        orch.context.indicator_context_warnings = []
        orch._indicator_context_cached = True


def validate_config(orch: "Orchestrator") -> ValidationResult:
    """Validate the initial configuration."""
    errors = []

    if not orch.config.strategy_name:
        errors.append("strategy_name requis")

    if orch.config.data_path:
        if not Path(orch.config.data_path).exists():
            errors.append(f"data_path n'existe pas: {orch.config.data_path}")
    elif orch.config.on_backtest_needed is None:
        errors.append("data_path requis")

    if not orch.config.param_specs:
        errors.append("param_specs requis (au moins un paramètre)")

    if errors:
        return ValidationResult.failure("; ".join(errors), errors)

    return ValidationResult.success()


def compute_walk_forward_metrics(orch: "Orchestrator") -> None:
    """Compute walk-forward validation metrics and update context."""
    # If data is already loaded (from UI), use it directly
    if orch._loaded_data is not None:
        data_df = orch._loaded_data
        try:
            orch.context.data_rows = len(data_df)
        except Exception:
            pass

        try:
            wf_metrics = run_walk_forward_for_agent(
                strategy_name=orch.config.strategy_name,
                params=orch.context.current_params,
                data=data_df,
                n_windows=6,
                train_ratio=0.75,
                n_workers=orch.config.n_workers,
            )

            orch.context.overfitting_ratio = wf_metrics["overfitting_ratio"]
            orch.context.classic_ratio = wf_metrics["classic_ratio"]
            orch.context.degradation_pct = wf_metrics["degradation_pct"]
            orch.context.test_stability_std = wf_metrics["test_stability_std"]
            orch.context.n_valid_folds = wf_metrics["n_valid_folds"]
            orch.context.walk_forward_windows = 6

            orch._log_event(
                "walk_forward_computed",
                overfitting_ratio=float(wf_metrics["overfitting_ratio"]),
                classic_ratio=float(wf_metrics["classic_ratio"]),
                degradation_pct=float(wf_metrics["degradation_pct"]),
                test_stability_std=float(wf_metrics["test_stability_std"]),
                n_valid_folds=int(wf_metrics["n_valid_folds"]),
            )
        except Exception as e:
            logger.warning("Échec du calcul des métriques walk-forward: %s", e)
            orch._warnings.append(f"Walk-forward échoué: {e}")
            orch._log_event("warning", message=f"Walk-forward échoué: {e}")

        return

    # Check if a data path is provided
    if not orch.config.data_path:
        logger.debug("Pas de data/data_path configuré, skip walk-forward metrics")
        return

    data_path = Path(orch.config.data_path)
    if not data_path.exists():
        logger.warning("Fichier de données introuvable: %s", data_path)
        return

    try:
        # Load data if not already done
        if orch._loaded_data is None:
            logger.info("Chargement des données depuis %s", data_path)
            import pandas as pd

            if data_path.suffix == ".csv":
                orch._loaded_data = pd.read_csv(data_path)
            elif data_path.suffix == ".parquet":
                orch._loaded_data = pd.read_parquet(data_path)
            else:
                logger.warning("Format non supporté pour walk-forward: %s", data_path.suffix)
                return

            logger.info("  Données chargées: %d lignes", len(orch._loaded_data))

        # Update context with data info
        orch.context.data_rows = len(orch._loaded_data)

        # Extract date range if available
        if "timestamp" in orch._loaded_data.columns or "date" in orch._loaded_data.columns:
            date_col = "timestamp" if "timestamp" in orch._loaded_data.columns else "date"
            try:
                import pandas as pd

                dates = pd.to_datetime(orch._loaded_data[date_col])
                orch.context.data_date_range = f"{dates.min()} \u2192 {dates.max()}"
            except Exception:
                pass

        # Execute walk-forward validation
        logger.info("Exécution de la validation walk-forward...")
        wf_metrics = run_walk_forward_for_agent(
            strategy_name=orch.config.strategy_name,
            params=orch.context.current_params,
            data=orch._loaded_data,
            n_windows=6,
            train_ratio=0.75,
            n_workers=orch.config.n_workers,
        )

        orch.context.overfitting_ratio = wf_metrics["overfitting_ratio"]
        orch.context.classic_ratio = wf_metrics["classic_ratio"]
        orch.context.degradation_pct = wf_metrics["degradation_pct"]
        orch.context.test_stability_std = wf_metrics["test_stability_std"]
        orch.context.n_valid_folds = wf_metrics["n_valid_folds"]
        orch.context.walk_forward_windows = 6

        logger.info(
            "Walk-forward terminé: overfitting_ratio=%.3f, degradation=%.1f%%, stability_std=%.3f",
            wf_metrics["overfitting_ratio"],
            wf_metrics["degradation_pct"],
            wf_metrics["test_stability_std"],
        )

        orch._log_event(
            "walk_forward_computed",
            overfitting_ratio=float(wf_metrics["overfitting_ratio"]),
            classic_ratio=float(wf_metrics["classic_ratio"]),
            degradation_pct=float(wf_metrics["degradation_pct"]),
            test_stability_std=float(wf_metrics["test_stability_std"]),
            n_valid_folds=int(wf_metrics["n_valid_folds"]),
        )

    except Exception as e:
        logger.warning("Échec du calcul des métriques walk-forward: %s", e)
        orch._warnings.append(f"Walk-forward échoué: {e}")
        orch._log_event("warning", message=f"Walk-forward échoué: {e}")


def handle_init(orch: "Orchestrator") -> None:
    """Handle INIT state - Validate config and run initial backtest."""
    orch._log_event("phase_start", phase="INIT")
    logger.info("Phase INIT: Validation configuration et backtest initial")

    # Validate configuration
    validation = validate_config(orch)
    if not validation.is_valid:
        orch._log_event(
            "config_invalid", errors=validation.errors or [], message=validation.message
        )
        orch.state_machine.fail(f"Configuration invalide: {validation.message}")
        return
    orch._log_event("config_valid")

    # Run initial backtest
    initial_metrics = None
    try:
        initial_metrics = orch._run_backtest(orch.context.current_params)
        if initial_metrics:
            orch.context.current_metrics = initial_metrics
            orch.context.best_metrics = initial_metrics
            orch.context.best_params = orch.context.current_params.copy()
            orch._log_event(
                "initial_backtest_done",
                sharpe=initial_metrics.sharpe_ratio,
                total_return=initial_metrics.total_return,
                max_drawdown=initial_metrics.max_drawdown,
            )
            logger.info(
                "Backtest initial: Sharpe=%.3f, Return=%.2f%%",
                initial_metrics.sharpe_ratio,
                initial_metrics.total_return * 100,
            )
        else:
            orch._warnings.append("Backtest initial sans métriques")
            orch._log_event("warning", message="Backtest initial sans métriques")
    except Exception as e:
        orch._warnings.append(f"Erreur backtest initial: {e}")
        orch._log_event("warning", message=f"Erreur backtest initial: {e}")
        logger.error("Erreur backtest initial: %s", e, exc_info=True)

    # Fallback: create zero metrics if backtest failed
    if initial_metrics is None:
        logger.warning("Backtest initial échoué, utilisation de métriques par défaut (zéro)")
        initial_metrics = MetricsSnapshot(
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            total_trades=0,
        )
        orch.context.current_metrics = initial_metrics
        orch._warnings.append("Utilisation de métriques par défaut (backtest échoué)")
        orch._log_event("warning", message="Métriques par défaut utilisées")

    # Compute walk-forward metrics
    compute_walk_forward_metrics(orch)

    # Indicator context (once per run)
    ensure_indicator_context(orch)

    # Transition to ANALYZE
    orch.state_machine.transition_to(AgentState.ANALYZE)
