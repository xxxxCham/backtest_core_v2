"""
Module-ID: ui.helpers

Purpose: Utilitaires UI - tables stratégies markdown, stat calcs, cache streamlit helpers.

Role in pipeline: user interface utilities

Key components: generate_strategies_table(), format_metric(), st_cache wrappers

Inputs: Strategies registry, metric values

Outputs: Markdown tables, formatted strings, cached dataframes

Dependencies: streamlit, pandas, ui.constants, ui.context

Conventions: Cache streamlit TTL; markdown tables sync auto; metric formatting précision.

Read-if: Modification format output ou stat calculations.

Skip-if: Vous appelez generate_strategies_table().
"""

from __future__ import annotations

# pylint: disable=too-many-lines
import math
import statistics
import time
import traceback
from decimal import Decimal, ROUND_FLOOR
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from ui.constants import (
    PARAM_CONSTRAINTS,
    get_strategy_description,
    get_strategy_display_name,
    get_strategy_type,
)
from ui.context import (
    BACKEND_AVAILABLE,
    ParameterSpec,
    calculate_indicator,
    get_storage,
    get_strategy,
    list_strategies,
    load_ohlcv,
)
from utils.observability import generate_run_id, get_obs_logger


def _coerce_period_timestamp(value: Any) -> Optional[pd.Timestamp]:
    """Normalise une valeur de date/heure en Timestamp UTC comparable."""
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def compute_period_days(start_ts: Any, end_ts: Any) -> int:
    """
    Calcule le nombre de jours entre deux timestamps.

    Args:
        start_ts: Timestamp/date/string de début
        end_ts: Timestamp/date/string de fin

    Returns:
        Nombre de jours (entier)
    """
    start_norm = _coerce_period_timestamp(start_ts)
    end_norm = _coerce_period_timestamp(end_ts)
    if start_norm is None or end_norm is None:
        return 0
    delta = end_norm - start_norm
    delta_seconds = float(delta.total_seconds())
    if not math.isfinite(delta_seconds) or delta_seconds < 0:
        return 0
    return max(1, int(delta_seconds / 86400))


def compute_period_days_from_df(df: pd.DataFrame) -> int:
    """
    Calcule le nombre de jours couverts par un DataFrame OHLCV.

    Args:
        df: DataFrame avec index datetime

    Returns:
        Nombre de jours (entier)
    """
    if df is None or df.empty:
        return 0
    return compute_period_days(df.index[0], df.index[-1])


def coerce_metric_float(value: Any, default: float = 0.0) -> float:
    """Convertit une métrique potentiellement sérialisée en float exploitable."""
    if value is None:
        return default
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass

    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else default

    if isinstance(value, str):
        cleaned = (
            value.strip()
            .replace("$", "")
            .replace("%", "")
            .replace(" ", "")
            .replace(",", "")
        )
        if not cleaned:
            return default
        try:
            number = float(cleaned)
        except ValueError:
            return default
        return number if math.isfinite(number) else default

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def format_pnl_with_daily(
    pnl: Any,
    period_days: int,
    show_plus: bool = False,
    escape_markdown: bool = False,
) -> str:
    """
    Formate un PnL avec son équivalent journalier.

    Args:
        pnl: PnL total
        period_days: Nombre de jours de la période
        show_plus: Si True, affiche un + devant les valeurs positives

    Returns:
        Chaîne formatée "PnL (PnL/jour/day)"
    """
    pnl_value = coerce_metric_float(pnl, default=0.0)
    if period_days <= 0:
        prefix = "+" if show_plus and pnl_value > 0 else ""
        result = f"{prefix}${pnl_value:,.2f}"
        return result.replace("$", "\\$") if escape_markdown else result

    pnl_per_day = pnl_value / period_days
    prefix = "+" if show_plus and pnl_value > 0 else ""
    result = f"{prefix}${pnl_value:,.2f} ({prefix}${pnl_per_day:,.2f}/jour)"
    return result.replace("$", "\\$") if escape_markdown else result


def generate_strategies_table() -> str:
    """
    Génère dynamiquement le tableau markdown des stratégies disponibles.

    Synchronise automatiquement avec le registre des stratégies pour éviter
    toute divergence entre la sidebar et la page principale.
    """
    available = list_strategies()

    table_lines = [
        "### Stratégies Disponibles",
        "",
        "| Stratégie | Type | Description |",
        "|-----------|------|-------------|",
    ]

    for strat_key in sorted(available):
        name = get_strategy_display_name(strat_key)
        stype = get_strategy_type(strat_key)
        desc = get_strategy_description(strat_key) or "Stratégie personnalisée"
        table_lines.append(f"| **{name}** | {stype} | {desc} |")

    return "\n".join(table_lines)


class ProgressMonitor:
    """
    Moniteur de progression en temps réel pour les backtests.

    Calcule la vitesse d'exécution et estime le temps restant en utilisant
    une moyenne glissante sur les 3 dernières secondes.
    """

    def __init__(self, total_runs: int):
        self.total_runs = total_runs
        self.runs_completed = 0
        self.start_time = time.perf_counter()
        self.history = deque(maxlen=3)
        self.last_update_time = self.start_time

    def update(self, runs_completed: int) -> Dict[str, Any]:
        self.runs_completed = runs_completed
        current_time = time.perf_counter()

        self.history.append((current_time, runs_completed))

        if len(self.history) >= 2:
            time_span = self.history[-1][0] - self.history[0][0]
            runs_in_span = self.history[-1][1] - self.history[0][1]

            if time_span > 0 and runs_in_span > 0:
                iteration_speed_per_sec = runs_in_span / time_span
                iteration_speed_per_2sec = iteration_speed_per_sec * 2
            else:
                iteration_speed_per_sec = 0
                iteration_speed_per_2sec = 0
        else:
            iteration_speed_per_sec = 0
            iteration_speed_per_2sec = 0

        elapsed_time = current_time - self.start_time

        remaining_runs = self.total_runs - runs_completed
        if iteration_speed_per_sec > 0 and remaining_runs > 0:
            time_remaining_sec = remaining_runs / iteration_speed_per_sec
        else:
            time_remaining_sec = 0

        progress = runs_completed / self.total_runs if self.total_runs > 0 else 0

        self.last_update_time = current_time

        return {
            "progress": progress,
            "runs_completed": runs_completed,
            "total_runs": self.total_runs,
            "speed_per_2sec": iteration_speed_per_2sec,
            "speed_per_sec": iteration_speed_per_sec,
            "elapsed_time_sec": elapsed_time,
            "time_remaining_sec": time_remaining_sec,
        }

    def format_time(self, seconds: float) -> str:
        if seconds <= 0:
            return "0s"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)


def render_progress_monitor(monitor: ProgressMonitor, placeholder) -> None:
    """
    Affiche la progression du backtest avec gestion des déconnexions WebSocket.

    Si le client se déconnecte (page fermée/rafraîchie), les erreurs sont
    ignorées silencieusement au lieu de polluer les logs.
    """
    try:
        metrics = monitor.update(monitor.runs_completed)

        with placeholder.container():
            st.progress(metrics["progress"])

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric(
                    "Progression",
                    f"{metrics['runs_completed']}/{metrics['total_runs']}",
                    f"{metrics['progress']*100:.1f}%",
                )

            with col2:
                st.metric(
                    "Vitesse",
                    f"{metrics['speed_per_sec']:.2f} runs/s",
                    f"{metrics['speed_per_2sec']:.1f} runs/2s",
                )

            with col3:
                elapsed_str = monitor.format_time(metrics["elapsed_time_sec"])
                st.metric("Temps écoulé", elapsed_str)

            with col4:
                remaining_str = monitor.format_time(metrics["time_remaining_sec"])
                st.metric("Temps restant", remaining_str)
    except Exception:
        # Client déconnecté (WebSocket fermé) - ignorer silencieusement
        pass


def render_live_metrics(
    placeholder,
    completed: int,
    total: int,
    start_time: float,
    best_pnl: float = 0.0,
    best_dd: float = 0.0,
    equity: Optional[float] = None,
) -> None:
    """
    Affichage live ultra-simple : un seul placeholder.markdown().
    Pas de container(), pas de widgets, pas de columns.
    Garantit un affichage fiable pendant les sweeps.
    """
    now = time.perf_counter()
    elapsed = now - start_time
    rate = completed / elapsed if elapsed > 0 and completed > 0 else 0.0
    pct = int(100 * completed / total) if total > 0 else 0
    remaining = (total - completed) / rate if rate > 0 else 0.0

    def _fmt(s: float) -> str:
        if s <= 0:
            return "—"
        m, sec = divmod(int(s), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m:02d}m{sec:02d}s"
        if m:
            return f"{m}m{sec:02d}s"
        return f"{sec}s"

    # ━━━ Tout en un seul bloc markdown ━━━
    if completed >= total and total > 0:
        line1 = f"### ✅ Terminé en {_fmt(elapsed)} · ⚡ {rate:,.0f} bt/s"
    elif rate > 0:
        line1 = f"### ⏱️ {_fmt(elapsed)} écoulé · ⏳ ~{_fmt(remaining)} restant · ⚡ {rate:,.0f} bt/s"
    else:
        line1 = f"### ⏱️ {_fmt(elapsed)} écoulé · ⏳ démarrage..."

    bar_len = 30
    filled = int(bar_len * pct / 100) if pct > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    line2 = f"`{bar}` **{completed:,}** / {total:,} ({pct}%)"

    parts = [line1, line2]
    if completed > 0 and (best_pnl != 0 or best_dd != 0):
        pnl_str = f"💰 **${best_pnl:+,.0f}**"
        dd_str = f"📉 DD {abs(best_dd):.1f}%"
        if equity is not None:
            eq_str = f"💹 Equity ${equity:,.0f}"
            parts.append(f"{pnl_str} · {dd_str} · {eq_str}")
        else:
            parts.append(f"{pnl_str} · {dd_str}")

    try:
        placeholder.markdown("\n\n".join(parts))
    except Exception as exc:
        # Ne PAS avaler silencieusement — logger pour debug
        print(f"[render_live_metrics ERROR] {exc}", flush=True)


def show_status(status_type: str, message: str, details: Optional[str] = None):
    if status_type == "success":
        st.success(f"✅ {message}")
    elif status_type == "error":
        st.error(f"❌ {message}")
        if details:
            with st.expander("Détails de l'erreur"):
                st.code(details)
    elif status_type == "warning":
        st.warning(f"⚠️ {message}")
    elif status_type == "info":
        st.info(f"ℹ️ {message}")


def validate_param(name: str, value: Any) -> Tuple[bool, str]:
    if name not in PARAM_CONSTRAINTS:
        return True, ""

    constraints = PARAM_CONSTRAINTS[name]

    if value < constraints["min"]:
        return False, f"{name} doit être ≥ {constraints['min']}"

    if value > constraints["max"]:
        return False, f"{name} doit être ≤ {constraints['max']}"

    return True, ""


def validate_all_params(params: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    for name, value in params.items():
        is_valid, error = validate_param(name, value)
        if not is_valid:
            errors.append(error)

    if "fast_period" in params and "slow_period" in params:
        if params["fast_period"] >= params["slow_period"]:
            errors.append("fast_period doit être < slow_period")

    return len(errors) == 0, errors


def apply_versioned_preset(preset: Any, strategy_key: str) -> None:
    try:
        values = preset.get_default_values()
    except Exception:
        values = {}

    for name, value in values.items():
        st.session_state[f"{strategy_key}_{name}"] = value

    if "leverage" in values:
        st.session_state["trading_leverage"] = values["leverage"]


def _infer_step_decimals(step: float) -> int:
    step_str = f"{step:.12f}".rstrip("0").rstrip(".")
    if "." in step_str:
        return len(step_str.split(".")[1])
    return 0


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ratio(value: Any, spec: Optional[ParameterSpec]) -> Optional[float]:
    if spec is None:
        return None

    min_val = _to_float(getattr(spec, "min_val", None))
    max_val = _to_float(getattr(spec, "max_val", None))
    step = _to_float(getattr(spec, "step", None))
    if min_val is None or max_val is None:
        return None
    if step is None or step <= 0:
        return None

    span = max_val - min_val
    if span <= 0:
        return None

    value_float = _to_float(value)
    if value_float is None:
        return None

    ratio = (value_float - min_val) / span
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


def _snap_value_to_spec(value: float, spec: Optional[ParameterSpec]) -> float:
    if spec is None:
        return value

    min_val = _to_float(getattr(spec, "min_val", None))
    max_val = _to_float(getattr(spec, "max_val", None))
    step = _to_float(getattr(spec, "step", None))
    if min_val is None or max_val is None:
        return value

    clamped = min(max(value, min_val), max_val)

    if step is None or step <= 0:
        return clamped

    min_dec = Decimal(str(min_val))
    step_dec = Decimal(str(step))
    target_dec = Decimal(str(clamped))
    steps = int(round(float((target_dec - min_dec) / step_dec)))
    snapped = min_dec + step_dec * steps

    max_dec = Decimal(str(max_val))
    if snapped < min_dec:
        snapped = min_dec
    elif snapped > max_dec:
        snapped = max_dec

    is_int = getattr(spec, "param_type", "") in ("int", int)
    if is_int:
        return float(int(round(float(snapped))))

    decimals = _infer_step_decimals(step)
    if decimals > 0:
        snapped = snapped.quantize(Decimal(1).scaleb(-decimals))
    return float(snapped)


def granularity_transform(
    params: Dict[str, Any],
    param_specs: Dict[str, ParameterSpec],
    delta: float,
    direction: str,
) -> Dict[str, Any]:
    """
    Applique une variation de granularité globale sur des paramètres.

    Règles:
    - direction='increase': rapproche vers max
    - direction='decrease': rapproche vers min
    - respect strict de min/max/step via snap final
    """
    if not params:
        return dict(params)

    delta_float = _to_float(delta)
    if delta_float is None or delta_float <= 0:
        return dict(params)
    delta_float = min(delta_float, 1.0)

    direction_norm = str(direction or "").strip().lower()
    if direction_norm not in {"increase", "decrease"}:
        return dict(params)

    transformed: Dict[str, Any] = dict(params)
    for name, current_value in params.items():
        spec = param_specs.get(name)
        ratio = _normalize_ratio(current_value, spec)
        if ratio is None:
            continue

        min_val = _to_float(getattr(spec, "min_val", None))
        max_val = _to_float(getattr(spec, "max_val", None))
        if min_val is None or max_val is None:
            continue

        if direction_norm == "increase":
            ratio_new = 1.0 - (1.0 - ratio) * (1.0 - delta_float)
        else:
            ratio_new = ratio * (1.0 - delta_float)

        target_value = min_val + ratio_new * (max_val - min_val)
        snapped_value = _snap_value_to_spec(target_value, spec)

        if getattr(spec, "param_type", "") in ("int", int):
            transformed[name] = int(round(snapped_value))
        else:
            transformed[name] = float(snapped_value)

    return transformed


def compute_global_granularity_percent(
    all_params: Dict[str, Dict[str, Any]],
    all_param_specs: Dict[str, Dict[str, ParameterSpec]],
) -> Optional[float]:
    """Calcule la granularité globale agrégée (moyenne des ratios normalisés) en %."""
    ratios: List[float] = []
    for strategy_key, params in (all_params or {}).items():
        specs = (all_param_specs or {}).get(strategy_key, {})
        if not params or not specs:
            continue
        for name, value in params.items():
            ratio = _normalize_ratio(value, specs.get(name))
            if ratio is not None:
                ratios.append(ratio)

    if not ratios:
        return None
    return (sum(ratios) / len(ratios)) * 100.0


def build_param_values(
    min_v: float,
    max_v: float,
    step: float,
    is_int: bool,
) -> List[float]:
    if step is None or step <= 0 or max_v < min_v:
        return [float(min_v)]

    if is_int:
        step_int = max(1, int(round(step)))
        return list(range(int(min_v), int(max_v) + 1, step_int))

    step_dec = Decimal(str(step))
    min_dec = Decimal(str(min_v))
    max_dec = Decimal(str(max_v))
    if step_dec <= 0:
        return [float(min_v)]

    count = int(((max_dec - min_dec) / step_dec).to_integral_value(rounding=ROUND_FLOOR)) + 1
    decimals = _infer_step_decimals(step)
    quant = Decimal(1).scaleb(-decimals) if decimals > 0 else None

    values: List[float] = []
    for i in range(count):
        v = min_dec + step_dec * i
        if v > max_dec:
            break
        if quant is not None:
            v = v.quantize(quant)
        val = float(v)
        if not values or val != values[-1]:
            values.append(val)

    if not values:
        values = [float(min_v)]

    return values


def create_param_range_selector(
    name: str,
    key_prefix: str = "",
    mode: str = "single",
    spec: Optional[ParameterSpec] = None,
    label: Optional[str] = None,
    container: Any = None,
) -> Any:
    constraints: Dict[str, Any] = {}
    is_int = False
    display_name = label or name

    if spec is not None:
        spec_type = spec.param_type
        is_int = spec_type == "int" or spec_type is int
        step = spec.step
        if step is None:
            range_size = float(spec.max_val) - float(spec.min_val)
            if is_int:
                step = max(1, int(range_size / 10))
            else:
                step = range_size / 10 if range_size > 0 else 0.1
        if is_int:
            step = max(1, int(round(step)))
        constraints = {
            "min": spec.min_val,
            "max": spec.max_val,
            "step": step,
            "default": spec.default,
            "description": spec.description,
            "type": "int" if is_int else "float",
        }

    else:
        from ui.constants import PARAM_CONSTRAINTS
        if name not in PARAM_CONSTRAINTS:
            st.sidebar.warning(f"Paramètre {name} sans contraintes définies")
            return None
        constraints = dict(PARAM_CONSTRAINTS[name])
        step = constraints.get("step", 1)
        is_int = constraints.get("type") == "int"
        if not is_int:
            try:
                is_int = float(step).is_integer()
            except (TypeError, ValueError):
                is_int = False

    unique_key = f"{key_prefix}_{name}"
    ui = container or st.sidebar

    if mode == "single":
        if is_int:
            return ui.slider(
                display_name,
                min_value=int(constraints["min"]),
                max_value=int(constraints["max"]),
                value=int(constraints["default"]),
                step=int(constraints["step"]),
                help=constraints["description"],
                key=unique_key,
            )
        return ui.slider(
            display_name,
            min_value=float(constraints["min"]),
            max_value=float(constraints["max"]),
            value=float(constraints["default"]),
            step=float(constraints["step"]),
            help=constraints["description"],
            key=unique_key,
        )

    with ui.expander(f"📊 {display_name}", expanded=False):
        st.caption(constraints["description"])

        col1, col2 = st.columns(2)

        if is_int:
            with col1:
                param_min = st.number_input(
                    "Min",
                    value=int(constraints["min"]),
                    step=1,
                    key=f"{unique_key}_min",
                )
            with col2:
                param_max = st.number_input(
                    "Max",
                    value=int(constraints["max"]),
                    step=1,
                    key=f"{unique_key}_max",
                )
            param_step = st.number_input(
                "Step",
                min_value=1,
                value=int(constraints["step"]),
                step=1,
                key=f"{unique_key}_step",
            )
        else:
            with col1:
                param_min = st.number_input(
                    "Min",
                    value=float(constraints["min"]),
                    step=0.1,
                    format="%.2f",
                    key=f"{unique_key}_min",
                )
            with col2:
                param_max = st.number_input(
                    "Max",
                    value=float(constraints["max"]),
                    step=0.1,
                    format="%.2f",
                    key=f"{unique_key}_max",
                )
            param_step = st.number_input(
                "Step",
                min_value=0.01,
                value=float(constraints["step"]),
                step=0.01,
                format="%.2f",
                key=f"{unique_key}_step",
            )

        if param_max >= param_min and param_step > 0:
            values = build_param_values(param_min, param_max, param_step, is_int=is_int)
            nb_values = max(1, len(values))
            st.caption(f"→ {nb_values} valeurs à tester")
        else:
            nb_values = 1
            st.warning("⚠️ Plage invalide")

        return {
            "min": param_min,
            "max": param_max,
            "step": param_step,
            "count": nb_values,
        }


def create_constrained_slider(name: str, granularity: float, key_prefix: str = "") -> Any:
    _ = granularity
    return create_param_range_selector(name, key_prefix, mode="single")


def extract_strategy_params_metadata(strategy_key: str) -> Tuple[Dict[str, ParameterSpec], Dict[str, Any], Dict[str, Any]]:
    """
    Extrait les métadonnées des paramètres d'une stratégie sans créer de widgets UI.

    Args:
        strategy_key: Clé unique de la stratégie

    Returns:
        Tuple de (param_specs, params, param_ranges) où:
        - param_specs: Dict des ParameterSpec
        - params: Dict des valeurs par défaut
        - param_ranges: Dict vide (pour compatibilité)
    """
    from ui.context import get_strategy

    strategy_class = get_strategy(strategy_key)
    if not strategy_class:
        return {}, {}, {}

    temp_strategy = strategy_class()
    param_specs = temp_strategy.parameter_specs or {}
    params = {}

    for param_name, spec in param_specs.items():
        if not getattr(spec, "optimize", True):
            continue
        params[param_name] = spec.default

    return param_specs, params, {}


def render_multi_strategy_params(
    strategy_keys: List[str],
    strategy_names: List[str],
    param_mode: str = "single",
    existing_state: Optional[Dict[str, Dict[str, Any]]] = None,
    granularity_delta: float = 0.0,
    granularity_direction: Optional[str] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Affiche les widgets de paramètres pour plusieurs stratégies sélectionnées.

    Args:
        strategy_keys: Liste des clés de stratégies
        strategy_names: Liste des noms d'affichage
        param_mode: "single" ou "range"
        existing_state: État existant des paramètres (pour préserver les valeurs modifiées)

    Returns:
        Tuple de (all_params, all_param_ranges, all_param_specs)
    """
    if existing_state is None:
        existing_state = st.session_state.get("multi_strategy_params", {})

    all_params = {}
    all_param_ranges = {}
    all_param_specs = {}

    for idx, (strat_key, strat_name) in enumerate(zip(strategy_keys, strategy_names)):
        # Extraire les métadonnées de la stratégie
        param_specs, default_params, _ = extract_strategy_params_metadata(strat_key)

        if not param_specs:
            continue

        # Section pour cette stratégie
        st.sidebar.markdown("---")
        strategy_header = f"📋 **Stratégie {idx + 1}**: {strat_name}"
        st.sidebar.markdown(strategy_header)

        params = {}
        param_ranges = {}

        # Récupérer l'état existant pour cette stratégie (si déjà modifié)
        existing_params = existing_state.get(strat_key, {})

        if param_mode == "single":
            # Prépare les valeurs actuelles pour une éventuelle transformation globale.
            current_values: Dict[str, Any] = {}
            for param_name, spec in param_specs.items():
                if not getattr(spec, "optimize", True):
                    continue
                unique_key_prefix = f"strat{idx}_{strat_key}"
                widget_key = f"{unique_key_prefix}_{param_name}"
                if widget_key not in st.session_state:
                    init_value = existing_params.get(param_name, spec.default)
                    st.session_state[widget_key] = init_value
                current_values[param_name] = st.session_state.get(widget_key, spec.default)

            if granularity_direction in {"increase", "decrease"} and granularity_delta > 0:
                updated_values = granularity_transform(
                    params=current_values,
                    param_specs=param_specs,
                    delta=granularity_delta,
                    direction=granularity_direction,
                )
                for param_name, new_value in updated_values.items():
                    widget_key = f"strat{idx}_{strat_key}_{param_name}"
                    st.session_state[widget_key] = new_value
        elif (
            param_mode == "range"
            and granularity_direction in {"increase", "decrease"}
            and granularity_delta > 0
        ):
            # En mode range, on ajuste la borne max de chaque paramètre.
            for param_name, spec in param_specs.items():
                if not getattr(spec, "optimize", True):
                    continue

                unique_key_prefix = f"strat{idx}_{strat_key}"
                min_key = f"{unique_key_prefix}_{param_name}_min"
                max_key = f"{unique_key_prefix}_{param_name}_max"

                if min_key not in st.session_state:
                    st.session_state[min_key] = getattr(spec, "min_val", None)
                if max_key not in st.session_state:
                    st.session_state[max_key] = getattr(spec, "max_val", None)

                current_min = st.session_state.get(min_key, getattr(spec, "min_val", None))
                current_max = st.session_state.get(max_key, getattr(spec, "max_val", None))
                updated_max = granularity_transform(
                    params={param_name: current_max},
                    param_specs={param_name: spec},
                    delta=granularity_delta,
                    direction=granularity_direction,
                ).get(param_name, current_max)

                try:
                    if float(updated_max) < float(current_min):
                        updated_max = current_min
                except (TypeError, ValueError):
                    pass

                st.session_state[max_key] = updated_max

        for param_name, spec in param_specs.items():
            if not getattr(spec, "optimize", True):
                continue

            # Clé unique pour éviter les collisions entre stratégies
            unique_key_prefix = f"strat{idx}_{strat_key}"
            widget_key = f"{unique_key_prefix}_{param_name}"

            if param_mode == "single":
                value = create_param_range_selector(
                    param_name,
                    unique_key_prefix,
                    mode="single",
                    spec=spec,
                )
                if value is not None:
                    params[param_name] = value
            else:  # mode == "range"
                # En mode range, on ne pré-initialise pas (les widgets sont des expanders)
                range_data = create_param_range_selector(
                    param_name,
                    unique_key_prefix,
                    mode="range",
                    spec=spec,
                )
                if range_data is not None:
                    param_ranges[param_name] = range_data
                    params[param_name] = spec.default

        all_params[strat_key] = params
        all_param_ranges[strat_key] = param_ranges
        all_param_specs[strat_key] = param_specs

        # Mettre à jour l'état persistant avec les nouvelles valeurs
        if strat_key not in existing_state:
            existing_state[strat_key] = {}
        existing_state[strat_key].update(params)

    # Persister l'état global
    st.session_state["multi_strategy_params"] = existing_state

    return all_params, all_param_ranges, all_param_specs


def safe_load_data(
    symbol: str,
    timeframe: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    symbol = str(symbol or "").strip().upper()
    timeframe = str(timeframe or "").strip()
    if symbol in {"", "_", "UNKNOWN"} or timeframe in {"", "_"}:
        return None, "❌ Sélectionnez un symbole et un timeframe valides."

    try:
        df = load_ohlcv(symbol, timeframe, start=start, end=end)

        if df is None or df.empty:
            return None, "❌ Données vides ou fichier non trouvé"

        required_cols = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return None, f"❌ Colonnes manquantes: {missing}"

        if not isinstance(df.index, pd.DatetimeIndex):
            return None, "❌ L'index n'est pas un DatetimeIndex"

        # Validation plus détaillée des données
        nan_count = df.isna().sum().sum()
        total_values = len(df) * len(df.columns)
        nan_pct = (nan_count / total_values) * 100 if total_values > 0 else 0

        if nan_pct > 10:
            return None, f"❌ Trop de valeurs NaN ({nan_pct:.1f}%, {nan_count}/{total_values})"

        # Validation cohérence OHLC
        invalid_ohlc = ((df['high'] < df['low']) |
                       (df['open'] < df['low']) | (df['open'] > df['high']) |
                       (df['close'] < df['low']) | (df['close'] > df['high'])).sum()

        if invalid_ohlc > 0:
            return None, f"❌ Données OHLC incohérentes ({invalid_ohlc} barres)"

        start_fmt = df.index[0].strftime("%Y-%m-%d %H:%M")
        end_fmt = df.index[-1].strftime("%Y-%m-%d %H:%M")
        quality_msg = f"NaN: {nan_pct:.1f}%" if nan_pct > 0 else "✓ Propre"
        return df, f"✅ {len(df)} barres ({start_fmt} → {end_fmt}) - {quality_msg}"

    except FileNotFoundError:
        from data.loader import _get_data_dir
        data_dir = _get_data_dir()
        return None, f"📁 Fichier non trouvé: {symbol}_{timeframe} dans {data_dir}"
    except ValueError as e:
        return None, f"📊 Erreur de données: {str(e)}"
    except pd.errors.EmptyDataError:
        return None, f"📄 Fichier vide: {symbol}_{timeframe}"
    except pd.errors.ParserError as e:
        return None, f"🔧 Erreur format fichier: {str(e)}"
    except Exception as exc:
        import traceback
        tb_summary = traceback.format_exc().split('\n')[-3] if len(traceback.format_exc().split('\n')) > 2 else str(exc)
        return None, f"⚠️ Erreur inattendue: {tb_summary}"


def apply_auto_market_stabilization_filter(
    df: pd.DataFrame,
    *,
    enabled: bool = False,
    method: str = "hybrid",
    window: int = 48,
    volume_ratio_max: float = 3.0,
    volatility_ratio_max: float = 2.5,
    min_consecutive_bars: int = 6,
    min_bars_keep: int = 200,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Coupe automatiquement un préfixe de marché instable (warmup/anomalies),
    puis retourne le DataFrame filtré et un rapport synthétique.

    Le rapport contient toujours les clés attendues par l'UI:
    - applied: bool
    - cut_bars: int
    - start_ts: str
    """
    info: Dict[str, Any] = {
        "applied": False,
        "cut_bars": 0,
        "start_ts": "n/a",
        "method": str(method or "hybrid"),
        "reason": "disabled",
    }

    if df is None or df.empty:
        info["reason"] = "empty_dataframe"
        return df, info

    if not enabled:
        return df, info

    required_cols = {"close", "volume"}
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        info["reason"] = f"missing_columns:{','.join(sorted(missing_cols))}"
        return df, info

    try:
        n_rows = len(df)
        min_keep = max(10, int(min_bars_keep))
        if n_rows <= min_keep:
            info["reason"] = "not_enough_rows"
            return df, info

        method_norm = str(method or "hybrid").strip().lower()
        if method_norm not in {"hybrid", "volume", "volatility"}:
            method_norm = "hybrid"
        info["method"] = method_norm

        window = max(5, int(window))
        min_consecutive = max(1, int(min_consecutive_bars))

        volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)
        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        abs_returns = close.pct_change().abs().replace([float("inf"), -float("inf")], pd.NA)

        min_periods = max(5, window // 4)
        vol_base = volume.rolling(window=window, min_periods=min_periods).median()
        vol_base = vol_base.fillna(volume.expanding(min_periods=1).median())

        ret_base = abs_returns.rolling(window=window, min_periods=min_periods).median()
        ret_base = ret_base.fillna(abs_returns.expanding(min_periods=1).median())

        vol_denom = vol_base.where(vol_base > 0)
        ret_denom = ret_base.where(ret_base > 0)

        vol_ratio = (volume / vol_denom).fillna(1.0)
        volatility_ratio = (abs_returns / ret_denom).fillna(1.0)

        volume_ok = vol_ratio <= max(1.0, float(volume_ratio_max))
        volatility_ok = volatility_ratio <= max(1.0, float(volatility_ratio_max))

        if method_norm == "volume":
            stable_mask = volume_ok
        elif method_norm == "volatility":
            stable_mask = volatility_ok
        else:
            stable_mask = volume_ok & volatility_ok

        stable_values = stable_mask.fillna(False).to_numpy(dtype=bool)
        cut_bars = 0
        upper_bound = max(0, n_rows - min_consecutive + 1)
        for idx in range(upper_bound):
            if stable_values[idx : idx + min_consecutive].all():
                cut_bars = idx
                break

        if cut_bars <= 0:
            info["reason"] = "already_stable"
            return df, info

        if (n_rows - cut_bars) < min_keep:
            info["reason"] = "min_bars_keep_guard"
            return df, info

        filtered = df.iloc[cut_bars:].copy()
        if filtered.empty:
            info["reason"] = "filtered_empty"
            return df, info

        first_ts = filtered.index[0]
        if isinstance(first_ts, pd.Timestamp):
            if first_ts.tzinfo is not None:
                first_ts = first_ts.tz_convert("UTC")
            start_ts = first_ts.strftime("%Y-%m-%d %H:%M")
        else:
            start_ts = str(first_ts)

        info.update(
            {
                "applied": True,
                "cut_bars": int(cut_bars),
                "start_ts": start_ts,
                "reason": "applied",
            }
        )
        return filtered, info
    except Exception as exc:
        info["reason"] = f"error:{exc}"
        return df, info


def _data_cache_key(
    symbol: str,
    timeframe: str,
    start_date: Optional[object],
    end_date: Optional[object],
) -> Tuple[str, str, Optional[str], Optional[str]]:
    start_str = str(start_date) if start_date else None
    end_str = str(end_date) if end_date else None
    return (symbol, timeframe, start_str, end_str)


def load_selected_data(
    symbol: str,
    timeframe: str,
    start_date: Optional[object],
    end_date: Optional[object],
) -> Tuple[Optional[pd.DataFrame], str]:
    from .cache_manager import cache_data, get_cached_data

    # Vérifier cache d'abord
    cached_df = get_cached_data(symbol, timeframe, start_date, end_date)
    if cached_df is not None:
        # Mise à jour session state avec données cached
        st.session_state["ohlcv_df"] = cached_df
        st.session_state["ohlcv_cache_key"] = _data_cache_key(
            symbol, timeframe, start_date, end_date
        )
        st.session_state["ohlcv_status_msg"] = "📋 Données du cache (5min TTL)"
        return cached_df, "📋 Données du cache (5min TTL)"

    # Charger depuis source si pas en cache
    start_str = str(start_date) if start_date else None
    end_str = str(end_date) if end_date else None
    df, msg = safe_load_data(symbol, timeframe, start_str, end_str)
    if df is not None:
        # Mettre en cache les nouvelles données
        cache_data(symbol, timeframe, start_date, end_date, df)
        st.session_state["ohlcv_df"] = df
        st.session_state["ohlcv_cache_key"] = _data_cache_key(
            symbol, timeframe, start_date, end_date
        )
        st.session_state["ohlcv_status_msg"] = msg
    return df, msg


def _parse_run_timestamp(value: Optional[str]) -> Optional[pd.Timestamp]:
    if not value:
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _format_run_timestamp(value: Optional[str]) -> str:
    ts = _parse_run_timestamp(value)
    if ts is None:
        return value or "n/a"
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC")
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _format_run_period(start: Optional[str], end: Optional[str]) -> str:
    start_fmt = _format_run_timestamp(start)
    end_fmt = _format_run_timestamp(end)
    if start_fmt == "n/a" and end_fmt == "n/a":
        return "n/a"
    return f"{start_fmt} -> {end_fmt}"


def _find_saved_run_meta(storage: Any, run_id: str) -> Optional[Any]:
    for meta in storage.list_results():
        if meta.run_id == run_id:
            return meta
    return None


def _build_saved_run_label(meta: Any) -> str:
    period = _format_run_period(meta.period_start, meta.period_end)
    extra = getattr(meta, "extra_metadata", {}) or {}
    badges = []
    mode = getattr(meta, "mode", "") or extra.get("origin")
    if mode:
        badges.append(str(mode))
    if extra.get("ui_partial_run"):
        completed = extra.get("ui_completed_runs")
        planned = extra.get("ui_planned_runs")
        if isinstance(completed, (int, float)) and isinstance(planned, (int, float)) and planned > 0:
            badges.append(f"partial {int(completed)}/{int(planned)}")
        else:
            badges.append("partial")
    builder_iteration = extra.get("builder_iteration")
    if builder_iteration is not None:
        badges.append(f"iter {builder_iteration}")
    builder_session_id = extra.get("builder_session_id")
    badge_prefix = f"[{' | '.join(badges)}] " if badges else ""
    session_suffix = f" | session {builder_session_id}" if builder_session_id else ""
    return (
        f"{badge_prefix}{meta.strategy} | {meta.symbol}/{meta.timeframe} | {period} | "
        f"{meta.run_id}{session_suffix}"
    )


def mark_result_as_partial(
    result: Optional[Any],
    *,
    reason: str,
    completed_runs: int,
    planned_runs: int,
) -> Optional[Any]:
    """Marque un RunResult UI comme partiel/interrompu sans casser sa structure."""
    if result is None or not isinstance(getattr(result, "meta", None), dict):
        return result

    completed = max(0, int(completed_runs))
    planned = max(0, int(planned_runs))
    completion_pct = (completed / planned) * 100.0 if planned > 0 else 0.0

    result.meta["ui_partial_run"] = True
    result.meta["ui_partial_reason"] = reason
    result.meta["ui_completed_runs"] = completed
    result.meta["ui_planned_runs"] = planned
    result.meta["ui_completion_pct"] = completion_pct
    return result


def get_partial_result_notice(result: Optional[Any]) -> Optional[str]:
    """Retourne un message UI si le résultat provient d'une optimisation interrompue."""
    if result is None or not isinstance(getattr(result, "meta", None), dict):
        return None
    if not result.meta.get("ui_partial_run", False):
        return None

    completed = result.meta.get("ui_completed_runs")
    planned = result.meta.get("ui_planned_runs")
    if isinstance(completed, (int, float)) and isinstance(planned, (int, float)) and planned > 0:
        return (
            "Résultat partiel issu d'une optimisation interrompue "
            f"({int(completed)}/{int(planned)} tests)."
        )
    return "Résultat partiel issu d'une optimisation interrompue."


def _save_result_to_storage(storage: Any, result: Optional[Any]) -> Tuple[bool, str]:
    if result is None:
        return False, "No result to save."
    run_id = result.meta.get("run_id") or generate_run_id()
    existing_ids = {meta.run_id for meta in storage.list_results()}
    if run_id in existing_ids:
        return False, f"Run already saved: {run_id}"
    try:
        saved_id = storage.save_result(result, run_id=run_id)
    except Exception as exc:
        return False, f"Save failed: {exc}"
    return True, f"Saved run: {saved_id}"


def _maybe_auto_save_run(result: Optional[Any]) -> None:
    if result is None:
        return
    if not st.session_state.get("auto_save_final_run", False):
        return
    partial_notice = get_partial_result_notice(result)
    if partial_notice is not None:
        st.session_state["saved_runs_status"] = "Auto-save skipped: interrupted partial result."
        return
    if result.meta.get("loaded_from_storage"):
        return
    if not BACKEND_AVAILABLE:
        return
    try:
        storage = get_storage()
    except Exception as exc:
        st.session_state["saved_runs_status"] = f"Auto-save failed: {exc}"
        return
    saved, msg = _save_result_to_storage(storage, result)
    if msg:
        st.session_state["saved_runs_status"] = msg


def render_saved_runs_panel(
    result: Optional[Any],
    strategy_key: str,
    symbol: str,
    timeframe: str,
) -> None:
    with st.sidebar.expander("🗂️ Runs sauvegardés", expanded=False):
        if not BACKEND_AVAILABLE:
            st.info("Runs sauvegardés indisponibles (backend non disponible).")
            return
        try:
            storage = get_storage()
        except Exception as exc:
            st.error(f"Erreur stockage: {exc}")
            return

        status_msg = st.session_state.pop("saved_runs_status", None)
        if status_msg:
            st.info(status_msg)

        if "auto_save_final_run" not in st.session_state:
            st.session_state["auto_save_final_run"] = True

        st.checkbox(
            "Sauvegarder automatiquement le run final",
            key="auto_save_final_run",
        )

        if result is not None:
            if st.button("Sauvegarder le run courant", key="save_current_run"):
                saved, msg = _save_result_to_storage(storage, result)
                if saved:
                    st.success(msg)
                else:
                    st.warning(msg)

        filter_current = st.checkbox(
            "Limiter à la sélection courante",
            value=True,
            key="saved_runs_filter_current",
        )
        filter_text = st.text_input(
            "Filtre texte",
            value="",
            key="saved_runs_filter_text",
        )

        runs = storage.list_results()
        if filter_current:
            runs = [
                r
                for r in runs
                if r.strategy == strategy_key
                and r.symbol == symbol
                and r.timeframe == timeframe
            ]
        if filter_text:
            filter_l = filter_text.lower()
            runs = [
                r
                for r in runs
                if filter_l in _build_saved_run_label(r).lower()
                or filter_l in r.run_id.lower()
            ]

        if not runs:
            st.caption("Aucun run sauvegardé.")
            return

        run_ids = [r.run_id for r in runs]
        label_map = {r.run_id: _build_saved_run_label(r) for r in runs}
        if st.session_state.get("saved_runs_selected") not in run_ids:
            st.session_state["saved_runs_selected"] = run_ids[0]
        selected_run_id = st.selectbox(
            "Run",
            options=run_ids,
            format_func=lambda rid: label_map.get(rid, rid),
            key="saved_runs_selected",
        )
        selected_meta = next((r for r in runs if r.run_id == selected_run_id), None)
        if selected_meta is not None:
            period_label = _format_run_period(
                selected_meta.period_start,
                selected_meta.period_end,
            )
        st.sidebar.caption(f"Period: {period_label}")
        st.sidebar.caption(
            f"Trades: {selected_meta.n_trades} | Bars: {selected_meta.n_bars}"
        )
        sharpe = selected_meta.metrics.get("sharpe_ratio", 0)
        ret_pct = selected_meta.metrics.get("total_return_pct", 0)
        max_dd = selected_meta.metrics.get("max_drawdown", 0)
        st.sidebar.caption(
            f"Sharpe: {sharpe:.2f} | Return: {ret_pct:.1f}% | MaxDD: {max_dd:.1f}%"
        )

    load_data = st.sidebar.checkbox(
        "Load data for charts",
        value=True,
        key="saved_runs_load_data",
    )
    if st.sidebar.button("Load selected run", key="load_selected_run"):
        st.session_state["pending_run_load_id"] = selected_run_id
        st.session_state["pending_run_load_data"] = load_data
        st.rerun()


def safe_run_backtest(
    engine: Any,
    df: pd.DataFrame,
    strategy: str,
    params: Dict[str, Any],
    symbol: str,
    timeframe: str,
    run_id: Optional[str] = None,
    silent_mode: bool = False,
    fast_metrics: bool = False,
) -> Tuple[Optional[Any], str]:
    run_id = run_id or generate_run_id(
        strategy=strategy,
        symbol=symbol,
        timeframe=timeframe,
    )
    logger = get_obs_logger("ui.app", run_id=run_id, strategy=strategy, symbol=symbol)

    if not silent_mode:
        logger.info("ui_backtest_start params=%s", params)

    try:
        engine.run_id = run_id
        engine.logger = get_obs_logger("backtest.engine", run_id=run_id)

        result = engine.run(
            df=df,
            strategy=strategy,
            params=params,
            symbol=symbol,
            timeframe=timeframe,
            silent_mode=silent_mode,
            fast_metrics=fast_metrics,
        )

        pnl = result.metrics.get("total_pnl", 0)
        sharpe = result.metrics.get("sharpe_ratio", 0)

        if not silent_mode:
            logger.info("ui_backtest_end pnl=%.2f sharpe=%.2f", pnl, sharpe)
        return result, f"Terminé | P&L: ${pnl:,.2f} | Sharpe: {sharpe:.2f}"

    except ValueError as exc:
        logger.warning("ui_backtest_validation_error error=%s", str(exc))
        return None, f"Paramètres invalides: {str(exc)}"
    except Exception as exc:
        logger.error("ui_backtest_error error=%s", str(exc))
        return None, f"Erreur: {str(exc)}\n{traceback.format_exc()}"


def safe_run_walk_forward(
    df: pd.DataFrame,
    strategy: str,
    params: Dict[str, Any],
    n_folds: int = 5,
    train_ratio: float = 0.7,
    expanding: bool = False,
) -> Tuple[Optional[Any], str]:
    """Lance une Walk-Forward Analysis et retourne (WalkForwardSummary, message)."""
    from backtest.walk_forward import (
        WalkForwardConfig,
        check_wfa_feasibility,
        run_walk_forward,
    )

    config = WalkForwardConfig(
        n_folds=n_folds,
        train_ratio=train_ratio,
        expanding=expanding,
    )

    ok, msg = check_wfa_feasibility(len(df), config=config)
    if not ok:
        return None, f"WFA impossible : {msg}"

    try:
        summary = run_walk_forward(df, strategy, params, config=config)
        if summary.n_valid_folds == 0:
            return None, "WFA : aucun fold valide (données insuffisantes)"
        verdict = "✅ Robuste" if summary.is_robust else "⚠️ Overfitting probable"
        msg = (
            f"{verdict} | {summary.n_valid_folds} folds "
            f"| Sharpe train {summary.avg_train_sharpe:.2f} → test {summary.avg_test_sharpe:.2f} "
            f"| Dégradation {summary.degradation_pct:.0f}%"
        )
        return summary, msg
    except Exception as exc:
        return None, f"Erreur WFA : {exc}"


def _strip_global_params(params: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("fees_bps", "slippage_bps", "initial_capital"):
        params.pop(key, None)
    return params


def build_strategy_params_for_comparison(
    strategy_key: str,
    use_preset: bool = True,
) -> Dict[str, Any]:
    try:
        strategy_class = get_strategy(strategy_key)
    except Exception:
        return {}
    if not strategy_class:
        return {}
    strategy_instance = strategy_class()
    params = dict(strategy_instance.default_params)
    if use_preset:
        preset = strategy_instance.get_preset()
        if preset is not None:
            params.update(preset.get_default_values())
    return _strip_global_params(params)


def _aggregate_metric(values: List[Any], method: str, higher_is_better: bool) -> float:
    cleaned: List[float] = []
    for value in values:
        try:
            val = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(val):
            continue
        cleaned.append(val)

    if not cleaned:
        return float("nan")

    if method == "median":
        return float(statistics.median(cleaned))
    if method == "worst":
        return float(min(cleaned) if higher_is_better else max(cleaned))
    return float(sum(cleaned) / len(cleaned))


def summarize_comparison_results(
    results: List[Dict[str, Any]],
    aggregate: str,
    primary_metric: str,
    expected_runs: int,
) -> List[Dict[str, Any]]:
    metric_directions = {
        "sharpe_ratio": 1,
        "total_return_pct": 1,
        "win_rate": 1,
        "total_pnl": 1,
        "trades": 1,
        "max_drawdown": -1,
    }
    metrics = [
        "sharpe_ratio",
        "total_return_pct",
        "max_drawdown",
        "win_rate",
        "total_pnl",
        "trades",
    ]
    by_strategy: Dict[str, List[Dict[str, Any]]] = {}
    for item in results:
        by_strategy.setdefault(item["strategy"], []).append(item)

    summary: List[Dict[str, Any]] = []
    for strategy_key, runs in by_strategy.items():
        row: Dict[str, Any] = {
            "strategy": strategy_key,
            "runs": len(runs),
        }
        if expected_runs > 0:
            row["coverage_pct"] = (len(runs) / expected_runs) * 100
        for metric in metrics:
            values = []
            for run in runs:
                if metric == "trades":
                    values.append(run.get("trades"))
                else:
                    values.append(run.get("metrics", {}).get(metric))
            row[metric] = _aggregate_metric(
                values,
                aggregate,
                metric_directions.get(metric, 1) >= 0,
            )
        summary.append(row)

    direction = metric_directions.get(primary_metric, 1)
    reverse = direction >= 0

    def _sort_key(item: Dict[str, Any]) -> float:
        value = item.get(primary_metric)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return float("-inf") if reverse else float("inf")
        return float(value)

    summary.sort(key=_sort_key, reverse=reverse)
    return summary


def build_indicator_overlays(
    strategy_key: str,
    df: pd.DataFrame,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    overlays: Dict[str, Any] = {}
    if df is None or df.empty:
        return overlays

    params = _strip_global_params(dict(params))

    try:
        if strategy_key == "bollinger_atr":
            bb_period = int(params.get("bb_period", 20))
            bb_std = float(params.get("bb_std", 2.0))
            entry_z = float(params.get("entry_z", bb_std))
            atr_period = int(params.get("atr_period", 14))
            atr_percentile = float(params.get("atr_percentile", 30))

            bb_result = calculate_indicator(
                "bollinger",
                df,
                {"period": bb_period, "std_dev": bb_std},
            )
            atr_values = calculate_indicator(
                "atr",
                df,
                {"period": atr_period},
            )
            atr_series = pd.Series(atr_values, index=df.index)
            overlays["bollinger"] = {
                "upper": pd.Series(bb_result["upper"], index=df.index),
                "lower": pd.Series(bb_result["lower"], index=df.index),
                "mid": pd.Series(bb_result["middle"], index=df.index),
                "entry_z": entry_z,
            }
            overlays["atr"] = {
                "atr": atr_series,
                "atr_percentile": atr_percentile,
            }

        elif strategy_key == "bollinger_best_longe_3i":
            bb_period = int(params.get("bb_period", 20))
            bb_std = float(params.get("bb_std", 2.0))
            entry_level = float(params.get("entry_level", 0.0))
            sl_level = float(params.get("sl_level", -0.5))
            tp_level = float(params.get("tp_level", 0.85))
            atr_period = int(params.get("atr_period", 14))
            atr_percentile = float(params.get("atr_percentile", 30))

            bb_result = calculate_indicator(
                "bollinger",
                df,
                {"period": bb_period, "std_dev": bb_std},
            )
            atr_values = calculate_indicator(
                "atr",
                df,
                {"period": atr_period},
            )
            upper = pd.Series(bb_result["upper"], index=df.index)
            lower = pd.Series(bb_result["lower"], index=df.index)
            mid = pd.Series(bb_result["middle"], index=df.index)
            entry_line = lower + entry_level * (upper - lower)
            atr_series = pd.Series(atr_values, index=df.index)
            overlays["bollinger"] = {
                "upper": upper,
                "lower": lower,
                "mid": mid,
                "entry_lower": entry_line,
                "sl_level": sl_level,
                "tp_level": tp_level,
            }
            overlays["atr"] = {
                "atr": atr_series,
                "atr_percentile": atr_percentile,
            }

        elif strategy_key == "bollinger_best_short_3i":
            bb_period = int(params.get("bb_period", 20))
            bb_std = float(params.get("bb_std", 2.0))
            entry_level = float(params.get("entry_level", 1.0))
            sl_level = float(params.get("sl_level", 1.5))
            tp_level = float(params.get("tp_level", 0.15))
            atr_period = int(params.get("atr_period", 14))
            atr_percentile = float(params.get("atr_percentile", 30))

            bb_result = calculate_indicator(
                "bollinger",
                df,
                {"period": bb_period, "std_dev": bb_std},
            )
            atr_values = calculate_indicator(
                "atr",
                df,
                {"period": atr_period},
            )
            upper = pd.Series(bb_result["upper"], index=df.index)
            lower = pd.Series(bb_result["lower"], index=df.index)
            mid = pd.Series(bb_result["middle"], index=df.index)
            entry_line = lower + entry_level * (upper - lower)
            atr_series = pd.Series(atr_values, index=df.index)
            overlays["bollinger"] = {
                "upper": upper,
                "lower": lower,
                "mid": mid,
                "entry_upper": entry_line,
                "sl_level": sl_level,
                "tp_level": tp_level,
            }
            overlays["atr"] = {
                "atr": atr_series,
                "atr_percentile": atr_percentile,
            }

        elif strategy_key == "ema_cross":
            fast_period = int(params.get("fast_period", 12))
            slow_period = int(params.get("slow_period", 26))
            close = df["close"]
            overlays["ema"] = {
                "fast": close.ewm(span=fast_period, adjust=False).mean(),
                "slow": close.ewm(span=slow_period, adjust=False).mean(),
            }

        elif strategy_key == "macd_cross":
            fast_period = int(params.get("fast_period", 12))
            slow_period = int(params.get("slow_period", 26))
            signal_period = int(params.get("signal_period", 9))
            macd_result = calculate_indicator(
                "macd",
                df,
                {
                    "fast": fast_period,
                    "slow": slow_period,
                    "signal": signal_period,
                },
            )
            overlays["macd"] = {
                "macd": pd.Series(macd_result["macd"], index=df.index),
                "signal": pd.Series(macd_result["signal"], index=df.index),
                "hist": pd.Series(macd_result["histogram"], index=df.index),
            }

        elif strategy_key == "rsi_reversal":
            rsi_period = int(params.get("rsi_period", 14))
            oversold = float(params.get("oversold_level", 30))
            overbought = float(params.get("overbought_level", 70))
            rsi_values = calculate_indicator(
                "rsi",
                df,
                {"period": rsi_period},
            )
            overlays["rsi"] = {
                "rsi": pd.Series(rsi_values, index=df.index),
                "oversold": oversold,
                "overbought": overbought,
            }

        elif strategy_key == "ma_crossover":
            fast_period = int(params.get("fast_period", 10))
            slow_period = int(params.get("slow_period", 30))
            close = df["close"]
            overlays["ma"] = {
                "fast": close.rolling(window=fast_period).mean(),
                "slow": close.rolling(window=slow_period).mean(),
            }

        elif strategy_key == "ema_stochastic_scalp":
            fast_ema = int(params.get("fast_ema", 50))
            slow_ema = int(params.get("slow_ema", 100))
            stoch_k = int(params.get("stoch_k", 14))
            stoch_d = int(params.get("stoch_d", 3))
            oversold = float(params.get("stoch_oversold", 20))
            overbought = float(params.get("stoch_overbought", 80))
            close = df["close"]
            overlays["ema"] = {
                "fast": close.ewm(span=fast_ema, adjust=False).mean(),
                "slow": close.ewm(span=slow_ema, adjust=False).mean(),
            }
            stoch_values = calculate_indicator(
                "stochastic",
                df,
                {"k_period": stoch_k, "d_period": stoch_d, "smooth_k": 3},
            )
            if isinstance(stoch_values, dict):
                overlays["stochastic"] = {
                    "k": pd.Series(stoch_values["stoch_k"], index=df.index),
                    "d": pd.Series(stoch_values["stoch_d"], index=df.index),
                    "oversold": oversold,
                    "overbought": overbought,
                }
            elif isinstance(stoch_values, tuple) and len(stoch_values) >= 2:
                overlays["stochastic"] = {
                    "k": pd.Series(stoch_values[0], index=df.index),
                    "d": pd.Series(stoch_values[1], index=df.index),
                    "oversold": oversold,
                    "overbought": overbought,
                }

        elif strategy_key == "bollinger_dual":
            bb_window = int(params.get("bb_window", 20))
            bb_std = float(params.get("bb_std", 2.0))
            ma_window = int(params.get("ma_window", 10))
            ma_type = str(params.get("ma_type", "sma")).lower()
            bb_result = calculate_indicator(
                "bollinger",
                df,
                {"period": bb_window, "std_dev": bb_std},
            )
            if isinstance(bb_result, dict):
                upper, middle, lower = bb_result["upper"], bb_result["middle"], bb_result["lower"]
            else:
                upper, middle, lower = bb_result[:3]
            overlays["bollinger"] = {
                "upper": pd.Series(upper, index=df.index),
                "lower": pd.Series(lower, index=df.index),
                "mid": pd.Series(middle, index=df.index),
            }
            close = df["close"]
            if ma_type == "ema":
                ma_series = close.ewm(span=ma_window, adjust=False).mean()
            else:
                ma_series = close.rolling(
                    window=ma_window, min_periods=ma_window
                ).mean()
            overlays["ma"] = {"center": ma_series}

        elif strategy_key == "atr_channel":
            atr_period = int(params.get("atr_period", 14))
            atr_mult = float(params.get("atr_mult", 2.0))
            close = df["close"]
            ema_center = close.ewm(span=atr_period, adjust=False).mean()
            atr_values = calculate_indicator("atr", df, {"period": atr_period})
            atr_series = pd.Series(atr_values, index=df.index)
            overlays["atr_channel"] = {
                "upper": ema_center + atr_series * atr_mult,
                "lower": ema_center - atr_series * atr_mult,
                "center": ema_center,
            }
            overlays["atr"] = {"atr": atr_series}
    except Exception:
        return {}

    return overlays


def safe_copy_cleanup(logger=None) -> None:
    # Mode CPU-only: aucun cleanup GPU requis
    return None


def run_sweep_parallel_with_callback(
    df, strategy, param_grid, initial_capital, n_workers=None, callback=None,
    silent_mode=True, fast_metrics=True, symbol="unknown", timeframe="unknown"  # ⚡ Performance
):
    """
    Exécute un sweep en parallèle avec callback de progression temps réel.

    Utilise SweepEngine moderne avec joblib/loky (plus stable que ProcessPoolExecutor).
    Support cache RAM 100k entries pour performance optimale sur gros sweeps.

    Note: GPU désactivé pour sweeps (CPU + cache RAM plus efficace, économise 10 Go VRAM).
    """
    import os

    from backtest.sweep import SweepEngine

    # Désactiver GPU pour sweeps (inutile en multiprocess, économise 10 Go VRAM + évite yoyo 2060)
    os.environ["BACKTEST_USE_GPU"] = "0"
    os.environ["BACKTEST_GPU_QUEUE_ENABLED"] = "0"

    # Réduire verbosité logs pour gros sweeps (éviter saturation terminal avec 2.4M logs)
    import logging
    logging.getLogger("backtest.engine").setLevel(logging.WARNING)
    logging.getLogger("backtest.sweep").setLevel(logging.INFO)

    if n_workers is None:
        n_workers = max(1, os.cpu_count() // 2)

    # Initialiser SweepEngine avec cache RAM optimisé si disponible
    indicator_cache_config = None

    engine = SweepEngine(
        max_workers=n_workers,
        initial_capital=initial_capital,
        auto_save=True
    )

    # Lancer le sweep avec SweepEngine (plus stable que ProcessPoolExecutor)
    try:
        sweep_results = engine.run_sweep(
            df=df,
            strategy=strategy,
            param_grid=param_grid,
            optimize_for="sharpe_ratio",
            silent_mode=silent_mode,
            fast_metrics=fast_metrics,
            indicator_cache_config=indicator_cache_config
        )

        # Formater résultats pour compatibilité avec l'UI
        results = []
        for result in sweep_results.results:
            if result is not None:
                formatted_result = {
                    "params": result.params,
                    "metrics": {
                        "total_pnl": result.metrics.total_pnl,
                        "sharpe_ratio": result.metrics.sharpe_ratio,
                        "win_rate_pct": result.metrics.win_rate_pct,
                        "max_drawdown_pct": result.metrics.max_drawdown_pct,
                        "total_trades": result.metrics.total_trades,
                        "profit_factor": result.metrics.profit_factor,
                        "total_return_pct": result.metrics.total_return_pct,
                    }
                }
                results.append(formatted_result)

                # Callback final avec tous les résultats
                if callback:
                    try:
                        best_result = {
                            "result": formatted_result,
                            "best_pnl": result.metrics.total_pnl
                        }
                        callback(len(results), len(sweep_results.results), best_result)
                    except Exception:
                        # Client déconnecté - ignorer l'erreur et continuer le sweep
                        pass
            else:
                results.append(None)

        return results

    except Exception as e:
        print(f"Erreur sweep SweepEngine: {e}")
        import traceback
        traceback.print_exc()
        return []


def run_sweep_sequential_with_callback(
    df, strategy, param_grid, initial_capital, callback=None,
    silent_mode=True, fast_metrics=True  # ⚡ Performance
):
    """Exécute un sweep en séquentiel avec callback de progression."""
    from backtest.engine import BacktestEngine
    from utils.config import Config

    config = Config(initial_capital=initial_capital)
    engine = BacktestEngine(config=config)

    results = []
    total_combos = len(param_grid)
    best_result = None

    for i, params in enumerate(param_grid):
        try:
            result, _ = safe_run_backtest(
                engine, df, strategy, params,
                "unknown", "unknown",  # Pas besoin de symbol/timeframe ici
                silent_mode=silent_mode,
                fast_metrics=fast_metrics
            )

            if result:
                results.append({"metrics": result.metrics, "params": params})
                pnl = result.metrics.get("total_pnl", 0.0)
                if best_result is None or pnl > best_result.get("best_pnl", float("-inf")):
                    best_result = {"result": result, "best_pnl": pnl}

            else:
                results.append(None)
        except Exception:
            results.append(None)

        # Callback de progression
        if callback:
            try:
                callback(i + 1, total_combos, best_result)
            except Exception:
                # Client déconnecté - ignorer l'erreur et continuer le sweep
                pass

    return results

