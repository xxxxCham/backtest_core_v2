"""
Module-ID: ui.validation_integration

Purpose: Intègre la validation walk-forward entre backend et UI.

Role in pipeline: validation / reporting

Key components: convert_fold_to_window_result

Inputs: ValidationFold, métriques

Outputs: WindowResult pour UI

Dependencies: backtest.validation, ui.components.validation_viewer

Conventions: Fenêtres temporelles validées

Read-if: Intégration validation walk-forward

Skip-if: Pas de validation walk-forward
"""

from __future__ import annotations

# pylint: disable=import-outside-toplevel
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.validation import ValidationFold
from ui.components.validation_viewer import ValidationReport, WindowResult


def convert_fold_to_window_result(
    fold: ValidationFold,
    fold_index: int,
    train_metrics: Dict[str, float],
    test_metrics: Dict[str, float],
    params: Dict[str, Any],
) -> WindowResult:
    """
    Convertit un ValidationFold en WindowResult pour le viewer UI.

    Args:
        fold: Fold de validation (contient train_df, test_df, timestamps)
        fold_index: Index de la fenêtre (0-based)
        train_metrics: Métriques calculées sur le train set
        test_metrics: Métriques calculées sur le test set
        params: Paramètres optimaux trouvés pour cette fenêtre

    Returns:
        WindowResult prêt pour l'affichage UI
    """
    return WindowResult(
        window_id=fold_index + 1,  # 1-based pour UI
        train_start=fold.train_start,
        train_end=fold.train_end,
        test_start=fold.test_start,
        test_end=fold.test_end,
        # Métriques train
        train_sharpe=train_metrics.get("sharpe_ratio", 0.0),
        train_return=train_metrics.get("total_return_pct", 0.0) / 100.0,  # Convertir % → ratio
        train_drawdown=abs(train_metrics.get("max_drawdown", 0.0)) / 100.0,
        train_trades=int(train_metrics.get("total_trades", 0)),
        # Métriques test
        test_sharpe=test_metrics.get("sharpe_ratio", 0.0),
        test_return=test_metrics.get("total_return_pct", 0.0) / 100.0,
        test_drawdown=abs(test_metrics.get("max_drawdown", 0.0)) / 100.0,
        test_trades=int(test_metrics.get("total_trades", 0)),
        # Paramètres
        params=params,
    )


def create_validation_report_from_results(
    strategy_name: str,
    validation_results: Dict[str, Any],
    created_at: Optional[datetime] = None,
) -> ValidationReport:
    """
    Crée un ValidationReport à partir des résultats de run_walk_forward_for_agent().

    Args:
        strategy_name: Nom de la stratégie testée
        validation_results: Résultats retournés par run_walk_forward_for_agent()
            Structure attendue:
            {
                'folds': List[Dict] avec keys: 'fold_id', 'train_metrics', 'test_metrics', 'params'
                'n_folds': int
                'train_pct': float (ex: 0.75)
                ... autres champs possibles
            }
        created_at: Timestamp du rapport (optionnel, défaut=maintenant)

    Returns:
        ValidationReport prêt pour render_validation_report()

    Example:
        >>> from agents.integration import run_walk_forward_for_agent
        >>> results = run_walk_forward_for_agent(strategy_name, params, data)
        >>> report = create_validation_report_from_results("ema_cross", results)
        >>> render_validation_report(report)
    """
    if created_at is None:
        created_at = datetime.now()

    folds_data = validation_results.get("folds", [])
    n_splits = validation_results.get("n_folds", len(folds_data))
    train_ratio = validation_results.get("train_pct", 0.75)

    # Convertir chaque fold en WindowResult
    windows: List[WindowResult] = []

    for i, fold_data in enumerate(folds_data):
        # Le fold peut contenir directement les timestamps ou un objet ValidationFold
        fold_obj = fold_data.get("fold")  # ValidationFold object si disponible
        train_metrics = fold_data.get("train_metrics", {})
        test_metrics = fold_data.get("test_metrics", {})
        params = fold_data.get("params", {})

        if fold_obj is not None and isinstance(fold_obj, ValidationFold):
            # Cas idéal : on a l'objet ValidationFold complet
            window = convert_fold_to_window_result(
                fold=fold_obj,
                fold_index=i,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                params=params,
            )
        else:
            # Fallback : reconstruire depuis les timestamps dans fold_data
            window = WindowResult(
                window_id=i + 1,
                train_start=pd.Timestamp(fold_data.get("train_start")),
                train_end=pd.Timestamp(fold_data.get("train_end")),
                test_start=pd.Timestamp(fold_data.get("test_start")),
                test_end=pd.Timestamp(fold_data.get("test_end")),
                # Métriques train
                train_sharpe=train_metrics.get("sharpe_ratio", 0.0),
                train_return=train_metrics.get("total_return_pct", 0.0) / 100.0,
                train_drawdown=abs(train_metrics.get("max_drawdown", 0.0)) / 100.0,
                train_trades=int(train_metrics.get("total_trades", 0)),
                # Métriques test
                test_sharpe=test_metrics.get("sharpe_ratio", 0.0),
                test_return=test_metrics.get("total_return_pct", 0.0) / 100.0,
                test_drawdown=abs(test_metrics.get("max_drawdown", 0.0)) / 100.0,
                test_trades=int(test_metrics.get("total_trades", 0)),
                # Paramètres
                params=params,
            )

        windows.append(window)

    return ValidationReport(
        strategy_name=strategy_name,
        created_at=created_at,
        windows=windows,
        n_splits=n_splits,
        train_ratio=train_ratio,
        purge_gap=0,  # NOTE: recuperer depuis validation_results si disponible
    )


def run_validation_and_display(
    strategy_name: str,
    params: Dict[str, Any],
    data: pd.DataFrame,
    n_windows: int = 6,
    train_ratio: float = 0.75,
    key: str = "walk_forward_validation",
) -> Optional[ValidationReport]:
    """
    Fonction tout-en-un : exécute Walk-Forward et affiche le rapport UI.

    Args:
        strategy_name: Nom de la stratégie
        params: Paramètres à valider
        data: DataFrame OHLCV
        n_windows: Nombre de fenêtres (défaut: 6 pour 2 ans de données)
        train_ratio: Ratio train/test (défaut: 0.75)
        key: Clé Streamlit unique

    Returns:
        ValidationReport généré (ou None si erreur)

    Example:
        >>> # Dans ui/app.py
        >>> if st.button("🔍 Validation Walk-Forward"):
        >>>     report = run_validation_and_display(
        >>>         strategy_name="ema_cross",
        >>>         params={"fast_period": 12, "slow_period": 26},
        >>>         data=df,
        >>>     )
    """
    try:
        import streamlit as st

        from agents.integration import run_walk_forward_for_agent
        from ui.components.validation_viewer import render_validation_report

        # Afficher un spinner pendant l'exécution
        with st.spinner(f"🔄 Walk-Forward Validation en cours ({n_windows} fenêtres)..."):
            validation_results = run_walk_forward_for_agent(
                strategy_name=strategy_name,
                params=params,
                data=data,
                n_windows=n_windows,
                train_ratio=train_ratio,
            )

        # Convertir en ValidationReport
        report = create_validation_report_from_results(
            strategy_name=strategy_name,
            validation_results=validation_results,
        )

        # Afficher le rapport UI
        render_validation_report(report, key=key)

        return report

    except Exception as e:
        import streamlit as st
        st.error(f"❌ Erreur lors de la validation Walk-Forward: {e}")
        import traceback
        st.code(traceback.format_exc())
        return None


__all__ = [
    "convert_fold_to_window_result",
    "create_validation_report_from_results",
    "run_validation_and_display",
]
