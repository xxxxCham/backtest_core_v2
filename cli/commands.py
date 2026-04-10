"""
Module-ID: cli.commands

Purpose: Implémentation CLI commands - backtest, sweep, optuna, validate, export, visualize.

Role in pipeline: CLI interface

Key components: cmd_backtest(), cmd_sweep(), cmd_optuna(), Colors, normalize_metric_name(), METRIC_ALIASES

Inputs: argparse parsed args (strategy, data, params, etc.)

Outputs: Console output, JSON results, HTML/CSV exports, visualization

Dependencies: argparse, json, pathlib, pandas, numpy

Conventions: Metric aliases (sharpe → sharpe_ratio); couleurs ANSI (désactivable --no-color); progress bars.

Read-if: Ajout commande CLI ou modification format output.

Skip-if: Vous appelez cmd_backtest(args) depuis main.
"""

import copy
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from . import formatters as _shared_formatters

logger = logging.getLogger(__name__)

# =============================================================================
# UTILITAIRES
# =============================================================================

# Système d'alias pour métriques CLI
METRIC_ALIASES = {
    "sharpe": "sharpe_ratio",
    "sortino": "sortino_ratio",
    "total_return": "total_return_pct",
    # Accepter aussi les formes complètes
    "sharpe_ratio": "sharpe_ratio",
    "sortino_ratio": "sortino_ratio",
    "total_return_pct": "total_return_pct",
}


def normalize_metric_name(metric: str) -> str:
    """Normalise le nom d'une métrique CLI en nom interne."""
    return METRIC_ALIASES.get(metric, metric)


class Colors:
    """Codes couleurs ANSI pour le terminal."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"

    @classmethod
    def disable(cls):
        """Désactive les couleurs."""
        cls.RESET = cls.BOLD = cls.RED = cls.GREEN = ""
        cls.YELLOW = cls.BLUE = cls.MAGENTA = cls.CYAN = ""
        # Garder le formatteur partagé cohérent avec --no-color.
        _shared_formatters.Colors.disable()


def print_header(text: str, char: str = "="):
    """Affiche un en-tête formaté (source partagée: cli.formatters)."""
    _shared_formatters.print_header(text, char=char)


def print_success(text: str):
    """Affiche un message de succès (source partagée: cli.formatters)."""
    _shared_formatters.print_success(text)


def print_error(text: str):
    """Affiche un message d'erreur (source partagée: cli.formatters)."""
    _shared_formatters.print_error(text)


def print_warning(text: str):
    """Affiche un avertissement (source partagée: cli.formatters)."""
    _shared_formatters.print_warning(text)


def print_info(text: str):
    """Affiche une information (source partagée: cli.formatters)."""
    _shared_formatters.print_info(text)


def format_table(headers: List[str], rows: List[List[str]], padding: int = 2) -> str:
    """Formate une table en texte (source partagée: cli.formatters)."""
    return _shared_formatters.format_table(headers, rows, indent=2, padding=padding)


def format_bytes(bytes_count: float) -> str:
    """Formate un nombre de bytes en unité lisible (source partagée: cli.formatters)."""
    return _shared_formatters.format_bytes(bytes_count)


def _apply_date_filter(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """Filtre un DataFrame OHLCV par date (UTC)."""
    if not start and not end:
        return df

    if start is not None:
        start_ts = pd.Timestamp(start, tz="UTC")
        df = df[df.index >= start_ts]
    if end is not None:
        end_ts = pd.Timestamp(end, tz="UTC")
        df = df[df.index <= end_ts]

    if df.empty:
        raise ValueError(f"Aucune donnée dans la période {start} - {end}")

    return df


def _get_resolved_data_dir() -> Path:
    """Résout le dossier de données via le loader central si disponible."""
    try:
        from data.loader import _get_data_dir

        return _get_data_dir()
    except Exception:
        env_data_dir = os.environ.get("BACKTEST_DATA_DIR")
        if env_data_dir:
            return Path(env_data_dir)
        return Path(__file__).parent.parent / "data" / "sample_data"


def _resolve_data_path(data_arg: str) -> Path:
    """Résout un chemin de données via le dossier réellement utilisé par le loader."""
    data_path = Path(data_arg)
    if data_path.exists():
        return data_path

    candidate = _get_resolved_data_dir() / data_arg
    if candidate.exists():
        return candidate

    return candidate


def _resolve_output_format(output_path: Path, requested_format: str | None, default: str = "json") -> str:
    """Détermine le format de sortie à partir de l'option et/ou du suffixe fichier."""
    if requested_format and requested_format != "auto":
        return requested_format

    suffix = output_path.suffix.lower().lstrip(".")
    if suffix in {"json", "csv", "parquet"}:
        return suffix
    return default


def _split_multi_args(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for raw in values:
        if raw is None:
            continue
        parts = [p.strip() for p in str(raw).split(",") if p.strip()]
        out.extend(parts)
    return out


def _resolve_strategies_from_catalog(args) -> List[str]:
    categories = _split_multi_args(getattr(args, "from_category", None))
    tags = _split_multi_args(getattr(args, "from_tag", None))
    if not categories and not tags:
        return []
    try:
        from catalog.strategy_catalog import list_entries
        from strategies import list_strategies
        entries = list_entries(categories=categories, tags=tags, status="active")
        available = set(list_strategies())
        names = []
        for entry in entries:
            name = str(entry.get("strategy_name") or "").strip()
            if not name:
                continue
            if name in available:
                names.append(name)
        return sorted(set(names))
    except Exception as exc:
        print_warning(f"Catalog selection failed: {exc}")
        return []


def _resolve_strategy_selection(args) -> List[str]:
    strategies = []
    if getattr(args, "strategy", None):
        strategies.append(str(args.strategy).lower())
    strategies.extend(_resolve_strategies_from_catalog(args))
    unique = []
    for name in strategies:
        if name and name not in unique:
            unique.append(name)
    return unique


def _derive_output_path(base: Optional[str], strategy_name: str) -> Optional[str]:
    if not base:
        return None
    output_path = Path(base)
    if output_path.exists() and output_path.is_dir():
        return str(output_path / f"{strategy_name}{output_path.suffix or '.json'}")
    if output_path.suffix:
        stem = output_path.stem
        return str(output_path.with_name(f"{stem}_{strategy_name}{output_path.suffix}"))
    return str(output_path / f"{strategy_name}.json")


def _flatten_sweep_results(
    strategy: str,
    granularity: float,
    metric: str,
    n_combinations: int,
    results: list[dict],
) -> list[dict]:
    """Convertit les résultats sweep en lignes tabulaires pour CSV/Parquet."""
    rows: list[dict] = []
    for rank, result in enumerate(results, start=1):
        params = result.get("params", {}) or {}
        metrics = result.get("metrics", {}) or {}
        row = {
            "rank": rank,
            "strategy": strategy,
            "granularity": granularity,
            "metric": metric,
            "n_combinations": n_combinations,
            "score": result.get("score", 0),
        }
        for key, value in params.items():
            row[f"param_{key}"] = value
        row.update(metrics)
        rows.append(row)
    return rows


def _extract_metrics_from_result_file(path: Path) -> dict:
    """Charge les métriques d'un JSON de backtest exporté."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("metrics", {})


def _safe_float(value, default: float = 0.0) -> float:
    """Convertit vers float avec fallback sûr (NaN/inf -> default)."""
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    if np.isnan(converted) or np.isinf(converted):
        return default
    return converted


def _percent_from_maybe_fraction(value, default: float = 0.0) -> float:
    """Normalise une valeur potentiellement en fraction vers un pourcentage."""
    converted = _safe_float(value, default=default)
    if -1.0 <= converted <= 1.0:
        return converted * 100.0
    return converted


def _pick_metric(metrics: dict, *keys: str):
    """Retourne la première métrique disponible/non vide parmi plusieurs clés."""
    for key in keys:
        if key not in metrics:
            continue
        value = metrics.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        return value
    return None


def _metrics_from_index_row(row: pd.Series) -> dict:
    """Normalise une ligne d'index (CSV/Parquet) vers un dict de métriques cohérent."""
    total_return_pct_raw = _pick_metric(row, "total_return_pct")
    if total_return_pct_raw is not None:
        total_return_pct = _safe_float(total_return_pct_raw, 0.0)
    else:
        total_return_pct = _safe_float(_pick_metric(row, "total_return"), 0.0) * 100.0

    max_dd_raw = _pick_metric(row, "max_drawdown_pct", "max_drawdown")
    max_drawdown_pct = _safe_float(max_dd_raw, 0.0)
    if _pick_metric(row, "max_drawdown_pct") is None:
        max_drawdown_pct = _percent_from_maybe_fraction(max_drawdown_pct, 0.0)

    return {
        "total_pnl": _safe_float(_pick_metric(row, "total_pnl", "pnl"), 0.0),
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown": max_drawdown_pct,
        "sharpe_ratio": _safe_float(_pick_metric(row, "sharpe_ratio", "sharpe"), 0.0),
        "sortino_ratio": _safe_float(_pick_metric(row, "sortino_ratio", "sortino"), 0.0),
        "profit_factor": _safe_float(_pick_metric(row, "profit_factor"), 0.0),
        "win_rate_pct": _percent_from_maybe_fraction(
            _pick_metric(row, "win_rate_pct", "win_rate"),
            0.0,
        ),
        "total_trades": _safe_float(
            _pick_metric(row, "total_trades", "n_trades", "trades_count"),
            0.0,
        ),
    }


def _extract_present_metrics_for_analyze(raw_metrics: dict) -> dict:
    """
    Extrait uniquement les métriques présentes avec normalisation légère.

    Important: cette fonction n'injecte pas de valeurs par défaut artificielles.
    """
    metrics = raw_metrics or {}
    extracted: dict[str, float] = {}

    total_pnl = _pick_metric(metrics, "total_pnl", "pnl")
    if total_pnl is not None:
        extracted["total_pnl"] = _safe_float(total_pnl, 0.0)

    total_return_pct = _pick_metric(metrics, "total_return_pct")
    if total_return_pct is not None:
        extracted["total_return_pct"] = _safe_float(total_return_pct, 0.0)
    else:
        total_return = _pick_metric(metrics, "total_return")
        if total_return is not None:
            extracted["total_return_pct"] = _safe_float(total_return, 0.0) * 100.0

    max_dd_pct = _pick_metric(metrics, "max_drawdown_pct")
    if max_dd_pct is not None:
        dd_value = _safe_float(max_dd_pct, 0.0)
        extracted["max_drawdown_pct"] = dd_value
        extracted["max_drawdown"] = dd_value
    else:
        max_dd = _pick_metric(metrics, "max_drawdown")
        if max_dd is not None:
            dd_value = _safe_float(max_dd, 0.0)
            extracted["max_drawdown_pct"] = dd_value
            extracted["max_drawdown"] = dd_value

    sharpe = _pick_metric(metrics, "sharpe_ratio", "sharpe")
    if sharpe is not None:
        extracted["sharpe_ratio"] = _safe_float(sharpe, 0.0)

    sortino = _pick_metric(metrics, "sortino_ratio", "sortino")
    if sortino is not None:
        extracted["sortino_ratio"] = _safe_float(sortino, 0.0)

    profit_factor = _pick_metric(metrics, "profit_factor")
    if profit_factor is not None:
        extracted["profit_factor"] = _safe_float(profit_factor, 0.0)

    win_rate_pct = _pick_metric(metrics, "win_rate_pct")
    if win_rate_pct is not None:
        extracted["win_rate_pct"] = _percent_from_maybe_fraction(win_rate_pct, 0.0)
    else:
        win_rate = _pick_metric(metrics, "win_rate")
        if win_rate is not None:
            extracted["win_rate_pct"] = _percent_from_maybe_fraction(win_rate, 0.0)

    total_trades = _pick_metric(metrics, "total_trades", "n_trades", "trades_count")
    if total_trades is not None:
        extracted["total_trades"] = _safe_float(total_trades, 0.0)

    return extracted


def _hydrate_records_from_run_store(records: list[dict], results_dir: Path) -> tuple[int, int, int]:
    """Complète les métriques depuis runs/<run_id>/metrics.json."""
    runs_dir = results_dir / "runs"
    if not runs_dir.exists():
        return 0, len(records), 0

    hydrated = 0
    missing = 0
    errors = 0

    for record in records:
        run_id = str(record.get("run_id", "") or "").strip()
        if not run_id:
            missing += 1
            continue

        metrics_path = runs_dir / run_id / "metrics.json"
        if not metrics_path.exists():
            missing += 1
            continue

        try:
            with open(metrics_path, encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                errors += 1
                continue
            extracted = _extract_present_metrics_for_analyze(payload)
            if not extracted:
                continue
            base_metrics = dict(record.get("metrics") or {})
            base_metrics.update(extracted)
            record["metrics"] = base_metrics
            hydrated += 1
        except Exception:
            errors += 1

    return hydrated, missing, errors


def _print_metrics_summary(prefix: str, metrics: dict):
    """Résumé court des métriques principales."""
    total_return_pct_raw = _pick_metric(metrics, "total_return_pct")
    if total_return_pct_raw is not None:
        total_return = _safe_float(total_return_pct_raw, 0.0)
    else:
        total_return = _safe_float(_pick_metric(metrics, "total_return"), 0.0) * 100.0

    max_dd = _safe_float(_pick_metric(metrics, "max_drawdown_pct", "max_drawdown"), 0.0)
    if _pick_metric(metrics, "max_drawdown_pct") is None:
        max_dd = _percent_from_maybe_fraction(max_dd, 0.0)

    sharpe = _safe_float(_pick_metric(metrics, "sharpe_ratio", "sharpe"), 0.0)
    win_rate = _percent_from_maybe_fraction(
        _pick_metric(metrics, "win_rate_pct", "win_rate"),
        0.0,
    )
    print(
        f"{prefix} sharpe={sharpe:.3f} | drawdown={max_dd:.2f}% | "
        f"total_return={total_return:+.2f}% | win_rate={win_rate:.2f}%"
    )


_RESULT_STORE_SINGLETON = None


def _resolve_results_write_mode(args=None) -> str:
    """Résout le mode de persistance résultats: legacy|shadow|v2."""
    mode = getattr(args, "results_write_mode", None) if args is not None else None
    if not mode:
        mode = os.environ.get("BACKTEST_RESULTS_WRITE_MODE")
    if not mode:
        mode = "shadow"
    mode = str(mode).strip().lower()
    if mode not in {"legacy", "shadow", "v2"}:
        mode = "shadow"
    return mode


def _should_persist_results_v2(args=None) -> bool:
    return _resolve_results_write_mode(args) in {"shadow", "v2"}


def _get_result_store():
    global _RESULT_STORE_SINGLETON
    if _RESULT_STORE_SINGLETON is None:
        from backtest.result_store import ResultStore
        root_dir = os.environ.get("BACKTEST_RESULTS_DIR", "backtest_results")
        _RESULT_STORE_SINGLETON = ResultStore(root_dir)
    return _RESULT_STORE_SINGLETON


def _infer_result_status(metrics: dict, trades_count: int = 0) -> str:
    """Déduit un statut standardisé pour l'index global."""
    if not metrics:
        return "invalid"
    account_ruined = bool(metrics.get("account_ruined", False))
    if account_ruined:
        return "blown_up"
    if trades_count <= 0:
        return "no_trades"
    return "ok"


def _persist_backtest_result_v2(
    *,
    result,
    mode: str,
    data_path: Path,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    args,
    diagnostics: dict | None = None,
) -> str | None:
    """Persiste un RunResult via l'API centrale de stockage."""
    if not _should_persist_results_v2(args):
        return None

    metrics = result.metrics.to_dict() if hasattr(result.metrics, "to_dict") else dict(result.metrics)
    status = _infer_result_status(metrics, trades_count=len(result.trades))
    try:
        store = _get_result_store()
        record = store.save_backtest_result(
            result,
            requested_run_id=result.meta.get("run_id"),
            mode=mode,
            status=status,
            metadata_extra={
                "strategy_name": strategy_name,
                "strategy_module": result.meta.get("strategy_module"),
                "symbol": symbol,
                "timeframe": timeframe,
                "params": result.meta.get("params", {}),
                "period_start": result.meta.get("period_start"),
                "period_end": result.meta.get("period_end"),
                "seed": getattr(args, "seed", None),
                "data_source": {
                    "path": str(data_path),
                    "rows": len(result.equity) if hasattr(result, "equity") else None,
                },
                "engine_settings": {
                    "initial_capital": getattr(args, "capital", None),
                    "fees_bps": getattr(args, "fees_bps", None),
                    "slippage_bps": getattr(args, "slippage_bps", None),
                    "fast_metrics": getattr(args, "fast_metrics", None),
                },
                "config_snapshot_extra": {
                    "command": getattr(args, "command", None),
                },
            },
            diagnostics=diagnostics,
        )
        return record.run_id
    except Exception:
        logger.warning("Persist backtest v2 failed", exc_info=True)
        return None


def _persist_summary_result_v2(
    *,
    mode: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    params: dict,
    metrics: dict,
    diagnostics: dict,
    metadata: dict | None = None,
    run_id: str | None = None,
    status: str = "ok",
) -> str | None:
    if not _should_persist_results_v2():
        return None
    try:
        store = _get_result_store()
        record = store.save_summary_run(
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            params=params,
            metrics=metrics,
            requested_run_id=run_id,
            metadata_extra=metadata or {},
            diagnostics=diagnostics,
            status=status,
        )
        return record.run_id
    except Exception:
        logger.warning("Persist summary v2 failed (mode=%s)", mode, exc_info=True)
        return None


def _to_native_value(value):
    """Normalise les scalaires numpy/pandas vers des types Python natifs."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return str(value)
    return value


def _should_reverse_sort(metric_name: str, values: list[float] | None = None) -> bool:
    """Détermine le sens de tri optimal selon la métrique.

    Pour les drawdowns:
    - valeurs négatives (convention courante): plus proche de 0 = meilleur -> reverse=True
    - valeurs positives: plus petit = meilleur -> reverse=False
    """
    normalized = normalize_metric_name(metric_name)
    if normalized not in {"max_drawdown", "max_drawdown_pct"}:
        return True

    if not values:
        return True

    numeric: list[float] = []
    for value in values:
        try:
            numeric.append(float(value))
        except Exception:
            continue

    if not numeric:
        return True

    return float(np.nanmedian(numeric)) < 0


_CYCLE_FILTER_PROFILES = {
    "explore": {
        "min_trades": 0,
        "max_drawdown": None,
        "require_positive_train": False,
    },
    "balanced": {
        "min_trades": 20,
        "max_drawdown": None,
        "require_positive_train": False,
    },
    "strict": {
        "min_trades": 40,
        "max_drawdown": 35.0,
        "require_positive_train": True,
    },
}


def _resolve_cycle_filter_settings(args) -> dict:
    """Résout les filtres effectifs de cmd_cycle selon profil + overrides utilisateur."""
    profile = getattr(args, "filter_profile", "balanced") or "balanced"
    defaults = _CYCLE_FILTER_PROFILES.get(profile, _CYCLE_FILTER_PROFILES["balanced"])

    min_trades_raw = getattr(args, "min_trades", None)
    min_trades = defaults["min_trades"] if min_trades_raw is None else int(min_trades_raw)
    min_trades = max(0, min_trades)

    max_drawdown = getattr(args, "max_drawdown", None)
    if max_drawdown is None:
        max_drawdown = defaults["max_drawdown"]

    require_positive = bool(
        getattr(args, "require_positive_train", False) or defaults["require_positive_train"]
    )

    return {
        "profile": profile,
        "min_trades": min_trades,
        "max_drawdown": max_drawdown,
        "require_positive_train": require_positive,
    }


# =============================================================================
# COMMANDE: LIST
# =============================================================================

def cmd_list(args) -> int:
    """Liste les ressources disponibles."""
    if args.no_color:
        Colors.disable()

    resource = args.resource

    if resource == "strategies":
        return _list_strategies(args)
    elif resource == "indicators":
        return _list_indicators(args)
    elif resource == "data":
        return _list_data(args)
    elif resource == "presets":
        return _list_presets(args)

    return 0


def cmd_indicators(args) -> int:
    """Alias: list indicators."""
    args.resource = "indicators"
    return cmd_list(args)


def _list_strategies(args) -> int:
    """Liste les stratégies."""
    from strategies import get_strategy, list_strategies

    strategies = list_strategies()

    if args.json:
        data = []
        for name in strategies:
            strat = get_strategy(name)
            if strat:
                instance = strat()
                data.append({
                    "name": name,
                    "description": getattr(instance, "description", ""),
                    "indicators": getattr(instance, "required_indicators", []),
                })
        print(json.dumps(data, indent=2))
        return 0

    print_header(f"Stratégies disponibles ({len(strategies)})")

    rows = []
    for name in sorted(strategies):
        strat = get_strategy(name)
        if strat:
            instance = strat()
            desc = getattr(instance, "description", "")[:50]
            indicators = ", ".join(instance.required_indicators[:3])
            if len(instance.required_indicators) > 3:
                indicators += "..."
            rows.append([name, desc, indicators])

    print(format_table(["Nom", "Description", "Indicateurs"], rows))
    return 0


def _list_indicators(args) -> int:
    """Liste les indicateurs."""
    from indicators.registry import get_indicator, list_indicators

    indicators = list_indicators()

    if args.json:
        data = []
        for name in indicators:
            info = get_indicator(name)
            if info:
                data.append({
                    "name": name,
                    "description": info.description,
                    "required_columns": list(info.required_columns),
                })
        print(json.dumps(data, indent=2))
        return 0

    print_header(f"Indicateurs disponibles ({len(indicators)})")

    rows = []
    for name in sorted(indicators):
        info = get_indicator(name)
        if info:
            cols = ", ".join(info.required_columns)
            desc = info.description[:40] if info.description else ""
            rows.append([name, cols, desc])

    print(format_table(["Nom", "Colonnes", "Description"], rows))
    return 0


def _list_data(args) -> int:
    """Liste les fichiers de données."""
    from data.loader import _scan_data_files, discover_available_data

    # Récupérer tokens et timeframes
    tokens, timeframes = discover_available_data()

    data_dir = _get_resolved_data_dir()
    data_files = list(_scan_data_files()) if data_dir.exists() else []

    if args.json:
        print(json.dumps({
            "data_dir": str(data_dir),
            "tokens": tokens,
            "timeframes": timeframes,
            "files": [str(f) for f in data_files]
        }, indent=2))
        return 0

    print_header(f"Fichiers de données ({len(data_files)})")

    print_info(f"Répertoire résolu: {data_dir}")

    if not data_files:
        print_warning("Aucun fichier de données trouvé")
        print_info("Vérifiez BACKTEST_DATA_DIR ou la banque du gestionnaire multi-timeframe.")
        return 0

    rows = []
    for f in sorted(data_files):
        path = Path(f)
        size = path.stat().st_size / 1024 if path.exists() else 0
        rows.append([path.name, f"{size:.1f} KB", path.suffix])

    print(format_table(["Fichier", "Taille", "Format"], rows))

    # Afficher aussi les tokens et timeframes
    if tokens:
        print(f"\n{Colors.BOLD}Tokens:{Colors.RESET} {', '.join(tokens)}")
    if timeframes:
        print(f"{Colors.BOLD}Timeframes:{Colors.RESET} {', '.join(timeframes)}")

    return 0


def _list_presets(args) -> int:
    """Liste les presets."""
    from utils.parameters import EMA_CROSS_PRESET, MINIMAL_PRESET, SAFE_RANGES_PRESET

    presets = [SAFE_RANGES_PRESET, MINIMAL_PRESET, EMA_CROSS_PRESET]

    if args.json:
        data = [p.to_dict() for p in presets]
        print(json.dumps(data, indent=2))
        return 0

    print_header(f"Presets disponibles ({len(presets)})")

    rows = []
    for p in presets:
        n_params = len(p.parameters)
        combos = p.estimate_combinations()
        rows.append([p.name, p.description[:40], str(n_params), f"~{combos:,}"])

    print(format_table(["Nom", "Description", "Params", "Combinaisons"], rows))
    return 0


# =============================================================================
# COMMANDE: INFO
# =============================================================================

def cmd_info(args) -> int:
    """Affiche les informations détaillées d'une ressource."""
    if args.no_color:
        Colors.disable()

    if args.resource_type == "strategy":
        return _info_strategy(args)
    elif args.resource_type == "indicator":
        return _info_indicator(args)

    return 0


def _info_strategy(args) -> int:
    """Affiche les infos d'une stratégie."""
    from strategies import get_strategy, list_strategies

    name = args.name.lower()
    strat_class = get_strategy(name)

    if not strat_class:
        print_error(f"Stratégie '{name}' non trouvée")
        print_info(f"Disponibles: {', '.join(list_strategies())}")
        return 1

    strat = strat_class()

    if getattr(args, "include_optional_params", False):
        strat._include_optional_params = True

    optional_skipped: List[str] = []
    if hasattr(strat, "parameter_specs") and strat.parameter_specs:
        optional_skipped = [
            name
            for name, spec in strat.parameter_specs.items()
            if not getattr(spec, "optimize", True)
        ]

    if optional_skipped and not getattr(strat, "_include_optional_params", False):
        if not args.quiet:
            skipped = ", ".join(optional_skipped)
            print_info(
                f"Paramètres optionnels ignorés: {skipped} (ajoutez --include-optional-params ou BACKTEST_INCLUDE_OPTIONAL_PARAMS=1)"
            )

    if args.json:
        data = {
            "name": name,
            "description": getattr(strat, "description", ""),
            "required_indicators": strat.required_indicators,
            "default_params": strat.default_params,
            "param_ranges": strat.param_ranges,
        }
        print(json.dumps(data, indent=2))
        return 0

    print_header(f"Stratégie: {name}")
    print(f"  Description: {getattr(strat, 'description', 'N/A')}")
    print(f"  Indicateurs: {', '.join(strat.required_indicators)}")

    print(f"\n{Colors.BOLD}Paramètres par défaut:{Colors.RESET}")
    for k, v in strat.default_params.items():
        print(f"    {k}: {v}")

    print(f"\n{Colors.BOLD}Plages d'optimisation:{Colors.RESET}")
    for k, (min_v, max_v) in strat.param_ranges.items():
        print(f"    {k}: [{min_v}, {max_v}]")

    return 0


def _info_indicator(args) -> int:
    """Affiche les infos d'un indicateur."""
    from indicators.registry import get_indicator, list_indicators

    name = args.name.lower()
    info = get_indicator(name)

    if not info:
        print_error(f"Indicateur '{name}' non trouvé")
        print_info(f"Disponibles: {', '.join(list_indicators())}")
        return 1

    if args.json:
        data = {
            "name": info.name,
            "description": info.description,
            "required_columns": list(info.required_columns),
            "settings_class": info.settings_class.__name__ if info.settings_class else None,
        }
        print(json.dumps(data, indent=2))
        return 0

    print_header(f"Indicateur: {name}")
    print(f"  Description: {info.description}")
    print(f"  Colonnes requises: {', '.join(info.required_columns)}")

    if info.settings_class:
        print(f"\n{Colors.BOLD}Paramètres (Settings):{Colors.RESET}")
        import inspect
        sig = inspect.signature(info.settings_class)
        for param_name, param in sig.parameters.items():
            if param_name != "self":
                default = param.default if param.default != inspect.Parameter.empty else "requis"
                print(f"    {param_name}: {default}")

    return 0


# =============================================================================
# COMMANDE: BACKTEST
# =============================================================================

def cmd_backtest(args) -> int:
    """Exécute un backtest."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            if args.output:
                sub_args.output = _derive_output_path(args.output, strategy_name)
            results.append(_cmd_backtest_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_backtest_single(args, strategies[0])


def _cmd_backtest_single(args, strategy_name: str) -> int:
    import json as json_module
    from pathlib import Path

    from backtest.engine import BacktestEngine
    from strategies import get_strategy, list_strategies

    # Validation stratégie
    strategy_name = strategy_name.lower()
    strat_class = get_strategy(strategy_name)

    if not strat_class:
        print_error(f"Stratégie '{strategy_name}' non trouvée")
        print_info(f"Disponibles: {', '.join(list_strategies())}")
        return 1

    # Validation données - chercher dans BACKTEST_DATA_DIR si chemin relatif
    data_path = _resolve_data_path(args.data)
    if not data_path.exists():
        print_error(f"Fichier non trouvé: {args.data}")
        print_info(f"Répertoire de recherche: {data_path.parent}")
        return 1

    # Parser paramètres JSON
    try:
        params = json_module.loads(args.params)
    except json_module.JSONDecodeError as e:
        print_error(f"Paramètres JSON invalides: {e}")
        return 1

    if not args.quiet:
        print_header("Backtest")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Données: {data_path}")
        print(f"  Capital: {args.capital:,.0f}")
        print(f"  Frais: {args.fees_bps} bps ({args.fees_bps/100:.2f}%)")
        if params:
            print(f"  Paramètres: {params}")
        print()

    # Chargement données
    if not args.quiet:
        print_info("Chargement des données...")

    # Utiliser les fonctions internes pour charger directement depuis le fichier
    from data.loader import _mark_data_quality, _normalize_ohlcv, _read_file, _trim_launch_period
    df = _read_file(data_path)
    df = _normalize_ohlcv(df)
    # timeframe résolu plus bas (ligne ~689), on a besoin ici du stem
    _stem = data_path.stem
    _tf = args.timeframe or (_stem.split("_")[1] if len(_stem.split("_")) > 1 else "1h")
    df = _trim_launch_period(df, _tf)
    df = _mark_data_quality(df)
    try:
        df = _apply_date_filter(df, args.start, args.end)
    except ValueError as e:
        print_error(str(e))
        return 1

    if not args.quiet:
        print_success(f"Données chargées: {len(df)} barres")

    # Exécution backtest
    if not args.quiet:
        print_info("Exécution du backtest...")

    # Créer la configuration avec les frais
    from utils.config import Config
    config_kwargs = {"fees_bps": args.fees_bps}
    if args.slippage_bps is not None:
        config_kwargs["slippage_bps"] = args.slippage_bps
    config = Config(**config_kwargs)

    engine = BacktestEngine(
        initial_capital=args.capital,
        config=config,
    )

    # Extraire symbol et timeframe du nom de fichier (ex: BTCUSDC_1h.parquet)
    stem = data_path.stem
    parts = stem.split("_")
    symbol = args.symbol or (parts[0] if parts else "UNKNOWN")
    timeframe = args.timeframe or (parts[1] if len(parts) > 1 else "1h")

    result = engine.run(
        df=df,
        strategy=strategy_name,
        params=params,
        symbol=symbol,
        timeframe=timeframe
    )

    persisted_run_id = _persist_backtest_result_v2(
        result=result,
        mode="backtest",
        data_path=data_path,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        args=args,
    )

    # Affichage résultats
    if not args.quiet:
        print()
        print_header("Résultats")
        _print_metrics(result.metrics)
        if result.meta.get("period_start") and result.meta.get("period_end"):
            print(f"    Period: {result.meta['period_start']} -> {result.meta['period_end']}")
        print(f"\n  Trades: {len(result.trades)}")
        if persisted_run_id:
            print(f"  Run ID: {persisted_run_id}")

    # Export si demandé
    if args.output:
        output_path = Path(args.output)

        # Gérer metrics qui peut être un dict ou un objet avec to_dict()
        if hasattr(result.metrics, 'to_dict'):
            metrics_dict = result.metrics.to_dict()
        elif isinstance(result.metrics, dict):
            metrics_dict = result.metrics
        else:
            metrics_dict = vars(result.metrics)

        # Gérer trades qui est un DataFrame
        if isinstance(result.trades, pd.DataFrame):
            trades_list = result.trades.to_dict('records')
        elif result.trades and len(result.trades) > 0:
            first_trade = result.trades[0]
            if hasattr(first_trade, 'to_dict'):
                trades_list = [t.to_dict() for t in result.trades]
            elif hasattr(first_trade, '__dict__'):
                trades_list = [vars(t) for t in result.trades]
            else:
                trades_list = list(result.trades)
        else:
            trades_list = []

        output_data = {
            "strategy": strategy_name,
            "params": params,
            "capital": args.capital,
            "fees_bps": args.fees_bps,
            "meta": result.meta,
            "metrics": metrics_dict,
            "n_trades": len(result.trades),
            "trades": trades_list,
        }

        if args.format == "json":
            with open(output_path, "w") as f:
                json_module.dump(output_data, f, indent=2, default=str)
        elif args.format == "csv":
            pd.DataFrame(result.trades).to_csv(output_path, index=False)
        elif args.format == "parquet":
            pd.DataFrame(result.trades).to_parquet(output_path)

        if not args.quiet:
            print_success(f"Résultats exportés: {output_path}")

    return 0


# =============================================================================
# COMMANDE: CATALOG
# =============================================================================

def cmd_catalog(args) -> int:
    """Gère le strategy catalog (list/move/tag/note/archive)."""
    if args.no_color:
        Colors.disable()

    action = getattr(args, "catalog_action", None)
    if not action:
        print_error("Action catalog requise: list|move|tag|note|archive")
        return 1

    from catalog.strategy_catalog import (
        CATEGORY_ORDER,
        archive_entries,
        list_entries,
        move_entries,
        note_entry,
        tag_entries,
    )

    if action == "list":
        categories = _split_multi_args(getattr(args, "category", None))
        tags = _split_multi_args(getattr(args, "tag", None))
        status = getattr(args, "status", "active")
        entries = list_entries(
            categories=categories,
            tags=tags,
            status=status,
            symbol=getattr(args, "symbol", None),
            timeframe=getattr(args, "timeframe", None),
            strategy_name=getattr(args, "strategy", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(entries, indent=2, default=str))
            return 0
        headers = ["id", "strategy", "symbol", "tf", "category", "status", "tags", "sharpe", "return", "trades"]
        rows: List[List[str]] = []
        for entry in entries:
            metrics = entry.get("last_metrics_snapshot") or {}
            rows.append([
                entry.get("id", ""),
                entry.get("strategy_name", ""),
                entry.get("symbol", ""),
                entry.get("timeframe", ""),
                entry.get("category", ""),
                entry.get("status", ""),
                ",".join(entry.get("tags") or []),
                f"{_safe_float(metrics.get('sharpe_ratio', metrics.get('sharpe', 0.0)), 0.0):.2f}",
                f"{_safe_float(metrics.get('total_return_pct', metrics.get('total_return', 0.0)), 0.0):.2f}",
                f"{int(metrics.get('total_trades', metrics.get('trades', 0)) or 0)}",
            ])
        print(format_table(headers, rows))
        if not entries:
            print_info("Catalog vide ou aucun match.")
        return 0

    if action == "move":
        if args.to not in CATEGORY_ORDER:
            print_error(f"Catégorie invalide: {args.to}")
            return 1
        changed = move_entries(args.id, args.to)
        print_success(f"{changed} entrée(s) déplacée(s) vers {args.to}")
        return 0

    if action == "tag":
        changed = tag_entries(args.id, args.tag)
        print_success(f"{changed} entrée(s) taggée(s) '{args.tag}'")
        return 0

    if action == "note":
        ok = note_entry(args.id, args.note)
        if ok:
            print_success("Note enregistrée")
            return 0
        print_error("Entrée introuvable")
        return 1

    if action == "archive":
        changed = archive_entries(args.id)
        print_success(f"{changed} entrée(s) archivée(s)")
        return 0

    print_error(f"Action catalog inconnue: {action}")
    return 1


def _print_metrics(metrics):
    """Affiche les métriques de performance."""
    m = metrics.to_dict() if hasattr(metrics, "to_dict") else metrics

    total_return_pct_raw = _pick_metric(m, "total_return_pct")
    if total_return_pct_raw is not None:
        total_return_pct = _safe_float(total_return_pct_raw, 0.0)
    else:
        total_return_pct = _safe_float(_pick_metric(m, "total_return"), 0.0) * 100.0

    max_drawdown_pct = _safe_float(_pick_metric(m, "max_drawdown_pct", "max_drawdown"), 0.0)
    if _pick_metric(m, "max_drawdown_pct") is None:
        max_drawdown_pct = _percent_from_maybe_fraction(max_drawdown_pct, 0.0)

    win_rate_pct = _percent_from_maybe_fraction(
        _pick_metric(m, "win_rate_pct", "win_rate"),
        0.0,
    )

    print(f"  {Colors.BOLD}Performance:{Colors.RESET}")
    print(f"    Total Return: {total_return_pct:+.2f}%")
    print(f"    Sharpe Ratio: {_safe_float(_pick_metric(m, 'sharpe_ratio', 'sharpe'), 0.0):.3f}")
    print(f"    Sortino Ratio: {_safe_float(_pick_metric(m, 'sortino_ratio', 'sortino'), 0.0):.3f}")
    print(f"    Max Drawdown: {max_drawdown_pct:.2f}%")
    print(f"    Win Rate: {win_rate_pct:.1f}%")
    print(f"    Profit Factor: {_safe_float(_pick_metric(m, 'profit_factor'), 0.0):.2f}")


# =============================================================================
# COMMANDE: SWEEP
# =============================================================================


def _run_cli_numba_sweep_if_possible(
    *,
    df: pd.DataFrame,
    strategy_name: str,
    grid: list[dict],
    metric: str,
    capital: float,
    fees_bps: float,
    slippage_bps: float,
    quiet: bool,
    thread_override: Optional[int] = None,
) -> Optional[list[dict]]:
    """Exécute un sweep Numba si stratégie + métrique sont compatibles."""
    from backtest.sweep_numba import run_numba_sweep_items_if_supported

    metric_key = normalize_metric_name(metric)
    numba_items = run_numba_sweep_items_if_supported(
        df=df,
        strategy_key=strategy_name,
        param_grid=grid,
        metric=metric_key,
        initial_capital=capital,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        thread_override=thread_override,
    )
    if numba_items is None:
        return None

    if not quiet:
        print_info("Backend Numba activé pour ce sweep")

    results: list[dict] = []
    for item in numba_items:
        clean_params = {
            k: _to_native_value(v)
            for k, v in (item.get("params", {}) or {}).items()
        }
        metrics = {
            key: _to_native_value(value)
            for key, value in (item.get("metrics", {}) or {}).items()
        }
        metrics["sharpe"] = metrics.get("sharpe_ratio", 0)
        metrics["max_drawdown"] = metrics.get("max_drawdown_pct", 0)
        metrics["win_rate"] = metrics.get("win_rate_pct", 0)
        metrics["n_trades"] = metrics.get("total_trades", 0)
        metrics["total_return"] = metrics.get("total_return_pct", 0) / 100.0
        results.append(
            {
                "params": clean_params,
                "metrics": metrics,
                "score": _to_native_value(item.get("score", metrics.get(metric_key, 0))),
            }
        )

    return results


def cmd_sweep(args) -> int:
    """Exécute une optimisation paramétrique."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            if args.output:
                sub_args.output = _derive_output_path(args.output, strategy_name)
            results.append(_cmd_sweep_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_sweep_single(args, strategies[0])


def _cmd_sweep_single(args, strategy_name: str) -> int:
    import json as json_module
    from pathlib import Path

    from backtest.engine import BacktestEngine
    from strategies import get_strategy
    from utils.parameters import ParameterSpec, compute_search_space_stats, generate_param_grid

    # Validation stratégie
    strategy_name = strategy_name.lower()
    strat_class = get_strategy(strategy_name)

    if not strat_class:
        print_error(f"Stratégie '{strategy_name}' non trouvée")
        return 1

    # Résolution du chemin des données
    data_path = _resolve_data_path(args.data)
    if not data_path.exists():
        print_error(f"Fichier non trouvé: {args.data}")
        return 1

    strat = strat_class()
    if getattr(args, "include_optional_params", False):
        strat._include_optional_params = True

    if not args.quiet:
        print_header("Optimisation Paramétrique (Sweep)")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Données: {data_path}")
        print(f"  Granularité: {args.granularity}")
        print(f"  Métrique: {args.metric}")
        print(f"  Workers: {args.parallel}")
        print()

    optional_skipped: List[str] = []
    if hasattr(strat, "parameter_specs") and strat.parameter_specs:
        optional_skipped = [
            name
            for name, spec in strat.parameter_specs.items()
            if not getattr(spec, "optimize", True)
        ]
    if optional_skipped and not getattr(strat, "_include_optional_params", False):
        if not args.quiet:
            skipped = ", ".join(optional_skipped)
            print_info(
                f"Paramètres optionnels ignorés: {skipped} "
                "(ajoutez --include-optional-params ou BACKTEST_INCLUDE_OPTIONAL_PARAMS=1)"
            )

    # Construire les specs de paramètres
    param_specs = {}
    for name, (min_v, max_v) in strat.param_ranges.items():
        default = strat.default_params.get(name, (min_v + max_v) / 2)
        param_type = "int" if isinstance(default, int) else "float"
        param_specs[name] = ParameterSpec(
            name=name,
            min_val=min_v,
            max_val=max_v,
            default=default,
            param_type=param_type,
        )

    # Générer la grille
    try:
        grid = generate_param_grid(
            param_specs,
            granularity=args.granularity,
            max_total_combinations=args.max_combinations,
        )
    except ValueError as e:
        print_error(str(e))
        print_info("Augmentez --granularity ou --max-combinations")
        return 1

    # Afficher les statistiques d'espace de recherche (unifié)
    stats = compute_search_space_stats(param_specs, max_combinations=args.max_combinations, granularity=args.granularity)

    if not args.quiet:
        print_info(f"Espace de recherche: {stats.total_combinations:,} combinaisons")
        for pname, pcount in stats.per_param_counts.items():
            print(f"    {pname}: {pcount} valeurs")

    # Charger données avec les fonctions internes
    from data.loader import _normalize_ohlcv, _read_file
    df = _read_file(data_path)
    df = _normalize_ohlcv(df)
    try:
        df = _apply_date_filter(df, args.start, args.end)
    except ValueError as e:
        print_error(str(e))
        return 1

    if not args.quiet:
        print_success(f"Données chargées: {len(df)} barres")
        print_info("Lancement de l'optimisation...")
        print()

    # Extraire symbol et timeframe du nom de fichier
    stem = data_path.stem
    parts = stem.split("_")
    symbol = args.symbol or (parts[0] if parts else "UNKNOWN")
    timeframe = args.timeframe or (parts[1] if len(parts) > 1 else "1h")

    # Créer la configuration avec les frais
    from utils.config import Config
    config_kwargs = {"fees_bps": args.fees_bps}
    if args.slippage_bps is not None:
        config_kwargs["slippage_bps"] = args.slippage_bps
    config = Config(**config_kwargs)

    # Exécuter le sweep
    results = _run_cli_numba_sweep_if_possible(
        df=df,
        strategy_name=strategy_name,
        grid=grid,
        metric=args.metric,
        capital=args.capital,
        fees_bps=float(config.fees_bps),
        slippage_bps=float(config.slippage_bps),
        quiet=args.quiet,
        thread_override=max(1, int(args.parallel)) if getattr(args, "parallel", None) else None,
    )

    if results is None:
        results = []

        for i, params in enumerate(grid):
            engine = BacktestEngine(
                initial_capital=args.capital,
                config=config,
            )

            try:
                result = engine.run(
                    df=df,
                    strategy=strategy_name,
                    params=params,
                    symbol=symbol,
                    timeframe=timeframe
                )
                # Gérer les métriques qui peuvent être un dict ou un objet avec to_dict()
                if hasattr(result.metrics, 'to_dict'):
                    metrics = result.metrics.to_dict()
                else:
                    metrics = dict(result.metrics)
                metrics = {k: _to_native_value(v) for k, v in metrics.items()}
                clean_params = {k: _to_native_value(v) for k, v in params.items()}

                # Normaliser le nom de la métrique
                metric_key = normalize_metric_name(args.metric)

                results.append({
                    "params": clean_params,
                    "metrics": metrics,
                    "score": _to_native_value(metrics.get(metric_key, 0)),
                })
            except Exception as e:
                if args.verbose:
                    print_warning(f"Erreur avec {params}: {e}")

            # Progress
            if not args.quiet and (i + 1) % 10 == 0:
                print(f"\r  Progress: {i+1}/{len(grid)} ({100*(i+1)/len(grid):.1f}%)", end="", flush=True)

    if not args.quiet:
        print("\r" + " " * 50 + "\r", end="")

    # Trier par score (métrique déjà normalisée)
    metric_key = normalize_metric_name(args.metric)
    reverse = _should_reverse_sort(
        args.metric,
        [r.get("score", 0) for r in results],
    )

    results.sort(key=lambda x: x.get("score", 0), reverse=reverse)

    # Afficher les meilleurs
    if not args.quiet:
        print_header(f"Top {args.top} Résultats (tri par {args.metric})")

        for i, r in enumerate(results[:args.top]):
            print(f"\n  {Colors.BOLD}#{i+1}{Colors.RESET}")
            print(f"    Paramètres: {r['params']}")
            print(f"    Sharpe: {r['metrics'].get('sharpe_ratio', 0):.3f}")
            print(f"    Return: {r['metrics'].get('total_return_pct', 0):+.2f}%")
            print(f"    Drawdown: {r['metrics'].get('max_drawdown', 0):.2f}%")

    # Export
    if args.output:
        output_path = Path(args.output)
        output_format = _resolve_output_format(output_path, getattr(args, "format", "auto"))

        export_data = {
            "strategy": strategy_name,
            "granularity": args.granularity,
            "metric": args.metric,
            "n_combinations": len(grid),
            "results": results,
        }

        if output_format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json_module.dump(export_data, f, indent=2, default=str)
        else:
            flat_rows = _flatten_sweep_results(
                strategy=strategy_name,
                granularity=args.granularity,
                metric=args.metric,
                n_combinations=len(grid),
                results=results,
            )
            output_df = pd.DataFrame(flat_rows)
            if output_format == "csv":
                output_df.to_csv(output_path, index=False)
            elif output_format == "parquet":
                output_df.to_parquet(output_path, index=False)
            else:
                print_error(f"Format de sortie sweep non supporté: {output_format}")
                return 1

        if not args.quiet:
            print()
            print_success(f"Résultats exportés: {output_path} ({output_format})")

    best_entry = results[0] if results else {"params": {}, "metrics": {}}
    persisted_run_id = _persist_summary_result_v2(
        mode="sweep",
        strategy=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        params=best_entry.get("params", {}) or {},
        metrics=best_entry.get("metrics", {}) or {},
        diagnostics={
            "results": results,
            "n_combinations": len(grid),
            "metric": args.metric,
            "granularity": args.granularity,
        },
        metadata={
            "period_start": str(df.index[0]) if len(df) else None,
            "period_end": str(df.index[-1]) if len(df) else None,
            "seed": getattr(args, "seed", None),
            "engine_settings": {
                "initial_capital": args.capital,
                "fees_bps": args.fees_bps,
                "slippage_bps": args.slippage_bps,
            },
            "data_source": {"path": str(data_path), "rows": len(df)},
            "config_snapshot_extra": {"command": "sweep", "top": args.top},
        },
        status="ok" if results else "invalid",
    )
    if persisted_run_id and not args.quiet:
        print_success(f"Run sweep indexé: {persisted_run_id}")

    return 0


# =============================================================================
# COMMANDE: VALIDATE
# =============================================================================

def cmd_validate(args) -> int:
    """Valide la configuration."""
    if args.no_color:
        Colors.disable()

    print_header("Validation")

    errors = []
    warnings = []

    # Valider stratégies
    if args.all or args.strategy:
        from strategies import get_strategy, list_strategies

        strategies = [args.strategy] if args.strategy else list_strategies()

        print(f"\n{Colors.BOLD}Stratégies:{Colors.RESET}")
        for name in strategies:
            strat = get_strategy(name)
            if strat:
                try:
                    instance = strat()
                    # Vérifier les attributs requis
                    _ = instance.required_indicators
                    _ = instance.default_params
                    _ = instance.param_ranges
                    print_success(f"  {name}")
                except Exception as e:
                    print_error(f"  {name}: {e}")
                    errors.append(f"Stratégie {name}: {e}")
            else:
                print_error(f"  {name}: non trouvée")
                errors.append(f"Stratégie {name} non trouvée")

    # Valider indicateurs
    if args.all:
        from indicators.registry import get_indicator, list_indicators

        print(f"\n{Colors.BOLD}Indicateurs:{Colors.RESET}")
        for name in list_indicators():
            info = get_indicator(name)
            if info and info.function:
                print_success(f"  {name}")
            else:
                print_error(f"  {name}: fonction manquante")
                errors.append(f"Indicateur {name}: fonction manquante")

    # Valider données
    if args.all or args.data:
        from pathlib import Path

        from data.loader import _normalize_ohlcv, _read_file

        print(f"\n{Colors.BOLD}Données:{Colors.RESET}")

        if args.data:
            data_files = [args.data]
        else:
            from data.loader import _scan_data_files

            data_files = [str(path) for path in _scan_data_files()]

        for f in data_files:
            try:
                df = _read_file(Path(f))
                df = _normalize_ohlcv(df)
                required = ["open", "high", "low", "close", "volume"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    print_warning(f"  {f}: colonnes manquantes {missing}")
                    warnings.append(f"{f}: colonnes manquantes {missing}")
                else:
                    print_success(f"  {f} ({len(df)} barres)")
            except Exception as e:
                print_error(f"  {f}: {e}")
                errors.append(f"{f}: {e}")

    # Résumé
    print()
    if errors:
        print_error(f"Validation échouée: {len(errors)} erreur(s)")
        return 1
    elif warnings:
        print_warning(f"Validation OK avec {len(warnings)} avertissement(s)")
        return 0
    else:
        print_success("Validation réussie!")
        return 0


# =============================================================================
# COMMANDE: EXPORT
# =============================================================================

def cmd_export(args) -> int:
    """Exporte les résultats."""
    if args.no_color:
        Colors.disable()

    import json as json_module
    from pathlib import Path

    input_path = Path(args.input)

    if not input_path.exists():
        print_error(f"Fichier non trouvé: {input_path}")
        return 1

    # Charger les résultats
    with open(input_path) as f:
        data = json_module.load(f)

    # Déterminer le fichier de sortie
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(f".{args.format}")

    if args.format == "html":
        _export_html(data, output_path)
    elif args.format == "csv":
        _export_csv(data, output_path)
    elif args.format == "excel":
        _export_excel(data, output_path)
    else:
        print_error(f"Format non supporté: {args.format}")
        return 1

    print_success(f"Export réussi: {output_path}")
    return 0


def _export_html(data: dict, output_path: Path):
    """Export en HTML."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .metric {{ font-size: 1.2em; margin: 10px 0; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
    </style>
</head>
<body>
    <h1>Rapport de Backtest</h1>
    <p>Stratégie: <strong>{data.get('strategy', 'N/A')}</strong></p>

    <h2>Métriques</h2>
    <div class="metrics">
"""

    metrics = data.get("metrics", {})
    for key, value in metrics.items():
        if isinstance(value, float):
            css_class = "positive" if value > 0 else "negative"
            html += f'        <p class="metric">{key}: <span class="{css_class}">{value:.4f}</span></p>\n'

    html += """    </div>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)


def _export_csv(data: dict, output_path: Path):
    """Export en CSV."""
    results = data.get("results", [])
    if results:
        rows = []
        for r in results:
            row = {**r.get("params", {}), **r.get("metrics", {})}
            rows.append(row)
        pd.DataFrame(rows).to_csv(output_path, index=False)
    else:
        # Single backtest
        metrics = data.get("metrics", {})
        pd.DataFrame([metrics]).to_csv(output_path, index=False)


def _export_excel(data: dict, output_path: Path):
    """Export en Excel."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise ImportError("openpyxl requis pour export Excel: pip install openpyxl")

    results = data.get("results", [])
    if results:
        rows = []
        for r in results:
            row = {**r.get("params", {}), **r.get("metrics", {})}
            rows.append(row)
        pd.DataFrame(rows).to_excel(output_path, index=False)
    else:
        metrics = data.get("metrics", {})
        pd.DataFrame([metrics]).to_excel(output_path, index=False)


__all__ = [
    "cmd_list",
    "cmd_info",
    "cmd_backtest",
    "cmd_sweep",
    "cmd_catalog",
    "cmd_validate",
    "cmd_export",
    "cmd_optuna",
    "cmd_visualize",
    "cmd_check_gpu",
    "cmd_benchmark",
    "cmd_llm_optimize",
    "cmd_grid_backtest",
    "cmd_analyze",
    "cmd_cycle",
    "cmd_indicators",
]


# =============================================================================
# COMMANDE: OPTUNA
# =============================================================================

def cmd_optuna(args) -> int:
    """Exécute une optimisation bayésienne via Optuna."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            if args.output:
                sub_args.output = _derive_output_path(args.output, strategy_name)
            results.append(_cmd_optuna_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_optuna_single(args, strategies[0])


def _cmd_optuna_single(args, strategy_name: str) -> int:
    import json as json_module
    from pathlib import Path

    # Vérifier que Optuna est disponible
    try:
        from backtest.optuna_optimizer import (
            OPTUNA_AVAILABLE,
            OptunaOptimizer,
            suggest_param_space,
        )
    except ImportError:
        print_error("Module optuna_optimizer non trouvé")
        return 1

    if not OPTUNA_AVAILABLE:
        print_error("Optuna n'est pas installé: pip install optuna")
        return 1

    from strategies import get_strategy, list_strategies

    # Validation stratégie
    strategy_name = strategy_name.lower()
    strat_class = get_strategy(strategy_name)

    if not strat_class:
        print_error(f"Stratégie '{strategy_name}' non trouvée")
        print_info(f"Stratégies disponibles: {', '.join(list_strategies())}")
        return 1

    # Résolution du chemin des données
    data_path = _resolve_data_path(args.data)

    if not data_path.exists():
        print_error(f"Fichier non trouvé: {args.data}")
        return 1

    if not args.quiet:
        print_header("Optimisation Bayésienne (Optuna)")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Données: {data_path}")
        print(f"  Trials: {args.n_trials}")
        print(f"  Métrique: {args.metric}")
        print(f"  Sampler: {args.sampler}")
        if args.pruning:
            print(f"  Pruning: activé ({args.pruner})")
        if args.multi_objective:
            print("  Mode: Multi-objectif (Pareto)")
        print()

    # Charger données
    from data.loader import _normalize_ohlcv, _read_file
    df = _read_file(data_path)
    df = _normalize_ohlcv(df)
    try:
        df = _apply_date_filter(df, args.start, args.end)
    except ValueError as e:
        print_error(str(e))
        return 1

    if not args.quiet:
        print_success(f"Données chargées: {len(df)} barres")

    # Construire le param_space
    strat = strat_class()

    if args.param_space:
        # Param space personnalisé via JSON
        try:
            param_space = json_module.loads(args.param_space)
        except json_module.JSONDecodeError as e:
            print_error(f"Erreur JSON param_space: {e}")
            return 1
    else:
        # Param space automatique depuis la stratégie
        param_space = suggest_param_space(strategy_name)

        # Enrichir avec les param_ranges de la stratégie si non couvert
        for name, (min_v, max_v) in strat.param_ranges.items():
            if name not in param_space:

                default = strat.default_params.get(name, (min_v + max_v) / 2)
                param_type = "int" if isinstance(default, int) else "float"
                param_space[name] = {
                    "type": param_type,
                    "low": min_v,
                    "high": max_v,
                }

    if not param_space:
        print_error(f"Aucun param_space défini pour {strategy_name}")
        return 1

    # Contraintes
    constraints = []
    if args.constraints:
        for c in args.constraints:
            parts = c.split(",")
            if len(parts) == 3:
                constraints.append((parts[0], parts[1], parts[2]))

    # Extraire symbol et timeframe
    stem = data_path.stem
    parts = stem.split("_")
    symbol = args.symbol or (parts[0] if parts else "UNKNOWN")
    timeframe = args.timeframe or (parts[1] if len(parts) > 1 else "1h")

    # Créer l'optimiseur
    from utils.config import Config
    config_kwargs = {"fees_bps": args.fees_bps}
    if args.slippage_bps is not None:
        config_kwargs["slippage_bps"] = args.slippage_bps
    config = Config(**config_kwargs)

    optimizer = OptunaOptimizer(
        strategy_name=strategy_name,
        data=df,
        param_space=param_space,
        constraints=constraints,
        initial_capital=args.capital,
        early_stop_patience=args.early_stop_patience,
        config=config,
        symbol=symbol,
        timeframe=timeframe,
        seed=args.seed,
    )

    if not args.quiet:
        print_info(f"Lancement optimisation ({args.n_trials} trials)...")
        if args.early_stop_patience:
            print_info(f"Early stopping activé: patience={args.early_stop_patience}")
        print()

    # Lancer l'optimisation
    try:
        if args.multi_objective:
            # Multi-objectif (Pareto)
            metrics = [normalize_metric_name(m.strip()) for m in args.metric.split(",")]
            directions = []
            for m in metrics:
                if m in ["max_drawdown"]:
                    directions.append("minimize")
                else:
                    directions.append("maximize")

            result = optimizer.optimize_multi_objective(
                n_trials=args.n_trials,
                metrics=metrics,
                directions=directions,
                timeout=args.timeout,
            )

            if not args.quiet:
                print_header("Résultats Multi-Objectif (Front de Pareto)")
                print(f"  Solutions Pareto: {len(result.pareto_front)}")
                print()

                for i, sol in enumerate(result.pareto_front[:args.top]):
                    print(f"  {Colors.BOLD}Solution #{i+1}{Colors.RESET}")
                    print(f"    Paramètres: {sol['params']}")
                    print(f"    Valeurs: {sol['values']}")
                    print()
        else:
            # Mono-objectif (normaliser la métrique)
            metric_key = normalize_metric_name(args.metric)
            direction = "minimize" if args.metric == "max_drawdown" else "maximize"

            result = optimizer.optimize(
                n_trials=args.n_trials,
                metric=metric_key,
                direction=direction,
                sampler=args.sampler,
                pruner=args.pruner if args.pruning else "none",
                timeout=args.timeout,
                show_progress=not args.quiet,
            )

            if not args.quiet:
                print_header(f"Résultats Optuna (Top {args.top})")
                print(f"  Trials: {result.n_completed}/{args.n_trials} complétés")
                print(f"  Pruned: {result.n_pruned}")
                print(f"  Temps total: {result.total_time:.1f}s")
                print()

                print(f"  {Colors.GREEN}Meilleur résultat:{Colors.RESET}")
                print(f"    Paramètres: {result.best_params}")
                print(f"    {args.metric}: {result.best_value:.4f}")
                if result.best_metrics:
                    best_drawdown = _safe_float(
                        result.best_metrics.get("max_drawdown_pct", result.best_metrics.get("max_drawdown", 0.0)),
                        0.0,
                    )
                    print(f"    Sharpe: {result.best_metrics.get('sharpe_ratio', 'N/A'):.3f}")
                    print(f"    Return: {result.best_metrics.get('total_return_pct', 0):+.2f}%")
                    print(f"    Drawdown: {best_drawdown:.2f}%")
                print()

                # Top N
                top_df = result.get_top_n(args.top)
                if not top_df.empty and len(top_df) > 0:
                    print(f"  {Colors.BOLD}Top {min(args.top, len(top_df))} configurations:{Colors.RESET}")
                    # Récupérer les noms des paramètres (excluant 'trial' et 'value')
                    param_cols = [c for c in top_df.columns if c not in ['trial', 'value']]
                    for idx, row_dict in enumerate(top_df.head(args.top).to_dict(orient="records")):
                        params = {col: row_dict[col] for col in param_cols if col in row_dict}
                        val = row_dict.get('value', float('nan'))
                        val_str = f"{val:.4f}" if np.isfinite(val) else "N/A"
                        print(f"    #{idx+1}: {params} → {val_str}")

    except Exception as e:
        print_error(f"Erreur lors de l'optimisation: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Export
    if args.output:
        output_path = Path(args.output)

        if args.multi_objective:
            export_data = {
                "strategy": strategy_name,
                "type": "multi_objective",
                "metrics": metrics,
                "n_trials": args.n_trials,
                "pareto_front": result.pareto_front,
            }
        else:
            export_data = {
                "strategy": strategy_name,
                "type": "single_objective",
                "metric": args.metric,
                "n_trials": args.n_trials,
                "n_completed": result.n_completed,
                "n_pruned": result.n_pruned,
                "total_time": result.total_time,
                "best_params": result.best_params,
                "best_value": result.best_value,
                "best_metrics": result.best_metrics,
                "history": result.history,
            }

        with open(output_path, "w") as f:
            json_module.dump(export_data, f, indent=2, default=str)

        if not args.quiet:
            print_success(f"Résultats exportés: {output_path}")

    if args.multi_objective:
        top_solution = (result.pareto_front[0] if result.pareto_front else {}) if result else {}
        if isinstance(top_solution, dict):
            metric_keys = set(metrics) if "metrics" in locals() else set()
            reserved = {"trial"} | metric_keys
            persist_params = {k: v for k, v in top_solution.items() if k not in reserved}
        else:
            persist_params = {}
        persist_metrics = {}
        diagnostics = {
            "type": "optuna_multi_objective",
            "metrics": metrics,
            "pareto_front": result.pareto_front if result else [],
            "n_trials": args.n_trials,
        }
    else:
        persist_params = result.best_params if result else {}
        persist_metrics = result.best_metrics if result else {}
        diagnostics = {
            "type": "optuna_single_objective",
            "metric": args.metric,
            "best_value": result.best_value if result else None,
            "n_trials": args.n_trials,
            "n_completed": result.n_completed if result else None,
            "n_pruned": result.n_pruned if result else None,
            "history": result.history if result else [],
        }

    persisted_run_id = _persist_summary_result_v2(
        mode="optuna",
        strategy=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        params=persist_params or {},
        metrics=persist_metrics or {},
        diagnostics=diagnostics,
        metadata={
            "period_start": str(df.index[0]) if len(df) else args.start,
            "period_end": str(df.index[-1]) if len(df) else args.end,
            "seed": getattr(args, "seed", None),
            "engine_settings": {
                "initial_capital": args.capital,
                "fees_bps": args.fees_bps,
                "slippage_bps": args.slippage_bps,
            },
            "data_source": {"path": str(data_path), "rows": len(df)},
            "config_snapshot_extra": {
                "command": "optuna",
                "sampler": args.sampler,
                "pruner": args.pruner if args.pruning else "none",
                "multi_objective": bool(args.multi_objective),
            },
        },
        status="ok",
    )
    if persisted_run_id and not args.quiet:
        print_success(f"Run optuna indexé: {persisted_run_id}")

    return 0


# =============================================================================
# COMMANDE: VISUALIZE
# =============================================================================

def cmd_visualize(args) -> int:
    """Visualise les résultats d'un backtest avec graphiques interactifs."""
    if args.no_color:
        Colors.disable()

    import json as json_module
    from pathlib import Path

    try:
        from utils.visualization import (
            PLOTLY_AVAILABLE,
            visualize_backtest,
        )
    except ImportError as e:
        print_error(f"Module visualization non disponible: {e}")
        return 1

    if not PLOTLY_AVAILABLE:
        print_error("Plotly requis pour la visualisation: pip install plotly")
        return 1

    # Charger les résultats
    input_path = Path(args.input)
    if not input_path.exists():
        print_error(f"Fichier non trouvé: {input_path}")
        return 1

    if not args.quiet:
        print_header("Visualisation des Résultats")
        print_info(f"Fichier: {input_path}")

    # Charger les données OHLCV si fournies
    df = None
    data_path = None

    if args.data:
        data_path = _resolve_data_path(args.data)
        if not data_path.exists():
            print_warning(f"Fichier de données non trouvé: {args.data}")
            data_path = None

    # Output path
    output_path = None
    if args.output:
        output_path = Path(args.output)
    elif args.html:
        output_path = input_path.with_suffix('.html')

    try:
        # Charger le fichier de résultats
        with open(input_path) as f:
            results_data = json_module.load(f)

        # Déterminer le type de résultat
        result_type = results_data.get('type', 'backtest')

        if result_type == 'sweep':
            # Résultats de sweep - prendre le meilleur
            all_results = results_data.get('results', [])
            if not all_results:
                print_error("Aucun résultat dans le sweep")
                return 1

            # Trier par métrique (sharpe par défaut)
            metric_key = args.metric or 'sharpe_ratio'
            sorted_results = sorted(
                all_results,
                key=lambda x: x.get('metrics', {}).get(metric_key, float('-inf')),
                reverse=True
            )
            best = sorted_results[0]

            trades = best.get('trades', [])
            metrics = best.get('metrics', {})
            params = best.get('params', {})
            equity_curve = best.get('equity_curve')
            strategy = results_data.get('strategy', 'Unknown')

            if not args.quiet:
                print_info(f"Meilleur résultat (sur {len(all_results)}): {params}")
                print_info(f"{metric_key}: {metrics.get(metric_key, 'N/A'):.4f}")

        elif result_type in ('single_objective', 'multi_objective'):
            # Résultats Optuna
            trades = results_data.get('trades', [])
            metrics = results_data.get('best_metrics', {})
            params = results_data.get('best_params', {})
            equity_curve = results_data.get('equity_curve')
            strategy = results_data.get('strategy', 'Unknown')

            if not trades:
                print_warning("Pas de trades dans les résultats Optuna")
                print_info(f"Meilleurs params: {params}")
                print_info(f"Meilleure valeur: {results_data.get('best_value', 'N/A')}")

                # Relancer un backtest avec les meilleurs params pour avoir les trades
                if args.data and data_path:
                    if not args.quiet:
                        print_info("Exécution du backtest avec les meilleurs paramètres...")

                    from backtest import BacktestEngine
                    from data.loader import _normalize_ohlcv, _read_file
                    from utils.config import Config

                    df = _read_file(data_path)
                    df = _normalize_ohlcv(df)

                    config = Config(fees_bps=args.fees_bps)
                    engine = BacktestEngine(
                        initial_capital=args.capital or 10000,
                        config=config,
                    )

                    stem = data_path.stem
                    parts = stem.split("_")
                    symbol = parts[0] if parts else "UNKNOWN"
                    timeframe = parts[1] if len(parts) > 1 else "1m"

                    result = engine.run(
                        df=df,
                        strategy=strategy,
                        params=params,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                    if isinstance(result.trades, pd.DataFrame):
                        trades = result.trades.to_dict("records")
                    else:
                        trades = (
                            [t.__dict__ for t in result.trades]
                            if hasattr(result, "trades")
                            else []
                        )
                    if hasattr(result.metrics, "to_dict"):
                        metrics = result.metrics.to_dict()
                    elif isinstance(result.metrics, dict):
                        metrics = result.metrics
                    else:
                        metrics = vars(result.metrics)
                    equity_curve = result.equity.tolist() if hasattr(result, "equity") else None

        else:
            # Backtest simple
            trades = results_data.get('trades', [])
            metrics = results_data.get('metrics', {})
            params = results_data.get('params', {})
            equity_curve = results_data.get('equity_curve')
            strategy = results_data.get('strategy', 'Unknown')

        if not trades and not equity_curve:
            print_error("Aucun trade ou equity curve à visualiser")
            print_info("Assurez-vous que le fichier contient des données de trades")
            return 1

        # Charger les données OHLCV
        if data_path and data_path.exists():
            # Charger directement depuis le fichier
            if data_path.suffix == '.parquet':
                df = pd.read_parquet(data_path)
            elif data_path.suffix == '.csv':
                df = pd.read_csv(data_path)
            elif data_path.suffix == '.json':
                df = pd.read_json(data_path)
            else:
                print_warning(f"Format non supporté: {data_path.suffix}")
                df = None

            if df is not None:
                # Normaliser les colonnes
                df.columns = df.columns.str.lower()
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df.set_index('timestamp', inplace=True)
                elif 'time' in df.columns:
                    df['time'] = pd.to_datetime(df['time'])
                    df.set_index('time', inplace=True)
                elif not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index)

                # Supprimer timezone pour éviter les problèmes de comparaison
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    df.index = df.index.tz_localize(None)

                if not args.quiet:
                    print_info(f"Données OHLCV chargées: {len(df)} barres")

        # Préparer le titre
        title = f"Backtest - {strategy}"
        if params:
            params_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:4])
            title += f"\n({params_str})"

        # Visualisation
        if df is not None:
            visualize_backtest(
                df=df,
                trades=trades,
                metrics=metrics,
                equity_curve=equity_curve,
                title=title,
                output_path=output_path,
                show=not args.no_show,
            )
        else:
            # Pas de données OHLCV - afficher seulement equity curve
            if equity_curve:
                from utils.visualization import plot_equity_curve
                fig = plot_equity_curve(
                    equity_curve,
                    initial_capital=metrics.get('initial_capital', 10000),
                    title=title,
                )
                if not args.no_show:
                    fig.show()

                if output_path:
                    fig.write_html(str(output_path))
                    print_success(f"Graphique sauvegardé: {output_path}")
            else:
                print_error("Pas de données suffisantes pour visualiser")
                return 1

        # Stats finales
        if not args.quiet:
            print()
            print_header("Métriques Clés", "-")
            pnl = _safe_float(_pick_metric(metrics, "pnl", "total_pnl"), 0.0)
            sharpe = _safe_float(_pick_metric(metrics, "sharpe_ratio", "sharpe"), 0.0)
            max_dd = _safe_float(_pick_metric(metrics, "max_drawdown_pct", "max_drawdown"), 0.0)
            if _pick_metric(metrics, "max_drawdown_pct") is None:
                max_dd = _percent_from_maybe_fraction(max_dd, 0.0)

            win_rate = _percent_from_maybe_fraction(
                _pick_metric(metrics, "win_rate_pct", "win_rate"),
                0.0,
            )

            pnl_color = Colors.GREEN if pnl >= 0 else Colors.RED
            print(f"  PnL:          {pnl_color}{pnl:+,.2f}{Colors.RESET}")
            print(f"  Sharpe:       {sharpe:.2f}")
            print(f"  Max DD:       {Colors.RED}{max_dd:.1f}%{Colors.RESET}")
            print(f"  Win Rate:     {win_rate:.1f}%")
            print(f"  Trades:       {len(trades)}")

        if output_path:
            print_success(f"Rapport HTML: {output_path}")

        return 0

    except Exception as e:
        print_error(f"Erreur lors de la visualisation: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


# =============================================================================
# COMMANDE: BENCHMARK
# =============================================================================

def cmd_benchmark(args) -> int:
    """Exécute les benchmarks de performance (indicateurs, simulateur, GPU)."""
    if args.no_color:
        Colors.disable()

    from performance.benchmark import (
        benchmark_gpu_vs_cpu,
        benchmark_indicator_calculation,
        benchmark_simulator_performance,
        run_all_benchmarks,
    )

    if not args.quiet:
        print_header("Benchmarks de performance", "=")

    try:
        if args.category == "all":
            run_all_benchmarks(verbose=not args.quiet)
        elif args.category == "indicators":
            comp = benchmark_indicator_calculation(data_size=args.size, period=args.period)
            if not args.quiet:
                print(comp.summary())
        elif args.category == "simulator":
            comp = benchmark_simulator_performance(n_bars=args.size)
            if not args.quiet:
                print(comp.summary())
        elif args.category == "gpu":
            comp = benchmark_gpu_vs_cpu(data_size=args.size)
            if not args.quiet:
                print(comp.summary())
        else:
            print_error(f"Catégorie inconnue: {args.category}")
            return 1
    except Exception as e:
        print_error(f"Erreur benchmark: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    return 0


# =============================================================================
# COMMANDE: CHECK-GPU
# =============================================================================

def cmd_check_gpu(args) -> int:
    """Diagnostic GPU désactivé (CPU-only)."""
    if args.no_color:
        Colors.disable()

    print_header("Diagnostic GPU", "=")
    print_warning("GPU désactivé (mode CPU-only).")
    print_info("Aucun test GPU/CUDA n'est exécuté.")
    return 0


# =============================================================================
# COMMANDE: LLM-OPTIMIZE
# =============================================================================

def cmd_llm_optimize(args) -> int:
    """Lance une optimisation LLM avec orchestrateur multi-agents."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            if args.output:
                sub_args.output = _derive_output_path(args.output, strategy_name)
            results.append(_cmd_llm_optimize_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_llm_optimize_single(args, strategies[0])


def _cmd_llm_optimize_single(args, strategy_name: str) -> int:
    from pathlib import Path

    from agents.integration import create_orchestrator_with_backtest
    from agents.llm_client import LLMConfig, LLMProvider
    from data.loader import load_ohlcv
    from strategies import get_strategy

    if not args.quiet:
        print_header("Optimisation LLM Multi-Agents")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Symbole: {args.symbol}")
        print(f"  Timeframe: {args.timeframe}")
        print(f"  Période: {args.start} → {args.end}")
        print(f"  Capital: {args.capital:,.0f}")
        print(f"  Modèle LLM: {args.model}")
        print(f"  Max itérations: {args.max_iterations}")
        print()

    # Charger les données
    if not args.quiet:
        print_info("Chargement des données...")

    try:
        df = load_ohlcv(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end
        )
    except Exception as e:
        print_error(f"Erreur chargement données: {e}")
        return 1

    if not args.quiet:
        print_success(f"Données chargées: {len(df)} barres")
        print(f"   Période réelle: {df.index[0]} → {df.index[-1]}")
        print()

    # Configuration LLM
    llm_config = LLMConfig(
        provider=LLMProvider.OLLAMA,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout,
    )

    # Récupérer les paramètres par défaut de la stratégie
    if not args.quiet:
        print_info("Récupération des paramètres par défaut...")

    strategy_class = get_strategy(strategy_name)
    if not strategy_class:
        print_error(f"Stratégie '{strategy_name}' non trouvée")
        return 1

    strategy_instance = strategy_class()
    initial_params = strategy_instance.default_params

    if not args.quiet:
        print_success(f"Paramètres initiaux: {list(initial_params.keys())}")
        print()

    # Créer l'orchestrateur
    if not args.quiet:
        print_info("Création de l'orchestrateur multi-agents...")

    try:
        orchestrator = create_orchestrator_with_backtest(
            strategy_name=strategy_name,
            data=df,
            data_symbol=args.symbol,
            data_timeframe=args.timeframe,
            initial_params=initial_params,
            llm_config=llm_config,
            initial_capital=args.capital,
            max_iterations=args.max_iterations,
            min_sharpe=args.min_sharpe,
            max_drawdown_limit=args.max_drawdown,
        )
    except Exception as e:
        print_error(f"Erreur création orchestrateur: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    if not args.quiet:
        print_success("Orchestrateur créé")
        print()
        print_header("Lancement de l'optimisation", "-")

    # Lancer l'optimisation
    try:
        result = orchestrator.run()
    except Exception as e:
        print_error(f"Erreur durant l'optimisation: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    result_decision = getattr(result, "decision", "ABORT")
    result_final_params = getattr(result, "final_params", None) or {}
    raw_final_metrics = getattr(result, "final_metrics", None)
    if hasattr(raw_final_metrics, "to_dict"):
        result_final_metrics = raw_final_metrics.to_dict()
    else:
        result_final_metrics = raw_final_metrics or {}

    result_iterations = getattr(result, "iterations", None)
    if result_iterations is None:
        result_iterations = getattr(result, "total_iterations", 0)

    result_reason = getattr(result, "reason", None) or getattr(result, "final_report", None)
    result_history = getattr(result, "history", None)
    if result_history is None:
        result_history = getattr(result, "iteration_history", None)

    # Afficher les résultats
    if not args.quiet:
        print()
        print_header("Résultats Finaux")

        if result_decision == "APPROVED":
            print_success(f"Décision: {result_decision}")
        elif result_decision == "REJECTED":
            print_warning(f"Décision: {result_decision}")
        else:
            print_error(f"Décision: {result_decision}")

        if result_final_params:
            print(f"\n{Colors.BOLD}Paramètres finaux:{Colors.RESET}")
            for k, v in result_final_params.items():
                print(f"    {k}: {v}")

        if result_final_metrics:
            print(f"\n{Colors.BOLD}Métriques finales:{Colors.RESET}")
            _print_metrics(result_final_metrics)

        print(f"\n  Itérations: {result_iterations}")

        if result_reason:
            print(f"\n  Raison: {result_reason}")

    # Export si demandé
    if args.output:
        output_path = Path(args.output)

        import json as json_module

        export_data = {
            "strategy": strategy_name,
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "period": {"start": args.start, "end": args.end},
            "model": args.model,
            "max_iterations": args.max_iterations,
            "decision": result_decision,
            "iterations": result_iterations,
            "final_params": result_final_params,
            "final_metrics": result_final_metrics,
            "reason": result_reason,
            "history": result_history,
        }

        with open(output_path, "w") as f:
            json_module.dump(export_data, f, indent=2, default=str)

        if not args.quiet:
            print()
            print_success(f"Résultats exportés: {output_path}")

    persisted_run_id = _persist_summary_result_v2(
        mode="llm_optimize",
        strategy=strategy_name,
        symbol=args.symbol,
        timeframe=args.timeframe,
        params=result_final_params,
        metrics=result_final_metrics,
        diagnostics={
            "decision": result_decision,
            "reason": result_reason,
            "iterations": result_iterations,
            "history": result_history,
        },
        metadata={
            "period_start": str(df.index[0]) if len(df) else args.start,
            "period_end": str(df.index[-1]) if len(df) else args.end,
            "seed": getattr(args, "seed", None),
            "engine_settings": {
                "initial_capital": args.capital,
                "min_sharpe": args.min_sharpe,
                "max_drawdown": args.max_drawdown,
                "temperature": args.temperature,
            },
            "data_source": {
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "rows": len(df),
            },
            "config_snapshot_extra": {
                "command": "llm-optimize",
                "model": args.model,
                "max_iterations": args.max_iterations,
            },
        },
        status="ok" if result_final_metrics else "invalid",
    )
    if persisted_run_id and not args.quiet:
        print_success(f"Run LLM indexé: {persisted_run_id}")

    return 0


# =============================================================================
# COMMANDE: GRID-BACKTEST
# =============================================================================

def cmd_grid_backtest(args) -> int:
    """Exécute un backtest en mode grille de paramètres."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            if args.output:
                sub_args.output = _derive_output_path(args.output, strategy_name)
            results.append(_cmd_grid_backtest_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_grid_backtest_single(args, strategies[0])


def _cmd_grid_backtest_single(args, strategy_name: str) -> int:
    import json as json_module
    from itertools import product
    from pathlib import Path

    from backtest.engine import BacktestEngine
    from data.loader import load_ohlcv
    from strategies import get_strategy
    from utils.config import Config
    from utils.parameters import normalize_param_grid_values

    if not args.quiet:
        print_header("Backtest Mode Grille")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Symbole: {args.symbol}")
        print(f"  Timeframe: {args.timeframe}")
        print(f"  Période: {args.start} → {args.end}")
        print(f"  Capital: {args.capital:,.0f}")
        print()

    # Charger les données
    if not args.quiet:
        print_info("Chargement des données...")

    try:
        df = load_ohlcv(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end
        )
    except Exception as e:
        print_error(f"Erreur chargement données: {e}")
        return 1

    if not args.quiet:
        print_success(f"Données chargées: {len(df)} barres")
        print(f"   Période réelle: {df.index[0]} → {df.index[-1]}")
        print()

    strategy_class = get_strategy(strategy_name)
    if not strategy_class:
        print_error(f"Stratégie '{strategy_name}' non trouvée")
        return 1

    strategy_instance = strategy_class()

    if getattr(args, "include_optional_params", False):
        strategy_instance._include_optional_params = True

    # Parser la grille de paramètres depuis JSON
    if args.param_grid:
        try:
            param_grid = json_module.loads(args.param_grid)
        except json_module.JSONDecodeError as e:
            print_error(f"Erreur parsing param_grid JSON: {e}")
            return 1
    else:
        # Utiliser une grille par défaut basée sur la stratégie
        optional_skipped: List[str] = []
        if hasattr(strategy_instance, "parameter_specs") and strategy_instance.parameter_specs:
            optional_skipped = [
                name
                for name, spec in strategy_instance.parameter_specs.items()
                if not getattr(spec, "optimize", True)
            ]

        if optional_skipped and not getattr(strategy_instance, "_include_optional_params", False):
            if not args.quiet:
                skipped = ", ".join(optional_skipped)
                print_info(
                    f"Paramètres optionnels ignorés: {skipped} (ajoutez --include-optional-params ou BACKTEST_INCLUDE_OPTIONAL_PARAMS=1)"
                )
        param_grid = {}

        # Générer une grille simple depuis param_ranges
        for param_name, (min_val, max_val) in strategy_instance.param_ranges.items():
            default = strategy_instance.default_params.get(param_name, (min_val + max_val) / 2)

            if isinstance(default, int):
                # Grille de 3 valeurs pour les entiers
                step = max(1, (max_val - min_val) // 2)
                param_grid[param_name] = [min_val, min_val + step, max_val]
            else:
                # Grille de 3 valeurs pour les floats
                param_grid[param_name] = [
                    min_val,
                    (min_val + max_val) / 2,
                    max_val
                ]

    if hasattr(strategy_instance, "parameter_specs") and strategy_instance.parameter_specs:
        try:
            param_grid, grid_warnings = normalize_param_grid_values(
                strategy_instance.parameter_specs,
                param_grid,
            )
        except ValueError as exc:
            print_error(str(exc))
            return 1
        for warning in grid_warnings:
            print_warning(warning)

    # Générer toutes les combinaisons
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    all_combinations = list(product(*param_values))

    # Limiter le nombre de combinaisons
    if len(all_combinations) > args.max_combinations:
        print_warning(f"Nombre de combinaisons ({len(all_combinations)}) > max ({args.max_combinations})")
        print_info(f"Limitation à {args.max_combinations} combinaisons")
        import random
        random.seed(42)
        all_combinations = random.sample(all_combinations, args.max_combinations)

    if not args.quiet:
        print_header("Grille de paramètres", "-")
        for param_name, values in param_grid.items():
            print(f"  {param_name}: {values}")
        print(f"\n  Total combinaisons: {len(all_combinations)}")
        print()

    # Créer la configuration avec les frais
    config_kwargs = {"fees_bps": args.fees_bps}
    if args.slippage_bps is not None:
        config_kwargs["slippage_bps"] = args.slippage_bps
    config = Config(**config_kwargs)

    # Exécuter les backtests
    if not args.quiet:
        print_info("Lancement des backtests...")
        print()

    grid = [dict(zip(param_names, param_combination)) for param_combination in all_combinations]
    numba_results = _run_cli_numba_sweep_if_possible(
        df=df,
        strategy_name=strategy_name,
        grid=grid,
        metric=args.metric,
        capital=args.capital,
        fees_bps=float(config.fees_bps),
        slippage_bps=float(config.slippage_bps),
        quiet=args.quiet,
        thread_override=None,
    )

    if numba_results is not None:
        results = [
            {
                "params": item["params"],
                "metrics": item["metrics"],
            }
            for item in numba_results
        ]
    else:
        results = []

        for i, params in enumerate(grid):
            engine = BacktestEngine(
                initial_capital=args.capital,
                config=config,
            )

            try:
                result = engine.run(
                    df=df,
                    strategy=strategy_name,
                    params=params,
                    symbol=args.symbol,
                    timeframe=args.timeframe
                )

                # Gérer les métriques
                if hasattr(result.metrics, 'to_dict'):
                    metrics = result.metrics.to_dict()
                else:
                    metrics = dict(result.metrics)

                results.append({
                    "params": params,
                    "metrics": metrics,
                })
            except Exception as e:
                if args.verbose:
                    print_warning(f"Erreur avec {params}: {e}")

            # Progress
            if not args.quiet and (i + 1) % 10 == 0:
                print(f"\r  Progress: {i+1}/{len(grid)} ({100*(i+1)/len(grid):.1f}%)", end="", flush=True)

    if not args.quiet:
        print("\r" + " " * 50 + "\r", end="")
        print_success(f"Backtests terminés: {len(results)} résultats")
        print()

    # Trier par métrique
    metric_key = args.metric
    reverse = _should_reverse_sort(
        args.metric,
        [r["metrics"].get(args.metric, 0) for r in results],
    )

    results.sort(key=lambda x: x["metrics"].get(metric_key, 0), reverse=reverse)

    # Afficher les meilleurs
    if not args.quiet:
        print_header(f"Top {args.top} Résultats (tri par {args.metric})")

        for i, r in enumerate(results[:args.top]):
            print(f"\n  {Colors.BOLD}#{i+1}{Colors.RESET}")
            print(f"    Paramètres: {r['params']}")
            print(f"    Sharpe: {r['metrics'].get('sharpe_ratio', 0):.3f}")
            print(f"    Return: {r['metrics'].get('total_return_pct', 0):+.2f}%")
            print(f"    Drawdown: {r['metrics'].get('max_drawdown', 0):.2f}%")
            print(f"    {args.metric}: {r['metrics'].get(metric_key, 0):.4f}")

    # Export
    if args.output:
        output_path = Path(args.output)

        export_data = {
            "strategy": strategy_name,
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "period": {"start": args.start, "end": args.end},
            "param_grid": param_grid,
            "n_combinations": len(all_combinations),
            "metric": args.metric,
            "results": results,
        }

        with open(output_path, "w") as f:
            json_module.dump(export_data, f, indent=2, default=str)

        if not args.quiet:
            print()
            print_success(f"Résultats exportés: {output_path}")

    best_result = results[0] if results else None
    best_params = best_result.get("params", {}) if best_result else {}
    best_metrics = best_result.get("metrics", {}) if best_result else {}
    persisted_run_id = _persist_summary_result_v2(
        mode="grid_backtest",
        strategy=strategy_name,
        symbol=args.symbol,
        timeframe=args.timeframe,
        params=best_params,
        metrics=best_metrics,
        diagnostics={
            "metric": args.metric,
            "n_combinations_tested": len(results),
            "n_combinations_requested": len(all_combinations),
            "top_results": results[: min(args.top, 10)],
        },
        metadata={
            "period_start": args.start,
            "period_end": args.end,
            "seed": getattr(args, "seed", None),
            "engine_settings": {
                "initial_capital": args.capital,
                "fees_bps": args.fees_bps,
                "slippage_bps": args.slippage_bps,
            },
            "data_source": {
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "rows": len(df),
            },
            "config_snapshot_extra": {
                "command": "grid-backtest",
                "max_combinations": args.max_combinations,
                "metric": args.metric,
            },
        },
        status="ok" if best_result else "invalid",
    )
    if persisted_run_id and not args.quiet:
        print_success(f"Run grid indexé: {persisted_run_id}")

    return 0


# =============================================================================
# COMMANDE: ANALYZE
# =============================================================================

def _metric_sort_value(metrics: dict, sort_by: str) -> float:
    """Retourne la valeur de tri d'une métrique, avec alias et fallback."""
    missing = float("inf") if sort_by in {"max_drawdown", "max_drawdown_pct"} else float("-inf")
    normalized = normalize_metric_name(sort_by)
    if normalized in metrics:
        return metrics.get(normalized, missing)
    if sort_by in metrics:
        return metrics.get(sort_by, missing)

    # Compatibilité drawdown pct/non-pct
    if sort_by == "max_drawdown_pct" and "max_drawdown" in metrics:
        return metrics.get("max_drawdown", missing)
    if sort_by == "max_drawdown" and "max_drawdown_pct" in metrics:
        return metrics.get("max_drawdown_pct", missing)

    return missing


def _normalize_drawdown_limit(limit: float | None) -> float | None:
    """Normalise une contrainte drawdown en borne négative (ex: 40 -> -40)."""
    if limit is None:
        return None
    try:
        return -abs(float(limit))
    except Exception:
        return None


def _run_cycle_walk_forward(
    *,
    df: pd.DataFrame,
    strategy: str,
    params: dict,
    capital: float,
    args,
) -> dict:
    """Exécute la validation walk-forward optionnelle pour cmd_cycle."""
    from backtest.walk_forward import (
        WalkForwardConfig,
        check_wfa_feasibility,
        run_walk_forward,
    )

    wf_mode = (getattr(args, "wf_mode", "both") or "both").lower()
    modes = ["rolling", "expanding"] if wf_mode == "both" else [wf_mode]

    payload = {
        "enabled": True,
        "mode": wf_mode,
        "config": {
            "n_folds": int(args.wf_folds),
            "train_ratio": float(args.wf_train_ratio),
            "embargo_pct": float(args.wf_embargo_pct),
            "min_train_bars": int(args.wf_min_train_bars),
            "min_test_bars": int(args.wf_min_test_bars),
        },
        "results": {},
    }

    for mode in modes:
        cfg = WalkForwardConfig(
            n_folds=int(args.wf_folds),
            train_ratio=float(args.wf_train_ratio),
            embargo_pct=float(args.wf_embargo_pct),
            min_train_bars=int(args.wf_min_train_bars),
            min_test_bars=int(args.wf_min_test_bars),
            expanding=(mode == "expanding"),
        )

        feasible, message = check_wfa_feasibility(len(df), config=cfg)
        if not feasible:
            payload["results"][mode] = {
                "status": "skipped",
                "reason": message,
            }
            continue

        summary = run_walk_forward(
            df=df,
            strategy_name=strategy,
            params=params,
            config=cfg,
            initial_capital=capital,
        )
        result = summary.to_dict()
        result["status"] = "ok"
        payload["results"][mode] = result

    return payload


def _is_metric_better(metric_name: str, candidate_value: float, reference_value: float) -> bool:
    """Compare deux scores selon le sens de tri de la métrique."""
    reverse = _should_reverse_sort(metric_name, [candidate_value, reference_value])
    if reverse:
        return float(candidate_value) > float(reference_value)
    return float(candidate_value) < float(reference_value)


def _build_local_param_specs(strat, seed_params: dict, range_ratio: float):
    """Construit des plages locales autour d'un seed paramétrique."""
    from utils.parameters import ParameterSpec

    range_ratio = max(0.01, min(1.0, float(range_ratio)))
    spec_map = getattr(strat, "parameter_specs", {}) or {}

    local_specs = {}
    for name, (global_min, global_max) in (strat.param_ranges or {}).items():
        spec = spec_map.get(name)
        param_type = getattr(spec, "param_type", None)
        if not param_type:
            default = strat.default_params.get(name, (global_min + global_max) / 2)
            param_type = "int" if isinstance(default, int) else "float"

        center_raw = seed_params.get(name, strat.default_params.get(name, (global_min + global_max) / 2))
        center = float(center_raw)
        gmin = float(global_min)
        gmax = float(global_max)
        half_window = max((gmax - gmin) * range_ratio * 0.5, 0.0)

        local_min = max(gmin, center - half_window)
        local_max = min(gmax, center + half_window)

        if param_type == "int":
            gmin_i = int(round(gmin))
            gmax_i = int(round(gmax))
            local_min_i = int(round(local_min))
            local_max_i = int(round(local_max))
            local_min_i = max(gmin_i, min(local_min_i, gmax_i))
            local_max_i = max(gmin_i, min(local_max_i, gmax_i))

            if local_min_i == local_max_i:
                if local_min_i > gmin_i:
                    local_min_i -= 1
                elif local_max_i < gmax_i:
                    local_max_i += 1

            local_specs[name] = ParameterSpec(
                name=name,
                min_val=min(local_min_i, local_max_i),
                max_val=max(local_min_i, local_max_i),
                default=int(round(center)),
                param_type="int",
            )
        else:
            if abs(local_max - local_min) < 1e-12:
                epsilon = max((gmax - gmin) * 0.05, 1e-6)
                local_min = max(gmin, center - epsilon)
                local_max = min(gmax, center + epsilon)

            local_specs[name] = ParameterSpec(
                name=name,
                min_val=float(local_min),
                max_val=float(local_max),
                default=float(center),
                param_type="float",
            )

    return local_specs


def _run_cycle_refinement(
    *,
    args,
    data_path: Path,
    strategy_name: str,
    coarse_candidates: list[dict],
    df_train: pd.DataFrame,
    output_path: Path,
) -> dict:
    """Affinage local autour des meilleurs candidats du sweep coarse."""
    import json as json_module

    from backtest.engine import BacktestEngine
    from strategies import get_strategy
    from utils.config import Config
    from utils.parameters import compute_search_space_stats, generate_param_grid

    strat_class = get_strategy(strategy_name)
    if not strat_class:
        return {"enabled": True, "status": "error", "error": f"Stratégie introuvable: {strategy_name}"}

    strat = strat_class()
    if getattr(args, "include_optional_params", False):
        strat._include_optional_params = True

    metric_key = normalize_metric_name(args.metric)
    seeds = coarse_candidates[: max(1, int(args.refine_top_candidates))]
    per_seed_stats = []
    unique_params: dict[str, dict] = {}

    for idx, seed in enumerate(seeds, start=1):
        seed_params = seed.get("params", {}) or {}
        local_specs = _build_local_param_specs(
            strat=strat,
            seed_params=seed_params,
            range_ratio=args.refine_range_ratio,
        )
        try:
            local_grid = generate_param_grid(
                local_specs,
                granularity=args.refine_granularity,
                max_total_combinations=args.refine_max_combinations,
            )
            per_seed_stats.append(
                {
                    "seed_rank": idx,
                    "seed_params": seed_params,
                    "n_combinations": len(local_grid),
                    "status": "ok",
                }
            )
            for params in local_grid:
                clean = {k: _to_native_value(v) for k, v in params.items()}
                key = json_module.dumps(clean, sort_keys=True, default=str)
                unique_params[key] = clean
        except Exception as e:
            per_seed_stats.append(
                {
                    "seed_rank": idx,
                    "seed_params": seed_params,
                    "n_combinations": 0,
                    "status": "skipped",
                    "reason": str(e),
                }
            )

    config_kwargs = {"fees_bps": args.fees_bps}
    if args.slippage_bps is not None:
        config_kwargs["slippage_bps"] = args.slippage_bps
    config = Config(**config_kwargs)

    stem = data_path.stem
    parts = stem.split("_")
    symbol = args.symbol or (parts[0] if parts else "UNKNOWN")
    timeframe = args.timeframe or (parts[1] if len(parts) > 1 else "1h")

    engine = BacktestEngine(initial_capital=args.capital, config=config)
    evaluated = []
    param_list = list(unique_params.values())
    for i, params in enumerate(param_list, start=1):
        try:
            result = engine.run(
                df=df_train,
                strategy=strategy_name,
                params=params,
                symbol=symbol,
                timeframe=timeframe,
                silent_mode=True,
                fast_metrics=True,
            )
            metrics = result.metrics.to_dict() if hasattr(result.metrics, "to_dict") else dict(result.metrics)
            metrics = {k: _to_native_value(v) for k, v in metrics.items()}
            evaluated.append(
                {
                    "params": params,
                    "metrics": metrics,
                    "score": _to_native_value(metrics.get(metric_key, 0)),
                    "source": "refine",
                }
            )
        except Exception as e:
            if getattr(args, "verbose", False):
                print_warning(f"Refine skip params={params}: {e}")

        if not args.quiet and (i % 50 == 0 or i == len(param_list)):
            print(f"\r  Refinement progress: {i}/{len(param_list)} ({100*i/max(1,len(param_list)):.1f}%)", end="", flush=True)

    if not args.quiet and param_list:
        print("\r" + " " * 70 + "\r", end="")

    reverse = _should_reverse_sort(args.metric, [r.get("score", 0) for r in evaluated])
    evaluated.sort(key=lambda item: item.get("score", 0), reverse=reverse)

    local_stats = compute_search_space_stats(
        _build_local_param_specs(
            strat=strat,
            seed_params=(seeds[0].get("params", {}) if seeds else {}),
            range_ratio=args.refine_range_ratio,
        ),
        max_combinations=args.refine_max_combinations,
        granularity=args.refine_granularity,
    ) if seeds else None

    payload = {
        "enabled": True,
        "status": "ok",
        "metric": args.metric,
        "granularity": args.refine_granularity,
        "range_ratio": args.refine_range_ratio,
        "max_combinations_per_seed": args.refine_max_combinations,
        "top_candidates_seeded": len(seeds),
        "n_unique_evaluated": len(evaluated),
        "search_space_estimate": local_stats.to_dict() if local_stats else None,
        "per_seed_stats": per_seed_stats,
        "best_candidate": evaluated[0] if evaluated else None,
        "results_top": evaluated[: max(20, int(args.report_top))],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return payload


def _write_cycle_interesting_report(
    *,
    path: Path,
    run_name: str,
    strategy: str,
    data_path: Path,
    metric: str,
    selected_source: str,
    selected_params: dict,
    coarse_top: list[dict],
    refine_top: list[dict] | None,
):
    """Écrit un rapport Markdown des configurations intéressantes."""

    def _fmt(candidate: dict, idx: int) -> str:
        params = candidate.get("params", {}) or {}
        m = candidate.get("metrics", {}) or {}
        sharpe = float(m.get("sharpe_ratio", 0) or 0)
        ret = float(m.get("total_return_pct", m.get("total_return", 0)) or 0)
        max_dd = float(m.get("max_drawdown_pct", m.get("max_drawdown", 0)) or 0)
        win = float(m.get("win_rate_pct", m.get("win_rate", 0)) or 0)
        trades = int(float(m.get("total_trades", 0) or 0))
        return (
            f"{idx}. params={params} | sharpe={sharpe:.3f} | "
            f"return={ret:+.2f}% | drawdown={max_dd:.2f}% | "
            f"win_rate={win:.2f}% | trades={trades}"
        )

    lines = [
        f"# Cycle Report - {run_name}",
        "",
        f"- Strategy: `{strategy}`",
        f"- Data: `{data_path}`",
        f"- Metric: `{metric}`",
        f"- Selected source: `{selected_source}`",
        f"- Selected params: `{selected_params}`",
        "",
        "## Coarse Sweep - Configurations Interessantes",
    ]

    if coarse_top:
        for i, candidate in enumerate(coarse_top, start=1):
            lines.append(_fmt(candidate, i))
    else:
        lines.append("Aucune configuration coarse disponible.")

    lines.append("")
    lines.append("## Refinement Local - Configurations Interessantes")
    if refine_top:
        for i, candidate in enumerate(refine_top, start=1):
            lines.append(_fmt(candidate, i))
    else:
        lines.append("Refinement non active ou aucune configuration refine disponible.")

    lines.append("")
    lines.append("## Notes")
    lines.append("- Les configurations sont ordonnées selon la métrique du cycle.")
    lines.append("- Validation OOS et walk-forward restent prioritaires avant usage production.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _parse_analyze_input(path: Path) -> list[dict]:
    """Charge un fichier de résultats unique (backtest/sweep JSON/CSV/Parquet)."""
    suffix = path.suffix.lower()

    def _to_py(value):
        if isinstance(value, np.generic):
            return value.item()
        return value

    # JSON: backtest ou sweep
    if suffix == ".json":
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            strategy = payload.get("strategy", "N/A")
            records = []
            for idx, result in enumerate(payload["results"], start=1):
                records.append(
                    {
                        "run_id": f"{path.stem}#{idx}",
                        "strategy": strategy,
                        "symbol": payload.get("symbol", "N/A"),
                        "timeframe": payload.get("timeframe", "N/A"),
                        "period_start": payload.get("period", {}).get("start", "N/A"),
                        "period_end": payload.get("period", {}).get("end", "N/A"),
                        "params": result.get("params", {}) or {},
                        "metrics": result.get("metrics", {}) or {},
                    }
                )
            return records

        if isinstance(payload, dict) and isinstance(payload.get("metrics"), dict):
            meta = payload.get("meta", {}) or {}
            return [
                {
                    "run_id": meta.get("run_id", path.stem),
                    "strategy": payload.get("strategy", meta.get("strategy", "N/A")),
                    "symbol": meta.get("symbol", "N/A"),
                    "timeframe": meta.get("timeframe", "N/A"),
                    "period_start": meta.get("period_start", "N/A"),
                    "period_end": meta.get("period_end", "N/A"),
                    "params": payload.get("params", {}) or {},
                    "metrics": payload.get("metrics", {}) or {},
                }
            ]

        raise ValueError("Format JSON non reconnu pour analyze --input")

    # CSV/Parquet: format tabulaire sweep
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        raise ValueError(f"Format non supporté pour --input: {suffix}")

    records = []
    reserved = {"rank", "strategy", "granularity", "metric", "n_combinations", "score"}
    param_cols = [c for c in df.columns if c.startswith("param_")]
    metric_cols = [c for c in df.columns if c not in reserved and c not in param_cols]

    for idx, row_dict in enumerate(df.to_dict(orient="records")):
        params = {c.replace("param_", "", 1): _to_py(row_dict[c]) for c in param_cols if pd.notna(row_dict[c])}
        metrics = {c: _to_py(row_dict[c]) for c in metric_cols if pd.notna(row_dict[c])}
        if "score" in df.columns and pd.notna(row_dict.get("score")):
            metrics["score"] = _to_py(row_dict["score"])

        records.append(
            {
                "run_id": f"{path.stem}#{idx+1}",
                "strategy": _to_py(row_dict["strategy"]) if "strategy" in df.columns else "N/A",
                "symbol": "N/A",
                "timeframe": "N/A",
                "period_start": "N/A",
                "period_end": "N/A",
                "params": params,
                "metrics": metrics,
            }
        )

    return records


def cmd_analyze(args) -> int:
    """Analyse les résultats de backtests stockés."""
    if args.no_color:
        Colors.disable()

    import json as json_module
    from pathlib import Path

    print_header("Analyse des Résultats de Backtests")

    # Mode input fichier unique (backtest/sweep)
    if args.input:
        input_path = Path(args.input)
        print(f"  Input: {input_path}")
        print()

        if not input_path.exists():
            print_error(f"Fichier non trouvé: {input_path}")
            return 1

        try:
            records = _parse_analyze_input(input_path)
        except Exception as e:
            print_error(f"Impossible de lire {input_path}: {e}")
            return 1
    else:
        # Mode historique index.parquet (v2) ou index.json (legacy)
        results_dir = Path(args.results_dir)
        print(f"  Répertoire: {results_dir}")
        print()

        if not results_dir.exists():
            print_error(f"Répertoire non trouvé: {results_dir}")
            return 1

        index_parquet = results_dir / "index.parquet"
        index_csv = results_dir / "index.csv"
        index_json = results_dir / "index.json"

        records = []
        if index_parquet.exists():
            idx_df = pd.read_parquet(index_parquet)
            for row_dict in idx_df.to_dict(orient="records"):
                records.append(
                    {
                        "run_id": str(row_dict.get("run_id", "N/A")),
                        "strategy": str(row_dict.get("strategy", "N/A")),
                        "symbol": str(row_dict.get("symbol", "N/A")),
                        "timeframe": str(row_dict.get("timeframe", "N/A")),
                        "period_start": "N/A",
                        "period_end": "N/A",
                        "params": {},
                        "metrics": _metrics_from_index_row(row_dict),
                    }
                )
        elif index_csv.exists():
            idx_df = pd.read_csv(index_csv)
            for row_dict in idx_df.to_dict(orient="records"):
                records.append(
                    {
                        "run_id": str(row_dict.get("run_id", "N/A")),
                        "strategy": str(row_dict.get("strategy", "N/A")),
                        "symbol": str(row_dict.get("symbol", "N/A")),
                        "timeframe": str(row_dict.get("timeframe", "N/A")),
                        "period_start": "N/A",
                        "period_end": "N/A",
                        "params": {},
                        "metrics": _metrics_from_index_row(row_dict),
                    }
                )
        elif index_json.exists():
            with open(index_json, encoding="utf-8") as f:
                index = json_module.load(f)
            for run_id, data in index.items():
                records.append(
                    {
                        "run_id": run_id,
                        "strategy": data.get("strategy", "N/A"),
                        "symbol": data.get("symbol", "N/A"),
                        "timeframe": data.get("timeframe", "N/A"),
                        "period_start": data.get("period_start", "N/A"),
                        "period_end": data.get("period_end", "N/A"),
                        "params": data.get("params", {}) or {},
                        "metrics": data.get("metrics", {}) or {},
                    }
                )
        else:
            print_error(f"Aucun index trouvé dans {results_dir} (index.parquet / index.csv / index.json)")
            return 1

        if getattr(args, "hydrate", False):
            hydrated, missing, errors = _hydrate_records_from_run_store(records, results_dir)
            print_info(
                f"Hydratation métriques: {hydrated} enrichis, {missing} absents, {errors} erreurs"
            )
            print()

    print_info(f"Nombre total de runs: {len(records)}")
    print()

    # Filtrer runs profitables
    if args.profitable_only:
        filtered_records = [
            r for r in records
            if r["metrics"].get("total_pnl", r["metrics"].get("total_return_pct", 0)) > 0
        ]
    else:
        filtered_records = records

    min_trades = max(0, int(getattr(args, "min_trades", 0) or 0))
    if min_trades > 0:
        filtered_records = [
            r for r in filtered_records
            if float((r.get("metrics", {}) or {}).get("total_trades", 0) or 0) >= min_trades
        ]

    print_header(
        f"Résultats {'profitables' if args.profitable_only else 'tous'} ({len(filtered_records)})",
        "-",
    )

    # Trier
    reverse = _should_reverse_sort(
        args.sort_by,
        [_metric_sort_value(r["metrics"], args.sort_by) for r in filtered_records],
    )
    sorted_runs = sorted(
        filtered_records,
        key=lambda r: _metric_sort_value(r["metrics"], args.sort_by),
        reverse=reverse,
    )

    # Top N affichage
    for i, data in enumerate(sorted_runs[:args.top], 1):
        print(f"\n{Colors.BOLD}Run #{i} - {data['run_id']}{Colors.RESET}")
        print(f"  Stratégie: {data['strategy']}")
        print(f"  Période: {data.get('period_start', 'N/A')} → {data.get('period_end', 'N/A')}")
        print(f"  Symbole: {data.get('symbol', 'N/A')} | Timeframe: {data.get('timeframe', 'N/A')}")

        print(f"\n  {Colors.BOLD}Paramètres:{Colors.RESET}")
        params = data.get("params", {}) or {}
        if params:
            for param, value in params.items():
                print(f"    {param}: {value}")
        else:
            print("    (aucun)")

        m = data.get("metrics", {}) or {}
        print(f"\n  {Colors.BOLD}Métriques:{Colors.RESET}")
        print(f"    PnL: ${m.get('total_pnl', 0):.2f} | Return: {m.get('total_return_pct', 0):.2f}%")
        print(f"    Sharpe: {m.get('sharpe_ratio', 0):.2f} | Sortino: {m.get('sortino_ratio', 0):.2f}")
        print(f"    Win Rate: {m.get('win_rate_pct', 0):.2f}% | Profit Factor: {m.get('profit_factor', 0):.2f}")
        print(f"    Max DD: {m.get('max_drawdown_pct', m.get('max_drawdown', 0)):.2f}% | Trades: {m.get('total_trades', 0)}")

    # Statistiques globales
    if args.stats and len(filtered_records) > 0:
        print()
        print_header("Statistiques Globales", "-")

        sharpe_values = [r["metrics"].get("sharpe_ratio", 0) for r in filtered_records]
        return_values = [r["metrics"].get("total_return_pct", 0) for r in filtered_records]
        dd_values = [r["metrics"].get("max_drawdown_pct", r["metrics"].get("max_drawdown", 0)) for r in filtered_records]

        print(f"  {Colors.BOLD}Sharpe Ratio:{Colors.RESET}")
        print(f"    Moyenne: {np.mean(sharpe_values):.2f}")
        print(f"    Médiane: {np.median(sharpe_values):.2f}")
        print(f"    Min: {np.min(sharpe_values):.2f} | Max: {np.max(sharpe_values):.2f}")

        print(f"\n  {Colors.BOLD}Return %:{Colors.RESET}")
        print(f"    Moyenne: {np.mean(return_values):.2f}%")
        print(f"    Médiane: {np.median(return_values):.2f}%")
        print(f"    Min: {np.min(return_values):.2f}% | Max: {np.max(return_values):.2f}%")

        print(f"\n  {Colors.BOLD}Max Drawdown %:{Colors.RESET}")
        print(f"    Moyenne: {np.mean(dd_values):.2f}%")
        print(f"    Médiane: {np.median(dd_values):.2f}%")
        print(f"    Min: {np.min(dd_values):.2f}% | Max: {np.max(dd_values):.2f}%")

    # Export si demandé
    if args.output:
        output_path = Path(args.output)
        export_data = {
            "total_runs": len(records),
            "filtered_runs": len(filtered_records),
            "filter": "profitable_only" if args.profitable_only else "all",
            "sort_by": args.sort_by,
            "top_runs": sorted_runs[:args.top],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json_module.dump(export_data, f, indent=2, default=str)
        print()
        print_success(f"Analyse exportée: {output_path}")

    return 0


# =============================================================================
# COMMANDE: CYCLE
# =============================================================================

def cmd_cycle(args) -> int:
    """Exécute un cycle complet: baseline train -> sweep train -> test OOS -> full."""
    if args.no_color:
        Colors.disable()

    strategies = _resolve_strategy_selection(args)
    if not strategies:
        print_error("Aucune stratégie sélectionnée (utilisez -s ou --from-category/--from-tag)")
        return 1
    if len(strategies) > 1:
        results = []
        for strategy_name in strategies:
            sub_args = copy.copy(args)
            sub_args.strategy = strategy_name
            sub_args.run_name = None
            if args.output_dir:
                sub_args.output_dir = str(Path(args.output_dir) / strategy_name)
            results.append(_cmd_cycle_single(sub_args, strategy_name))
        return 0 if all(r == 0 for r in results) else 1
    return _cmd_cycle_single(args, strategies[0])


def _cmd_cycle_single(args, strategy_name: str) -> int:
    from argparse import Namespace

    data_path = _resolve_data_path(args.data)
    if not data_path.exists():
        print_error(f"Fichier non trouvé: {args.data}")
        return 1

    if args.walk_forward:
        if not (0.0 < float(args.wf_train_ratio) < 1.0):
            print_error("--wf-train-ratio doit être strictement entre 0 et 1")
            return 1
        if int(args.wf_folds) <= 0:
            print_error("--wf-folds doit être > 0")
            return 1
        if int(args.wf_min_train_bars) <= 0 or int(args.wf_min_test_bars) <= 0:
            print_error("--wf-min-train-bars et --wf-min-test-bars doivent être > 0")
            return 1
    elif args.require_wf_robust:
        print_warning("--require-wf-robust ignoré car --walk-forward n'est pas activé")

    if args.refine:
        if not (0.0 <= float(args.refine_granularity) <= 1.0):
            print_error("--refine-granularity doit être entre 0 et 1")
            return 1
        if int(args.refine_top_candidates) <= 0:
            print_error("--refine-top-candidates doit être > 0")
            return 1
        if int(args.refine_max_combinations) <= 0:
            print_error("--refine-max-combinations doit être > 0")
            return 1
        if not (0.0 < float(args.refine_range_ratio) <= 1.0):
            print_error("--refine-range-ratio doit être dans (0, 1]")
            return 1

    filter_settings = _resolve_cycle_filter_settings(args)
    effective_min_trades = int(filter_settings["min_trades"])
    effective_max_drawdown = filter_settings["max_drawdown"]
    effective_require_positive_train = bool(filter_settings["require_positive_train"])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_name = args.run_name or f"cycle_{strategy_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # Charger données pour calcul de fenêtre/split
    from data.loader import _normalize_ohlcv, _read_file

    df_all = _normalize_ohlcv(_read_file(data_path))
    if len(df_all) < 50:
        print_error(f"Données insuffisantes pour un cycle fiable: {len(df_all)} barres")
        return 1

    global_start = args.train_start or str(df_all.index[0])
    global_end = args.test_end or str(df_all.index[-1])
    df_window = _apply_date_filter(df_all, global_start, global_end)

    if args.train_end and args.test_start:
        train_start = args.train_start or str(df_window.index[0])
        train_end = args.train_end
        test_start = args.test_start
        test_end = args.test_end or str(df_window.index[-1])
    else:
        split_idx = max(1, min(len(df_window) - 1, int(len(df_window) * args.split_ratio)))
        train_start = str(df_window.index[0])
        train_end = str(df_window.index[split_idx - 1])
        test_start = str(df_window.index[split_idx])
        test_end = str(df_window.index[-1])
        if not args.quiet and (args.train_end or args.test_start):
            print_warning("train_end/test_start incomplets: split automatique appliqué")

    df_train = _apply_date_filter(df_window, train_start, train_end)

    if not args.quiet:
        print_header("Cycle Complet")
        print(f"  Stratégie: {strategy_name}")
        print(f"  Données: {data_path}")
        print(f"  Train: {train_start} -> {train_end}")
        print(f"  Test:  {test_start} -> {test_end}")
        print(f"  Metric sweep: {args.metric}")
        print(f"  Output dir: {output_dir}")
        print(
            "  Filtres candidats: "
            f"profile={filter_settings['profile']}, "
            f"min_trades={effective_min_trades}, "
            f"max_drawdown={effective_max_drawdown if effective_max_drawdown is not None else 'none'}, "
            f"require_positive_train={'yes' if effective_require_positive_train else 'no'}"
        )
        if args.walk_forward:
            print(
                "  Walk-Forward: "
                f"mode={args.wf_mode}, folds={args.wf_folds}, "
                f"train_ratio={args.wf_train_ratio:.2f}, embargo={args.wf_embargo_pct:.3f}"
            )
        print()

    # Préflight optionnel
    if not args.skip_validate:
        if not args.quiet:
            print_info("Préflight: validate --all")
        validate_args = Namespace(
            all=True,
            strategy=None,
            data=None,
            no_color=args.no_color,
            verbose=args.verbose,
            quiet=args.quiet,
        )
        rc = cmd_validate(validate_args)
        if rc != 0:
            return rc

    # Artefacts
    train_baseline_path = output_dir / f"{run_name}_train_baseline.json"
    train_sweep_path = output_dir / f"{run_name}_train_sweep.json"
    train_refine_path = output_dir / f"{run_name}_train_refine.json"
    test_best_path = output_dir / f"{run_name}_test_best.json"
    full_best_path = output_dir / f"{run_name}_full_best.json"
    report_path = output_dir / f"{run_name}_interesting.md"
    summary_path = output_dir / f"{run_name}_summary.json"
    walk_forward_path = output_dir / f"{run_name}_walkforward.json"

    # 1) Baseline train
    if not args.quiet:
        print_info("Étape 1/4: backtest baseline (train)")
    rc = cmd_backtest(
        Namespace(
            strategy=strategy_name,
            data=str(data_path),
            start=train_start,
            end=train_end,
            symbol=args.symbol,
            timeframe=args.timeframe,
            params="{}",
            capital=args.capital,
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            output=str(train_baseline_path),
            format="json",
            no_color=args.no_color,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    )
    if rc != 0:
        return rc

    # 2) Sweep train
    if not args.quiet:
        print_info("Étape 2/4: sweep (train)")
    rc = cmd_sweep(
        Namespace(
            strategy=strategy_name,
            data=str(data_path),
            start=train_start,
            end=train_end,
            symbol=args.symbol,
            timeframe=args.timeframe,
            granularity=args.granularity,
            include_optional_params=args.include_optional_params,
            max_combinations=args.max_combinations,
            metric=args.metric,
            parallel=args.parallel,
            output=str(train_sweep_path),
            format="json",
            capital=args.capital,
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            top=args.top,
            no_color=args.no_color,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    )
    if rc != 0:
        return rc

    with open(train_sweep_path, encoding="utf-8") as f:
        sweep_payload = json.load(f)
    sweep_results = sweep_payload.get("results", [])
    if not sweep_results:
        print_error("Sweep vide: aucune combinaison exploitable")
        return 1

    metric_key = normalize_metric_name(args.metric)
    reverse = _should_reverse_sort(
        args.metric,
        [(item.get("metrics", {}) or {}).get(metric_key, item.get("score", 0)) for item in sweep_results],
    )

    filtered = []
    max_drawdown_limit = _normalize_drawdown_limit(effective_max_drawdown)
    for item in sweep_results:
        metrics = item.get("metrics", {}) or {}
        trades = metrics.get("total_trades", 0)
        ret = metrics.get("total_return_pct", 0)
        max_dd = metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0))
        if trades < effective_min_trades:
            continue
        if max_drawdown_limit is not None and float(max_dd) < max_drawdown_limit:
            continue
        if effective_require_positive_train and ret <= 0:
            continue
        filtered.append(item)
    if not filtered:
        filtered = sweep_results
        if not args.quiet:
            print_warning("Aucun candidat ne respecte les filtres (min_trades/max_drawdown/return), fallback sur top brut")

    filtered.sort(
        key=lambda r: (r.get("metrics", {}) or {}).get(metric_key, r.get("score", 0)),
        reverse=reverse,
    )
    coarse_top_candidates = filtered[: max(1, int(args.report_top))]
    best_candidate = filtered[0]
    coarse_best_metrics = filtered[0].get("metrics", {}) or {}
    best_source = "coarse"

    refine_summary = None
    refine_top_candidates = None
    if args.refine:
        if not args.quiet:
            print_info("Étape 2b: affinage local autour des meilleurs candidats (train)")
        try:
            refine_summary = _run_cycle_refinement(
                args=args,
                data_path=data_path,
                strategy_name=strategy_name,
                coarse_candidates=filtered,
                df_train=df_train,
                output_path=train_refine_path,
            )
            refine_top_candidates = (refine_summary.get("results_top", []) if isinstance(refine_summary, dict) else []) or []
            refine_best = (refine_summary.get("best_candidate") if isinstance(refine_summary, dict) else None)
            if refine_best:
                refine_score = float(refine_best.get("score", 0) or 0)
                coarse_score = float(
                    (best_candidate.get("metrics", {}) or {}).get(metric_key, best_candidate.get("score", 0)) or 0
                )
                if _is_metric_better(args.metric, refine_score, coarse_score):
                    best_candidate = refine_best
                    best_source = "refine"
                    if not args.quiet:
                        print_info("Affinage: meilleur candidat mis à jour (source=refine)")
                elif not args.quiet:
                    print_info("Affinage: meilleur candidat coarse conservé")
            if not args.quiet:
                print_success(f"Affinage exporté: {train_refine_path}")
        except Exception as e:
            refine_summary = {
                "enabled": True,
                "status": "error",
                "error": str(e),
            }
            if not args.quiet:
                print_warning(f"Affinage non exécuté: {e}")

    best_params = best_candidate.get("params", {}) or {}

    if not args.quiet:
        print_info(f"Candidat retenu ({best_source}): {best_params}")

    best_params_json = json.dumps(best_params)

    # 3) Test OOS
    if not args.quiet:
        print_info("Étape 3/4: backtest OOS (test)")
    rc = cmd_backtest(
        Namespace(
            strategy=strategy_name,
            data=str(data_path),
            start=test_start,
            end=test_end,
            symbol=args.symbol,
            timeframe=args.timeframe,
            params=best_params_json,
            capital=args.capital,
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            output=str(test_best_path),
            format="json",
            no_color=args.no_color,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    )
    if rc != 0:
        return rc

    # 4) Fenêtre complète cycle
    if not args.quiet:
        print_info("Étape 4/4: backtest full (fenêtre complète)")
    rc = cmd_backtest(
        Namespace(
            strategy=strategy_name,
            data=str(data_path),
            start=global_start,
            end=global_end,
            symbol=args.symbol,
            timeframe=args.timeframe,
            params=best_params_json,
            capital=args.capital,
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            output=str(full_best_path),
            format="json",
            no_color=args.no_color,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    )
    if rc != 0:
        return rc

    baseline_metrics = _extract_metrics_from_result_file(train_baseline_path)
    test_metrics = _extract_metrics_from_result_file(test_best_path)
    full_metrics = _extract_metrics_from_result_file(full_best_path)
    best_train_metrics = best_candidate.get("metrics", {}) or {}
    refine_best_metrics = {}
    if isinstance(refine_summary, dict):
        refine_best_metrics = ((refine_summary.get("best_candidate") or {}).get("metrics", {}) or {})

    walk_forward_summary = None
    if args.walk_forward:
        if not args.quiet:
            print_info("Étape 5/5: validation walk-forward")
        try:
            walk_forward_summary = _run_cycle_walk_forward(
                df=df_window,
                strategy=strategy_name,
                params=best_params,
                capital=args.capital,
                args=args,
            )
            with open(walk_forward_path, "w", encoding="utf-8") as f:
                json.dump(walk_forward_summary, f, indent=2, default=str)
            if not args.quiet:
                print_success(f"Walk-forward exporté: {walk_forward_path}")
        except Exception as e:
            walk_forward_summary = {
                "enabled": True,
                "status": "error",
                "error": str(e),
            }
            print_warning(f"Walk-forward non exécuté: {e}")

    report_written = False
    try:
        _write_cycle_interesting_report(
            path=report_path,
            run_name=run_name,
            strategy=strategy_name,
            data_path=data_path,
            metric=args.metric,
            selected_source=best_source,
            selected_params=best_params,
            coarse_top=coarse_top_candidates,
            refine_top=refine_top_candidates,
        )
        report_written = True
        if not args.quiet:
            print_success(f"Rapport configurations intéressantes: {report_path}")
    except Exception as e:
        if not args.quiet:
            print_warning(f"Impossible de générer le rapport des configurations: {e}")

    summary = {
        "run_name": run_name,
        "strategy": strategy_name,
        "data": str(data_path),
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "windows": {
            "global_start": global_start,
            "global_end": global_end,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        },
        "settings": {
            "capital": args.capital,
            "fees_bps": args.fees_bps,
            "slippage_bps": args.slippage_bps,
            "metric": args.metric,
            "granularity": args.granularity,
            "max_combinations": args.max_combinations,
            "parallel": args.parallel,
            "top": args.top,
            "filter_profile": filter_settings["profile"],
            "min_trades": effective_min_trades,
            "max_drawdown": effective_max_drawdown,
            "require_positive_train": effective_require_positive_train,
            "input_min_trades": args.min_trades,
            "input_max_drawdown": args.max_drawdown,
            "input_require_positive_train": args.require_positive_train,
            "walk_forward": bool(args.walk_forward),
            "wf_mode": args.wf_mode,
            "wf_folds": args.wf_folds,
            "wf_train_ratio": args.wf_train_ratio,
            "wf_embargo_pct": args.wf_embargo_pct,
            "wf_min_train_bars": args.wf_min_train_bars,
            "wf_min_test_bars": args.wf_min_test_bars,
            "require_wf_robust": bool(args.require_wf_robust),
            "refine": bool(args.refine),
            "refine_top_candidates": args.refine_top_candidates,
            "refine_granularity": args.refine_granularity,
            "refine_max_combinations": args.refine_max_combinations,
            "refine_range_ratio": args.refine_range_ratio,
            "report_top": args.report_top,
        },
        "selected_params": best_params,
        "selected_source": best_source,
        "metrics": {
            "baseline_train": baseline_metrics,
            "best_train_candidate": best_train_metrics,
            "best_train_coarse_candidate": coarse_best_metrics,
            "best_train_refine_candidate": refine_best_metrics if refine_best_metrics else None,
            "best_test_oos": test_metrics,
            "best_full_window": full_metrics,
        },
        "validation": {
            "walk_forward": walk_forward_summary,
            "refinement": refine_summary,
        },
        "artifacts": {
            "train_baseline": str(train_baseline_path),
            "train_sweep": str(train_sweep_path),
            "train_refine": str(train_refine_path) if refine_summary else None,
            "test_best": str(test_best_path),
            "full_best": str(full_best_path),
            "walk_forward": str(walk_forward_path) if walk_forward_summary else None,
            "interesting_report": str(report_path) if report_written else None,
            "summary": str(summary_path),
        },
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    persisted_cycle_id = _persist_summary_result_v2(
        mode="cycle",
        strategy=strategy_name,
        symbol=args.symbol or "UNKNOWN",
        timeframe=args.timeframe or "N/A",
        params=best_params,
        metrics=full_metrics,
        diagnostics=summary,
        metadata={
            "period_start": global_start,
            "period_end": global_end,
            "seed": getattr(args, "seed", None),
            "engine_settings": {
                "initial_capital": args.capital,
                "fees_bps": args.fees_bps,
                "slippage_bps": args.slippage_bps,
            },
            "data_source": {"path": str(data_path), "rows": len(df_window)},
            "config_snapshot_extra": {
                "command": "cycle",
                "run_name": run_name,
                "selected_source": best_source,
            },
        },
        run_id=run_name,
        status="ok",
    )
    if persisted_cycle_id and walk_forward_summary and _should_persist_results_v2():
        try:
            store = _get_result_store()
            store.save_walk_forward_folds(
                parent_run_id=persisted_cycle_id,
                strategy=strategy_name,
                symbol=args.symbol or "UNKNOWN",
                timeframe=args.timeframe or "N/A",
                params=best_params,
                walk_forward_payload=walk_forward_summary,
                metadata_extra={
                    "period_start": global_start,
                    "period_end": global_end,
                    "seed": getattr(args, "seed", None),
                },
            )
        except Exception as exc:
            logger.warning(
                "cycle_walk_forward_persist_failed parent_run_id=%s error=%s",
                persisted_cycle_id,
                exc,
            )
            print_warning(f"Échec sauvegarde folds walk-forward: {exc}")

    if args.export_html:
        cmd_export(
            Namespace(
                input=str(test_best_path),
                format="html",
                output=str(output_dir / f"{run_name}_test_best.html"),
                template=None,
                no_color=args.no_color,
                verbose=args.verbose,
                quiet=args.quiet,
            )
        )
        cmd_export(
            Namespace(
                input=str(full_best_path),
                format="html",
                output=str(output_dir / f"{run_name}_full_best.html"),
                template=None,
                no_color=args.no_color,
                verbose=args.verbose,
                quiet=args.quiet,
            )
        )

    print()
    print_header("Résumé Cycle")
    print(f"  Paramètres retenus ({best_source}): {best_params}")
    _print_metrics_summary("  Train baseline:", baseline_metrics)
    _print_metrics_summary("  Train best:", best_train_metrics)
    if refine_summary and isinstance(refine_summary, dict) and refine_summary.get("status") == "ok":
        print(
            f"  Refinement: {refine_summary.get('n_unique_evaluated', 0)} "
            f"combinaisons locales évaluées"
        )
    _print_metrics_summary("  Test OOS:", test_metrics)
    _print_metrics_summary("  Full window:", full_metrics)
    if walk_forward_summary:
        wf_results = walk_forward_summary.get("results", {}) if isinstance(walk_forward_summary, dict) else {}
        robust_ok = False
        for mode in ("rolling", "expanding"):
            result = wf_results.get(mode)
            if not result:
                continue
            status = result.get("status", "ok")
            if status != "ok":
                print(f"  WFA {mode}: {status} ({result.get('reason', 'n/a')})")
                continue
            is_robust = bool(result.get("is_robust", False))
            robust_ok = robust_ok or is_robust
            print(
                f"  WFA {mode}: n_valid={result.get('n_valid_folds', 0)} | "
                f"avg_test_sharpe={result.get('avg_test_sharpe', 0):.3f} | "
                f"overfit_ratio={result.get('avg_overfitting_ratio', 0):.3f} | "
                f"confidence={result.get('confidence_score', 0):.3f} | "
                f"robust={'yes' if is_robust else 'no'}"
            )
        if args.require_wf_robust and not robust_ok:
            print_error("Cycle invalidé: aucune vue walk-forward n'est robuste")
            print(f"  Fichier résumé: {summary_path}")
            return 2
    if report_written:
        print(f"  Rapport intéressant: {report_path}")
    if persisted_cycle_id:
        print(f"  Run cycle indexé: {persisted_cycle_id}")
    print(f"  Fichier résumé: {summary_path}")

    return 0


# =============================================================================
# BUILDER — Strategy Builder LLM
# =============================================================================


def cmd_builder(args) -> int:
    """Lance le Strategy Builder pour créer une stratégie via LLM.

    Le builder utilise le LLM pour concevoir itérativement une stratégie
    de trading en combinant les indicateurs existants du registry.
    Les fichiers générés sont isolés dans sandbox_strategies/<session_id>/.
    """
    from agents.llm_client import LLMConfig
    from agents.strategy_builder import StrategyBuilder

    objective = args.objective
    data_path = _resolve_data_path(args.data)

    if not data_path.exists():
        print(f"{Colors.RED}❌ Fichier non trouvé: {args.data}{Colors.RESET}")
        print(f"   Répertoire cherché: {data_path.parent}")
        return 1

    print()
    print(f"{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}  🏗️  Strategy Builder{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print()
    print(f"  Objectif : {Colors.BLUE}{objective}{Colors.RESET}")
    print(f"  Données  : {data_path}")
    print(f"  Itérations max : {args.max_iterations}")
    print(f"  Sharpe cible   : {args.target_sharpe}")
    print()

    # Charger les données (via load_ohlcv pour bénéficier du trim post-listing + data quality)
    try:
        from data.loader import load_ohlcv
        stem = data_path.stem
        parts = stem.split("_", 1)
        _symbol = args.symbol if hasattr(args, "symbol") and args.symbol else (parts[0] if parts else "UNKNOWN")
        _tf = args.timeframe if hasattr(args, "timeframe") and args.timeframe else (parts[1] if len(parts) > 1 else "1h")
        df = load_ohlcv(_symbol, _tf, start=getattr(args, "start", None), end=getattr(args, "end", None))
        print(f"  📊 Données chargées : {len(df)} barres")
    except Exception as e:
        print(f"{Colors.RED}❌ Erreur chargement données: {e}{Colors.RESET}")
        return 1

    # Configurer LLM
    llm_config = LLMConfig.from_env()
    if args.model:
        llm_config.model = args.model
    print(f"  🤖 Modèle LLM : {llm_config.model}")
    print()

    # Créer le builder et lancer
    builder = StrategyBuilder(llm_config=llm_config)

    print(f"  📋 Indicateurs disponibles : {len(builder.available_indicators)}")
    print(f"     {', '.join(builder.available_indicators[:10])}...")
    print()
    print(f"{Colors.BOLD}{'─' * 60}{Colors.RESET}")
    print()

    multi_cycle = None
    if getattr(args, "multi_llm", False):
        from core.llm_multi import MultiLLMSessionManager, discover_local_models

        inventory = discover_local_models(
            ollama_host=llm_config.ollama_host,
            include_live_ollama=True,
        )
        manager = MultiLLMSessionManager(
            profile_name=args.multi_llm_profile,
            base_llm_config=llm_config,
            inventory=inventory,
        )
        print(f"  🧩 Multi-LLM : actif ({manager.profile_name})")
        builder_assignment = manager.resolve_role_assignment("builder_llm")
        if builder_assignment is None or not builder_assignment.available:
            print(
                "  ❌ builder_llm indisponible sur l'hôte Ollama actif pour ce profil "
                f"({llm_config.ollama_host})"
            )
            return 2
        if manager.missing_roles:
            print(
                f"  ⚠️  Roles manquants : {', '.join(manager.missing_roles)} "
                "(fallbacks deterministes conserves)"
            )
        else:
            print("  ✅ Tous les roles LLM actifs sont resolus localement")
        print()

        def _builder_runner(run_objective: str, run_model: str):
            run_llm_config = LLMConfig(
                provider=llm_config.provider,
                model=run_model,
                ollama_host=llm_config.ollama_host,
                openai_api_key=llm_config.openai_api_key,
                openai_base_url=llm_config.openai_base_url,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
                top_p=llm_config.top_p,
                timeout_seconds=llm_config.timeout_seconds,
                max_retries=llm_config.max_retries,
                retry_delay_seconds=llm_config.retry_delay_seconds,
            )
            run_builder = StrategyBuilder(llm_config=run_llm_config)
            return run_builder.run(
                objective=run_objective,
                data=df,
                max_iterations=args.max_iterations,
                target_sharpe=args.target_sharpe,
                initial_capital=args.capital,
                symbol=getattr(args, "symbol", None) or "UNKNOWN",
                timeframe=getattr(args, "timeframe", None) or "1h",
            )

        multi_cycle = manager.run_cycle(
            symbols=[getattr(args, "symbol", None) or "UNKNOWN"],
            timeframes=[getattr(args, "timeframe", None) or "1h"],
            available_indicators=builder.available_indicators,
            history_tail=[],
            target_sharpe=args.target_sharpe,
            builder_runner=_builder_runner,
            fallback_objective=objective,
        )
        objective = multi_cycle.objective
        session = multi_cycle.builder_session
        print(f"  🎯 Objectif final : {objective}")
        print(f"  🏗️  builder_llm  : {multi_cycle.builder_model}")
        print(
            f"  🧭 Routeur local : {multi_cycle.router_decision.get('action', 'iterate')} "
            f"| {multi_cycle.router_decision.get('reason', '')}"
        )
    else:
        session = builder.run(
            objective=objective,
            data=df,
            max_iterations=args.max_iterations,
            target_sharpe=args.target_sharpe,
            initial_capital=args.capital,
            symbol=getattr(args, "symbol", None) or "UNKNOWN",
            timeframe=getattr(args, "timeframe", None) or "1h",
        )

    # Afficher le résumé
    print()
    print(f"{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}  📊 Résumé Strategy Builder{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print()
    print(f"  Session    : {session.session_id}")
    print(f"  Statut     : {session.status}")
    print(f"  Itérations : {len(session.iterations)}")

    if session.best_sharpe > float("-inf"):
        color = Colors.GREEN if session.best_sharpe > 0 else Colors.RED
        print(f"  Best Sharpe: {color}{session.best_sharpe:.3f}{Colors.RESET}")

    if session.best_iteration:
        bt = session.best_iteration.backtest_result
        if bt:
            print(f"  Best Return: {getattr(bt, 'total_return_pct', 0):.2f}%")
            print(f"  Best DD    : {getattr(bt, 'max_drawdown_pct', 0):.2f}%")
            print(f"  Trades     : {getattr(bt, 'total_trades', 0)}")

    print()
    print(f"  📁 Fichiers : {session.session_dir}")
    print()

    # Historique des itérations
    for it in session.iterations:
        icon = "✅" if it.decision == "accept" else "🔄" if it.decision == "continue" else "❌"
        sharpe_str = ""
        if it.backtest_result:
            s = getattr(it.backtest_result, 'sharpe_ratio', 0)
            sharpe_str = f" | Sharpe={s:.3f}"
        error_str = f" | ⚠️ {it.error[:60]}" if it.error else ""
        print(f"  {icon} Iter {it.iteration}: {it.hypothesis[:50]}{sharpe_str}{error_str}")

    best_bt = session.best_iteration.backtest_result if session.best_iteration else None
    builder_metrics = {
        "sharpe_ratio": getattr(best_bt, "sharpe_ratio", 0.0) if best_bt else 0.0,
        "total_return_pct": getattr(best_bt, "total_return_pct", 0.0) if best_bt else 0.0,
        "max_drawdown_pct": getattr(best_bt, "max_drawdown_pct", 0.0) if best_bt else 0.0,
        "total_trades": getattr(best_bt, "total_trades", 0) if best_bt else 0,
    }
    persisted_builder_id = _persist_summary_result_v2(
        mode="builder",
        strategy="strategy_builder",
        symbol="UNKNOWN",
        timeframe="N/A",
        params={},
        metrics=builder_metrics,
        diagnostics={
            "objective": objective,
            "session_id": session.session_id,
            "status": session.status,
            "iterations": len(session.iterations),
            "best_iteration": session.best_iteration.iteration if session.best_iteration else None,
            "session_dir": str(session.session_dir),
            "multi_llm": bool(getattr(args, "multi_llm", False)),
            "multi_llm_profile": getattr(args, "multi_llm_profile", ""),
            "multi_llm_router_decision": (
                multi_cycle.router_decision if multi_cycle is not None else {}
            ),
        },
        metadata={
            "period_start": str(df.index[0]) if len(df) else None,
            "period_end": str(df.index[-1]) if len(df) else None,
            "seed": getattr(args, "seed", None),
            "data_source": {"path": str(data_path), "rows": len(df)},
            "config_snapshot_extra": {
                "command": "builder",
                "model": llm_config.model,
                "multi_llm": bool(getattr(args, "multi_llm", False)),
                "multi_llm_profile": getattr(args, "multi_llm_profile", ""),
                "max_iterations": args.max_iterations,
                "target_sharpe": args.target_sharpe,
                "session_id": session.session_id,
            },
        },
        run_id=f"builder_{session.session_id}",
        status="ok" if session.status in {"completed", "success"} else "invalid",
    )
    if persisted_builder_id:
        print(f"  Run builder indexé: {persisted_builder_id}")

    print()
    return 0


def cmd_multi_llm(args) -> int:
    """Audit / validation / installation helpers for the parallel multi-LLM builder."""

    from core.llm_multi import (
        discover_local_models,
        install_missing_models,
        plan_missing_downloads,
        resolve_profile_assignments,
    )

    action = getattr(args, "multi_llm_action", None) or "audit"
    inventory = discover_local_models(
        ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        include_live_ollama=True,
    )
    profile = getattr(args, "profile", "24GB_balanced")
    require_live_ollama = bool(inventory.live_ollama_reachable)

    if action == "audit":
        payload = inventory.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            summary = payload["summary"]
            print_header("Inventaire multi-LLM")
            print(f"Racines scannées : {len(summary['scanned_roots'])}")
            print(f"Modèles vérifiés : {summary['verified_models']}")
            print(f"Références catalogue seules : {summary['catalog_only_models']}")
            print(f"Backends : {summary['by_backend']}")
            if summary["missing_roots"]:
                print(f"Racines absentes : {', '.join(summary['missing_roots'])}")
        return 0

    resolution = resolve_profile_assignments(
        profile,
        inventory,
        require_live_ollama=require_live_ollama,
    )
    if action == "validate":
        payload = {
            "profile_name": resolution["profile_name"],
            "description": resolution["description"],
            "missing_roles": resolution["missing_roles"],
            "assignments": [
                assignment.to_dict() for assignment in resolution["assignments"]
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print_header(f"Validation multi-LLM: {resolution['profile_name']}")
            for assignment in resolution["assignments"]:
                status = "OK" if assignment.available else "MISSING"
                print(
                    f"{assignment.role:>24}: {status:<7} | "
                    f"request={assignment.requested_model or '-'} | "
                    f"resolved={assignment.resolved_model or '-'}"
                )
        return 0 if not resolution["missing_roles"] else 2

    if action == "install":
        requests = plan_missing_downloads(
            profile,
            inventory,
            require_live_ollama=require_live_ollama,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "profile": profile,
                        "requests": [request.to_dict() for request in requests],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        if not requests:
            print("Aucun modèle manquant à installer.")
            return 0
        results = install_missing_models(
            requests,
            ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        for result in results:
            status = "OK" if result.success else "FAIL"
            print(f"{status:>4} | {result.role:>24} | {result.model_name}")
            if result.log_path:
                print(f"      log: {result.log_path}")
        return 0 if all(result.success for result in results) else 1

    print_error(f"Action multi-LLM inconnue: {action}")
    return 1
