"""
Module-ID: ui.components.strategy_catalog_panel

Purpose: Strategy catalog panel (filters + multi-select + bulk move).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from catalog.strategy_catalog import CATEGORY_ORDER, STATUS_VALUES, list_entries, move_entries


_NOTE_ID_RE = re.compile(r"(?im)^\s*id\s*:\s*([a-z0-9_]+)\s*$")
_NOTE_ARCHETYPE_RE = re.compile(r"(?im)^\s*archetype\s*:\s*([a-z0-9_]+)\s*$")


def _extract_strategy_candidates(entry: Dict[str, object]) -> List[str]:
    candidates: List[str] = []

    strategy_name = str(entry.get("strategy_name") or "").strip()
    if strategy_name:
        candidates.append(strategy_name)

    note = str(entry.get("note") or "")
    for regex in (_NOTE_ID_RE, _NOTE_ARCHETYPE_RE):
        for match in regex.findall(note):
            value = str(match or "").strip()
            if value:
                candidates.append(value)

    # Dédupliquer en conservant l'ordre.
    deduped: List[str] = []
    for value in candidates:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _resolve_strategy_key(entry: Dict[str, object], available_keys: set[str]) -> str:
    for candidate in _extract_strategy_candidates(entry):
        if candidate in available_keys:
            return candidate
    return ""


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _first_present(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None and value != "":
                return value
    return None


@lru_cache(maxsize=512)
def _load_builder_session_summary(session_id: str) -> Dict[str, Any]:
    session_id = str(session_id or "").strip()
    if not session_id:
        return {}

    summary_path = Path("sandbox_strategies") / session_id / "session_summary.json"
    if not summary_path.exists():
        return {}

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _best_iteration_metrics(summary: Dict[str, Any]) -> Dict[str, Any]:
    iterations = summary.get("iterations")
    if not isinstance(iterations, list):
        return {}

    best: Optional[Dict[str, Any]] = None
    best_key: Optional[tuple] = None
    for item in iterations:
        if not isinstance(item, dict):
            continue
        sharpe = _to_float(item.get("sharpe"))
        ret = _to_float(item.get("return_pct"))
        pnl = _to_float(_first_present(item, "total_pnl", "pnl"))
        trades = _to_int(item.get("trades"))
        if sharpe is None and ret is None and pnl is None and trades is None:
            continue

        rank_key = (
            1 if sharpe is not None else 0,
            sharpe if sharpe is not None else float("-inf"),
            1 if ret is not None else 0,
            ret if ret is not None else float("-inf"),
            1 if pnl is not None else 0,
            pnl if pnl is not None else float("-inf"),
            trades if trades is not None else -1,
        )
        if best_key is None or rank_key > best_key:
            best_key = rank_key
            best = {
                "sharpe": sharpe,
                "return_pct": ret,
                "pnl": pnl,
                "trades": trades,
            }

    return best or {}


def _metrics_for_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    metrics = entry.get("last_metrics_snapshot") or {}
    if not isinstance(metrics, dict):
        metrics = {}

    sharpe = _first_present(metrics, "sharpe_ratio", "sharpe")

    ret = _first_present(metrics, "total_return_pct")
    if ret is None:
        total_return_ratio = _to_float(_first_present(metrics, "total_return"))
        if total_return_ratio is not None:
            ret = total_return_ratio * 100.0

    pnl = _first_present(metrics, "total_pnl", "pnl")
    trades = _first_present(metrics, "total_trades", "trades")
    initial_capital = _first_present(
        metrics,
        "initial_capital",
        "capital",
        "capital_initial",
        "starting_capital",
    )

    meta = entry.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    if sharpe is None:
        sharpe = _first_present(meta, "best_sharpe", "sharpe")
    if trades is None:
        trades = _first_present(meta, "best_trades", "total_trades", "trades")
    if ret is None:
        ret = _first_present(meta, "best_return_pct", "total_return_pct", "return_pct")
    if pnl is None:
        pnl = _first_present(meta, "best_pnl", "total_pnl", "pnl")
    if initial_capital is None:
        initial_capital = _first_present(
            meta,
            "initial_capital",
            "capital",
            "capital_initial",
            "starting_capital",
        )

    if sharpe is None or ret is None or pnl is None or trades is None:
        summary = _load_builder_session_summary(str(meta.get("session_id") or ""))
        fallback = _best_iteration_metrics(summary)
        if sharpe is None:
            sharpe = fallback.get("sharpe")
        if ret is None:
            ret = fallback.get("return_pct")
        if pnl is None:
            pnl = fallback.get("pnl")
        if trades is None:
            trades = fallback.get("trades")

    sharpe_value = _to_float(sharpe)
    return_pct_value = _to_float(ret)
    pnl_value = _to_float(pnl)
    initial_capital_value = _to_float(initial_capital)
    if initial_capital_value is None or initial_capital_value <= 0:
        initial_capital_value = 10000.0

    # Dérivation croisée PnL <-> Return% quand une seule des deux métriques est disponible.
    if return_pct_value is None and pnl_value is not None:
        return_pct_value = (pnl_value / initial_capital_value) * 100.0
    if pnl_value is None and return_pct_value is not None:
        pnl_value = initial_capital_value * (return_pct_value / 100.0)

    # Conserver None si la donnée n'existe pas réellement: mieux qu'un faux 0.
    trades_value = _to_int(trades)

    return {
        "sharpe": sharpe_value,
        "return_pct": return_pct_value,
        "pnl": pnl_value,
        "trades": trades_value,
    }


def render_strategy_catalog_panel(strategy_options: Dict[str, str]) -> None:
    st.markdown("---")
    st.subheader("🗂️ Strategy Catalog")
    st.caption(
        "💡 **Filtrez et sélectionnez vos stratégies** — "
        "Les filtres ci-dessous sont optionnels pour affiner la liste."
    )

    entries_all = list_entries(status=None)
    all_tags: List[str] = sorted({t for e in entries_all for t in (e.get("tags") or [])})
    all_symbols = sorted({e.get("symbol") for e in entries_all if e.get("symbol")})
    all_timeframes = sorted({e.get("timeframe") for e in entries_all if e.get("timeframe")})

    # Filtres principaux (catégorie + statut)
    col_a, col_b = st.columns(2)
    with col_a:
        categories = st.multiselect(
            "📂 Catégorie (filtre optionnel)",
            CATEGORY_ORDER,
            default=st.session_state.get("catalog_filter_categories", []),
            key="catalog_filter_categories",
            help="Laissez vide pour voir toutes les catégories"
        )
    with col_b:
        status = st.selectbox(
            "Statut",
            ["all"] + STATUS_VALUES,
            index=0,
            key="catalog_filter_status",
        )

    # Filtres avancés (collapsible pour éviter la confusion)
    with st.expander("🔍 Filtres avancés (optionnels)", expanded=False):
        st.caption("Ces filtres sont optionnels et servent uniquement à affiner la recherche.")

        col_c, col_d = st.columns(2)
        with col_c:
            symbols = st.multiselect(
                "🪙 Token (filtre)",
                all_symbols,
                default=st.session_state.get("catalog_filter_symbols", []),
                key="catalog_filter_symbols",
                help="Optionnel : filtrer par token spécifique"
            )
        with col_d:
            timeframes = st.multiselect(
                "⏰ Timeframe (filtre)",
                all_timeframes,
                default=st.session_state.get("catalog_filter_timeframes", []),
                key="catalog_filter_timeframes",
                help="Optionnel : filtrer par timeframe spécifique"
            )

        tags = st.multiselect(
            "🏷️ Tags (filtre)",
            all_tags,
            default=st.session_state.get("catalog_filter_tags", []),
            key="catalog_filter_tags",
            help="Optionnel : filtrer par tags"
        )

    # Récupérer les valeurs des filtres depuis session_state (car définies dans l'expander)
    symbols_filter = st.session_state.get("catalog_filter_symbols", [])
    timeframes_filter = st.session_state.get("catalog_filter_timeframes", [])
    tags_filter = st.session_state.get("catalog_filter_tags", [])

    # Appliquer les filtres
    entries = list_entries(
        categories=categories or None,
        tags=tags_filter or None,
        status=None if status == "all" else status,
    )
    if symbols_filter:
        entries = [e for e in entries if e.get("symbol") in symbols_filter]
    if timeframes_filter:
        entries = [e for e in entries if e.get("timeframe") in timeframes_filter]

    if not entries:
        st.info("Aucune entree dans le catalog avec ces filtres.")
        return

    reverse_strategy_options = {v: k for k, v in strategy_options.items()}
    available_strategy_keys = set(reverse_strategy_options.keys())

    rows = []
    selected_ids = set(st.session_state.get("catalog_selected_ids", []))
    for entry in entries:
        metrics = _metrics_for_entry(entry)
        resolved_strategy_key = _resolve_strategy_key(entry, available_strategy_keys)
        strategy_display = resolved_strategy_key or str(entry.get("strategy_name") or "")
        rows.append(
            {
                "select": entry.get("id") in selected_ids,
                "id": entry.get("id"),
                "strategy": strategy_display,
                "symbol": entry.get("symbol"),
                "timeframe": entry.get("timeframe"),
                "category": entry.get("category"),
                "status": entry.get("status"),
                "builder_state": entry.get("builder_state"),
                "tags": ", ".join(entry.get("tags") or []),
                "sharpe": metrics.get("sharpe"),
                "return_pct": metrics.get("return_pct"),
                "pnl": metrics.get("pnl"),
                "trades": metrics.get("trades"),
                "runnable": "yes" if resolved_strategy_key else "no",
            }
        )

    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "select": st.column_config.CheckboxColumn("Select"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
            "return_pct": st.column_config.NumberColumn("Return (%)", format="%.2f%%"),
            "pnl": st.column_config.NumberColumn("PnL ($)", format="$%.2f"),
            "trades": st.column_config.NumberColumn("Trades", format="%d"),
        },
        disabled=[
            "id",
            "strategy",
            "symbol",
            "timeframe",
            "category",
            "status",
            "builder_state",
            "tags",
            "sharpe",
            "return_pct",
            "pnl",
            "trades",
            "runnable",
        ],
    )

    selected_ids = edited.loc[edited["select"] == True, "id"].tolist()  # noqa: E712
    st.session_state["catalog_selected_ids"] = selected_ids

    # Résumé de sélection
    if selected_ids:
        runnable_count = sum(1 for row in rows if row["id"] in selected_ids and row["runnable"] == "yes")
        st.success(f"✅ **{len(selected_ids)} stratégie(s) sélectionnée(s)** — {runnable_count} exécutable(s)")
    else:
        st.info("ℹ️ Aucune stratégie sélectionnée. Cochez les cases pour sélectionner.")

    # Actions sur la sélection
    st.markdown("### Actions")
    action_col_a, action_col_b, action_col_c = st.columns([2, 1, 2])

    with action_col_a:
        move_to = st.selectbox(
            "📦 Déplacer vers catégorie",
            CATEGORY_ORDER,
            index=0,
            key="catalog_move_target",
            help="Déplacer les stratégies sélectionnées vers une autre catégorie"
        )
    with action_col_b:
        if st.button("📦 Move", key="catalog_move_btn", disabled=not selected_ids, use_container_width=True):
            changed = move_entries(selected_ids, move_to)
            st.success(f"✅ {changed} stratégie(s) déplacée(s)")
            st.rerun()
    with action_col_c:
        if st.button(
            "✅ Utiliser cette sélection",
            key="catalog_set_selection",
            disabled=not selected_ids,
            type="primary",
            use_container_width=True,
            help="Appliquer cette sélection comme stratégies actives pour le backtest"
        ):
            labels = []
            skipped = 0
            for entry in entries:
                if entry.get("id") not in selected_ids:
                    continue
                resolved_strategy_key = _resolve_strategy_key(entry, available_strategy_keys)
                label = reverse_strategy_options.get(resolved_strategy_key)
                if label:
                    labels.append(label)
                else:
                    skipped += 1
            # Ne pas modifier directement `strategies_select` ici:
            # le widget est instancié dans la sidebar plus haut dans ce run.
            # On passe par une sélection "pending" appliquée avant rendu widget.
            st.session_state["_catalog_strategy_selection_pending"] = labels
            st.session_state["_catalog_strategy_selection_skipped"] = skipped
            st.rerun()
